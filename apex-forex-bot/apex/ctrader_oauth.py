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
import os
import hmac
import time
import base64
import hashlib

from apex import config as cfg
from apex import user_store
from apex.brokers import ctrader

_STATE_TTL = 600  # 10 minutes to complete the authorization

# Growth-phase gate: only a live account at the partner broker counts (demo
# accounts and other brokers don't generate IB rebate). Set
# REQUIRE_LIVE_FP_MARKETS=false on Render to lift this back to "any cTrader
# account, demo or live" — e.g. for going back to the paid, broker-agnostic model.
_REQUIRE_LIVE_BROKER = (os.getenv("REQUIRE_LIVE_FP_MARKETS", "true").strip().lower() not in ("0", "false", "no"))
_ALLOWED_BROKER_SUBSTR = (os.getenv("REQUIRED_BROKER_NAME", "fp markets") or "").strip().lower()
# Owner's own test/demo accounts always pass the gate regardless of broker or
# live/demo — comma-separated ctids, e.g. "4258018,18000057".
_GATE_ALLOWLIST = {s.strip() for s in os.getenv("BROKER_GATE_ALLOWLIST", "").split(",") if s.strip()}


def broker_gate_reason(account: dict, access_token: str) -> str:
    """Empty string if `account` is allowed under the current growth-phase
    gate, else a short client-facing reason it was rejected. Does one extra
    cTrader call (brokerName isn't on the account-list response) only when
    the account is live — no point paying that cost for a demo account."""
    if not _REQUIRE_LIVE_BROKER:
        return ""
    if str(account.get("ctid")) in _GATE_ALLOWLIST:
        return ""
    if not account.get("live"):
        return ("demo accounts aren't eligible right now — free access requires a "
                "<b>live</b> account with our partner broker")
    try:
        broker = ctrader.get_broker_name(access_token, account["ctid"], "live")
    except Exception as e:
        return f"couldn't verify your broker ({str(e)[:80]}) — try again in a moment"
    if _ALLOWED_BROKER_SUBSTR not in broker.lower():
        return (f"this account is with <b>{broker or 'an unrecognized broker'}</b> — free access "
                f"requires a live account with our partner broker specifically")
    return ""

# Fallback for the case where cTrader does not echo the `state` param back to
# the redirect (it's standard OAuth2 but undocumented for cTrader). When a user
# runs /ctrader we record their chat_id here; if the callback arrives without a
# usable state, we bind it to the most recent pending authorization. The bot's
# poll loop and HTTP callback run in the SAME process, so this dict is shared.
_pending = {}  # chat_id -> ts


def _record_pending(chat_id):
    _pending[str(chat_id)] = int(time.time())


def _recent_pending():
    """Most recent chat_id that started authorization within the TTL, else None."""
    now = int(time.time())
    fresh = {c: t for c, t in _pending.items() if now - t <= _STATE_TTL}
    _pending.clear()
    _pending.update(fresh)
    if not fresh:
        return None
    return max(fresh, key=fresh.get)


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
    _record_pending(chat_id)
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
    # Prefer the signed state; fall back to the most recent pending /ctrader if
    # cTrader didn't echo state back (so onboarding works either way).
    chat_id = parse_state(state) or _recent_pending()
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
    bal, bal_err, gate_reason = None, None, ""
    if len(accounts) == 1:
        a = accounts[0]
        gate_reason = broker_gate_reason(a, access)
        if not gate_reason:
            updates["ctrader_account_id"] = a["ctid"]
            updates["ctrader_env"] = "live" if a["live"] else "demo"
            # Mirror the account's real balance into paper mode so the client sees
            # THEIR money, not an arbitrary $1000. Also a live connection check:
            # if this fails, candles/orders will fail identically — surface it now.
            # Right after OAuth the pooled socket is cold: connect, app auth,
            # account auth and the trader request all happen on a brand-new
            # TLS session, and the whole chain has been observed timing out
            # twice in a row (account_balance already retries once itself) —
            # the client then gets "Balance unavailable: timed out" while the
            # trading loop reads the same balance fine seconds later.
            #
            # One more attempt after a short pause covers the cold-start case
            # without making the browser wait through another full timeout in
            # the common path, where the first call simply works.
            for _attempt in (1, 2):
                try:
                    bal = ctrader.account_balance(access, a["ctid"],
                                                  updates["ctrader_env"])
                    updates["paper_balance"] = bal
                    bal_err = None
                    break
                except Exception as e:
                    bal_err = str(e)
                    print(f"[cTrader OAuth] balance attempt {_attempt} failed "
                          f"for {a['ctid']}: {e}")
                    if _attempt == 1:
                        time.sleep(2)
    user_store.update(chat_id, updates)
    _pending.pop(str(chat_id), None)

    # A loop that was already running (auto-restore at boot) still holds the OLD
    # token/balance — it reads the user record only at start. Restart it so the
    # fresh credentials and the mirrored balance take effect immediately.
    try:
        from apex import telegram as _tg
        _tg._restart_user_loop(chat_id)
    except Exception as e:
        print(f"[cTrader OAuth] loop restart failed: {e}")

    # Notify the client in Telegram (best-effort), ONCE.
    #
    # The whole block below fired twice in production — the client saw
    # "cTrader connected!" and the setup card duplicated. This endpoint is a
    # browser redirect target, so a reload, a prefetch, or a double tap
    # replays it, and during a Render deploy two instances are live and both
    # poll the same bot token. A shared claim collapses those into one
    # message; keyed on the account so linking a DIFFERENT account still
    # notifies. Short TTL: this guards a burst, not a later reconnect.
    _notify_key = f"ctconnect:{chat_id}:{updates.get('ctrader_account_id', '?')}"
    if user_store.claim(_notify_key, ttl_s=90) is False:
        print(f"[cTrader OAuth] duplicate callback for {chat_id} — not notifying twice")
        return 200, _html("cTrader",
                          "<div class='h ok'>✅ Connected</div>"
                          "<div class='p'>Your cTrader account is linked. "
                          "You can close this page and return to Telegram.</div>")
    try:
        from apex import telegram as tg
        if len(accounts) == 1 and gate_reason:
            a = accounts[0]
            live_link = os.getenv("BROKER_LIVE_LINK", "").strip()
            link_line = f"\n\n👉 {live_link}" if live_link else ""
            tg.send_to(chat_id,
                       f"❌ <b>Account not eligible</b>\n\n"
                       f"Account <code>{a['ctid']}</code> — {gate_reason}."
                       f"{link_line}\n\n"
                       "Once you have the right account, send /ctrader again.")
        elif len(accounts) == 1:
            a = accounts[0]
            env = "LIVE 🔴" if a["live"] else "demo 🧪"
            # Even after the retry, a cold connection can still time out. The
            # client does not need an error string for that — the number is
            # already known from the last successful read, and the loop will
            # refresh it within a tick. Showing a stale-but-labelled figure
            # beats showing a warning that reads like the account is broken.
            if bal is not None:
                bal_line = f"💰 Balance: <b>${bal:,.2f}</b>\n"
            else:
                _known = user_store.load(chat_id).get("paper_balance")
                if isinstance(_known, (int, float)) and _known:
                    bal_line = (f"💰 Balance: <b>${_known:,.2f}</b> "
                                f"<i>(last known — refreshing)</i>\n")
                else:
                    bal_line = (f"⏳ Balance loading… <i>{(bal_err or '')[:60]}</i>\n"
                                if bal_err else "")
            # A RECONNECT is not a first run. onboard_start() used to fire
            # unconditionally here, so re-authorising cTrader — a token
            # refresh, a re-link, tapping /ctrader again — threw an
            # already-configured client back into "Setup 1/2: what do you want
            # to trade?". Nothing was actually lost, but from the client's
            # side it is indistinguishable from the bot forgetting their
            # settings and abandoning an open position. That is a support
            # ticket every time, and worse on a live account.
            u_now = user_store.load(chat_id)
            already_set_up = bool(u_now.get("symbol") and u_now.get("strategy"))
            if not already_set_up:
                tg.send_to(chat_id,
                           f"✅ <b>cTrader connected!</b>\n\n"
                           f"Account <code>{a['ctid']}</code> ({env})\n"
                           f"{bal_line}\n"
                           "Setting up your bot — 2 quick taps. 👇")
                tg.onboard_start(chat_id)
            else:
                # Say what is still running, and name the open position — that
                # is the question a reconnect actually raises.
                pos = u_now.get("open_position_snapshot") or {}
                if pos.get("symbol"):
                    pos_line = (f"📊 Open position kept: <b>{pos.get('entrySide') or pos.get('side')} "
                                f"{pos['symbol']}</b> @ {pos.get('entryPrice')}\n"
                                f"   SL {pos.get('sl')} · TP {pos.get('tp')}\n")
                else:
                    pos_line = "📊 No open position.\n"
                what = ("🤖 Auto-Pilot" if u_now.get("autopilot")
                        else f"📈 {u_now.get('symbol')}")
                tg.send_to(chat_id,
                           f"✅ <b>cTrader reconnected!</b>\n\n"
                           f"Account <code>{a['ctid']}</code> ({env})\n"
                           f"{bal_line}"
                           f"{pos_line}\n"
                           f"Your setup is unchanged — {what}, "
                           f"{u_now.get('strategy')}, risk {float(u_now.get('risk', 0)):.1%}.\n"
                           "Nothing was reset. Send /settings to change anything.")
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
