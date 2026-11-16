"""Append-only audit trail for the future live-execution path.

This is deliberately separate from the customer-facing journal. The journal
answers "what happened to my rule?" for product UX. The live audit answers
"what exactly did the platform do, refuse, or verify?" for review, support and
incident reconstruction.

It imports no execution primitive. It records evidence around a path that is
still unreachable until the live-execution invariant test is rewritten during
the dedicated live milestone review.
"""

import json
import time
import uuid

from apex import user_store
from apex.platform import journal
from apex.platform import store as _store

LIVE_ORDER = "live_order"
REFUSAL = "refusal"
ENTITLEMENT_CHANGE = "entitlement_change"
CONSENT_CHANGE = "consent_change"
MODE_VERIFICATION = "mode_verification"

KINDS = (LIVE_ORDER, REFUSAL, ENTITLEMENT_CHANGE, CONSENT_CHANGE,
         MODE_VERIFICATION)

_SECRET_HINTS = ("token", "secret", "password", "apikey", "api_key",
                 "client_secret", "access", "refresh", "authorization",
                 "cookie", "session", "credential")


class AuditConflict(ValueError):
    """The event id already exists, so appending would rewrite history."""


class AuditUnavailable(RuntimeError):
    """The store could not confirm an append-only write."""


def _k_entry(owner, event_id):
    return f"{_store._ns()}:{_store._P}:liveaudit:{owner}:{event_id}"


def _k_index(owner):
    return f"{_store._ns()}:{_store._P}:liveaudit:index:{owner}"


def _new_event_id():
    return uuid.uuid4().hex


def _safe_str(value):
    if value is None:
        return None
    return str(value)


def _contains_secret_key(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            low = str(key).lower()
            if any(h in low for h in _SECRET_HINTS):
                return True, str(key)
            hit, name = _contains_secret_key(value)
            if hit:
                return True, name
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            hit, name = _contains_secret_key(value)
            if hit:
                return True, name
    return False, None


def _no_credentials(obj):
    hit, name = _contains_secret_key(obj)
    if hit:
        raise ValueError(
            f"live audit entries must not contain credential field {name!r}")


def _write_once(key, row):
    """Create `key`, refusing if it already exists.

    The ordinary platform store exposes an overwrite primitive because rules
    and drafts need one. Audit entries do not. This function uses create-only
    operations directly so a second append with the same event id is refused
    instead of replacing the original row.
    """
    raw = json.dumps(row, separators=(",", ":"), sort_keys=True)
    if user_store._USE_REDIS:
        if user_store._BACKEND == "redis":
            try:
                ok = user_store._r.set(key, raw, nx=True)
            except Exception as e:                       # noqa: BLE001
                raise AuditUnavailable(
                    "audit store did not confirm the append") from e
            if ok:
                return
            raise AuditConflict("audit event already exists")
        res = user_store._upstash_post(["SET", key, raw, "NX"])
        if res is None:
            raise AuditUnavailable("audit store did not confirm the append")
        if str(res).upper() == "OK":
            return
        raise AuditConflict("audit event already exists")

    path = _store._local_path(key)
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(raw)
    except FileExistsError as e:
        raise AuditConflict("audit event already exists") from e


def _read_index(owner):
    raw = _store._read(_k_index(owner))
    return raw if isinstance(raw, list) else []


def _index(owner, row):
    """Best-effort read index; entries remain durable without it."""
    head = {
        "id": row["eventId"],
        "kind": row["kind"],
        "ts": row["ts"],
        "actorId": row.get("actorId"),
        "accountId": row.get("accountId"),
        "ruleDocId": row.get("ruleDocId"),
        "decisionId": row.get("decisionId"),
        "gate": row.get("gate"),
        "code": row.get("code"),
    }
    idx = _read_index(owner)
    if not any(h.get("id") == row["eventId"] for h in idx):
        idx.insert(0, head)
        _store._write(_k_index(owner), idx[:10000])


def _base(kind, *, user_id, actor_id=None, event_id=None, ts=None, **fields):
    if kind not in KINDS:
        raise ValueError(f"audit kind must be one of {KINDS}, got {kind!r}")
    if not user_id:
        raise ValueError("audit event needs a user_id")
    row = {
        "eventId": event_id or _new_event_id(),
        "kind": kind,
        "ts": float(time.time() if ts is None else ts),
        "userId": str(user_id),
        "actorId": str(actor_id or user_id),
    }
    for key, value in fields.items():
        if value is not None:
            row[key] = value
    _no_credentials(row)
    return journal.redact(row)


def append(row):
    """Append one already-shaped audit row and return the stored row."""
    if not isinstance(row, dict):
        raise ValueError("audit append needs a dict row")
    row = dict(row)
    row.setdefault("eventId", _new_event_id())
    row.setdefault("ts", time.time())
    if row.get("kind") not in KINDS:
        raise ValueError(f"audit kind must be one of {KINDS}")
    if not row.get("userId"):
        raise ValueError("audit event needs a userId")
    row["userId"] = str(row["userId"])
    row["actorId"] = str(row.get("actorId") or row["userId"])
    _no_credentials(row)
    row = journal.redact(row)
    _write_once(_k_entry(row["userId"], row["eventId"]), row)
    _index(row["userId"], row)
    return row


def get(user_id, event_id):
    row = _store._read(_k_entry(str(user_id), str(event_id)))
    if not isinstance(row, dict) or str(row.get("userId")) != str(user_id):
        raise LookupError("no such live audit event")
    return row


def query(user_id, *, kind=None, limit=100):
    if kind is not None and kind not in KINDS:
        raise ValueError(f"audit kind must be one of {KINDS}")
    limit = max(1, min(int(limit or 100), 500))
    heads = _read_index(str(user_id))
    rows = []
    for head in heads:
        if kind is not None and head.get("kind") != kind:
            continue
        try:
            rows.append(get(user_id, head["id"]))
        except LookupError:
            continue
        if len(rows) >= limit:
            break
    return rows


def record_live_order(*, user_id, actor_id, account_id, rule_doc_id,
                      rule_doc_version, decision_id, request, broker_reply,
                      position_id=None, event_id=None, ts=None):
    row = _base(
        LIVE_ORDER, user_id=user_id, actor_id=actor_id, event_id=event_id,
        ts=ts, accountId=_safe_str(account_id),
        ruleDocId=_safe_str(rule_doc_id), ruleDocVersion=rule_doc_version,
        decisionId=_safe_str(decision_id), request=request,
        brokerReply=broker_reply, positionId=_safe_str(position_id))
    return append(row)


def record_refusal(*, user_id, actor_id, gate, code, decision_id=None,
                   account_id=None, rule_doc_id=None, rule_doc_version=None,
                   detail=None, event_id=None, ts=None):
    if not gate:
        raise ValueError("audit refusal needs a gate")
    if not code:
        raise ValueError("audit refusal needs a code")
    row = _base(
        REFUSAL, user_id=user_id, actor_id=actor_id, event_id=event_id,
        ts=ts, gate=_safe_str(gate), code=_safe_str(code),
        decisionId=_safe_str(decision_id), accountId=_safe_str(account_id),
        ruleDocId=_safe_str(rule_doc_id), ruleDocVersion=rule_doc_version,
        detail=detail)
    return append(row)


def record_entitlement_change(*, user_id, actor_id, before, after,
                              event_id=None, ts=None):
    row = _base(ENTITLEMENT_CHANGE, user_id=user_id, actor_id=actor_id,
                event_id=event_id, ts=ts, before=before, after=after)
    return append(row)


def record_consent_change(*, user_id, actor_id, before, after,
                          event_id=None, ts=None):
    row = _base(CONSENT_CHANGE, user_id=user_id, actor_id=actor_id,
                event_id=event_id, ts=ts, before=before, after=after)
    return append(row)


def record_mode_verification(*, user_id, actor_id, account_id, requested_mode,
                             broker_answer, event_id=None, ts=None):
    row = _base(MODE_VERIFICATION, user_id=user_id, actor_id=actor_id,
                event_id=event_id, ts=ts, accountId=_safe_str(account_id),
                requestedMode=_safe_str(requested_mode),
                brokerAnswer=broker_answer)
    return append(row)


def storage_files_for_tests(user_id, event_id):
    """Expose local test paths without making the production API writable."""
    return {
        "entry": _store._local_path(_k_entry(str(user_id), str(event_id))),
        "index": _store._local_path(_k_index(str(user_id))),
    }
