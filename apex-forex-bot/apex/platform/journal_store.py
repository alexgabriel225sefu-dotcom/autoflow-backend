"""Where journal entries live, and how a client reads their own back.

THE ONE RULE: an empty page means we looked and found nothing.

`query` never fabricates an entry and never invents a total. When a client has
written nothing, the answer is an empty list with status ok and a total of
zero — a statement that the store was read, not a placeholder standing in for
a read that did not happen. That distinction is the reason this module exists
separately from journal.py, which stays pure and knows nothing about storage.

OWNERSHIP IS THE KEY, AS IT IS FOR RULES

Every entry is stored under its owner's id and every read is scoped by it, so
asking for somebody else's journal looks in a namespace where it is not. The
entry's own user_id is compared as well, one line further down, as the second
line of defence against a key built wrong.

THE INDEX, AND WHAT IT COSTS

Redis is reached here through user_store's get_blob/set_blob, which give no
atomic list append. So the per-user index is an ordered JSON list read,
modified and written back, guarded by user_store.claim_value where a shared
backend exists. Without one — development only — the guard is absent and two
processes appending at once could lose a line. That is stated rather than
hidden, and it is why the entry itself is written BEFORE the index: a crash
between the two loses the entry from the list but not from storage, which is
recoverable, while the other order would index an entry that was never
written.
"""

import json
import time
import uuid

from apex import user_store
from apex.platform import journal as _j
from apex.platform import store as _store

# Per client. A journal is evidence, not a metrics pipeline: this is enough to
# cover months of a normal account, and the cap is stated so nobody discovers
# it as data loss later.
MAX_ENTRIES = 5000
_LOCK_TTL_S = 10


class JournalNotFound(LookupError):
    """No such entry for this owner. Same answer as one that never existed."""


def _k_entry(owner, entry_id):
    return f"{_store._ns()}:{_store._P}:jentry:{owner}:{entry_id}"


def _k_index(owner):
    return f"{_store._ns()}:{_store._P}:jindex:{owner}"


def _k_lock(owner):
    return f"{_store._ns()}:{_store._P}:jlock:{owner}"


def _read_index(owner):
    raw = _store._read(_k_index(owner))
    return raw if isinstance(raw, list) else []


def append(entry):
    """Persist one entry. Returns it.

    The entry is already redacted by JournalEntry's constructor — redaction
    happens on the way IN, so a credential that never entered cannot leak out
    of here later through a query or an export.
    """
    owner = str(entry.user_id)
    row = entry.as_dict()
    _store._write(_k_entry(owner, entry.entry_id), row)

    token = uuid.uuid4().hex
    got = user_store.claim_value(_k_lock(owner), token, ttl_s=_LOCK_TTL_S)
    try:
        idx = _read_index(owner)
        idx.insert(0, {"id": entry.entry_id, "ts": entry.ts,
                       "status": entry.status, "kind": entry.kind,
                       "symbol": entry.symbol,
                       "accountId": entry.account_id,
                       "ruleDocId": entry.rule_doc_id})
        if len(idx) > MAX_ENTRIES:
            for dropped in idx[MAX_ENTRIES:]:
                _store._write(_k_entry(owner, dropped["id"]), None)
            idx = idx[:MAX_ENTRIES]
        _store._write(_k_index(owner), idx)
    finally:
        if got:
            try:
                user_store.release_claim(_k_lock(owner), token)
            except Exception:
                pass
    return entry


def get(owner_id, entry_id):
    """One entry, or JournalNotFound."""
    owner = str(owner_id)
    row = _store._read(_k_entry(owner, str(entry_id)))
    if not row:
        raise JournalNotFound("no such journal entry")
    if str(row.get("userId")) != owner:
        raise JournalNotFound("no such journal entry")
    return row


def _matches(head, *, account_id, symbol, since, until, rule_doc_id, status):
    if account_id is not None and str(head.get("accountId")) != str(account_id):
        return False
    if symbol is not None:
        n = lambda s: str(s or "").replace("_", "").replace("/", "").upper()
        if n(head.get("symbol")) != n(symbol):
            return False
    if since is not None and float(head.get("ts") or 0) < float(since):
        return False
    if until is not None and float(head.get("ts") or 0) > float(until):
        return False
    if rule_doc_id is not None and head.get("ruleDocId") != rule_doc_id:
        return False
    if status is not None and head.get("status") != status:
        return False
    return True


def query(owner_id, *, account_id=None, symbol=None, since=None, until=None,
          rule_doc_id=None, status=None, limit=50, offset=0):
    """A page of this client's journal, newest first.

    Filtering happens on the INDEX, which carries just enough of each entry to
    answer every filter. Only the entries that survive are then loaded, so a
    narrow filter over a long journal does not read the whole thing.
    """
    owner = str(owner_id)
    if status is not None and status not in _j.STATUSES:
        raise ValueError(f"status must be one of {', '.join(_j.STATUSES)}")
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))

    heads = [h for h in _read_index(owner)
             if _matches(h, account_id=account_id, symbol=symbol,
                         since=since, until=until, rule_doc_id=rule_doc_id,
                         status=status)]
    page = heads[offset:offset + limit]
    rows = []
    for h in page:
        row = _store._read(_k_entry(owner, h["id"]))
        if row and str(row.get("userId")) == owner:
            rows.append(row)
    return {
        "status": "ok",
        "entries": rows,
        "total": len(heads),
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(page) < len(heads),
    }


def record_evaluation(decision, snapshot, *, correlation_id, user_id,
                      account_id=None, ts=None):
    return append(_j.for_evaluation(decision, snapshot,
                                    correlation_id=correlation_id,
                                    user_id=user_id, account_id=account_id,
                                    ts=ts))


def record_execution(request, *, correlation_id, result=None, ts=None):
    return append(_j.for_execution(request, correlation_id=correlation_id,
                                   result=result, ts=ts))


def record_order_sent(request, *, correlation_id, ts=None):
    return append(_j.for_order_sent(request, correlation_id=correlation_id,
                                    ts=ts))


def record_error(message, *, correlation_id, user_id, account_id=None,
                 symbol=None, ts=None):
    return append(_j.for_error(message, correlation_id=correlation_id,
                               user_id=user_id, account_id=account_id,
                               symbol=symbol, ts=ts))


def record_automation(status, *, correlation_id, user_id, **kw):
    return append(_j.for_automation(status, correlation_id=correlation_id,
                                    user_id=user_id, **kw))


def record_position_closed(position, *, correlation_id, user_id, **kw):
    return append(_j.for_position_closed(
        position, correlation_id=correlation_id, user_id=user_id, **kw))
