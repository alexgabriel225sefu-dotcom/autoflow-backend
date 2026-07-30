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
import functools
import json
import os
import time
import uuid

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

# One shared session so a transient network blip (DNS hiccup, Upstash/Telegram
# 502) gets retried with backoff instead of turning into an unhandled
# exception on every single call to that host.
_session = requests.Session()
_retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
_session.mount("https://", HTTPAdapter(max_retries=_retries))
_session.mount("http://", HTTPAdapter(max_retries=_retries))

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

# Affiliate/referral bot — its data lives in Supabase behind the website API,
# and it's a thin Telegram front-end, so it's reached over HTTP (not the Redis
# bus): admin-list + telegram-stats for reads, its bot token for messaging.
_SITE = (os.getenv("SITE_URL") or "https://aicashsystem.space").rstrip("/")
_AFF_SECRET = os.getenv("AFFILIATE_BOT_SECRET") or ""
_AFF_TOKEN = os.getenv("AFFILIATE_BOT_TOKEN") or ""


def _ns(product: str) -> str:
    p = (product or "").strip().lower()
    if p not in _PRODUCTS:
        raise ValueError(f"product must be one of {sorted(_PRODUCTS)}")
    return p


def _redis(product: str, *parts):
    cfg = _REDIS.get(product, _REDIS["forex"])
    try:
        r = _session.post(cfg["url"], json=[str(p) for p in parts],
                          headers={"Authorization": f"Bearer {cfg['token']}"}, timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Upstash request failed: {e}") from e
    return r.json().get("result")


def _call(product: str, action: str, args: dict = None, timeout: float = 20.0):
    """Send a command to the bot and wait for its result."""
    ns = _ns(product)
    cid = uuid.uuid4().hex[:16]
    _redis(ns, "LPUSH", f"{ns}:commands", json.dumps(
        {"id": cid, "action": action, "args": args or {}, "ts": int(time.time())}))
    deadline = time.time() + timeout
    key = f"{ns}:cmdresult:{cid}"
    while time.time() < deadline:
        try:
            raw = _redis(ns, "GET", key)
        except RuntimeError:
            # A transient Upstash blip mid-poll shouldn't fail the whole
            # command — keep polling until the deadline.
            raw = None
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


def _tool_safe(fn):
    """Turn any unexpected exception (bad input, Upstash/Telegram outage,
    malformed data) into a plain error dict instead of an unhandled
    traceback — one flaky call must never look like the connector is down."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            return {"error": str(e)}
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"unexpected error in {fn.__name__}: {e}"}
    return wrapper


# ─── Read tools ────────────────────────────────────────────
@mcp.tool()
@_tool_safe
def bot_alive(product: str) -> dict:
    """Is the crypto/forex bot alive? Returns seconds since its last heartbeat."""
    ns = _ns(product)
    hb = _redis(ns, "GET", f"{ns}:mcp_heartbeat")
    if not hb:
        return {"alive": False, "reason": "no heartbeat — bot down or control plane off"}
    age = int(time.time()) - int(hb)
    return {"alive": age < 120, "last_seen_sec_ago": age}


@mcp.tool()
@_tool_safe
def bot_status(product: str) -> dict:
    """Live snapshot: active users and each one's symbol, strategy, running
    state, balance and connected cTrader account. product = crypto | forex."""
    return _call(product, "status")


@mcp.tool()
@_tool_safe
def user_detail(product: str, user_id: str) -> dict:
    """Full (token-redacted) settings + dashboard for one user."""
    return _call(product, "user_detail", {"user_id": user_id})


@mcp.tool()
@_tool_safe
def ctrader_account(product: str, user_id: str) -> dict:
    """Live cTrader balance + all open positions for a user, read fresh from
    the broker."""
    return _call(product, "ctrader_account", {"user_id": user_id})


@mcp.tool()
@_tool_safe
def recent_events(product: str, limit: int = 40) -> dict:
    """Recent notable events (errors, closes, health, stops) — newest first.
    Read straight from Redis, so it works even if the bot is down."""
    return {"events": _lrange(product, "events", limit)}


@mcp.tool()
@_tool_safe
def audit_log(product: str, limit: int = 40) -> dict:
    """Every remote command executed on the bot — the tamper-evident trail."""
    return {"audit": _lrange(product, "audit", limit)}


@mcp.tool()
@_tool_safe
def recent_commands(product: str, limit: int = 60) -> dict:
    """What clients sent in Telegram (level tg_in) and the exact orders the bot
    sent to cTrader (level order) — newest first."""
    evs = _lrange(product, "events", 200)
    keep = [e for e in evs if e.get("level") in ("tg_in", "order")]
    return {"commands": keep[:max(1, int(limit))]}


# ─── Action tools (need MCP_CONTROL_ENABLED=true on the bot) ──
@mcp.tool()
@_tool_safe
def restart_user(product: str, user_id: str) -> dict:
    """Restart a user's trading loop (heals a stuck/desynced loop)."""
    return _call(product, "restart_loop", {"user_id": user_id})


@mcp.tool()
@_tool_safe
def bot_power(product: str, user_id: str, on: bool) -> dict:
    """Turn a user's bot ON (start trading) or OFF (pause)."""
    return _call(product, "bot_on" if on else "bot_off", {"user_id": user_id})


@mcp.tool()
@_tool_safe
def refresh_ctrader_token(product: str, user_id: str) -> dict:
    """Force a cTrader token refresh + reconnect for a user (heals auth errors)."""
    return _call(product, "refresh_token", {"user_id": user_id})


@mcp.tool()
@_tool_safe
def set_user_setting(product: str, user_id: str, key: str, value) -> dict:
    """Change one strategy/risk setting for a user (e.g. strategy, risk, symbol,
    timeframe, trailing, max_trades_day) and restart their loop. Auth/token/
    license fields are not settable."""
    return _call(product, "set_setting", {"user_id": user_id, "key": key, "value": value})


@mcp.tool()
@_tool_safe
def send_telegram(product: str, user_id: str, text: str) -> dict:
    """Send a Telegram message to a user from the bot."""
    return _call(product, "send_message", {"user_id": user_id, "text": text})


@mcp.tool()
@_tool_safe
def force_close(product: str, user_id: str) -> dict:
    """Immediately close a user's open position at the broker."""
    return _call(product, "force_close", {"user_id": user_id})


@mcp.tool()
@_tool_safe
def open_trade(product: str, user_id: str, side: str, symbol: str = None) -> dict:
    """Open a trade on command: side = BUY or SELL, optional symbol (defaults to
    the user's current symbol). SAFETY: demo accounts only — the bot refuses on a
    real-money account, so this can never place a live order remotely."""
    args = {"user_id": user_id, "side": side}
    if symbol:
        args["symbol"] = symbol
    return _call(product, "force_trade", args)


# ─── Affiliate / referral bot (over the website API) ─────────
def _site_post(path: str, body: dict, timeout: float = 15.0):
    r = _session.post(f"{_SITE}{path}", json=body, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"error": f"HTTP {r.status_code}"}


@mcp.tool()
@_tool_safe
def affiliates_overview() -> dict:
    """All affiliates with their sales totals (paid / pending / refunded) —
    the referral program at a glance."""
    if not _AFF_SECRET:
        return {"error": "AFFILIATE_BOT_SECRET not set on the MCP server"}
    d = _site_post("/api/affiliates/admin-list", {"secret": _AFF_SECRET})
    affs = d.get("affiliates") or []
    tot = {"affiliates": len(affs),
           "sales": sum(a["sales"]["total"] for a in affs),
           "paid_cents": sum(a["sales"]["paid"] for a in affs),
           "pending_cents": sum(a["sales"]["pending"] for a in affs)}
    return {"totals": tot, "affiliates": affs}


@mcp.tool()
@_tool_safe
def affiliate_stats(chat_id: str) -> dict:
    """Live earnings/clicks/sales for one affiliate by their Telegram chat id."""
    if not _AFF_SECRET:
        return {"error": "AFFILIATE_BOT_SECRET not set on the MCP server"}
    return _site_post("/api/affiliates/telegram-stats",
                      {"chatId": chat_id, "secret": _AFF_SECRET})


@mcp.tool()
@_tool_safe
def message_affiliate(chat_id: str, text: str) -> dict:
    """Send a Telegram message to an affiliate from the referral bot."""
    if not _AFF_TOKEN:
        return {"error": "AFFILIATE_BOT_TOKEN not set on the MCP server"}
    r = _session.post(f"https://api.telegram.org/bot{_AFF_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": text[:3500],
                            "parse_mode": "HTML", "disable_web_page_preview": True},
                      timeout=10)
    return {"sent": r.ok, "status": r.status_code}


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
