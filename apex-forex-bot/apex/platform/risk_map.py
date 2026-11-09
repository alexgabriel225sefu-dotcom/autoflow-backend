"""Portfolio risk aggregation with explicit unreadable/unknown states."""
import math
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
    balance_ok = (isinstance(balance, (int, float)) and not isinstance(balance, bool)
                  and math.isfinite(balance) and balance > 0)
    # A partial book is not a percentage. Missing stops used to divide a
    # zero (or a partial sum) by the balance and show 0%, which reads as
    # "nothing is at risk". Unknown stays unknown.
    fraction = (round(total_risk / balance, 8)
                if unread == 0 and balance_ok else None)
    if unread:
        currency = None
        correlations = None
    else:
        currency = _currency_exposure(readable_rows)
        correlations = _correlated_pairs(readable_rows)
    result = {"status": "ok", "totalRisk": round(total_risk, 8),
              "riskFraction": fraction,
              "symbols": dict(by_symbol), "currencyExposure": currency,
              "correlatedPairs": correlations,
              "lossIfEveryStopHit": None if unread else round(total_risk, 8),
              "gapScenario": {"status": "unknown", "reason": "gap size was not supplied"},
              "unreadablePositions": unread,
              "warnings": (["some positions have unknown stop risk"] if unread else [])}
    if not balance_ok:
        result["warnings"].append("account balance is unknown; risk percentage is unavailable")
    if unread:
        result["warnings"].append(
            "correlation is unknown because some positions could not be read")
    return result


def numeric_balance(value):
    """The account balance as a positive finite number, or None.

    A missing balance, a zero, or a payload that is not a number is unknown.
    It is never coerced to 0, which a percentage would then display as safety.
    """
    if isinstance(value, dict):
        return numeric_balance(value.get("balance"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def from_reads(positions, account):
    """One account's risk from the broker reads, or an explicit failure."""
    if not isinstance(positions, dict) or positions.get("status") != "ok":
        out = build([], unreadable=True)
        if isinstance(positions, dict):
            out["reason"] = positions.get("reason") or out.get("reason")
            out["errorCode"] = positions.get("errorCode")
            out["correlationId"] = positions.get("correlationId")
            out["mode"] = positions.get("mode")
            out["accountId"] = positions.get("accountId")
        return out
    rows = positions.get("positions")
    if not isinstance(rows, list):
        out = build([], unreadable=True)
        out["reason"] = "positions came back in a shape that could not be read"
        out["errorCode"] = positions.get("errorCode") or "MALFORMED"
        out["correlationId"] = positions.get("correlationId")
        out["mode"] = positions.get("mode")
        out["accountId"] = positions.get("accountId")
        return out
    balance = None
    if isinstance(account, dict) and account.get("status") == "ok":
        balance = numeric_balance(account.get("balance"))
    out = build(rows, balance=balance)
    out["mode"] = positions.get("mode")
    out["accountId"] = positions.get("accountId")
    if not isinstance(account, dict) or account.get("status") != "ok":
        out["balanceStatus"] = account.get("status") if isinstance(account, dict) else "unavailable"
        out["errorCode"] = (account or {}).get("errorCode") if isinstance(account, dict) else None
        out["correlationId"] = (account or {}).get("correlationId") if isinstance(account, dict) else None
    return out


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
