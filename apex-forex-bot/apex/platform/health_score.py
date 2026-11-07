"""Conservative automation health scoring; unknown dependencies reduce score."""
from typing import Any


def score(signals: dict[str, Any]) -> dict[str, Any]:
    not_connected = signals.get("brokerConnected") is False
    checks = {
        "broker": "not_applicable" if not_connected else signals.get("brokerConnected"),
        "data": "not_applicable" if not_connected else signals.get("dataFresh"),
        "session": "not_applicable" if not_connected else signals.get("sessionValid"),
        "rule": signals.get("ruleValid"),
        "risk": "not_applicable" if not_connected else signals.get("riskGuardReady"),
        "store": signals.get("storeAvailable"),
        "incidents": (None if signals.get("criticalIncidents") is None
                      else signals.get("criticalIncidents") is False),
    }
    known = [v for v in checks.values() if isinstance(v, bool)]
    points = sum(v is True for v in known)
    denominator = len(known) if not_connected else len(checks)
    value = round(points / denominator * 100) if denominator else 0
    unknown = [name for name, value in checks.items() if value is None]
    warnings = [f"{name} status is unknown" for name in unknown]
    if not_connected:
        warnings.insert(0, "Connect a cTrader account to check data and session.")
    if any(value is False for value in checks.values()):
        warnings.append("one or more health checks failed")
    status = ("not_connected" if not_connected else
              "healthy" if value >= 85 else "degraded" if value >= 60 else "blocked")
    return {"score": value, "status": status,
            "checks": checks, "warnings": warnings}
