"""Multi-account isolation helpers. No broker writes and no account switching."""
from typing import Any


def isolate(user_id: str, accounts: list[dict[str, Any]]) -> dict[str, Any]:
    if not user_id:
        raise ValueError("user id is required")
    out = []
    for account in accounts:
        if not isinstance(account, dict) or account.get("ctid") is None:
            continue
        out.append({"ctid": str(account["ctid"]), "mode": account.get("mode"),
                    "selected": bool(account.get("selected")),
                    "scope": f"{user_id}:{account['ctid']}"})
    return {"status": "ok", "accounts": out,
            "isolation": "each account is scoped to the authenticated user"}
