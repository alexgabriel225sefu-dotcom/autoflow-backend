"""Conservative automation health scoring; unknown dependencies reduce score.

Candle freshness and position-quote safety are separate from whether the
broker account is linked. A closed market does not count as a dead feed.
The risk guard is ready only when it was actually evaluated and allowed the
next entry. Unavailable is not ready, and it is never reported as ready.
"""
from typing import Any

# How long one bar of each timeframe is. A last bar older than this, plus a
# short grace, is stale while the market is open. It is not compared with a
# flat 120 seconds: that called every hourly bar stale for most of the hour.
_BAR_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}
_FRESH_GRACE_S = 120
# Left out of the score. They are states, not failures and not unknowns.
_EXCLUDED = ("not_applicable", "market_closed")


def bar_seconds(timeframe: str | None) -> int:
    return _BAR_SECONDS.get(str(timeframe or "1h").strip().lower(), 3600)


def candle_freshness(stamp, *, now: float, timeframe: str | None,
                     market_open: bool):
    """True, False, 'market_closed', or None.

    None means the stamp could not be read. False means a bar was read and
    it is older than this timeframe allows while the market is open. A closed
    market is neither of those: no new bar is expected.
    """
    if not market_open:
        return "market_closed"
    try:
        age = float(now) - float(stamp)
    except (TypeError, ValueError):
        return None
    if age < -_FRESH_GRACE_S:
        return None
    return age <= bar_seconds(timeframe) + _FRESH_GRACE_S


def quote_safety(positions_status, positions, *, market_open: bool):
    """Whether open-position quotes are safe to treat as current.

    This is not the broker-link check and not candle freshness. A closed
    market does not make an old quote a feed failure. A failed read while
    the market is open is not safe.
    """
    if not market_open:
        return "market_closed"
    if positions_status != "ok":
        return False
    rows = [row for row in (positions or []) if isinstance(row, dict)]
    if not rows:
        return "not_applicable"
    for row in rows:
        if row.get("quoteStale") is True or row.get("quoteAgeSec") is None:
            return False
    return True


def risk_guard_ready(evaluation) -> bool:
    """True only when this evaluation allowed the next entry.

    A missing evaluation, an exception's stand-in, or a guard that blocked
    because an input was unknown are all not ready. Nothing here defaults
    to ready.
    """
    if not isinstance(evaluation, dict):
        return False
    return evaluation.get("allowed") is True and evaluation.get("mode") == "ready"


def score(signals: dict[str, Any]) -> dict[str, Any]:
    not_connected = signals.get("brokerConnected") is False
    checks = {
        "broker": "not_applicable" if not_connected else signals.get("brokerConnected"),
        "data": "not_applicable" if not_connected else signals.get("dataFresh"),
        "quotes": "not_applicable" if not_connected else signals.get("quoteSafety"),
        "session": "not_applicable" if not_connected else signals.get("sessionValid"),
        "rule": signals.get("ruleValid"),
        "risk": "not_applicable" if not_connected else signals.get("riskGuardReady"),
        "store": signals.get("storeAvailable"),
        "incidents": (None if signals.get("criticalIncidents") is None
                      else signals.get("criticalIncidents") is False),
    }
    applicable = [v for v in checks.values() if v not in _EXCLUDED]
    points = sum(v is True for v in applicable)
    denominator = len(applicable)
    value = round(points / denominator * 100) if denominator else 0
    unknown = [name for name, value in checks.items() if value is None]
    warnings = [f"{name} status is unknown" for name in unknown]
    if not_connected:
        warnings.insert(0, "Connect a cTrader account to check data and session.")
    if any(v == "market_closed" for v in checks.values()):
        warnings.append(
            "The market is closed, so candle age and quote age are not "
            "treated as a feed failure.")
    if any(value is False for value in checks.values()):
        warnings.append("one or more health checks failed")
    status = ("not_connected" if not_connected else
              "healthy" if value >= 85 else "degraded" if value >= 60 else "blocked")
    return {"score": value, "status": status,
            "checks": checks, "warnings": warnings}


def assemble(*, connected, market_open, session_valid, rule_valid,
             store_available, critical_incidents, timeframe, now,
             candle_status, candle_stamp, positions_status, positions,
             guard):
    """Turn one observation into the signals `score` consumes.

    Callers pass what they already read. This function does not open a
    broker connection. `guard` is the risk-guard evaluation, or None when
    that evaluation could not be produced. None is not ready.
    """
    if connected is False:
        data = "not_applicable"
        quotes = "not_applicable"
        risk = "not_applicable"
    elif not market_open:
        data = "market_closed"
        quotes = "market_closed"
        risk = risk_guard_ready(guard)
    else:
        if candle_status != "ok":
            data = None
        else:
            data = candle_freshness(
                candle_stamp, now=now, timeframe=timeframe, market_open=True)
        quotes = quote_safety(positions_status, positions, market_open=True)
        risk = risk_guard_ready(guard)
    return score({
        "brokerConnected": connected,
        "sessionValid": session_valid,
        "storeAvailable": store_available,
        "ruleValid": rule_valid,
        "riskGuardReady": risk,
        "quoteSafety": quotes,
        "dataFresh": data,
        "criticalIncidents": critical_incidents,
    })
