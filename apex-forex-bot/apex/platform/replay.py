"""Candle-by-candle read-only replay timeline."""
from typing import Any


def timeline(candles: list[dict[str, Any]], *, max_bars: int = 5000) -> dict[str, Any]:
    if not isinstance(candles, list) or not candles:
        raise ValueError("at least one candle is required")
    if len(candles) > max_bars:
        raise ValueError("candle limit exceeded")
    events = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict) or candle.get("close") is None:
            events.append({"index": index, "state": "data_unavailable"})
            continue
        events.append({"index": index, "state": "observed", "close": candle["close"],
                       "timestamp": candle.get("timestamp")})
    return {"status": "ok", "events": events, "readOnly": True,
            "disclaimer": "Replay is historical inspection and does not place orders."}
