"""Portfolio risk aggregation with explicit unreadable/unknown states."""
from collections import defaultdict
from typing import Any


def build(positions: list[dict[str, Any]], *, balance: float | None = None,
          unreadable: bool = False) -> dict[str, Any]:
    if unreadable:
        return {"status": "unavailable", "reason": "positions could not be read"}
    if not isinstance(positions, list):
        return {"status": "unavailable", "reason": "positions response was invalid"}
    by_symbol: dict[str, dict[str, float]] = defaultdict(lambda: {"long": 0.0, "short": 0.0, "risk": 0.0})
    currency: dict[str, float] = defaultdict(float)
    unread = 0
    total_risk = 0.0
    for row in positions:
        try:
            symbol = str(row["symbol"])
            side = str(row["side"]).lower()
            units = abs(float(row["units"]))
            risk = row.get("riskToStop")
            if risk is None or row.get("hasStop") is False:
                unread += 1
                continue
            risk = abs(float(risk))
            by_symbol[symbol]["long" if side == "buy" else "short"] += units
            by_symbol[symbol]["risk"] += risk
            total_risk += risk
        except (KeyError, TypeError, ValueError):
            unread += 1
    result = {"status": "ok", "totalRisk": round(total_risk, 8),
              "riskFraction": round(total_risk / balance, 8) if balance and balance > 0 else None,
              "symbols": dict(by_symbol), "currencyExposure": dict(currency),
              "unreadablePositions": unread,
              "warnings": (["some positions have unknown stop risk"] if unread else [])}
    if balance is None:
        result["warnings"].append("account balance is unknown; risk percentage is unavailable")
    return result
