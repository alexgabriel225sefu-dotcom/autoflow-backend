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

# Who is mid-authorization, for observability and for the escape hatch below.
# The bot's poll loop and the HTTP callback run in the SAME process, so this
# dict is shared between them.
_pending = {}  # chat_id -> ts

# A callback with no verifiable state cannot be attributed to anyone. There is
# no amount of care that turns "somebody authorized a broker account" into
# "THIS Telegram user authorized it" without a signed correlation value, and
# the consequence of getting it wrong is that one client's broker account —
# real money — is wired to another client's chat.
#
# So the fallback is OFF. Only a valid signed state links an account.
#
# The escape hatch exists because cTrader's echoing of `state` is undocumented,
# and if a broker-side change ever stops it, onboarding breaks for everyone
# with no way in. Setting CTRADER_ALLOW_STATELESS_CALLBACK=true re-enables the
# single-pending fallback — never the multi-pending guess, which was the actual
# vulnerability. It is a deliberate operator decision, logged on every use,
# not a default.
ALLOW_STATELESS = (os.getenv("CTRADER_ALLOW_STATELESS_CALLBACK", "")
                   .strip().lower() in ("1", "true", "yes", "on"))


class OAuthSigningSecretMissing(RuntimeError):
    """No secret is available to sign the OAuth `state` parameter."""


class StatelessCallbackInProduction(RuntimeError):
    """Raised at startup when production is configured to trust unsigned
    callbacks. Refusing to boot is the point: a service that starts in this
    configuration links broker accounts to whoever happens to be mid-flow."""


def _production() -> bool:
    # Imported lazily: user_store imports config, and config is imported by
    # half the package. The rule itself lives there and must not be forked —
    # it is deliberately inverted (unknown environment counts as production).
    from apex import user_store
    return user_store._is_production()


def assert_safe_config():
    """Refuse to start if production would accept unsigned OAuth callbacks.

    The escape hatch below exists for one scenario — cTrader silently stops
    echoing `state` and onboarding breaks for everyone with no way in. That is
    a development-time diagnosis, not a production posture: an unsigned
    callback cannot be attributed to a client, so accepting one in production
    means somebody's broker account can be wired to another person's chat.

    A warning would not be enough. The setting is a single environment
    variable, and a variable left on after a debugging session is exactly how
    this ends up live — the failure is silent, and the damage is somebody
    else's real money. So it fails at startup, loudly, before the first
    callback can arrive.
    """
    # A signing secret is not optional. Checked here so the failure lands at
    # startup rather than on the first client who tries to link an account.
    if not (cfg.TELEGRAM_BOT_TOKEN or cfg.CTRADER_CLIENT_SECRET):
        raise OAuthSigningSecretMissing(
            "No OAuth state signing secret is configured. `state` is what "
            "proves a callback belongs to the chat that began the flow, so "
            "without it one person's broker account can be bound to another "
            "person's chat. Set TELEGRAM_BOT_TOKEN (or CTRADER_CLIENT_SECRET).")
    if ALLOW_STATELESS and _production():
        raise StatelessCallbackInProduction(
            "CTRADER_ALLOW_STATELESS_CALLBACK is on and this is production. "
            "An unsigned OAuth callback cannot be attributed to a client, so "
            "it can bind one person's broker account to another person's "
            "chat. Unset it, or declare a development environment "
            "(APP_ENV=dev).")


def stateless_allowed() -> bool:
    """The escape hatch, as it actually applies at runtime.

    Defence in depth against `assert_safe_config` not having been called: even
    if something starts the service without the startup check, production
    still refuses. The startup failure is the loud path; this is the one that
    holds when the loud path is skipped.
    """
    if not ALLOW_STATELESS:
        return False
    try:
        if _production():
            print("[cTrader OAuth] ⛔ stateless callback requested but this is "
                  "production — refusing. This should have failed at startup.")
            return False
    except Exception:
        return False        # cannot establish the environment → refuse
    return True


def _record_pending(chat_id):
    _pending[str(chat_id)] = int(time.time())


def _fresh_pending():
    """Prune expired entries and return what is still in flight."""
    now = int(time.time())
    fresh = {c: t for c, t in _pending.items() if now - t <= _STATE_TTL}
    _pending.clear()
    _pending.update(fresh)
    return fresh


def _recent_pending():
    """Identify a stateless callback. Returns None unless explicitly enabled.

    The original returned `max(fresh)` — the most recent of however many people
    were mid-authorization. That is not a tie-break, it is an account-linking
    vulnerability: with two clients running /ctrader in the same ten minutes,
    a callback without a usable state binds one person's broker tokens to the
    other person's Telegram chat, and neither can tell it happened.

    Narrowing it to "exactly one pending" removed the two-client case but not
    the premise, which is that an unauthenticated callback is trusted at all:
    anyone who can reach the public callback URL while one client happens to
    be authorizing can still have their own broker account bound to that
    client's chat. Nothing in a stateless callback proves otherwise.
    """
    fresh = _fresh_pending()
    if not stateless_allowed():
        if fresh:
            print(f"[cTrader OAuth] REFUSED a callback with no valid state "
                  f"({len(fresh)} authorization(s) pending). An unsigned "
                  f"callback cannot be attributed to a client; the user must "
                  f"retry /ctrader.")
        return None
    if len(fresh) != 1:
        print(f"[cTrader OAuth] stateless callback allowed by config but "
              f"{len(fresh)} authorizations are pending — still refusing, "
              f"there is no way to tell which client this belongs to")
        return None
    who = next(iter(fresh))
    print(f"[cTrader OAuth] WARNING: binding a stateless callback to {who} "
          f"because CTRADER_ALLOW_STATELESS_CALLBACK is on. This trusts an "
          f"unauthenticated callback — turn it off once state round-trips.")
    return who


_used_states = {}          # state -> ts, for the no-Redis single-instance case


def _consume_state(state) -> bool:
    """Redeem a state exactly once. False means it was already used — or that
    we could not establish that it wasn't.

    Replay protection has to be AUTHORITATIVE, which means shared. The previous
    version fell back to an in-process set when the claim could not be made,
    and that set cannot see another container: instance A consumes the state,
    Redis blips, instance B receives the same signed state and its own memory
    says nothing about it. The state is accepted twice, and the second
    acceptance links a broker account.

    So an unavailable claim is now a REJECTION, not a fallback. The cost is
    that a client authorizing during a Redis outage must retry; the cost of the
    alternative is a broker account bound twice.

    The in-process set remains only for the declared local-development case,
    where there is exactly one process and nothing to disagree with it.
    """
    from apex import user_store
    h = hashlib.sha256(str(state).encode()).hexdigest()[:32]
    got = user_store.claim(f"oauth:state:{h}", ttl_s=_STATE_TTL * 2)
    if got is False:
        return False
    if got is True:
        return True

    # got is None: no shared backend, or it errored.
    if getattr(user_store, "_USE_REDIS", False):
        print("[cTrader OAuth] ⛔ replay protection unavailable — REJECTING the "
              "callback. A state that cannot be proven unused must not link an "
              "account.")
        return False
    # Single-process development only. user_store refuses to start without a
    # shared backend unless ALLOW_LOCAL_BACKEND_DEV was declared, so reaching
    # here means there is genuinely only one process.
    now = int(time.time())
    for k, t in list(_used_states.items()):
        if now - t > _STATE_TTL * 2:
            _used_states.pop(k, None)
    if h in _used_states:
        return False
    _used_states[h] = now
    return True


def _secret() -> bytes:
    """The key that signs the OAuth `state`. No literal fallback.

    This used to end in `or "apex"` — a string published in this repository.
    `state` is what proves a callback belongs to the chat that started the
    flow; anyone who can forge one can bind THEIR cTrader account to SOMEBODY
    ELSE'S Telegram chat, or the reverse. A signing key readable from the
    source is not a key.

    The bot token is always set in any deployment that can talk to Telegram at
    all, so this is unreachable in practice — which is exactly why it must
    raise rather than paper over it. An unreachable branch that silently
    weakens a signature is the kind that gets reached after some future
    refactor moves config loading around.
    """
    raw = cfg.TELEGRAM_BOT_TOKEN or cfg.CTRADER_CLIENT_SECRET
    if not raw:
        raise OAuthSigningSecretMissing(
            "No OAuth state signing secret: set TELEGRAM_BOT_TOKEN (or "
            "CTRADER_CLIENT_SECRET). Without one, a callback cannot be tied "
            "to the chat that started it.")
    return raw.encode()


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
    # A signed state is the ONLY thing that attributes this callback to a
    # client. The stateless path is off unless an operator turns it on, and it
    # says so loudly when it fires.
    chat_id = parse_state(state)
    if chat_id and not _consume_state(state):
        # Valid signature, but this exact state has already been redeemed.
        # The signature alone does not make a state single-use: it stays valid
        # for its whole TTL, so a captured callback URL could be replayed to
        # re-link an account.
        print(f"[cTrader OAuth] REFUSED a replayed state for {chat_id}")
        chat_id = None
    if not chat_id:
        chat_id = _recent_pending()
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
            bal, bal_err = ctrader.account_balance_retry(
                access, a["ctid"], updates["ctrader_env"])
            if bal is not None:
                updates["paper_balance"] = bal
    # STRICT: this is the only moment these tokens exist. The authorization
    # code has already been exchanged and cannot be replayed, so a write that
    # silently does not land leaves the client looking connected while the bot
    # holds no credentials — and the only way back is to authorize again, which
    # nothing tells them to do. Fail visibly instead.
    try:
        user_store.update(chat_id, updates, strict=True)
    except Exception as e:
        print(f"[cTrader OAuth] CREDENTIAL WRITE FAILED for {chat_id}: {e}")
        return 500, _html("cTrader", "<div class='h err'>Could not save the connection</div>"
                          "<div class='p'>Your broker authorized us, but we could not store "
                          "the connection. Nothing was linked. Please return to Telegram and "
                          "send /ctrader to try again.</div>")
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
            u_now = user_store.load(chat_id)
            bal_line = tg.balance_line_from(bal, bal_err,
                                            u_now.get("paper_balance"))
            if not tg.already_onboarded(u_now):
                tg.send_to(chat_id,
                           f"✅ <b>cTrader connected!</b>\n\n"
                           f"Account <code>{a['ctid']}</code> ({env})\n"
                           f"{bal_line}\n"
                           "Setting up your account — 2 quick taps. 👇")
                tg.onboard_start(chat_id)
            else:
                tg.send_to(chat_id, tg.reconnect_summary(
                    u_now,
                    f"✅ <b>cTrader reconnected!</b>\n\n"
                    f"Account <code>{a['ctid']}</code> ({env})\n{bal_line}"))
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
