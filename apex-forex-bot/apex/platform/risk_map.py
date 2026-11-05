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
    readable_rows = []
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
            readable_rows.append((symbol, side, units, risk))
        except (KeyError, TypeError, ValueError):
            unread += 1
    currency = _currency_exposure(readable_rows)
    correlations = _correlated_pairs(readable_rows)
    result = {"status": "ok", "totalRisk": round(total_risk, 8),
              "riskFraction": round(total_risk / balance, 8) if balance and balance > 0 else None,
              "symbols": dict(by_symbol), "currencyExposure": currency,
              "correlatedPairs": correlations,
              "lossIfEveryStopHit": None if unread else round(total_risk, 8),
              "gapScenario": {"status": "unknown", "reason": "gap size was not supplied"},
              "unreadablePositions": unread,
              "warnings": (["some positions have unknown stop risk"] if unread else [])}
    if balance is None:
        result["warnings"].append("account balance is unknown; risk percentage is unavailable")
    return result


def _currency_exposure(rows):
    exposure = defaultdict(float)
    for symbol, side, units, _risk in rows:
        compact = symbol.upper().replace("_", "").replace("/", "").replace("-", "")
        if len(compact) < 6:
            exposure[compact or "unknown"] += units if side == "buy" else -units
            continue
        base, quote = compact[:3], compact[3:6]
        sign = 1 if side == "buy" else -1
        exposure[base] += sign * units
        exposure[quote] -= sign * units
    return {k: round(v, 8) for k, v in sorted(exposure.items())}


def _correlated_pairs(rows):
    groups = []
    for i, (symbol, side, units, _risk) in enumerate(rows):
        compact = symbol.upper().replace("_", "").replace("/", "").replace("-", "")
        a = {compact[:3], compact[3:6]} if len(compact) >= 6 else {compact}
        for other, other_side, other_units, _ in rows[i + 1:]:
            other_compact = other.upper().replace("_", "").replace("/", "").replace("-", "")
            b = ({other_compact[:3], other_compact[3:6]}
                 if len(other_compact) >= 6 else {other_compact})
            shared = sorted(a & b)
            if shared:
                groups.append({"symbols": [symbol, other], "sharedCurrencies": shared,
                               "direction": "same" if side == other_side else "opposite",
                               "units": round(units + other_units, 8)})
    return groups
