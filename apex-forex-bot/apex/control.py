"""Remote control plane over Redis — powers the Ruflo MCP server.

The MCP server (hosted by the operator, wired into Claude as a custom connector)
never touches the bot process directly. Instead it uses the shared Redis
as a message bus:

  • the bot LPUSHes notable events to  {ns}:events   (a capped ring buffer)
  • the MCP server LPUSHes commands to  {ns}:commands (JSON: {id, action, args})
  • the bot pops a command, runs the matching handler, and writes the result to
    {ns}:cmdresult:{id}  (short TTL); the MCP server polls that key
  • every executed command is appended to {ns}:audit for a tamper-evident trail
  • {ns}:heartbeat is refreshed so the MCP server knows the bot is alive

Safety:
  • Read actions always work. WRITE actions (restart, set-setting, send-message,
    power on/off, close) run ONLY when MCP_CONTROL_ENABLED is truthy — a single
    env var the operator can flip to instantly revoke remote action capability.
  • Handlers are injected by bot.py, so this module stays dependency-free and
    can't import the bot in a cycle.
"""
import json
import os
import threading
import time

import requests as _req

# ─── Backend selection (same priority as user_store) ──────
_REDIS_URL = os.getenv("REDIS_URL", "")

_URL   = (os.getenv("UPSTASH_REDIS_REST_URL")   or "").rstrip("/")
_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""

_BACKEND = "none"
_r = None

if _REDIS_URL:
    try:
        import redis as _redis_lib
        _r = _redis_lib.from_url(_REDIS_URL, decode_responses=True,
                                 socket_connect_timeout=5, socket_timeout=8,
                                 retry_on_timeout=True)
        _r.ping()
        _BACKEND = "redis"
    except Exception as e:
        print(f"[Control] REDIS_URL set but connection failed: {e}")
        _r = None

if _BACKEND == "none" and _URL and _TOKEN:
    _BACKEND = "upstash"

_ENABLED_STORE = _BACKEND != "none"

_NS = (os.getenv("PRODUCT") or "forex").strip().lower()
K_EVENTS   = f"{_NS}:events"
K_COMMANDS = f"{_NS}:commands"
K_AUDIT    = f"{_NS}:audit"
K_HEART    = f"{_NS}:mcp_heartbeat"
_RESULT    = lambda cid: f"{_NS}:cmdresult:{cid}"

WRITE_ACTIONS = {"restart_loop", "bot_on", "bot_off", "refresh_token",
                 "set_setting", "send_message", "force_close", "force_trade"}


def actions_enabled() -> bool:
    return (os.getenv("MCP_CONTROL_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


# ─── Redis commands (standard or Upstash REST) ────────────
def _cmd(*parts):
    if not _ENABLED_STORE:
        return None
    if _BACKEND == "redis":
        try:
            cmd_name = parts[0].upper()
            args = parts[1:]
            if cmd_name == "SET":
                return _r.set(args[0], args[1])
            elif cmd_name == "GET":
                return _r.get(args[0])
            elif cmd_name == "LPUSH":
                return _r.lpush(args[0], args[1])
            elif cmd_name == "LTRIM":
                return _r.ltrim(args[0], int(args[1]), int(args[2]))
            elif cmd_name == "RPOP":
                return _r.rpop(args[0])
            elif cmd_name == "EXPIRE":
                return _r.expire(args[0], int(args[1]))
            elif cmd_name == "LRANGE":
                return _r.lrange(args[0], int(args[1]), int(args[2]))
            else:
                return _r.execute_command(*parts)
        except Exception as e:
            print(f"[Control] redis {parts[0] if parts else '?'} failed: {e}")
            return None
    try:
        r = _req.post(_URL, json=[str(p) for p in parts],
                      headers={"Authorization": f"Bearer {_TOKEN}"}, timeout=8)
        r.raise_for_status()
        return r.json().get("result")
    except Exception as e:
        print(f"[Control] redis {parts[0] if parts else '?'} failed: {e}")
        return None


# ─── Event ring buffer ────────────────────────────────────
_LEVEL_FOR = {
    "AI_ERROR": "error", "DATA_ERROR": "error", "BROKER_HEALTH": "warn",
    "STOP": "warn", "NEWS_WARN": "info", "FLASH_WARN": "warn",
    "STOP_MOVED": "info", "CLOSE": "trade", "BROKER_CLOSE": "trade",
    "BROKER_CLOSE_MULTI": "trade", "BUY": "trade", "SELL": "trade",
}


def event(level, msg, user_id=None, extra=None):
    """Record a notable event to the ring buffer (kept to the last 200)."""
    if not _ENABLED_STORE:
        return
    rec = {"ts": int(time.time()), "level": level, "msg": str(msg)[:400]}
    if user_id is not None:
        rec["user"] = str(user_id)
    if extra:
        rec["extra"] = extra
    _cmd("LPUSH", K_EVENTS, json.dumps(rec))
    _cmd("LTRIM", K_EVENTS, 0, 199)


def event_from_alert(user_id, result):
    """Tee a per-user alert into the event log so the operator can see the same
    stream the client sees — errors, closes, health, stops."""
    action = (result or {}).get("action", "")
    if action in ("HEARTBEAT", "MARKET_PULSE", "SKIP_WARN"):
        return
    level = _LEVEL_FOR.get(action, "info")
    sym = result.get("symbol", "")
    bits = [action, sym]
    for k in ("reason", "reasons", "event", "netPnl", "sl", "side", "price"):
        if result.get(k) not in (None, ""):
            bits.append(f"{k}={result[k]}")
    event(level, " ".join(str(b) for b in bits if b), user_id=user_id)


# ─── Command consumer ─────────────────────────────────────
def _record_result(cid, ok, data):
    payload = json.dumps({"id": cid, "ok": ok, "data": data, "ts": int(time.time())})
    _cmd("SET", _RESULT(cid), payload)
    _cmd("EXPIRE", _RESULT(cid), 180)


def _audit(entry):
    _cmd("LPUSH", K_AUDIT, json.dumps(entry))
    _cmd("LTRIM", K_AUDIT, 0, 499)


def start_consumer(handlers, poll=10.0, heartbeat_interval=60.0):
    """Spawn the daemon that executes MCP commands. `handlers` is
    {action: callable(args:dict) -> json-able result}.

    poll: seconds between command checks (10s default — ~260K cmds/month).
    heartbeat_interval: seconds between heartbeat writes (60s — ~43K cmds/month).
    Total ~300K cmds/month per bot, well within Upstash free 500K.
    """
    if not _ENABLED_STORE:
        print("[Control] No Redis configured — MCP control plane OFF")
        return

    def _run():
        print(f"[Control] MCP control plane ON (ns={_NS}, backend={_BACKEND}, "
              f"poll={poll}s, heartbeat={heartbeat_interval}s, "
              f"actions={'enabled' if actions_enabled() else 'READ-ONLY'})")
        last_heartbeat = 0
        while True:
            try:
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    _cmd("SET", K_HEART, int(now))
                    last_heartbeat = now
                raw = _cmd("RPOP", K_COMMANDS)
                if not raw:
                    time.sleep(poll)
                    continue
                cmd = json.loads(raw)
                cid = cmd.get("id") or str(int(time.time() * 1000))
                action = cmd.get("action", "")
                args = cmd.get("args") or {}
                if action in WRITE_ACTIONS and not actions_enabled():
                    _record_result(cid, False, "write actions disabled "
                                   "(set MCP_CONTROL_ENABLED=true to allow)")
                    continue
                fn = handlers.get(action)
                if not fn:
                    _record_result(cid, False, f"unknown action: {action}")
                    continue
                try:
                    data = fn(args)
                    _record_result(cid, True, data)
                    _audit({"ts": int(time.time()), "action": action,
                            "args": args, "ok": True})
                except Exception as e:
                    _record_result(cid, False, str(e)[:300])
                    _audit({"ts": int(time.time()), "action": action,
                            "args": args, "ok": False, "err": str(e)[:200]})
            except Exception as e:
                print(f"[Control] consumer loop error: {e}")
                time.sleep(poll)

    threading.Thread(target=_run, daemon=True).start()
