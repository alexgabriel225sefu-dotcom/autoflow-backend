"""Candle-by-candle read-only replay timeline."""
from typing import Any


def timeline(candles: list[dict[str, Any]], *, max_bars: int = 5000,
             rule: dict[str, Any] | None = None, symbol: str | None = None,
             timeframe: str | None = None) -> dict[str, Any]:
    if not isinstance(candles, list) or not candles:
        raise ValueError("at least one candle is required")
    if len(candles) > max_bars:
        raise ValueError("candle limit exceeded")
    events = []
    history: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict) or candle.get("close") is None:
            events.append({"index": index, "state": "data_unavailable"})
            continue
        history.append(candle)
        event = {"index": index, "state": "observed", "close": candle["close"],
                 "timestamp": candle.get("time", candle.get("timestamp"))}
        if rule is not None:
            event.update(_explain_bar(rule, history, symbol, timeframe, candle))
        events.append(event)
    return {"status": "ok", "events": events, "readOnly": True,
            "disclaimer": "Replay is historical inspection and does not place orders."}


def _explain_bar(rule, history, symbol, timeframe, candle):
    """Evaluate only bars through the cursor; never pass future data."""
    if not symbol or not timeframe or candle.get("time", candle.get("timestamp")) is None:
        return {"conditions": [], "entry": None, "stop": None,
                "explanation": "The rule could not be read at this bar."}
    from apex.platform import decision as _decision
    from apex.platform import evaluator as _evaluator
    from apex.platform import explain as _explain
    from apex.platform.snapshot import MarketSnapshot
    verdict = _evaluator.evaluate(
        dict(rule, state="active"),
        MarketSnapshot(symbol=symbol, timeframe=timeframe, candles=list(history),
                       price=candle.get("close"), ts=float(candle.get("time", candle.get("timestamp")))))
    detail = _explain.explain(verdict.as_dict())
    entry = candle.get("open") if verdict.verdict in (_decision.BUY, _decision.SELL) else None
    stop = _stop_for_bar(rule, entry, verdict.verdict, symbol)
    return {"conditions": {"met": detail.get("met", []), "unmet": detail.get("unmet", []),
                            "unknown": detail.get("unknown", [])},
            "entry": {"side": verdict.verdict, "price": entry} if entry is not None else None,
            "stop": stop, "explanation": detail.get("headline"),
            "dataAvailableThrough": candle.get("time", candle.get("timestamp"))}


def _stop_for_bar(rule, entry, verdict, symbol):
    if entry is None or verdict not in ("BUY", "SELL"):
        return None
    stop = rule.get("stopLoss") if isinstance(rule, dict) else None
    if not isinstance(stop, dict):
        return None
    pips = stop.get("pips")
    try:
        from apex import forex
        distance = forex.from_pips(float(pips), symbol, float(entry))
    except (TypeError, ValueError):
        return None
    return round(float(entry) - distance if verdict == "BUY" else float(entry) + distance, 8)
