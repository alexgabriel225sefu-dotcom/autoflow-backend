"""What the agent is allowed to look at — and what it can never touch.

THE RULE THIS MODULE EXISTS TO ENFORCE

§13 and §14 of the brief: the AI gets read tools, and the account context is
server-authoritative. The agent never names a user, an account or an
environment — it is HANDED one, and every tool can only see inside it.

That is not a convention here, it is the shape of the code. A tool receives a
`ToolContext` that was built from an already-authenticated identity, and the
argument dict the model produces is filtered against a declared allowlist
before the tool runs. A model asking for `user_id` gets the argument dropped,
not honoured — and the drop is recorded.

WHY THERE IS NO EXECUTE TOOL

There is no `execute_order`, no `close_position`, no `set_risk_limit`, and
adding one would defeat every other control in the platform. The proposal
tools return objects. `gates.authorize_order` remains the only thing that can
permit an order.

TOOL OUTPUT IS DATA, NEVER INSTRUCTIONS

§35. Everything returned here is wrapped so the prompt builder can mark it as
data. A symbol name, a trade note or a broker error string can contain
anything, and the agent must never read "ignore previous instructions" out of
a tool result and act on it.
"""

import time

# Declared per tool: the ONLY argument names that survive. Anything else the
# model invents is dropped before the call. Deliberately tiny — a tool that
# accepts an owner field is a tool that can be pointed at another account.
_ALLOWED_ARGS = {
    "get_market_state": ("symbol",),
    "get_market_regime": ("symbol",),
    "get_symbol_features": ("symbol",),
    "get_spread": ("symbol",),
    "get_open_positions": (),
    "get_portfolio_risk": (),
    "get_account_state": (),
    "get_trade_history": ("limit",),
    "get_position_state": ("symbol",),
    "get_market_status": (),
}

# Names a model may never supply, on any tool. Kept explicit rather than
# implied by the allowlist so a future tool that forgets its entry still
# cannot be steered.
FORBIDDEN_ARGS = frozenset({
    "user_id", "userId", "chat_id", "chatId", "account_id", "accountId",
    "environment", "env", "paper", "live", "broker", "token", "access_token",
    "owner", "ctid", "ctrader_account_id",
})

TOOLS_VERSION = "1.0.0"


class ToolContext:
    """The account this agent run is allowed to see. Built server-side.

    Nothing in a model reply can change any field. The constructor takes the
    identity from a caller that already authenticated it, and the tools read
    only from here.
    """

    __slots__ = ("user_id", "environment", "symbol", "_dash", "_user", "_frozen")

    def __init__(self, user_id, *, environment=None, symbol=None, dash=None,
                 user=None):
        self.user_id = str(user_id)
        self.environment = environment
        self.symbol = symbol
        self._dash = dash or {}
        self._user = user or {}
        self._frozen = True

    def __setattr__(self, name, value):
        if name != "_frozen" and getattr(self, "_frozen", False):
            raise AttributeError(
                f"the tool context is fixed for the run; {name!r} cannot change")
        object.__setattr__(self, name, value)


class ToolCall:
    """One recorded invocation. Metadata only — §88."""

    __slots__ = ("name", "ok", "duration_ms", "error", "dropped_args", "at")

    def __init__(self, name, ok, duration_ms, error="", dropped_args=()):
        self.name, self.ok = name, ok
        self.duration_ms = duration_ms
        self.error = str(error)[:160]
        self.dropped_args = list(dropped_args)
        self.at = time.time()

    def to_dict(self):
        return {"tool": self.name, "ok": self.ok,
                "durationMs": self.duration_ms, "error": self.error,
                "droppedArgs": self.dropped_args, "at": round(self.at, 3)}


def _data(payload, *, status="OK"):
    """Wrap a result so the prompt builder can label it DATA (§35, §15)."""
    return {"_kind": "tool_data", "_status": status, "at": int(time.time()),
            **(payload or {})}


# ── The tools ────────────────────────────────────────────────────────────
# Each takes (ctx, **args) and returns a plain dict. None of them accepts an
# owner, and none of them can write.

def get_market_state(ctx, symbol=None):
    d = ctx._dash or {}
    m = d.get("market") or {}
    sym = symbol or d.get("symbol")
    return _data({"symbol": sym, "price": d.get("currentPrice"),
                  "trend": m.get("trend"), "momentum": m.get("momentum"),
                  "volatility": m.get("volatility"), "rsi": m.get("rsi"),
                  "atrPct": m.get("atrPct"),
                  # Freshness travels with the reading (§30). A stale price
                  # that looks current is the failure this field prevents.
                  "lastTickTs": d.get("lastTickTs"),
                  "dataStatus": _freshness(d.get("lastTickTs"))})


def get_market_regime(ctx, symbol=None):
    from apex import regime as _rg
    raw = (ctx._dash or {}).get("regime")
    r = _rg.from_legacy(raw, symbol=symbol or (ctx._dash or {}).get("symbol"))
    return _data(r.to_dict())


def get_symbol_features(ctx, symbol=None):
    d = ctx._dash or {}
    m = d.get("market") or {}
    return _data({"symbol": symbol or d.get("symbol"),
                  "trend": m.get("trend"), "momentum": m.get("momentum"),
                  "volatility": m.get("volatility"),
                  "notable": m.get("notable"), "sessions": d.get("sessions")})


def get_spread(ctx, symbol=None):
    d = ctx._dash or {}
    pos = next((p for p in (d.get("positions") or [])
                if str(p.get("symbol", "")).upper()
                == str(symbol or d.get("symbol") or "").upper()), None)
    return _data({"symbol": symbol or d.get("symbol"),
                  "spreadPips": (pos or {}).get("entrySpreadPips"),
                  "note": "spread at entry where recorded; None means unread"})


def get_open_positions(ctx):
    rows = [{"symbol": p.get("symbol"), "side": p.get("side"),
             "entryPrice": p.get("entryPrice"), "stopLoss": p.get("stopLoss"),
             "takeProfit": p.get("takeProfit"), "pnlUsd": p.get("pnlUsd"),
             "pnlSource": p.get("pnlSource")}
            for p in ((ctx._dash or {}).get("positions") or []) if p.get("symbol")]
    return _data({"count": len(rows), "positions": rows})


def get_portfolio_risk(ctx):
    from apex import portfolio as _pf
    st = _pf.state(ctx._dash or {})
    guard = (ctx._dash or {}).get("riskGuard") or {}
    return _data({**st, "halted": bool(guard.get("halted")),
                  "reasons": guard.get("reasons") or []})


def get_account_state(ctx):
    """Balance, equity and environment — never credentials (§24, §56)."""
    d = ctx._dash or {}
    return _data({"balance": d.get("balance"), "equity": d.get("equityLive"),
                  "floatingPnl": d.get("floatingPnl"),
                  "equitySource": d.get("equitySource"),
                  "environment": ctx.environment or d.get("mode"),
                  "openCount": d.get("openCount"), "maxPositions": d.get("maxpos")})


def get_trade_history(ctx, limit=10):
    from apex import user_store
    try:
        n = max(1, min(int(limit or 10), 25))
    except (TypeError, ValueError):
        n = 10
    rows = (user_store.load_trades(ctx.user_id) or [])[-n:]
    return _data({"count": len(rows), "trades": [
        {"time": t.get("time"), "symbol": t.get("symbol"), "side": t.get("side"),
         "netPnl": t.get("netPnl"), "entry": t.get("entry"), "exit": t.get("exit"),
         "strategyId": t.get("strategyId")} for t in rows]})


def get_position_state(ctx, symbol=None):
    d = ctx._dash or {}
    want = str(symbol or d.get("symbol") or "").replace("_", "").upper()
    p = next((x for x in (d.get("positions") or [])
              if str(x.get("symbol", "")).replace("_", "").upper() == want), None)
    if not p:
        return _data({"symbol": want, "open": False}, status="NO_POSITION")
    return _data({"symbol": p.get("symbol"), "open": True, "side": p.get("side"),
                  "entryPrice": p.get("entryPrice"),
                  "stopLoss": p.get("stopLoss"), "takeProfit": p.get("takeProfit"),
                  "pnlUsd": p.get("pnlUsd"), "thesis": p.get("thesis")})


def get_market_status(ctx):
    from apex import forex
    try:
        is_open = bool(forex.is_market_open())
    except Exception:
        # None, not False. "We could not tell" and "the market is shut" are
        # different facts, and a closed-market reading nobody measured would
        # explain away a scanner that is silent for the wrong reason.
        is_open = None
    d = ctx._dash or {}
    return _data({"open": is_open, "brokerHealth": d.get("brokerHealth"),
                  "dataStatus": _freshness(d.get("lastTickTs"))})


def _freshness(ts, stale_after_s=120):
    """FRESH / STALE / UNKNOWN. Never silently FRESH (§30)."""
    if not ts:
        return "UNKNOWN"
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return "FRESH" if age <= stale_after_s else "STALE"


REGISTRY = {
    "get_market_state": get_market_state,
    "get_market_regime": get_market_regime,
    "get_symbol_features": get_symbol_features,
    "get_spread": get_spread,
    "get_open_positions": get_open_positions,
    "get_portfolio_risk": get_portfolio_risk,
    "get_account_state": get_account_state,
    "get_trade_history": get_trade_history,
    "get_position_state": get_position_state,
    "get_market_status": get_market_status,
}


def describe():
    """The tool list as the prompt presents it. Names and args only."""
    return [{"name": n, "args": list(_ALLOWED_ARGS.get(n, ()))}
            for n in sorted(REGISTRY)]


def call(ctx, name, args=None):
    """(result, ToolCall). Never raises, never widens the context.

    Arguments are filtered against the tool's own allowlist BEFORE the call.
    A model asking for `user_id` has it dropped and recorded — not honoured,
    and not silently ignored either, because a model probing for an owner
    field is something an operator should be able to see in the journal.
    """
    t0 = time.time()
    fn = REGISTRY.get(name)
    if fn is None:
        return (None, ToolCall(name, False, 0, "unknown tool"))

    allowed = set(_ALLOWED_ARGS.get(name, ()))
    clean, dropped = {}, []
    for k, v in (args or {}).items():
        if k in FORBIDDEN_ARGS or k not in allowed:
            dropped.append(k)
            continue
        clean[k] = v
    try:
        out = fn(ctx, **clean)
        ms = int((time.time() - t0) * 1000)
        return out, ToolCall(name, True, ms, dropped_args=dropped)
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        # A failing tool is a missing fact, never a reason to act. The caller
        # gets None and decides; it does not get a plausible-looking default.
        return None, ToolCall(name, False, ms, str(e), dropped)
