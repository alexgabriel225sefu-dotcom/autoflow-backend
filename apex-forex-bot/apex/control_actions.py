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
    "timeframe", "sl_pips", "tp_pips", "leverage", "min_confidence",
    # "paper" is DELIBERATELY ABSENT. Setting it false is live activation, and
    # the Telegram path that owns that transition also demands risk acceptance,
    # a typed confirmation code and an initial risk cap. Exposing it here made
    # a second activation route that skipped all three — one generic setter
    # call and a demo client is trading real money. There is exactly one
    # authoritative live-activation path, and it is not this one.
    "max_trades_day", "max_dd_pct", "max_daily_loss_pct", "trailing",
    # Total risk allowed across all concurrent positions. The loop sizes each
    # trade at min(risk, max_total_risk / maxpos), so with the default 5% and
    # maxpos=2 no trade can exceed 2.5% no matter what `risk` says — and until
    # now that ceiling could only be moved by editing the store directly.
    # A cap the operator cannot reach is not a policy, it is a dead end: the
    # client raises `risk`, nothing changes, and there is nothing in the
    # interface explaining why. It sits alongside the other limits and is
    # bounded by the same validation.
    "max_total_risk",
    "breakeven_r", "news_filter", "session_filter", "exit_mode", "style",
    # Whether the calendar PUSHES messages. Distinct from news_filter, which
    # decides whether the bot stands aside for releases — a client can want
    # the pause without the messages, or the messages without the pause.
    "news_alerts",
    "atr_stops", "htf", "confirm", "maxpos", "copilot",
    # The three-way automation level (signals / approval / full). `copilot`
    # stays settable for anything that still speaks the old two-way boolean —
    # apex.automation reconciles the pair, so setting either one is coherent.
    "automation",
    # Streak state, not a strategy knob. It no longer resizes anything — the
    # risk ladder it drove was removed — but it is still counted, journalled
    # and shown to the client, and a duplicate-journaling bug once pushed it to
    # 4 after two real losses. Settable so a wrong count can be corrected
    # rather than misreported until a winning trade clears it.
    "loss_streak",
}

# Named secrets. Kept because two of them are not obviously credential-shaped
# from the name alone, and `ctrader_accounts` is a broker payload rather than
# a key.
_REDACT = {"ctrader_access_token", "ctrader_refresh_token",
           "ctrader_accounts"}

# …and the shape rule, because a denylist of names only ever covers the
# secrets that existed when it was written. `groq_key` and `gemini_key` were
# added to the user record long after this list, and neither was added to it —
# so `user_detail`, documented as token-redacted, returned a client's Groq key
# in full. Observed live, in a transcript.
#
# Anything whose FIELD NAME looks credential-shaped is dropped, so a secret
# added tomorrow is covered on the day it is added rather than on the day
# somebody notices it leaking.
_SECRET_SUFFIXES = ("_key", "_token", "_secret", "_password", "_hash")
_SECRET_WORDS = ("secret", "password", "passphrase", "apikey", "credential")


def _is_secret(field) -> bool:
    f = str(field or "").lower()
    if f in _REDACT:
        return True
    if f.endswith(_SECRET_SUFFIXES):
        return True
    return any(w in f for w in _SECRET_WORDS)

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
_BOOL_KEYS = {"autopilot", "paper", "trailing", "news_filter", "news_alerts",
              "atr_stops", "htf", "copilot"}   # "paper" typed here only for legacy callers;
                                  # it is not in _SETTABLE, so MCP cannot set it
_LIST_KEYS = {"autopilot_universe", "watchlist", "session_filter"}
_INT_KEYS = {"min_confidence", "max_trades_day", "maxpos", "loss_streak"}
_FLOAT_KEYS = {"risk", "sl_pips", "tp_pips", "leverage", "max_dd_pct",
               "max_daily_loss_pct", "breakeven_r", "max_total_risk"}
# Keys whose VALUE is checked, not just its type. Passing these through untyped
# is not harmless: every consumer downstream substitutes a default for a value
# it does not recognise, so a rejected write here is the difference between the
# client being told "no" and the account quietly running on something else.
# apex.automation.mode() falls back to the MOST PERMISSIVE level, so
# `automation=aproval` (typo) would have stored fine and traded unattended.
# The fixed sets live here; the ones that must be resolved at call time are in
# _allowed_values below.
_ENUM_KEYS = {"automation": automation.MODES}

# `symbol` is checked by a predicate rather than a list: forex.is_tradeable is
# a positive allowlist over currency pairs and metals, and enumerating it here
# would be a second copy that drifts from the one the loop actually trades by.
_PREDICATE_KEYS = ("symbol",)


def _allowed_values(key):
    """Valid values for `key`, or None when it is not value-checked.

    RESOLVED AT CALL TIME, DELIBERATELY. The strategy registry fills as a side
    effect of importing the strategy modules, and this module imports none of
    them: at import time `strategy_api.available()` is EMPTY (0 entries, vs 17
    once they are loaded). A list built at module level here would therefore
    reject every valid strategy rather than only the invalid ones — the
    opposite of what this check is for. telegram._handle_strategy already
    resolves the same set this way, at call time.

    Every set comes from the registry or map the runtime itself reads, so a
    strategy or timeframe added later is accepted without editing this file.
    """
    if key in _ENUM_KEYS:
        return set(_ENUM_KEYS[key])
    if key == "strategy":
        from apex import ai, strategy_api
        # MEASURED, not assumed: the registry holds 17 ids and is a strict
        # SUPERSET of STRATEGY_MODES (10) — "auto" included, as a registered
        # module like any other. STRATEGY_MODES therefore adds nothing today
        # and is here as a floor against one specific failure, not as a
        # description of the sets.
        #
        # That failure: the registry is populated by IMPORT SIDE EFFECT, and
        # this module imports no strategy module (it cannot — the cycle runs
        # back through user_loop). available() is non-empty here only because
        # user_loop, imported at the top of this file, pulls them in
        # transitively. An import reorder upstream would empty it, and a
        # validator whose allowlist is empty rejects EVERYTHING — taking the
        # product down rather than degrading. STRATEGY_MODES is the floor that
        # keeps the core modes writable if that happens, and
        # tests/test_setting_value_validation.py stubs available() to [] to
        # prove it.
        #
        # A third term, | {"auto"}, was specified and written, then removed:
        # it is reachable only if the registry is empty AND "auto" has left
        # STRATEGY_MODES, and no mutation of this function could make the
        # tests notice its absence. Dead code that cannot fail is worse than
        # no code — it reads as a guarantee while guaranteeing nothing.
        return set(strategy_api.available()) | set(ai.STRATEGY_MODES)
    if key == "timeframe":
        # forex.TIMEFRAMES rather than the broker's own `_period()` map, even
        # though that map is the authority: test_failure_matrix.py forbids any
        # module outside the trading core from importing a broker, and this
        # module is the operator interface — precisely the one that rule
        # exists to keep away from a broker. forex.TIMEFRAMES mirrors
        # _period()'s keys and a test asserts the two are equal, so the check
        # is still against the real set without the layering violation.
        from apex import forex
        return set(forex.TIMEFRAMES)
    return None


_FALSEY = {"false", "0", "no", "off", "none", "null", ""}


def coerce_setting(key, val):
    """Type AND value-check a control-plane value by its key, so what gets
    stored is what the loop will actually read.

    Raises ValueError for a recognised key given a value the runtime would not
    honour. That refusal is the point: `strategy`, `symbol` and `timeframe`
    each have a consumer that substitutes a default for anything it does not
    recognise, so storing an unchecked value left the client reading back one
    setting while the account ran on another. A rejected write is visible; a
    substituted value is not.

    Unknown keys still pass through untouched — this is a typing and
    validation table, not a blocklist. A key nobody listed here is stored as
    given, exactly as before.
    """
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
    if key in _PREDICATE_KEYS:
        from apex import forex
        v = str(val).strip()
        if not forex.is_tradeable(v):
            raise ValueError(
                f"'{key}' is not an instrument this platform trades (got "
                f"{val!r}). Spot FX with a USD leg, plus metals.")
        return v
    allowed = _allowed_values(key)
    if allowed is not None:
        v = str(val).strip().lower()
        if v not in allowed:
            # Rejected value FIRST, allowed set last. apex/control.py:532
            # truncates a failed command's message to 300 chars before the
            # caller ever sees it, and the strategy list is already ~200 of
            # them: written the other way round, registering a few more
            # strategies would silently start cutting off the one part of the
            # message that says what was actually wrong.
            raise ValueError(
                f"{val!r} is not a valid '{key}'. Must be one of: "
                f"{', '.join(sorted(allowed))}")
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
        # Secrets are replaced, not dropped. Dropping them hid whether a
        # client had configured an AI key at all — which is operational fact,
        # not secret material, and the operator needs it to answer "why is the
        # assistant not answering for this client". `_connected_ctrader` below
        # has always made exactly this distinction.
        u = {k: ("•set•" if v else v) if _is_secret(k) else v
             for k, v in user_store.load(uid).items()}
        u["_connected_ctrader"] = bool(user_store.load(uid).get("ctrader_access_token"))
        return {"user": uid, "record": u, "summary": _summarize(uid),
                "dash": user_loop.get_dash(uid) or {}}

    def h_trade_journal(args):
        """The closed-trade journal, for analysis that needs more than the dash.

        `dash["trades"]` is capped at 50 AND rebuilt in memory, so after a
        restart it holds only what has closed since. The durable record is the
        journal in the store, and until now nothing exposed it — which meant an
        analysis of "what actually works" could only ever see the last few
        days.

        LABELLED IS THE NUMBER THAT MATTERS, NOT TOTAL

        A row without a confidence carries no regime, no strategy version and
        no entry snapshot. It says a trade happened and what it paid; it cannot
        say why. `ev.labelled_count` is the platform's own definition of what
        is measurable, and it is reported here beside the total so a caller
        cannot mistake 131 rows for 131 usable observations.

        Read-only. Touches no broker and changes nothing.
        """
        uid = str(args["user_id"])
        rows = user_store.load_trades(uid) or []
        n = max(1, min(int(args.get("limit", 200) or 200), 500))
        labelled_only = bool(args.get("labelled_only"))

        def _labelled(t):
            pnl = t.get("netPnl") if t.get("netPnl") is not None else t.get("grossPnl")
            return t.get("confidence") is not None and pnl is not None

        sel = [t for t in rows if _labelled(t)] if labelled_only else rows
        # Newest last in the store; the caller wants newest first.
        out = list(reversed(sel))[:n]

        # Only the fields an analysis reads. The journal also carries entry
        # snapshots that are useful to the calibrator and noise here, and
        # trimming keeps a 500-row answer from being mostly whitespace.
        keep = ("time", "symbol", "side", "entry", "exit", "netPnl", "grossPnl",
                "costUsd", "balance", "openedAt", "positionId", "confidence",
                "regime", "spreadPips", "atr", "slPips", "tpPips", "probability",
                "evR", "strategyId", "strategyVersion", "mode", "action", "win")
        try:
            from apex import ev as _ev
            lab = _ev.labelled_count(rows)
        except Exception:
            lab = sum(1 for t in rows if _labelled(t))

        return {
            "user": uid,
            "total": len(rows),
            # Stated separately and deliberately: a caller reading `total` as
            # the size of its sample would be measuring rows it cannot explain.
            "labelled": lab,
            "returned": len(out),
            "labelledOnly": labelled_only,
            "trades": [{k: t.get(k) for k in keep if k in t} for t in out],
        }

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
        if key == "paper":
            raise ValueError(
                "'paper' is not remotely settable. Switching to live money is "
                "an activation, not a setting: it requires risk acceptance and "
                "a typed confirmation from the account holder in Telegram.")
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
        # Only previews until a button is pressed, and the control plane
        # cannot press it. Listed anyway: deciding which of a client's rows
        # stop counting as their own trades belongs to the client, and the
        # preview is where that decision is made.
        "/markartefacts",
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

    # ── Operations API (apex/ops_api.py) ──────────────────
    # Small, explicit, read-only tools rather than one powerful generic one.
    # There is deliberately no ops_execute(action, params) and no ops_query(sql):
    # a generic tool is only as safe as the caller's restraint, and the caller
    # is a language model reading a chat message.
    from apex import ops_api

    def _uid_arg(args):
        return args.get("user_id")

    ops = {
        "ops_system_health":        lambda a: ops_api.system_health(),
        "ops_user_health":          lambda a: ops_api.user_health(_uid_arg(a)),
        "ops_user_license":         lambda a: ops_api.user_license(_uid_arg(a)),
        "ops_user_broker_status":   lambda a: ops_api.user_broker_status(_uid_arg(a)),
        "ops_user_risk":            lambda a: ops_api.user_risk(_uid_arg(a)),
        "ops_user_positions":       lambda a: ops_api.user_positions(_uid_arg(a)),
        "ops_user_orders":          lambda a: ops_api.user_orders(_uid_arg(a),
                                                                  a.get("limit", 10)),
        "ops_user_worker_status":   lambda a: ops_api.user_worker_status(_uid_arg(a)),
        "ops_user_ownership":       lambda a: ops_api.user_ownership(_uid_arg(a)),
        "ops_user_incidents":       lambda a: ops_api.user_incidents(_uid_arg(a),
                                                                     a.get("limit", 20)),
        "ops_recent_errors":        lambda a: ops_api.recent_errors(a.get("user_id"),
                                                                    a.get("limit", 20)),
        "ops_reconcile_status":     lambda a: ops_api.reconcile_status(_uid_arg(a)),
        "ops_investigate":          lambda a: ops_api.investigate(_uid_arg(a)),
        "ops_degraded_users":       lambda a: ops_api.degraded_users(a.get("limit", 50)),
        "ops_unprotected_positions": lambda a: ops_api.unprotected_positions(
                                                   a.get("limit", 50)),
        "ops_broker_reconcile":     lambda a: ops_api.broker_reconcile(_uid_arg(a)),
    }

    return {
        "status": h_status,
        "user_detail": h_user_detail,
        "trade_journal": h_trade_journal,
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
        **ops,
    }
