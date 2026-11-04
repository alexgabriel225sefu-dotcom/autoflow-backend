"""Incident derivation from observable health facts, without inventing data."""
from typing import Any


def derive(facts: dict[str, Any]) -> dict[str, Any]:
    incidents = []
    if facts.get("brokerStatus") in ("unavailable", "reauth_required"):
        incidents.append({"severity": "high", "kind": "broker", "status": facts["brokerStatus"]})
    if facts.get("riskBlocked") is True:
        incidents.append({"severity": "high", "kind": "risk_guard", "status": "blocked"})
    if facts.get("storeAvailable") is False:
        incidents.append({"severity": "critical", "kind": "store", "status": "unavailable"})
    return {"status": "ok", "incidents": incidents,
            "message": "No observed incidents" if not incidents else "Observed incidents require review"}
