"""cTrader OAuth2 onboarding — links a client's cTrader account to the bot.

Flow (all from the client's phone, no PC needed):
  1. Client sends /ctrader in Telegram.
  2. Bot replies with an authorize link (state = signed chat_id).
  3. Client opens it, logs into cTrader, approves access.
  4. cTrader redirects to CTRADER_REDIRECT_URI?code=...&state=...
     → that URL is served by the bot's HTTP server (bot.py do_GET).
  5. handle_callback() verifies state, exchanges the code for tokens, fetches
     the client's trading accounts, stores them on the user record, and pings
     the client back in Telegram with the result.

Security: state is HMAC-signed with the Telegram bot token (always secret and
present), so a third party cannot forge a callback that binds tokens to someone
else's chat. Codes are single-use and short-lived on cTrader's side.
"""
import hmac
import time
import base64
import hashlib

from apex import config as cfg
from apex import user_store
from apex.brokers import ctrader

_STATE_TTL = 600  # 10 minutes to complete the authorization


def _secret() -> bytes:
    # Bot token is secret and always set; fall back to client secret.
    return (cfg.TELEGRAM_BOT_TOKEN or cfg.CTRADER_CLIENT_SECRET or "apex").encode()


def make_state(chat_id) -> str:
    """Signed, time-stamped state carrying the Telegram chat id."""
    payload = f"{chat_id}.{int(time.time())}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    token = f"{payload}.{sig}"
    return base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")


def parse_state(state: str):
    """Return chat_id if the state is valid and unexpired, else None."""
    try:
        pad = "=" * (-len(state) % 4)
        token = base64.urlsafe_b64decode(state + pad).decode()
        chat_id, ts, sig = token.rsplit(".", 2)
        payload = f"{chat_id}.{ts}"
        expect = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expect):
            return None
        if time.time() - int(ts) > _STATE_TTL:
            return None
        return chat_id
    except Exception:
        return None


def redirect_uri() -> str:
    """Where cTrader sends the client back. Configurable; defaults to the bot's
    own Render URL so the callback hits this service's HTTP server."""
    if cfg.CTRADER_REDIRECT_URI:
        return cfg.CTRADER_REDIRECT_URI
    import os
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    return f"{base}/api/ctrader/callback" if base else ""


def authorize_link(chat_id) -> str:
    return ctrader.authorize_url(redirect_uri(), make_state(chat_id))


def _html(title, body) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>body{{font-family:system-ui,sans-serif;"
        "background:#0b0e16;color:#e6e9ef;display:flex;min-height:100vh;margin:0;"
        "align-items:center;justify-content:center;text-align:center;padding:24px}"
        ".c{max-width:420px}.h{font-size:22px;font-weight:800;margin-bottom:10px}"
        ".p{color:#94a3b8;line-height:1.6;font-size:15px}.ok{color:#22c55e}"
        ".err{color:#ff5c74}</style></head><body><div class='c'>"
        f"{body}</div></body></html>"
    )


def handle_callback(query: dict):
    """query: parsed query string (dict of lists OR dict of str).
    Returns (http_status, html). Also stores tokens + notifies the client."""
    def _q(k):
        v = query.get(k)
        if isinstance(v, list):
            return v[0] if v else ""
        return v or ""

    err = _q("error")
    if err:
        return 400, _html("cTrader", f"<div class='h err'>Authorization failed</div>"
                          f"<div class='p'>{err}. Please return to Telegram and try /ctrader again.</div>")

    code = _q("code")
    state = _q("state")
    chat_id = parse_state(state)
    if not code or not chat_id:
        return 400, _html("cTrader", "<div class='h err'>Invalid or expired link</div>"
                          "<div class='p'>Please return to Telegram and send /ctrader to get a fresh link.</div>")

    try:
        tok = ctrader.exchange_code(code, redirect_uri())
        access = tok.get("accessToken") or tok.get("access_token")
        refresh = tok.get("refreshToken") or tok.get("refresh_token")
        if not access:
            raise RuntimeError("no access token in response")
        accounts = ctrader.list_accounts(access)
    except Exception as e:
        return 502, _html("cTrader", "<div class='h err'>Connection error</div>"
                          f"<div class='p'>{e}. Return to Telegram and try /ctrader again.</div>")

    # Persist tokens + account list. Auto-select if exactly one account.
    updates = {
        "broker": "ctrader",
        "ctrader_access_token": access,
        "ctrader_refresh_token": refresh,
        "ctrader_accounts": accounts,
    }
    if len(accounts) == 1:
        a = accounts[0]
        updates["ctrader_account_id"] = a["ctid"]
        updates["ctrader_env"] = "live" if a["live"] else "demo"
    user_store.update(chat_id, updates)

    # Notify the client in Telegram (best-effort).
    try:
        from apex import telegram as tg
        if len(accounts) == 1:
            a = accounts[0]
            env = "LIVE 🔴" if a["live"] else "demo 🧪"
            tg.send_to(chat_id,
                       f"✅ <b>cTrader connected!</b>\n\nAccount <code>{a['ctid']}</code> ({env}) is linked.\n\n"
                       "You're in <b>paper mode</b> by default — test risk-free first.\n"
                       "When ready for real money: /env live\nStart trading: /start")
        elif accounts:
            lines = "\n".join(
                f"• <code>{a['ctid']}</code> — {'LIVE 🔴' if a['live'] else 'demo 🧪'}"
                for a in accounts)
            tg.send_to(chat_id,
                       "✅ <b>cTrader connected!</b>\n\nYou have multiple accounts:\n"
                       f"{lines}\n\nPick one with <code>/ctaccount &lt;id&gt;</code>")
        else:
            tg.send_to(chat_id, "⚠️ cTrader connected but no trading accounts were found. "
                       "Open a demo account in cTrader, then send /ctrader again.")
    except Exception as e:
        print(f"[cTrader OAuth] notify failed: {e}")

    return 200, _html("cTrader",
                      "<div class='h ok'>✅ Connected</div>"
                      "<div class='p'>Your cTrader account is linked. "
                      "You can close this page and return to Telegram.</div>")
