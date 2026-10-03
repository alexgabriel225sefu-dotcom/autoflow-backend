"""From a RuleDecision to an order — through the existing gate, never beside it.

THERE IS NO SECOND EXECUTION PATH HERE, AND THAT IS THE ENTIRE POINT.

This module imports no broker, calls no gate and takes no ledger claim. It
turns a decision into an ExecutionRequest and hands that to
`user_loop.force_trade`, which is the controller that already performs, in
order: ownership.may_trade, gates.authorize_order, gates.audit,
ledger.claim/record, and only then broker.place_order.

Re-implementing those five steps here would mean two places that must both
stay correct forever. The first time they disagreed, one of them would be
placing orders the other believed were refused.

WHAT THIS MODULE REFUSES, AND WHY EACH REFUSAL IS LOUD

  HOLD, REJECT, CLOSE      never become an order (execution.from_decision)
  no stop                  no defined worst case, so no size can be derived
  LIMIT or STOP order      the connector places MARKET orders only
  a required constraint    maxSlippagePoints and expiresAfterSec cannot be
  the path cannot honour   honoured by place_order, so a rule asking for one
                           is refused rather than sent as a plain market order
                           the client would believe was protected

That last one is the whole reason `SUPPORTED_CONSTRAINTS` is empty rather than
absent. Stating the capability as an empty set is a claim that was checked;
leaving it unstated would let every constraint through unexamined.

INTENDED SIZE VERSUS ACTUAL SIZE

For a risk-percent rule the exact unit count is decided inside force_trade,
which also applies the minimum-lot floor check. This module records its own
`forex.calc_units` figure as the request's INTENT and lets force_trade remain
authoritative. The journal carries both. They should agree; when they do not,
the journal shows it rather than hiding it behind one number.
"""

import uuid

from apex import forex, indicators
from apex.platform import decision as _dec
from apex.platform import execution as _exec
from apex.platform import journal as _journal
from apex.platform import journal_store as _jstore

# What the execution path can actually honour today, checked against
# brokers/ctrader.py place_order(side, units, instrument, sl, tp).
SUPPORTED_CONSTRAINTS = frozenset()
SUPPORTED_ORDER_TYPES = frozenset({"MARKET"})


class BridgeRefused(RuntimeError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def stop_and_target(rule_doc, snapshot, side):
    """(stop_price, take_profit_price) from the rule's own terms.

    Raises rather than falling back to an engine default. A rule whose stop
    cannot be computed must not be executed with somebody else's stop — that
    is the silent substitution this codebase exists to prevent.
    """
    price = snapshot.price
    if not price:
        raise BridgeRefused("NO_PRICE", "the snapshot carries no price")
    sym = snapshot.symbol
    sl_cfg = (rule_doc or {}).get("stopLoss") or {}
    mode = sl_cfg.get("mode")

    if mode == "pips":
        dist = forex.from_pips(float(sl_cfg["pips"]), sym, price)
    elif mode == "atr":
        series = indicators.atr(snapshot.candles,
                                int(sl_cfg.get("atrPeriod") or 14))
        atr = series[-1] if series else None
        if not atr:
            raise BridgeRefused(
                "NO_ATR", "this rule sizes its stop from ATR and the snapshot "
                          "has too little history to compute one")
        dist = float(sl_cfg["atrMultiple"]) * float(atr)
    else:
        raise BridgeRefused("NO_STOP_MODE",
                            f"stopLoss.mode {mode!r} is not one this platform "
                            f"can turn into a price")
    if dist <= 0:
        raise BridgeRefused("STOP_AT_ENTRY",
                            "the computed stop distance is zero")

    sl = price - dist if side == _dec.BUY else price + dist

    tp_cfg = (rule_doc or {}).get("takeProfit") or {}
    tp = None
    if tp_cfg.get("mode") == "pips" and tp_cfg.get("pips"):
        tdist = forex.from_pips(float(tp_cfg["pips"]), sym, price)
        tp = price + tdist if side == _dec.BUY else price - tdist
    elif tp_cfg.get("mode") == "rr" and tp_cfg.get("rr"):
        tdist = float(tp_cfg["rr"]) * dist
        tp = price + tdist if side == _dec.BUY else price - tdist
    # No target is allowed: a rule may manage its exit through exit conditions
    # or a trailing stop. A missing STOP is not — see the raise above.
    return round(sl, 6), (round(tp, 6) if tp is not None else None)


def _intended_units(rule_doc, snapshot, sl_price, balance):
    sizing = (rule_doc or {}).get("sizing") or {}
    if sizing.get("mode") == "fixed_volume":
        return forex.lots_to_units(float(sizing["fixedVolume"]),
                                   snapshot.symbol)
    stop_pips = abs(forex.to_pips(snapshot.price - sl_price, snapshot.symbol,
                                  snapshot.price))
    if stop_pips <= 0 or not balance:
        return None
    return forex.calc_units(balance, float(sizing.get("riskPercent") or 1) / 100.0,
                            stop_pips, snapshot.symbol, snapshot.price)


def build(rule_doc, decision, snapshot, *, user_id, account_id, mode,
          balance=None, decision_id=None):
    """The ExecutionRequest, or raise. Places nothing."""
    order = (rule_doc or {}).get("order") or {}
    otype = order.get("type", "MARKET")
    # Checked BEFORE from_decision so a client configuring a limit order is
    # told the real reason rather than something about constraints.
    if decision.executable and otype not in SUPPORTED_ORDER_TYPES:
        raise _exec.ExecutionRefused(
            _exec.CONSTRAINT_UNSUPPORTED,
            f"this rule asks for a {otype} order and the connected broker "
            f"path places MARKET orders only — refusing rather than sending "
            f"a different order type than the one configured",
            constraint="order.type")

    sl = tp = None
    if decision.executable:
        sl, tp = stop_and_target(rule_doc, snapshot, decision.side
                                 or decision.verdict)
    units = _intended_units(rule_doc, snapshot, sl, balance) if sl else None
    if decision.executable and not units:
        # Refused rather than sent with a placeholder. A request carrying a
        # volume nobody computed is a request whose risk nobody knows, and a
        # token value here would travel straight into the journal as if it
        # meant something.
        raise _exec.ExecutionRefused(
            _exec.SIZING_FAILED,
            "the intended position size could not be computed — the account "
            "balance or the stop distance is missing")

    return _exec.from_decision(
        decision, rule_doc, user_id=user_id, account_id=account_id,
        volume=units, mode=mode,
        decision_id=decision_id or uuid.uuid4().hex,
        stop_loss=sl, take_profit=tp,
        supported=SUPPORTED_CONSTRAINTS)


def submit(rule_doc, decision, snapshot, *, user_id, account_id, mode,
           balance=None, decision_id=None, correlation_id=None,
           executor=None):
    """Build the request and hand it to the existing execution controller.

    `executor` is injectable so a test can assert exactly what would be sent
    without a broker anywhere near it. The default is the real controller.

    Returns {"ok", "request", "result", "journal"} or
            {"ok": False, "refusal": {...}, "journal": ...}.
    """
    correlation_id = correlation_id or uuid.uuid4().hex
    try:
        req = build(rule_doc, decision, snapshot, user_id=user_id,
                    account_id=account_id, mode=mode, balance=balance,
                    decision_id=decision_id)
    except (_exec.ExecutionRefused, BridgeRefused) as e:
        entry = _jstore.append(_journal.for_error(
            f"{e.code}: {getattr(e, 'detail', str(e))}",
            correlation_id=correlation_id, user_id=user_id,
            account_id=account_id, symbol=decision.symbol))
        return {"ok": False, "request": None, "result": None,
                "refusal": {"code": e.code,
                            "detail": getattr(e, "detail", str(e))},
                "journal": entry}

    if executor is None:
        # Imported here, not at module import, so this file can be loaded and
        # tested without pulling in the whole engine.
        from apex import user_loop
        executor = user_loop.force_trade

    sizing = (rule_doc or {}).get("sizing") or {}
    risk = (float(sizing["riskPercent"]) / 100.0
            if sizing.get("mode") == "risk_percent"
            and sizing.get("riskPercent") else None)
    lots = (float(sizing["fixedVolume"])
            if sizing.get("mode") == "fixed_volume" else None)

    # Written BEFORE the controller is called. The gap between "sent" and
    # whatever comes back is exactly where an ambiguous broker failure lives:
    # if this process dies mid-call, the journal still shows an order left the
    # platform, which is the only way anyone can go looking for it.
    _jstore.record_order_sent(req, correlation_id=correlation_id)

    result = executor(user_id, req.side, symbol=req.symbol, lots=lots,
                      sl_override=req.stop_loss, tp_override=req.take_profit,
                      risk_override=risk, origin="rule")

    entry = _jstore.record_execution(req, correlation_id=correlation_id,
                                     result=result)
    return {"ok": bool((result or {}).get("ok", True)) and
            "error" not in (result or {}),
            "request": req, "result": result, "journal": entry}
