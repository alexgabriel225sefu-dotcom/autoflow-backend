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
import json
import os
import time
import uuid

import requests
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP

_URL = (os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
_SECRET = os.getenv("RUFLO_MCP_SECRET") or "ruflo"
_PRODUCTS = {"crypto", "forex"}


def _ns(product: str) -> str:
    p = (product or "").strip().lower()
    if p not in _PRODUCTS:
        raise ValueError(f"product must be one of {sorted(_PRODUCTS)}")
    return p


def _redis(*parts):
    r = requests.post(_URL, json=[str(p) for p in parts],
                      headers={"Authorization": f"Bearer {_TOKEN}"}, timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def _call(product: str, action: str, args: dict = None, timeout: float = 20.0):
    """Send a command to the bot and wait for its result."""
    ns = _ns(product)
    cid = uuid.uuid4().hex[:16]
    _redis("LPUSH", f"{ns}:commands", json.dumps(
        {"id": cid, "action": action, "args": args or {}, "ts": int(time.time())}))
    deadline = time.time() + timeout
    key = f"{ns}:cmdresult:{cid}"
    while time.time() < deadline:
        raw = _redis("GET", key)
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
    raw = _redis("LRANGE", f"{ns}:{key}", 0, max(1, min(int(n), 200)) - 1) or []
    out = []
    for r in raw:
        try:
            out.append(json.loads(r))
        except Exception:
            pass
    return out


mcp = FastMCP("ruflo", stateless_http=True)


# ─── Read tools ────────────────────────────────────────────
@mcp.tool()
def bot_alive(product: str) -> dict:
    """Is the crypto/forex bot alive? Returns seconds since its last heartbeat."""
    ns = _ns(product)
    hb = _redis("GET", f"{ns}:mcp_heartbeat")
    if not hb:
        return {"alive": False, "reason": "no heartbeat — bot down or control plane off"}
    age = int(time.time()) - int(hb)
    return {"alive": age < 30, "last_seen_sec_ago": age}


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


# Mount the MCP app behind the secret path: https://<host>/<secret>/mcp
app = Starlette(routes=[Mount(f"/{_SECRET}", app=mcp.streamable_http_app())])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
