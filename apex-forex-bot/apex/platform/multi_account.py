"""Multi-account isolation helpers. No broker writes and no account switching.

The in-memory store is a small, transport-free reference implementation of
the isolation contract. A production adapter may persist the same two scoped
maps, but it must preserve the user/account key and copy-on-write behaviour.
"""
from copy import deepcopy
from typing import Any

from apex import user_store


def _part(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or ":" in text:
        raise ValueError(f"{name} is invalid")
    return text


def scope_key(user_id: str, ctid: str) -> str:
    """Return a collision-resistant logical scope, never an account-only key."""
    user = _part(user_id, "user id")
    account = _part(ctid, "account id")
    return f"{len(user)}:{user}:{len(account)}:{account}"


class AccountIsolation:
    """Copy-on-write account data and kill switches scoped to one user.

    This class deliberately has no broker dependency. It is used by tests and
    by future persistence adapters to make accidental cross-account lookups
    difficult: every operation requires both the authenticated user and ctid.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._kills: dict[tuple[str, str | None], dict[str, Any]] = {}

    def put(self, user_id: str, ctid: str, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("account data must be an object")
        user = _part(user_id, "user id")
        account = _part(ctid, "account id")
        self._records[scope_key(user, account)] = deepcopy(data)

    def get(self, user_id: str, ctid: str) -> dict[str, Any] | None:
        value = self._records.get(scope_key(user_id, ctid))
        return deepcopy(value) if value is not None else None

    def list_user(self, user_id: str) -> list[dict[str, Any]]:
        user = _part(user_id, "user id")
        prefix = f"{len(user)}:{user}:"
        rows = []
        for key, data in self._records.items():
            if not key.startswith(prefix):
                continue
            account = key[len(prefix):].split(":", 1)[1]
            rows.append({"userId": user, "ctid": account, "data": deepcopy(data)})
        return rows

    def set_kill(self, user_id: str, ctid: str | None, active: bool,
                 *, reason: str = "") -> None:
        user = _part(user_id, "user id")
        account = None if ctid is None else _part(ctid, "account id")
        key = (user, account)
        if active:
            self._kills[key] = {"active": True, "reason": str(reason or "")}
        else:
            self._kills.pop(key, None)

    def kill_state(self, user_id: str, ctid: str) -> dict[str, Any]:
        user = _part(user_id, "user id")
        account = _part(ctid, "account id")
        specific = self._kills.get((user, account))
        global_state = self._kills.get((user, None))
        state = specific or global_state
        if state is None:
            return {"active": False, "scope": scope_key(user, account), "reason": ""}
        return deepcopy({"active": True, "scope": scope_key(user, account), **state})

    def is_killed(self, user_id: str, ctid: str) -> bool:
        return bool(self.kill_state(user_id, ctid)["active"])


class UserStoreIsolation:
    """Persistence adapter exercising the same contract against user_store.

    The browser never calls this directly.  Keeping the adapter here makes
    the isolation tests run against the real durable record shape before any
    multi-account controls are exposed.
    """

    FIELD = "platformAccountScopes"

    def _read(self, user_id: str) -> dict[str, Any]:
        return dict((user_store.load(_part(user_id, "user id")) or {}).get(self.FIELD) or {})

    def put(self, user_id: str, ctid: str, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("account data must be an object")
        uid, aid = _part(user_id, "user id"), _part(ctid, "account id")
        scopes = self._read(uid)
        scopes[aid] = {"data": deepcopy(data), "kill": scopes.get(aid, {}).get("kill", {})}
        user_store.update(uid, {self.FIELD: scopes})

    def get(self, user_id: str, ctid: str) -> dict[str, Any] | None:
        row = self._read(user_id).get(_part(ctid, "account id"))
        return deepcopy(row.get("data")) if isinstance(row, dict) and "data" in row else None

    def set_kill(self, user_id: str, ctid: str | None, active: bool,
                 *, reason: str = "") -> None:
        uid = _part(user_id, "user id")
        key = "__global__" if ctid is None else _part(ctid, "account id")
        scopes = self._read(uid)
        row = dict(scopes.get(key) or {})
        row["kill"] = {"active": True, "reason": str(reason or "")} if active else {}
        scopes[key] = row
        user_store.update(uid, {self.FIELD: scopes})

    def kill_state(self, user_id: str, ctid: str) -> dict[str, Any]:
        uid, aid = _part(user_id, "user id"), _part(ctid, "account id")
        scopes = self._read(uid)
        specific = (scopes.get(aid) or {}).get("kill") or {}
        global_state = (scopes.get("__global__") or {}).get("kill") or {}
        state = specific or global_state
        return {"active": bool(state.get("active")), "scope": scope_key(uid, aid),
                "reason": state.get("reason", "")}

    def is_killed(self, user_id: str, ctid: str) -> bool:
        return self.kill_state(user_id, ctid)["active"]


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
