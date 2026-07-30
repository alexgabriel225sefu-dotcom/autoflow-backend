"""Action handlers for the MCP control plane (see control.py).

Each handler takes an ``args`` dict and returns a JSON-able result. Kept in its
own module so control.py stays dependency-free; bot.py wires this in at startup.

Read handlers are always available. Write handlers only actually run when
MCP_CONTROL_ENABLED is set (enforced in control.py before dispatch).
"""
from apex import user_store, user_loop
from apex import config as cfg

# Settings the operator may change remotely — the Strategy-Builder / risk knobs.
# Deliberately EXCLUDES tokens, account ids, license, and anything auth-related.
_SETTABLE = {
    "strategy", "risk", "symbol", "autopilot", "autopilot_universe", "watchlist",
    "timeframe", "sl_pips", "tp_pips", "leverage", "min_confidence", "paper",
    "max_trades_day", "max_dd_pct", "max_daily_loss_pct", "trailing",
    "breakeven_r", "news_filter", "session_filter", "exit_mode", "style",
    "atr_stops", "htf", "confirm", "maxpos", "copilot",
}

_REDACT = {"ctrader_access_token", "ctrader_refresh_token",
           "ctrader_accounts"}

# The control-plane transport hands every value over as a STRING, but the loop
# reads these settings with bool() / list() and never re-parses them.
#   bool("false") is True  → switching trailing, news_filter, atr_stops, htf,
#     copilot, autopilot or paper OFF remotely did nothing; the setting still
#     read as ON and the operator had no way to tell.
#   list("EURUSD") is ['E','U','R','U','S','D'] → a watchlist set remotely
#     would hand the scanner six one-letter symbols.
# Numbers happened to survive because the loop wraps them in float()/int(),
# which parse strings — they are typed here anyway so what is stored matches
# what was meant.
_BOOL_KEYS = {"autopilot", "paper", "trailing", "news_filter", "atr_stops",
              "htf", "copilot"}
_LIST_KEYS = {"autopilot_universe", "watchlist", "session_filter"}
_INT_KEYS = {"min_confidence", "max_trades_day", "maxpos"}
_FLOAT_KEYS = {"risk", "sl_pips", "tp_pips", "leverage", "max_dd_pct",
               "max_daily_loss_pct", "breakeven_r"}

_FALSEY = {"false", "0", "no", "off", "none", "null", ""}


def coerce_setting(key, val):
    """Type a control-plane value by its key, so what gets stored is what the
    loop will actually read. Unknown keys pass through untouched."""
    if key in _BOOL_KEYS:
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() not in _FALSEY
    if key in _LIST_KEYS:
        if isinstance(val, (list, tuple)):
            return [str(v).strip() for v in val if str(v).strip()]
        raw = str(val).strip()
        if raw.startswith("["):  # JSON array over a string transport
            try:
                import json
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if str(v).strip()]
            except (ValueError, TypeError):
                pass
        return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if key in _INT_KEYS:
        return int(float(val))
    if key in _FLOAT_KEYS:
        return float(val)
    return val


def _summarize(uid):
    u = user_store.load(uid)
    dash = user_loop.get_dash(uid) or {}
    return {
        "user": str(uid),
        "running": user_loop.is_running(uid),
        "active": bool(u.get("active")),
        "paper": u.get("paper", True),
        "symbol": dash.get("symbol") or u.get("symbol"),
        "strategy": u.get("strategy", "auto"),
        "autopilot": bool(u.get("autopilot")),
        "balance": dash.get("balance"),
        "mode": dash.get("mode"),
        "broker": dash.get("broker"),
        "ctrader_account": u.get("ctrader_account_id"),
    }


def build():
    """Return {action: handler} wired to the live bot. Imported lazily to dodge
    the telegram <-> user_loop import cycle."""
    from apex import telegram as tg

    def h_status(args):
        uids = user_store.all_active() or []
        return {"product": cfg.PRODUCT, "active_count": len(uids),
                "users": [_summarize(u) for u in uids]}

    def h_user_detail(args):
        uid = str(args["user_id"])
        u = {k: v for k, v in user_store.load(uid).items() if k not in _REDACT}
        u["_connected_ctrader"] = bool(user_store.load(uid).get("ctrader_access_token"))
        return {"user": uid, "record": u, "summary": _summarize(uid),
                "dash": user_loop.get_dash(uid) or {}}

    def h_events(args):
        from apex import control
        n = int(args.get("limit", 40))
        raw = control._cmd("LRANGE", control.K_EVENTS, 0, max(1, min(n, 200)) - 1) or []
        import json as _j
        out = []
        for r in raw:
            try:
                out.append(_j.loads(r))
            except Exception:
                pass
        return {"events": out}

    def h_ctrader_account(args):
        uid = str(args["user_id"])
        u = user_store.load(uid)
        broker, _ = user_loop._make_broker(u)
        res = {"user": uid}
        try:
            res["balance"] = broker.get_balance()
        except Exception as e:
            res["balance_error"] = str(e)[:200]
        try:
            res["positions"] = broker.get_all_positions()
        except Exception as e:
            res["positions_error"] = str(e)[:200]
        return res

    def h_restart_loop(args):
        uid = str(args["user_id"])
        tg._restart_user_loop(uid)
        return {"user": uid, "restarted": True, "running": user_loop.is_running(uid)}

    def h_bot_on(args):
        uid = str(args["user_id"])
        tg._auto_start_user(uid)
        return {"user": uid, "running": user_loop.is_running(uid)}

    def h_bot_off(args):
        uid = str(args["user_id"])
        user_loop.stop(uid)
        return {"user": uid, "running": user_loop.is_running(uid)}

    def h_refresh_token(args):
        uid = str(args["user_id"])
        u = user_store.load(uid)
        _, fcfg = user_loop._make_broker(u)
        ok = user_loop._refresh_ctrader_token(uid, fcfg)
        return {"user": uid, "refreshed": bool(ok)}

    def h_set_setting(args):
        uid = str(args["user_id"])
        key = str(args["key"])
        if key not in _SETTABLE:
            raise ValueError(f"'{key}' is not remotely settable")
        val = coerce_setting(key, args["value"])
        user_store.update(uid, {key: val})
        tg._restart_user_loop(uid)
        return {"user": uid, "set": {key: val}, "running": user_loop.is_running(uid)}

    def h_send_message(args):
        uid = str(args["user_id"])
        text = str(args["text"])[:3500]
        tg.send_to(uid, text)
        return {"user": uid, "sent": True}

    def h_force_close(args):
        uid = str(args["user_id"])
        return {"user": uid, "result": user_loop.force_close(uid)}

    def h_force_trade(args):
        """Open a trade on command (BUY/SELL a symbol). SAFETY: demo accounts
        only — refuses on a live/real-money account so it can never place a real
        order remotely. Gated behind MCP_CONTROL_ENABLED like all writes."""
        uid = str(args["user_id"])
        side = str(args["side"]).upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        symbol = args.get("symbol")
        u = user_store.load(uid)
        env = (u.get("ctrader_env") or "demo").lower()
        if env not in ("demo", "practice"):
            raise ValueError("refused: force_trade is demo-only (real-money account)")
        return {"user": uid, "result": user_loop.force_trade(uid, side, symbol)}

    return {
        "status": h_status,
        "user_detail": h_user_detail,
        "events": h_events,
        "ctrader_account": h_ctrader_account,
        "restart_loop": h_restart_loop,
        "bot_on": h_bot_on,
        "bot_off": h_bot_off,
        "refresh_token": h_refresh_token,
        "set_setting": h_set_setting,
        "send_message": h_send_message,
        "force_close": h_force_close,
        "force_trade": h_force_trade,
    }
