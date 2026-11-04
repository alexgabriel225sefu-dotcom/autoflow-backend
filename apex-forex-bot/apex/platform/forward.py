"""Forward-test ledger for hypothetical signals; never submits orders."""
from typing import Any


def record(signals: list[dict[str, Any]], *, max_items: int = 1000) -> dict[str, Any]:
    if not isinstance(signals, list):
        raise ValueError("signals must be a list")
    if len(signals) > max_items:
        raise ValueError("signal limit exceeded")
    events = []
    for item in signals:
        if not isinstance(item, dict):
            continue
        events.append({"timestamp": item.get("timestamp"), "symbol": item.get("symbol"),
                       "decision": item.get("decision", "unknown"), "execution": "hypothetical",
                       "slippage": item.get("slippage"), "status": "recorded"})
    return {"status": "ok", "readOnly": True, "events": events,
            "disclaimer": "Forward testing is hypothetical and does not place orders."}
