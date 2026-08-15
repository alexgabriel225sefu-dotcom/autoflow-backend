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

# ─── Capability levels ────────────────────────────────────
# An operations assistant reads state; it does not move money. Before this,
# `force_trade` and `force_close` rode the SAME switch as `restart_loop`, so
# turning on remote restarts also handed out order placement and position
# closing. Levels split them, and each level has its own gate.
#
#   1 READ ONLY            always available
#   2 CONTROLLED OPS       MCP_CONTROL_ENABLED, and the caller must confirm
#   3 FINANCIAL            MCP_FINANCIAL_ENABLED, off by default, separately
#
# Anything not listed is treated as level 3. An action nobody classified is an
# action nobody thought about, and the safe reading of that is "the dangerous
# kind" — a new handler cannot become remotely callable by being forgotten.
LEVEL_1_READ = {
    "status", "user_detail", "events", "ctrader_account", "audit_log",
    "affiliates_overview", "affiliate_stats", "recent_commands", "recent_events",
    "bot_alive", "bot_status",
    # The ops API (see apex/ops_api.py). All read-only by construction.
    "ops_system_health", "ops_user_health", "ops_user_license",
    "ops_user_broker_status", "ops_user_risk", "ops_user_positions",
    "ops_user_orders", "ops_user_worker_status", "ops_user_ownership",
    "ops_user_incidents", "ops_recent_errors", "ops_reconcile_status",
    "ops_investigate", "ops_degraded_users", "ops_unprotected_positions",
}
LEVEL_2_CONTROLLED = {
    "restart_loop", "bot_on", "bot_off", "refresh_token", "set_setting",
    "send_message", "message_affiliate", "client_message",
}
LEVEL_3_FINANCIAL = {"force_close", "force_trade"}

# Level-2 actions that change what the bot DOES rather than merely restarting
# it still need MCP_CONTROL_ENABLED; confirmation is enforced per-call.
CONFIRM_REQUIRED = LEVEL_2_CONTROLLED


def level_of(action) -> int:
    if action in LEVEL_1_READ:
        return 1
    if action in LEVEL_2_CONTROLLED:
        return 2
    return 3                     # unlisted == financial == denied by default


def actions_enabled() -> bool:
    return (os.getenv("MCP_CONTROL_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def financial_enabled() -> bool:
    """Level 3 needs its OWN switch, deliberately separate from level 2.

    An operator who turns on remote restarts has not thereby agreed to let a
    chat assistant place orders. Financial capability is never a side effect of
    enabling operations.
    """
    return (os.getenv("MCP_FINANCIAL_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def authorize(action, args=None):
    """(ok, reason) for one command. The single place authorization is decided."""
    lvl = level_of(action)
    if lvl == 1:
        return True, "LEVEL_1_READ"
    if lvl == 2:
        if not actions_enabled():
            return False, "LEVEL_2_DISABLED (set MCP_CONTROL_ENABLED=true)"
        if action in CONFIRM_REQUIRED and not (args or {}).get("confirm"):
            return False, "CONFIRMATION_REQUIRED (resend with confirm=true)"
        return True, "LEVEL_2_CONFIRMED"
    if not financial_enabled():
        return False, ("LEVEL_3_FINANCIAL_DISABLED — financial actions are not "
                       "available to the operations interface")
    if not (args or {}).get("confirm"):
        return False, "CONFIRMATION_REQUIRED (resend with confirm=true)"
    return True, "LEVEL_3_CONFIRMED"


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


# Argument names that must never reach the audit log. The log is read by an
# assistant and echoed into chat, so a token landing here leaves the process
# entirely. Matching is on the KEY, and by substring, so `ctrader_access_token`
# and a future `access_token_v2` are both caught.
_SECRET_ARG_HINTS = ("token", "secret", "key", "password", "passwd", "credential",
                     "auth", "cookie", "session", "private")


def _safe_args(args):
    """Arguments with anything credential-shaped replaced by a marker."""
    out = {}
    for k, v in (args or {}).items():
        lk = str(k).lower()
        if any(h in lk for h in _SECRET_ARG_HINTS):
            out[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 120:
            out[k] = v[:120] + "…"
        else:
            out[k] = v
    return out


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
                lvl = level_of(action)
                operator = str(cmd.get("operator") or "unknown")[:64]
                # Authorization is decided in ONE place and recorded whether it
                # passed or failed. A refusal nobody can see is indistinguishable
                # from a request nobody made.
                allowed, why = authorize(action, args)
                if not allowed:
                    _record_result(cid, False, why)
                    _audit({"ts": int(time.time()), "cid": cid, "action": action,
                            "level": lvl, "operator": operator,
                            "user": str(args.get("user_id") or ""),
                            "args": _safe_args(args), "authorized": False,
                            "confirmed": bool(args.get("confirm")),
                            "ok": False, "err": why})
                    continue
                fn = handlers.get(action)
                if not fn:
                    _record_result(cid, False, f"unknown action: {action}")
                    continue
                base = {"ts": int(time.time()), "cid": cid, "action": action,
                        "level": lvl, "operator": operator,
                        "user": str(args.get("user_id") or ""),
                        "args": _safe_args(args), "authorized": True,
                        "confirmed": bool(args.get("confirm"))}
                try:
                    data = fn(args)
                    _record_result(cid, True, data)
                    _audit({**base, "ok": True})
                except Exception as e:
                    # The message only. A traceback can carry file paths, config
                    # values and occasionally the argument that failed to parse.
                    _record_result(cid, False, str(e)[:300])
                    _audit({**base, "ok": False, "err": str(e)[:200]})
            except Exception as e:
                print(f"[Control] consumer loop error: {e}")
                time.sleep(poll)

    threading.Thread(target=_run, daemon=True).start()
