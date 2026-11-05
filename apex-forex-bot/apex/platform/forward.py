"""Forward-test ledger for hypothetical signals; never submits orders."""
import time
from typing import Any

from apex import user_store


def record(signals: list[dict[str, Any]], *, max_items: int = 1000) -> dict[str, Any]:
    if not isinstance(signals, list):
        raise ValueError("signals must be a list")
    if len(signals) > max_items:
        raise ValueError("signal limit exceeded")
    events = []
    for item in signals:
        if not isinstance(item, dict):
            continue
        events.append(_event(item))
    return {"status": "ok", "readOnly": True, "events": events,
            "disclaimer": "Forward testing is hypothetical and does not place orders."}


def record_for_user(user_id: str, *, rule: dict[str, Any] | None,
                    candles: list[dict[str, Any]] | None = None,
                    executable_price: float | None = None,
                    max_items: int = 1000) -> dict[str, Any]:
    """Evaluate the selected rule on the supplied live snapshot and persist it.

    This is intentionally a recording endpoint, not a scheduler or an order
    path.  The caller supplies the latest read-only candle and an optional
    later executable price; missing values remain unknown.
    """
    if not isinstance(rule, dict):
        raise ValueError("an active rule is required")
    bars = candles or []
    if not isinstance(bars, list) or len(bars) > max_items:
        raise ValueError("candle limit exceeded")
    if not bars:
        return {"status": "unavailable", "readOnly": True,
                "reason": "the candle snapshot could not be read", "events": []}
    symbol = str(rule.get("symbols", [""])[0] if isinstance(rule.get("symbols"), list)
                 and rule.get("symbols") else rule.get("symbol") or "")
    timeframe = str(rule.get("timeframe") or "1h")
    from apex.platform.backtest import _rule_signal
    signal = _rule_signal(rule, symbol, timeframe)
    decision = signal(bars[-1]) or {}
    side = decision.get("side") if isinstance(decision, dict) else None
    close = _number(bars[-1].get("close"))
    later = _number(executable_price)
    slip = None if close is None or later is None else later - close
    event = _event({"timestamp": bars[-1].get("time", time.time()),
                    "symbol": symbol, "signal": side or "none",
                    "decision": side or "hold", "signalPrice": close,
                    "executablePrice": later, "slippage": slip,
                    "execution": "hypothetical", "ruleDocId": rule.get("ruleDocId")})
    existing = user_store.load(user_id) or {}
    history = list(existing.get("forwardEvents") or [])
    history.append(event)
    user_store.update(user_id, {"forwardEvents": history[-max_items:]})
    return {"status": "ok", "readOnly": True, "events": [event],
            "history": history[-max_items:],
            "disclaimer": "Forward testing is hypothetical and does not place orders."}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _event(item: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": item.get("timestamp"), "symbol": item.get("symbol"),
            "signal": item.get("signal", item.get("decision", "unknown")),
            "decision": item.get("decision", "unknown"),
            "execution": {"mode": "hypothetical", "status": "recorded",
                           "price": item.get("executablePrice"),
                           "slippage": item.get("slippage")},
            "status": "recorded", "ruleDocId": item.get("ruleDocId")}
