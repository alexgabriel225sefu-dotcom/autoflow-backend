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
    checked = sorted(k for k in ("brokerStatus", "riskBlocked", "storeAvailable")
                     if facts.get(k) is not None)
    not_checked = sorted(k for k in ("brokerStatus", "riskBlocked", "storeAvailable")
                         if facts.get(k) is None)
    if incidents:
        message = "Observed incidents require review"
    elif checked:
        message = ("Nothing wrong in what was checked (" + ", ".join(checked) + ")."
                   + (" Not checked: " + ", ".join(not_checked) + "." if not_checked else ""))
    else:
        message = "Nothing could be checked just now, so this is not an all-clear."
    return {"status": "ok", "incidents": incidents, "checked": checked,
            "notChecked": not_checked, "message": message}
