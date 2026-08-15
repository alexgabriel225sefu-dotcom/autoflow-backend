"""Action handlers for the MCP control plane (see control.py).

Each handler takes an ``args`` dict and returns a JSON-able result. Kept in its
own module so control.py stays dependency-free; bot.py wires this in at startup.

Read handlers are always available. Write handlers only actually run when
MCP_CONTROL_ENABLED is set (enforced in control.py before dispatch).
"""
from apex import automation, user_store, user_loop
from apex import config as cfg

# Settings the operator may change remotely — the Strategy-Builder / risk knobs.
# Deliberately EXCLUDES tokens, account ids, license, and anything auth-related.
_SETTABLE = {
    "strategy", "risk", "symbol", "autopilot", "autopilot_universe", "watchlist",
    "timeframe", "sl_pips", "tp_pips", "leverage", "min_confidence", "paper",
    "max_trades_day", "max_dd_pct", "max_daily_loss_pct", "trailing",
    "breakeven_r", "news_filter", "session_filter", "exit_mode", "style",
    "atr_stops", "htf", "confirm", "maxpos", "copilot",
    # The three-way automation level (signals / approval / full). `copilot`
    # stays settable for anything that still speaks the old two-way boolean —
    # apex.automation reconciles the pair, so setting either one is coherent.
    "automation",
    # Risk-ladder state, not a strategy knob. Settable because a miscounted
    # streak silently quarters every position and there was no way to correct
    # it short of waiting for a winning trade — a duplicate-journaling bug once
    # pushed it to 4 after two real losses, and the account traded at a quarter
    # size until it was noticed.
    "loss_streak",
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
_INT_KEYS = {"min_confidence", "max_trades_day", "maxpos", "loss_streak"}
_FLOAT_KEYS = {"risk", "sl_pips", "tp_pips", "leverage", "max_dd_pct",
               "max_daily_loss_pct", "breakeven_r"}
# Keys whose value is one of a fixed set. Passing these through untyped is not
# harmless: apex.automation.mode() falls back to the MOST PERMISSIVE level for
# anything it does not recognise, so `automation=aproval` (typo) would have
# stored fine and silently traded the account unattended.
_ENUM_KEYS = {"automation": automation.MODES}

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
    if key in _ENUM_KEYS:
        v = str(val).strip().lower()
        if v not in _ENUM_KEYS[key]:
            raise ValueError(
                f"'{key}' must be one of {', '.join(_ENUM_KEYS[key])} (got {val!r})")
        return v
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
        # Resolved, not raw: the operator needs to know what the loop will
        # actually do, which is not always what either stored key says alone.
        "automation": automation.mode(u),
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
        # `automation` and `copilot` are two views of ONE setting, and mode()
        # lets the boolean win when they disagree. So whichever half is
        # written, write both — otherwise a stale counterpart quietly overrules
        # the instruction just given, and user_detail reports one level while
        # the loop runs another.
        #
        # The boolean cannot express `signals`, so `copilot=False` must NOT be
        # read as "go full automation": on an account already set to Signals
        # Only that would hand execution to the bot on a write that never
        # mentioned execution. It means "not approval" — which of the two
        # non-approval levels applies is whatever the account already had.
        if key == "automation":
            patch = automation.patch(val)
        elif key == "copilot":
            if val:
                patch = automation.patch("approval")
            else:
                _cur = automation.mode(user_store.load(uid))
                patch = automation.patch("signals" if _cur == "signals" else "full")
        else:
            patch = {key: val}
        user_store.update(uid, patch)
        tg._restart_user_loop(uid)
        return {"user": uid, "set": patch, "running": user_loop.is_running(uid)}

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


    # Commands that are destructive, irreversible, or move real money are NOT
    # reachable this way. The point of client_message is to let the operator
    # WALK a client's flow and see what the bot really replies — not to hand
    # the control plane a remote shell over somebody's account. force_trade
    # and force_close already exist as deliberate, separately-audited actions;
    # anything on this list has to be typed by the person whose account it is.
    _MSG_DENY = {
        "/reset",        # disconnects the broker and wipes every setting
        "/paper",        # paper OFF is the real-money switch
        "/env",          # routes to /paper
        "/setkeys",      # credential rotation
        "/deploy",       # ships code
        "/purgebad",     # destroys journal rows
        "/grant", "/revoke",   # access control
        "/buy", "/sell", "/close",   # use force_trade / force_close instead
    }

    def h_client_message(args):
        """Deliver `text` to the bot as if the client had typed it.

        The bot's command dispatch lived inside the getUpdates loop, so the
        only way to exercise a command was for a human to type it — which
        meant remote verification was reading code and hoping. This runs the
        IDENTICAL dispatch a real message runs: same handlers, same replies
        sent to the client's own Telegram.

        It genuinely acts as the client, so it is deliberately narrower than
        the client is: see _MSG_DENY.
        """
        uid = str(args["user_id"])
        text = str(args.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        if len(text) > 400:
            raise ValueError("text too long")
        cmd = text.split()[0].lower().split("@")[0]
        if cmd in _MSG_DENY:
            raise ValueError(
                f"refused: {cmd} is not available through the control plane — "
                f"it is destructive or moves real money, so it has to be sent "
                f"by the account owner")
        from apex import control
        control.event("mcp_msg", text[:120], user_id=uid)
        tg.dispatch_command(uid, text)
        return {"user": uid, "delivered": text,
                "note": "the bot replied in the client's Telegram"}

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
        "client_message": h_client_message,
    }
