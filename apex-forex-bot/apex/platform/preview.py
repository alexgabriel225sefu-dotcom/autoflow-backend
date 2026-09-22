"""What a rule WOULD decide, on a snapshot the caller supplies. Changes nothing.

THIS MODULE CANNOT TRADE, AND THAT IS STRUCTURAL

It imports the evaluator and the contracts. It does not import a broker, the
gates, the ledger, user_loop or the bridge, so there is no expression it could
evaluate that would place an order. A test walks its AST and asserts exactly
that, which is why the boundary is a fact about the file rather than a
sentence in this docstring.

It also writes nothing. Not a position, not a balance, not an execution
journal entry. A preview a client runs twenty times while tuning a rule must
not leave twenty entries in the record of what their account actually did.

THE SNAPSHOT IS SUPPLIED, NOT FETCHED

A preview that fetched its own candles would need a broker, and a preview that
invented them would be the most misleading screen on the platform — a verdict
that looks like it came from the market. So the caller passes the bars in. If
they are missing or too short, the answer is an explicit refusal, never a
verdict reached on data that was not there.
"""

from apex.platform import conditions as _cond
from apex.platform import decision as _dec
from apex.platform import evaluator as _eval
from apex.platform import ruledoc as _rd
from apex.platform.snapshot import MarketSnapshot

# Enough bars for the longest default any condition uses. Below this the
# evaluator would refuse condition by condition anyway; refusing up front says
# so once, clearly.
MIN_CANDLES = 2

_REQUIRED_BAR_KEYS = ("open", "high", "low", "close")


class PreviewRefused(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _candles(raw):
    if not isinstance(raw, list) or len(raw) < MIN_CANDLES:
        raise PreviewRefused(
            "INSUFFICIENT_DATA",
            f"a preview needs at least {MIN_CANDLES} candles in "
            f"`snapshot.candles`; none were supplied")
    out = []
    for i, bar in enumerate(raw):
        if not isinstance(bar, dict):
            raise PreviewRefused("INSUFFICIENT_DATA",
                                 f"candle {i} is not an object")
        missing = [k for k in _REQUIRED_BAR_KEYS if bar.get(k) is None]
        if missing:
            raise PreviewRefused(
                "INSUFFICIENT_DATA",
                f"candle {i} is missing {', '.join(missing)}")
        try:
            out.append({k: float(bar[k]) for k in _REQUIRED_BAR_KEYS})
        except (TypeError, ValueError):
            raise PreviewRefused("INSUFFICIENT_DATA",
                                 f"candle {i} has a non-numeric price")
    return out


def build_snapshot(rule_doc, payload):
    """A MarketSnapshot from what the caller sent, or a refusal."""
    payload = payload or {}
    candles = _candles(payload.get("candles"))
    symbols = (rule_doc or {}).get("symbols") or []
    symbol = payload.get("symbol") or (symbols[0] if symbols else None)
    if not symbol:
        raise PreviewRefused("INSUFFICIENT_DATA",
                             "no symbol to preview against")
    ts = payload.get("ts")
    if ts is None:
        # Not defaulted to now. A preview whose timestamp the platform chose
        # is a preview whose time-of-day and weekday conditions answered a
        # question the client never asked.
        raise PreviewRefused(
            "INSUFFICIENT_DATA",
            "`snapshot.ts` is required — the evaluator must not read the "
            "clock, and a timestamp we picked would silently decide every "
            "session and weekday condition in the rule")
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        raise PreviewRefused("INSUFFICIENT_DATA",
                             "`snapshot.ts` must be a unix timestamp")
    return MarketSnapshot(
        symbol=symbol,
        timeframe=payload.get("timeframe") or (rule_doc or {}).get("timeframe"),
        candles=candles,
        price=payload.get("price", candles[-1]["close"]),
        ts=ts,
        spread_pips=payload.get("spreadPips"),
        session=payload.get("session"),
        open_positions=payload.get("openPositions") or [],
        balance=payload.get("balance"))


def preview(rule_doc, payload):
    """{decision, executable: False, ...} — a verdict, never an order.

    `executable` is reported as False regardless of the verdict. The decision
    object's own `executable` means "this verdict COULD become an order"; here
    nothing will, and a client reading a preview must not be left to infer
    that from context.
    """
    problems = _rd.validate(rule_doc, known_condition_ids=_cond.available())
    if problems:
        raise PreviewRefused(
            "RULE_INVALID",
            "this rule cannot be previewed until it is valid: "
            + "; ".join(problems[:5]))
    snap = build_snapshot(rule_doc, payload)
    d = _eval.evaluate(dict(rule_doc, state=_rd.ACTIVE), snap)
    return {
        "status": "ok",
        "decision": d.as_dict(),
        # The rule was NOT run live. Stated, not implied.
        "executable": False,
        "wouldTrade": d.verdict in (_dec.BUY, _dec.SELL),
        "snapshot": snap.as_dict(),
    }
