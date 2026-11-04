"""Conservative automation health scoring; unknown dependencies reduce score."""
from typing import Any


def score(signals: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "broker": signals.get("brokerConnected"), "data": signals.get("dataFresh"),
        "session": signals.get("sessionValid"), "rule": signals.get("ruleValid"),
        "risk": signals.get("riskGuardReady"), "store": signals.get("storeAvailable"),
        "incidents": (None if signals.get("criticalIncidents") is None
                      else signals.get("criticalIncidents") is False),
    }
    known = [v for v in checks.values() if isinstance(v, bool)]
    points = sum(v is True for v in known)
    value = round(points / len(checks) * 100) if len(checks) else 0
    unknown = [name for name, value in checks.items() if value is None]
    warnings = [f"{name} status is unknown" for name in unknown]
    if any(value is False for value in checks.values()):
        warnings.append("one or more health checks failed")
    return {"score": value, "status": "healthy" if value >= 85 else "degraded" if value >= 60 else "blocked",
            "checks": checks, "warnings": warnings}
