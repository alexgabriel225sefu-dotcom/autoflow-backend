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
    from apex.platform.backtest import decision_at_end
    decision = decision_at_end(rule, symbol, timeframe, bars) or {}
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


def pending_symbols(user_id: str) -> set[str]:
    """Symbols with a signal whose later executable quote is still unknown."""
    try:
        rows = (user_store.load(user_id) or {}).get("forwardEvents") or []
    except Exception:
        return set()
    return {
        _norm_symbol(row.get("symbol")) for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("execution"), dict)
        and row["execution"].get("status") == "pending"
        and row.get("symbol")
    }

def record_bar_close(user_id: str, *, rule: dict[str, Any] | None,
                     symbol: str, timeframe: str,
                     candles: list[dict[str, Any]] | None,
                     bar_close_time: float,
                     later_quote: dict[str, Any] | None = None,
                     max_items: int = 1000,
                     load=None, update=None) -> dict[str, Any]:
    """Record one closed-bar decision and resolve older hypothetical signals.

    This is the worker's only write surface. It evaluates the same pure signal
    builder used by backtest/replay, stores no broker credentials, and never
    calls an execution or order function. A signal is first stored with a
    pending execution. A later broker quote may resolve that event and add the
    directional hypothetical slippage; if that quote is unavailable the value
    remains unknown.
    """
    if not isinstance(rule, dict):
        raise ValueError("an active rule is required")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol is required")
    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe is required")
    bars = candles or []
    if not isinstance(bars, list) or not bars:
        return {"status": "unavailable", "readOnly": True,
                "reason": "the candle snapshot could not be read", "events": []}
    try:
        close_time = float(bar_close_time)
    except (TypeError, ValueError):
        raise ValueError("bar_close_time is required")
    read = load or user_store.load
    write = update or user_store.update
    existing = read(user_id) or {}
    history = list(existing.get("forwardEvents") or [])
    changed: list[dict[str, Any]] = []

    if isinstance(later_quote, dict):
        changed.extend(_resolve_pending(history, symbol, later_quote,
                                        max_items=max_items))

    key = (str(rule.get("ruleDocId") or ""), _norm_symbol(symbol), close_time)
    duplicate = any(_event_key(row) == key for row in history
                    if isinstance(row, dict))
    new_event = None
    if not duplicate:
        from apex.platform.backtest import decision_at_end
        decision = decision_at_end(dict(rule, state="active"), symbol,
                                   timeframe, bars)
        side = (decision or {}).get("side") if isinstance(decision, dict) else None
        signal_price = _number(bars[-1].get("close"))
        new_event = {
            "timestamp": close_time,
            "barCloseTime": close_time,
            "symbol": symbol,
            "signal": side or "none",
            "decision": side or "hold",
            "decisionReason": (decision or {}).get("reason") if isinstance(decision, dict) else None,
            "signalPrice": signal_price,
            "execution": {
                "mode": "hypothetical",
                "status": "pending" if side in ("BUY", "SELL") else "not_applicable",
                "price": None,
                "slippage": None,
            },
            "status": "recorded",
            "ruleDocId": rule.get("ruleDocId"),
        }
        history.append(new_event)
        changed.append(new_event)

    trimmed = history[-max_items:]
    if changed:
        write(user_id, {"forwardEvents": trimmed})
    return {"status": "ok", "readOnly": True, "events": changed,
            "history": trimmed,
            "disclaimer": "Forward testing is hypothetical and does not place orders."}


def _resolve_pending(history: list[dict[str, Any]], symbol: str,
                     quote: dict[str, Any], *, max_items: int) -> list[dict[str, Any]]:
    received = _number(quote.get("receivedAt", quote.get("timestamp")))
    if received is None:
        return []
    bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
    changed = []
    for row in history:
        execution = row.get("execution") if isinstance(row, dict) else None
        if (not isinstance(row, dict)
                or _norm_symbol(row.get("symbol")) != _norm_symbol(symbol)
                or not isinstance(execution, dict)
                or execution.get("status") != "pending"):
            continue
        close_time = _number(row.get("barCloseTime"))
        if close_time is None or received <= close_time:
            continue
        side = row.get("signal")
        price = ask if side == "BUY" else bid if side == "SELL" else None
        if price is None:
            continue
        signal_price = _number(row.get("signalPrice"))
        slippage = None
        if signal_price is not None:
            slippage = price - signal_price if side == "BUY" else signal_price - price
        row["execution"] = {"mode": "hypothetical", "status": "priced",
                             "price": price, "slippage": slippage,
                             "pricedAt": received}
        changed.append(row)
    return changed


def _event_key(row: dict[str, Any]):
    return (str(row.get("ruleDocId") or ""),
            _norm_symbol(row.get("symbol")),
            _number(row.get("barCloseTime")))


def _norm_symbol(symbol: Any) -> str:
    return str(symbol or "").replace("/", "").replace("_", "").upper()


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
