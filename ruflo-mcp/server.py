"""Ruflo MCP server — a remote control connector for the Apex trading bots.

Hosted by the operator and wired into Claude as a custom connector. It talks to
the SAME Upstash Redis the bots use:

  • reads the bots' event ring buffer + audit trail directly
  • sends commands on {ns}:commands and polls {ns}:cmdresult:{id} for the reply
    (the bot executes them — see apex/control.py + apex/control_actions.py)

Security:
  • Mounted behind a secret path segment: RUFLO_MCP_SECRET. The connector URL is
    https://<host>/<secret>/mcp — without the secret you get 404.
  • Write actions additionally require MCP_CONTROL_ENABLED=true ON THE BOTS, an
    independent kill-switch the operator controls.
  • Only the operator has the Upstash creds this server needs.

Env:
  UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN   (same as the bots)
  RUFLO_MCP_SECRET                                    (path secret for the URL)
  PORT                                                (Render sets this)
"""
import hashlib
import hmac
import json
import os
import time
import uuid

import requests
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

_REDIS = {
    "forex": {
        "url": (os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/"),
        "token": os.getenv("UPSTASH_REDIS_REST_TOKEN") or "",
    },
    "crypto": {
        "url": (os.getenv("UPSTASH_CRYPTO_URL")
                or os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/"),
        "token": (os.getenv("UPSTASH_CRYPTO_TOKEN")
                  or os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""),
    },
}
_SECRET = os.getenv("RUFLO_MCP_SECRET") or "ruflo"
_PRODUCTS = {"crypto", "forex"}

_SITE = (os.getenv("SITE_URL") or "https://aicashsystem.space").rstrip("/")


def _ns(product: str) -> str:
    p = (product or "").strip().lower()
    if p not in _PRODUCTS:
        raise ValueError(f"product must be one of {sorted(_PRODUCTS)}")
    return p


def _redis(product: str, *parts):
    cfg = _REDIS.get(product, _REDIS["forex"])
    r = requests.post(cfg["url"], json=[str(p) for p in parts],
                      headers={"Authorization": f"Bearer {cfg['token']}"}, timeout=10)
    r.raise_for_status()
    return r.json().get("result")


# Who this server acts as, and the secret that proves it.
#
# The bot refuses level 2 and level 3 commands from an operator it cannot
# identify. A name alone is not identification — anyone who can write to the
# command queue could type one — so when MCP_SIGNING_SECRET is set the envelope
# is signed and the bot verifies it. The secret is shared between this server
# and the bot, and nothing else needs it.
OPERATOR = (os.getenv("MCP_OPERATOR_NAME") or "").strip()
SIGNING_SECRET = (os.getenv("MCP_SIGNING_SECRET") or "").strip()


def _sign(envelope: dict) -> str:
    """HMAC over the canonical envelope. Empty when no secret is configured."""
    if not SIGNING_SECRET:
        return ""
    payload = json.dumps({k: envelope[k] for k in ("id", "action", "args", "ts",
                                                   "operator")},
                         sort_keys=True, separators=(",", ":"))
    return hmac.new(SIGNING_SECRET.encode(), payload.encode(),
                    hashlib.sha256).hexdigest()


def _call(product: str, action: str, args: dict = None, timeout: float = 20.0):
    """Send a command to the bot and wait for its result."""
    ns = _ns(product)
    cid = uuid.uuid4().hex[:16]
    envelope = {"id": cid, "action": action, "args": args or {},
                "ts": int(time.time()), "operator": OPERATOR}
    sig = _sign(envelope)
    if sig:
        envelope["sig"] = sig
    _redis(ns, "LPUSH", f"{ns}:commands", json.dumps(envelope))
    deadline = time.time() + timeout
    key = f"{ns}:cmdresult:{cid}"
    while time.time() < deadline:
        raw = _redis(ns, "GET", key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return {"ok": False, "data": "unparseable result"}
        time.sleep(1.0)
    return {"ok": False, "data": f"timeout — the {ns} bot did not answer in "
            f"{timeout:g}s (is it deployed and running?)"}


def _lrange(product: str, key: str, n: int):
    ns = _ns(product)
    raw = _redis(ns, "LRANGE", f"{ns}:{key}", 0, max(1, min(int(n), 200)) - 1) or []
    out = []
    for r in raw:
        try:
            out.append(json.loads(r))
        except Exception:
            pass
    return out


# Serve the MCP endpoint natively at /<secret>/mcp — mounting FastMCP under a
# Starlette prefix skips its lifespan, which never starts the session manager
# (the endpoint then dies with a connect error). Setting the path here keeps the
# lifespan intact. DNS-rebinding protection is off because the secret path is the
# guard and the real host (…onrender.com) isn't localhost.
mcp = FastMCP(
    "ruflo",
    stateless_http=True,
    streamable_http_path=f"/{_SECRET}/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ─── Read tools ────────────────────────────────────────────
@mcp.tool()
def bot_alive(product: str) -> dict:
    """Is the crypto/forex bot alive? Returns seconds since its last heartbeat."""
    ns = _ns(product)
    hb = _redis(ns, "GET", f"{ns}:mcp_heartbeat")
    if not hb:
        return {"alive": False, "reason": "no heartbeat — bot down or control plane off"}
    age = int(time.time()) - int(hb)
    return {"alive": age < 120, "last_seen_sec_ago": age}


@mcp.tool()
def bot_status(product: str) -> dict:
    """Live snapshot: active users and each one's symbol, strategy, running
    state, balance and connected cTrader account. product = crypto | forex."""
    return _call(product, "status")


@mcp.tool()
def user_detail(product: str, user_id: str) -> dict:
    """Full (token-redacted) settings + dashboard for one user."""
    return _call(product, "user_detail", {"user_id": user_id})


@mcp.tool()
def ctrader_account(product: str, user_id: str) -> dict:
    """Live cTrader balance + all open positions for a user, read fresh from
    the broker."""
    return _call(product, "ctrader_account", {"user_id": user_id})


@mcp.tool()
def recent_events(product: str, limit: int = 40) -> dict:
    """Recent notable events (errors, closes, health, stops) — newest first.
    Read straight from Redis, so it works even if the bot is down."""
    return {"events": _lrange(product, "events", limit)}


@mcp.tool()
def audit_log(product: str, limit: int = 40) -> dict:
    """Every remote command executed on the bot — the tamper-evident trail."""
    return {"audit": _lrange(product, "audit", limit)}


@mcp.tool()
def recent_commands(product: str, limit: int = 60) -> dict:
    """What clients sent in Telegram (level tg_in) and the exact orders the bot
    sent to cTrader (level order) — newest first."""
    evs = _lrange(product, "events", 200)
    keep = [e for e in evs if e.get("level") in ("tg_in", "order")]
    return {"commands": keep[:max(1, int(limit))]}


# ─── Action tools (need MCP_CONTROL_ENABLED=true on the bot) ──
@mcp.tool()
def restart_user(product: str, user_id: str) -> dict:
    """Restart a user's trading loop (heals a stuck/desynced loop)."""
    return _call(product, "restart_loop", {"user_id": user_id})


@mcp.tool()
def bot_power(product: str, user_id: str, on: bool) -> dict:
    """Turn a user's bot ON (start trading) or OFF (pause)."""
    return _call(product, "bot_on" if on else "bot_off", {"user_id": user_id})


@mcp.tool()
def refresh_ctrader_token(product: str, user_id: str) -> dict:
    """Force a cTrader token refresh + reconnect for a user (heals auth errors)."""
    return _call(product, "refresh_token", {"user_id": user_id})


@mcp.tool()
def set_user_setting(product: str, user_id: str, key: str, value) -> dict:
    """Change one strategy/risk setting for a user (e.g. strategy, risk, symbol,
    timeframe, trailing, max_trades_day) and restart their loop. Auth/token/
    license fields are not settable."""
    return _call(product, "set_setting", {"user_id": user_id, "key": key, "value": value})


@mcp.tool()
def send_telegram(product: str, user_id: str, text: str) -> dict:
    """Send a Telegram message to a user from the bot."""
    return _call(product, "send_message", {"user_id": user_id, "text": text})


@mcp.tool()
def force_close(product: str, user_id: str) -> dict:
    """Immediately close a user's open position at the broker."""
    return _call(product, "force_close", {"user_id": user_id})


@mcp.tool()
def open_trade(product: str, user_id: str, side: str, symbol: str = None) -> dict:
    """Open a trade on command: side = BUY or SELL, optional symbol (defaults to
    the user's current symbol). SAFETY: demo accounts only — the bot refuses on a
    real-money account, so this can never place a live order remotely."""
    args = {"user_id": user_id, "side": side}
    if symbol:
        args["symbol"] = symbol
    return _call(product, "force_trade", args)


@mcp.tool()
def client_message(product: str, user_id: str, text: str) -> dict:
    """Send `text` to the bot AS THE CLIENT — the bot handles it and replies in
    their Telegram, exactly as if they had typed it.

    This drives the real command dispatch (same access checks, same handlers,
    same replies), so it is the way to verify what a client actually gets
    rather than reading the code and hoping. Use it for read-only and
    configuration commands: /status, /help, /strategy, /risk, /summary,
    /verbose, /report, /news, or plain-language questions.

    REFUSED, by design: /reset, /paper, /env, /setkeys, /deploy, /purgebad,
    /grant, /revoke, /buy, /sell, /close. Those are destructive or move real
    money and must be sent by the account owner. Use open_trade / force_close
    for trades — they are separately audited and demo-only."""
    return _call(product, "client_message", {"user_id": user_id, "text": text})


def _site_post(path: str, body: dict, timeout: float = 15.0):
    r = requests.post(f"{_SITE}{path}", json=body, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"error": f"HTTP {r.status_code}"}

async def _health(request):
    return PlainTextResponse("ruflo-mcp ok")


# The MCP app already serves /<secret>/mcp (with its lifespan). Add a root health
# check for Render. Connector URL: https://<host>/<secret>/mcp
app = mcp.streamable_http_app()
app.router.routes.append(Route("/", _health))
app.router.routes.append(Route("/healthz", _health))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
