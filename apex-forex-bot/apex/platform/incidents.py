"""Incident derivation from observable health facts, without inventing data."""
import time
from typing import Any

from apex import user_store


def derive(facts: dict[str, Any]) -> dict[str, Any]:
    incidents = []
    if facts.get("brokerStatus") in ("unavailable", "reauth_required"):
        incidents.append(_incident("high", "broker", facts["brokerStatus"], facts))
    if facts.get("riskBlocked") is True:
        incidents.append(_incident("high", "risk_guard", "blocked", facts))
    if facts.get("storeAvailable") is False:
        incidents.append(_incident("critical", "store", "unavailable", facts))
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


def record(user_id: str, facts: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Persist only incidents derived from current observable facts."""
    current = derive(facts)
    if not current["incidents"]:
        return {"status": "ok", "incidents": [], "history": _history(user_id)}
    history = _history(user_id)
    for incident in current["incidents"]:
        if not any(row.get("kind") == incident.get("kind")
                   and row.get("status") == incident.get("status")
                   and row.get("recoveredAt") is None for row in history):
            history.append(incident)
    history = history[-200:]
    user_store.update(user_id, {"incidents": history})
    return {**current, "history": history}


def _history(user_id: str) -> list[dict[str, Any]]:
    try:
        value = (user_store.load(user_id) or {}).get("incidents") or []
        return [row for row in value if isinstance(row, dict)]
    except Exception:
        return []


def _incident(severity: str, kind: str, status: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"severity": severity, "kind": kind, "status": status,
            "startedAt": facts.get("startedAt", time.time()),
            "affectedScope": facts.get("affectedScope", "account automation"),
            "systemAction": facts.get("systemAction", "blocked or paused the affected path"),
            "traderActionRequired": facts.get("traderActionRequired", True),
            "recoveredAt": facts.get("recoveredAt")}
