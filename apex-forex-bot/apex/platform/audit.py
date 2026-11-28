"""The audit trail §7 requires — append-only, chained, and never credentialed.

WHY THIS IS NOT journal_store

`journal_store` is a client's own history, and it is built for that: it caps
at MAX_ENTRIES and DELETES the overflow, and it writes with `set_blob`, which
replaces whatever was at the key. Both choices are right for a journal and
both disqualify it from being an audit trail, because the records §7 lists —
every live order, every refusal, every entitlement and consent change, every
mode verification — are exactly the ones somebody comes looking for after an
incident, which is when they are the oldest things in the store.

So this module exists beside the journal rather than inside it. A decision is
journalled for the client AND audited for the record; the two answer different
questions and must not share a retention policy.

THE THREE PROPERTIES, AND WHAT EACH ONE COSTS

**Append-only.** Every record is written with SET NX and no expiry
(`user_store.set_blob_nx`). A sequence number that exists is REFUSED, never
replaced — §7: "a record the application can rewrite is not an audit trail".
`set_blob` and `del_blob` are not imported, not referenced, and asserted
absent from this module's AST, because an overwriting primitive sitting unused
here is one edit away from being used.

**Tamper-evident.** Append-only writes cannot stop deletion at the
infrastructure level — nothing an application does can. What it can do is make
a deletion or an alteration DETECTABLE, so the records are hash-chained: each
one carries the hash of the one before it, and `verify()` walks the chain and
names the first break. A trail nobody can check is a trail nobody can rely on.

**No credential, ever.** Redaction happens on the way IN, through the same
`journal.redact` the journal uses, which masks on the KEY rather than guessing
from values. A value that never entered cannot leak later through a read, an
export or a support screen.

THE SEQUENCE NUMBER, AND WHY THERE IS NO HEAD POINTER

Records are keyed by a per-owner sequence number, so a gap is visible rather
than inferred from timestamps. The obvious way to find the next number is a
stored `head` pointer — and this module deliberately does not have one. A
pointer would be the single mutable thing in an append-only trail: it needs an
overwriting write, and a stale or forged one would hide the tail of a trail
from every reader that trusted it. So the end is derived from the records
instead: a doubling search for a write (O(log n)), and a gap-tolerant walk for
a read, which keeps going past a missing record rather than treating it as the
end. Nothing in this module is written twice, including its bookkeeping.

WHAT IT CANNOT DO

It records; it decides nothing and reaches no broker. There is no import of
the execution path here and there must never be one.

See §7 of docs/LIVE_EXECUTION_SPECIFICATION.md.
"""

import hashlib
import json
import time

from apex import user_store
from apex.platform import journal as _journal
from apex.platform import store as _store

# ── record kinds ────────────────────────────────────────────────────────────
LIVE_ORDER = "live_order"
REFUSAL = "refusal"
ENTITLEMENT = "entitlement_change"
CONSENT = "consent_change"
MODE_VERIFICATION = "mode_verification"
KINDS = (LIVE_ORDER, REFUSAL, ENTITLEMENT, CONSENT, MODE_VERIFICATION)

# Declared, and declared as None, so the absence is a decision somebody made
# rather than a line nobody wrote. journal_store caps at 5000 and deletes the
# overflow; an audit trail that evicts its oldest records has thrown away the
# evidence before anyone asks for it.
MAX_ENTRIES = None

# How far a write will walk forward past sequence numbers already taken before
# giving up. Reached only under heavy concurrent appending, or after a gap left
# the search for the end low — a recovery path, not a hot one.
_MAX_SEQ_PROBE = 1000

# How far a reader looks past a missing record before accepting that the trail
# ends there. A gap wider than this is indistinguishable from the end, and
# saying where the limit is beats scanning forever.
_GAP_PROBE = 64

# An upper bound on the doubling search, so a store returning nonsense cannot
# turn the hunt for the end of a trail into an unbounded read loop.
_SEQ_CEILING = 1 << 30


class AuditUnavailable(RuntimeError):
    """The store could not confirm the write, so nothing may be assumed."""


class AuditImmutable(RuntimeError):
    """Something is already recorded at this sequence number."""


class AuditNotFound(LookupError):
    """No such record for this owner. Same answer as one that never existed."""


class SharedBackendRequired(RuntimeError):
    """An audit trail cannot be per-container."""


# ── the backend this needs ──────────────────────────────────────────────────
def shared_backend():
    """True when records are visible to every other instance."""
    return bool(getattr(user_store, "_USE_REDIS", False))


def assert_shared_backend():
    """Raise unless the trail is one trail.

    In production `user_store` already refuses to import without a shared
    backend, so that gate fires first and this one is the backstop: it keeps
    the guarantee attached to the audit trail itself rather than borrowed from
    a check in another module that a future edit could relax.
    """
    if shared_backend():
        return True
    raise SharedBackendRequired(
        "the audit trail requires a shared backend and this process has "
        "none.\n"
        "A local JSON store is per-container: each instance would keep its "
        "own partial trail, and the record of a live order would exist only "
        "on whichever container happened to place it. That is worse than no "
        "trail, because each one reads as complete.\n"
        "Configure REDIS_URL or the Upstash REST pair — see §7 of "
        "docs/LIVE_EXECUTION_SPECIFICATION.md."
    )


# ── keys ────────────────────────────────────────────────────────────────────
def _k_record(owner, seq):
    return f"{_store._ns()}:{_store._P}:audit:{owner}:{int(seq)}"


# ── the chain ───────────────────────────────────────────────────────────────
def _canonical(row):
    """The bytes a hash is taken over. Sorted keys, no incidental whitespace,
    so the same record hashes the same way in any process."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


def _hash_of(row):
    """The record's hash, over everything in it EXCEPT the hash field.

    `prevHash` is inside the hashed body on purpose: that is what binds each
    record to its predecessor, so altering an earlier record invalidates every
    record after it rather than only itself.
    """
    body = {k: v for k, v in row.items() if k != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def _read_row(owner, seq):
    """One stored record, or None. Raises if the store cannot be asked."""
    raw = user_store.get_blob(_k_record(owner, seq))
    if raw is None:
        return None
    try:
        row = json.loads(raw)
    except Exception as e:                                   # noqa: BLE001
        raise AuditUnavailable(
            f"audit record {owner}:{seq} is not readable as JSON "
            f"({type(e).__name__}) — it is present and cannot be trusted, "
            f"which verify() reports rather than skipping") from e
    return row if isinstance(row, dict) else None


def _last_seq(owner):
    """The highest sequence number in use, found from the RECORDS.

    There is no stored "head" pointer, and that is the design rather than an
    omission. A pointer would be the one mutable thing in an append-only
    trail: it would need `set_blob`, and a stale or forged one could hide the
    tail of a trail from every reader that believed it. Deriving the end from
    the records removes that whole class of problem — nothing here can be
    rewritten, because nothing here is written twice.

    Doubling, then a binary search between the last hit and the first miss, so
    an append costs O(log n) reads rather than one per existing record. A gap
    left by a removed record can make this land low; that is safe for a WRITE,
    because the NX write collides forward past anything already there, and
    readers use the gap-tolerant walk below instead.
    """
    if _read_row(owner, 1) is None:
        return 0
    lo, hi = 1, 2
    while hi <= _SEQ_CEILING and _read_row(owner, hi) is not None:
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _read_row(owner, mid) is not None:
            lo = mid
        else:
            hi = mid
    return lo


def _walk(owner):
    """(seq, row) for every record, oldest first, tolerating gaps.

    Readers cannot use `_last_seq`: a record removed from the middle would
    shorten the binary search's answer and silently hide everything after it,
    which is precisely the tampering this trail exists to expose. So a read
    keeps going until it has seen `_GAP_PROBE` consecutive empty slots. That
    costs a fixed number of extra reads per read, and buys an answer that does
    not depend on the store being untampered with.
    """
    seq, misses = 1, 0
    while misses <= _GAP_PROBE:
        row = _read_row(owner, seq)
        if row is None:
            misses += 1
        else:
            misses = 0
            yield seq, row
        seq += 1


def _write_record(row):
    """Persist one record at its own sequence number. Never replaces one.

    This is the only function here that writes a record, and SET NX is the
    only way it writes — so "append-only" is a property of one line rather
        than a convention spread across five call sites.
    """
    owner = str(row.get("userId") or "")
    seq = int(row.get("seq") or 0)
    if not owner or seq < 1:
        raise ValueError("an audit record needs an owner and a sequence "
                         "number before it can be written")
    got = user_store.set_blob_nx(_k_record(owner, seq),
                                 _canonical(row).decode("utf-8"))
    if got is None:
        # Not "already there". The store could not be asked, and a caller
        # that carries on has placed a live order with no record of it.
        raise AuditUnavailable(
            f"the store could not confirm the audit record for {owner} at "
            f"sequence {seq}; nothing may be assumed to have been recorded")
    if got is False:
        raise AuditImmutable(
            f"sequence {seq} is already recorded for {owner} and an audit "
            f"record is never replaced")
    return row


def _append(owner, body):
    """Chain one record on and store it. Returns the stored record."""
    assert_shared_backend()
    owner = str(owner)
    seq = _last_seq(owner) + 1
    for _ in range(_MAX_SEQ_PROBE):
        prev = _read_row(owner, seq - 1) if seq > 1 else None
        row = dict(body)
        row["seq"] = seq
        # The empty string rather than None for the first record: one type for
        # the field, so a comparison never silently compares None to "".
        row["prevHash"] = str((prev or {}).get("hash") or "")
        row["hash"] = _hash_of(row)
        try:
            return _write_record(row)
        except AuditImmutable:
            # A concurrent writer holds this number. Move forward and re-chain
            # against whatever is now behind us; never replace.
            seq += 1
            continue
    raise AuditUnavailable(
        f"could not find a free audit sequence number for {owner} after "
        f"{_MAX_SEQ_PROBE} attempts")


def _base(kind, *, user_id, actor, account_id=None, ts=None):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if not str(user_id or "").strip():
        raise ValueError("an audit record needs the account it is about")
    if not str(actor or "").strip():
        # §7 requires WHO for every record, not only for the ones where it is
        # convenient. "system:loop" is an actor; empty is a missing field.
        raise ValueError(
            f"an audit record needs an actor — §7 requires who performed "
            f"every {kind} and an unattributable record is not evidence")
    return {"kind": kind, "userId": str(user_id), "actor": str(actor),
            "accountId": (str(account_id) if account_id is not None else None),
            "ts": float(time.time() if ts is None else ts)}


# ── what §7 names, one function each ────────────────────────────────────────
def record_live_order(*, user_id, actor, request, broker_reply,
                      account_id=None, rule_doc_id=None, rule_doc_version=None,
                      decision_id=None, position_id=None, ts=None):
    """§7: who, when, which rule version, which decision, the full request,
    the broker's reply, and the resulting position id."""
    row = _base(LIVE_ORDER, user_id=user_id, actor=actor,
                account_id=account_id, ts=ts)
    row.update({
        "ruleDocId": rule_doc_id,
        "ruleDocVersion": rule_doc_version,
        "decisionId": decision_id,
        "positionId": position_id,
        # Redacted here, on the way in. The full request is required and a
        # credential inside it is not part of what is required.
        "request": _journal.redact(request),
        "brokerReply": _journal.redact(broker_reply),
    })
    return _append(user_id, row)


def record_refusal(*, user_id, actor, gate, code, reason, account_id=None,
                   rule_doc_id=None, rule_doc_version=None, decision_id=None,
                   ts=None):
    """§7: every refusal, with its gate and its code."""
    if not str(gate or "").strip():
        raise ValueError(
            "a refusal must name the gate that refused — a refusal nobody "
            "can attribute cannot be reviewed or fixed")
    if not str(code or "").strip():
        raise ValueError(
            "a refusal must carry its code — the reason is prose for a "
            "human, the code is what a review counts")
    row = _base(REFUSAL, user_id=user_id, actor=actor,
                account_id=account_id, ts=ts)
    row.update({"gate": str(gate), "code": str(code),
                "reason": str(reason or "")[:1000],
                "ruleDocId": rule_doc_id,
                "ruleDocVersion": rule_doc_version,
                "decisionId": decision_id})
    return _append(user_id, row)


def record_entitlement_change(*, user_id, actor, field, old_value, new_value,
                              reason=None, account_id=None, ts=None):
    """§7: every entitlement change, with the actor."""
    if not str(field or "").strip():
        raise ValueError("an entitlement change must name the field")
    row = _base(ENTITLEMENT, user_id=user_id, actor=actor,
                account_id=account_id, ts=ts)
    row.update({"field": str(field),
                "oldValue": _journal.redact(old_value),
                "newValue": _journal.redact(new_value),
                "reason": str(reason or "")[:1000]})
    return _append(user_id, row)


def record_consent_change(*, user_id, actor, document, version, granted,
                          account_id=None, ts=None):
    """§7: every consent change, with the actor.

    The document VERSION is part of the record because consent is to a text,
    and "they agreed" is not evidence of what they agreed to.
    """
    if not str(document or "").strip():
        raise ValueError("a consent change must name the document")
    if not str(version or "").strip():
        raise ValueError(
            "a consent change must name the document's version — consent to "
            "an unnamed version cannot be shown to cover any particular text")
    row = _base(CONSENT, user_id=user_id, actor=actor,
                account_id=account_id, ts=ts)
    row.update({"document": str(document), "documentVersion": str(version),
                "granted": bool(granted)})
    return _append(user_id, row)


def record_mode_verification(*, user_id, actor, answer, source,
                             account_id=None, detail=None, ts=None):
    """§7: every mode verification and its answer.

    `source` is required. A mode "verification" with no source is an
    assumption that has been given a record, which is worse than no record:
    §3 is explicit that the fact must come from the broker.
    """
    if not str(answer or "").strip():
        raise ValueError("a mode verification must record its answer")
    if not str(source or "").strip():
        raise ValueError(
            "a mode verification must record where the answer came from — "
            "§3 requires it to come from the broker, and a record with no "
            "source cannot show that it did")
    row = _base(MODE_VERIFICATION, user_id=user_id, actor=actor,
                account_id=account_id, ts=ts)
    row.update({"answer": str(answer), "source": str(source),
                "detail": str(detail or "")[:1000]})
    return _append(user_id, row)


# ── reading back ────────────────────────────────────────────────────────────
def get(owner_id, seq):
    """One record, or AuditNotFound.

    The owner is in the key AND compared again on the record, the same two
    lines of defence `journal_store.get` uses, against a key built wrong.
    """
    owner = str(owner_id)
    row = _read_row(owner, int(seq))
    if not row:
        raise AuditNotFound("no such audit record")
    if str(row.get("userId")) != owner:
        raise AuditNotFound("no such audit record")
    return row


def query(owner_id, *, kind=None, since=None, until=None, limit=None):
    """This owner's records, oldest first.

    An empty list means the trail was read and is empty — never a placeholder
    for a read that did not happen.
    """
    owner = str(owner_id)
    out = []
    for _seq, row in _walk(owner):
        if str(row.get("userId")) != owner:
            continue
        if kind is not None and row.get("kind") != kind:
            continue
        ts = row.get("ts")
        if since is not None and not (ts is not None and ts >= since):
            continue
        if until is not None and not (ts is not None and ts <= until):
            continue
        out.append(row)
        if limit is not None and len(out) >= int(limit):
            break
    return out


def _record_exists_after(owner, seq, span):
    """True when any record sits in the `span` slots after `seq`.

    This is what tells a removed record apart from the end of the trail, and
    it asks the records rather than any stored count — a count is the thing an
    alteration would change first.
    """
    for n in range(seq + 1, seq + 1 + int(span)):
        if _read_row(owner, n):
            return True
    return False


def verify(owner_id):
    """Walk the chain. {"ok", "checked", "brokenAt", "detail"}.

    Reports the FIRST break and where, because "something is wrong somewhere"
    is not actionable at three in the morning. The three breaks it can find:

      * a record whose stored hash does not match its contents — altered
      * a record whose prevHash does not match the previous record — the
        chain was re-linked, or a record was inserted
      * a missing sequence number with records after it — removed
    """
    owner = str(owner_id)
    prev_hash = ""
    checked = 0
    seq = 1
    while True:
        row = _read_row(owner, seq)
        if row is None:
            if _record_exists_after(owner, seq, _GAP_PROBE):
                return {"ok": False, "checked": checked, "brokenAt": seq,
                        "detail": (f"record {seq} is missing from a trail "
                                   f"that continues past it — an audit "
                                   f"record was removed after it was "
                                   f"written")}
            return {"ok": True, "checked": checked, "brokenAt": None,
                    "detail": f"{checked} record(s) chained, none altered"}
        stored = str(row.get("hash") or "")
        if stored != _hash_of(row):
            return {"ok": False, "checked": checked, "brokenAt": seq,
                    "detail": (f"record {seq} does not match its own hash — "
                               f"its contents were altered after it was "
                               f"written")}
        if str(row.get("prevHash") or "") != prev_hash:
            return {"ok": False, "checked": checked, "brokenAt": seq,
                    "detail": (f"record {seq} does not chain to record "
                               f"{seq - 1} — the trail was re-linked, or a "
                               f"record was inserted")}
        prev_hash = stored
        checked += 1
        seq += 1


# Refused here rather than on first use: a service whose audit trail cannot be
# one trail must not get as far as placing the order it would fail to record.
# Placed last so every name above is defined before the refusal fires.
assert_shared_backend()
