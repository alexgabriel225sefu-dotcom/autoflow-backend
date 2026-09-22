"""Where RuleDocs live, and whose they are.

THE ONE RULE THIS FILE ENFORCES: you cannot read a document without saying
whose it is.

Ownership is not a check performed after loading — it is the key. Every
function takes `owner_id` first and builds the storage key from it, so asking
for another client's RuleDoc does not fail a comparison somebody could forget
to write: it looks in a namespace where the document is not. The comparison is
still made, one line below, but only as a second line of defence against a
mistake in key construction.

The failure that shape prevents is the ordinary one. `get(rule_doc_id)`
followed by `if doc.userId != me: refuse` is correct until the day a new
endpoint calls `get` and forgets the second line, and nothing about that
endpoint looks wrong in review.

ACTIVATED VERSIONS ARE WRITTEN ONCE AND NEVER AGAIN. The journal points at
(ruleDocId, version); if that pair could be rewritten, every past entry would
describe terms that no longer exist, and "why was this order opened?" would
have no truthful answer.
"""

import json
import os
import time

from apex import user_store
from apex.platform import ruledoc

# Namespaced away from the engine's own keys so a RuleDoc can never collide
# with a user record.
_P = "a4t"


class NotFound(LookupError):
    """No such document for this owner. Deliberately indistinguishable from
    'exists but belongs to someone else' — telling those apart would let a
    caller enumerate other clients' rule ids."""


class OwnershipViolation(PermissionError):
    """A stored document does not belong to the owner it was fetched for.
    Only reachable through a key-construction bug, and loud on purpose."""


def _ns():
    return user_store._NS or "apex"


def _k_current(owner, rid):
    return f"{_ns()}:{_P}:rule:{owner}:{rid}"


def _k_version(owner, rid, version):
    return f"{_ns()}:{_P}:rulev:{owner}:{rid}:{int(version)}"


def _k_index(owner):
    return f"{_ns()}:{_P}:rules:{owner}"


# ── storage, with the same dev fallback the user records use ────────────────
# user_store refuses at import in production when no shared backend exists, so
# reaching the file branch here means a declared development environment.

def _local_path(key):
    safe = key.replace(":", "__")
    d = os.path.join(user_store._DIR, _P)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{safe}.json")


def _read(key):
    if user_store._USE_REDIS:
        raw = user_store.get_blob(key)
    else:
        p = _local_path(key)
        raw = open(p).read() if os.path.exists(p) else None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # A corrupt record is not an empty one. Returning None here would let
        # a caller create a "first" document over the top of a damaged one.
        raise ValueError(f"stored document at {key} is not readable JSON")


def _write(key, doc):
    raw = json.dumps(doc, separators=(",", ":"))
    if user_store._USE_REDIS:
        user_store.set_blob(key, raw)
    else:
        with open(_local_path(key), "w") as f:
            f.write(raw)


def _index_add(owner, rid):
    if user_store._USE_REDIS:
        user_store._redis_sadd(_k_index(owner), rid)
        return
    p = _local_path(_k_index(owner))
    ids = json.loads(open(p).read()) if os.path.exists(p) else []
    if rid not in ids:
        ids.append(rid)
        with open(p, "w") as f:
            f.write(json.dumps(ids))


def _index_members(owner):
    if user_store._USE_REDIS:
        return [str(m) for m in user_store._redis_smembers(_k_index(owner))]
    p = _local_path(_k_index(owner))
    return json.loads(open(p).read()) if os.path.exists(p) else []


# ── the guard every read passes through ─────────────────────────────────────
def _owned(owner, doc):
    if doc is None:
        raise NotFound("no such rule")
    if str(doc.get("userId")) != str(owner):
        raise OwnershipViolation(
            "a document was found under one owner's key carrying another "
            "owner's id — refusing to serve it")
    return doc


# ── public API ──────────────────────────────────────────────────────────────
def create(owner_id, doc):
    """Store a new draft. The owner is taken from the caller, not the body.

    Overwriting `userId` rather than trusting it is the point: a client who
    POSTs a document claiming someone else's id must not be able to plant it
    in their account, and refusing the request instead would only invite the
    frontend to send the field at all.
    """
    owner_id = str(owner_id)
    doc = dict(doc or {})
    doc["userId"] = owner_id
    rid = doc.get("ruleDocId")
    if not rid:
        raise ValueError("a RuleDoc needs a ruleDocId")
    if _read(_k_current(owner_id, rid)) is not None:
        raise ValueError(f"rule {rid} already exists")
    doc.setdefault("state", ruledoc.DRAFT)
    doc["updatedAt"] = time.time()
    _write(_k_current(owner_id, rid), doc)
    _index_add(owner_id, rid)
    return doc


def get(owner_id, rule_doc_id):
    """The current document, or NotFound."""
    return _owned(str(owner_id),
                  _read(_k_current(str(owner_id), str(rule_doc_id))))


def exists(owner_id, rule_doc_id):
    try:
        get(owner_id, rule_doc_id)
        return True
    except NotFound:
        return False


def list_docs(owner_id, *, states=None):
    """Every rule this owner has, newest change first."""
    owner_id = str(owner_id)
    out = []
    for rid in _index_members(owner_id):
        raw = _read(_k_current(owner_id, rid))
        if raw is None:
            continue                      # indexed but deleted; skip quietly
        doc = _owned(owner_id, raw)
        if states and doc.get("state") not in states:
            continue
        out.append(doc)
    return sorted(out, key=lambda d: d.get("updatedAt") or 0, reverse=True)


def save_draft(owner_id, doc):
    """Overwrite a DRAFT in place.

    An active document is refused here. Editing one would rewrite terms a
    position may already have been opened under; `ruledoc.next_version` is how
    an active rule is changed.
    """
    owner_id = str(owner_id)
    rid = str(doc.get("ruleDocId") or "")
    current = get(owner_id, rid)          # ownership + existence
    ruledoc.assert_editable(current)
    out = dict(doc)
    out["userId"] = owner_id              # never movable by the request body
    out["ruleDocId"] = rid
    out["state"] = ruledoc.DRAFT
    out["updatedAt"] = time.time()
    _write(_k_current(owner_id, rid), out)
    return out


def activate(owner_id, rule_doc_id, *, known_condition_ids=None, now=None):
    """Validate, freeze, and make this version the live one.

    The frozen copy is written BEFORE the current pointer moves. If the second
    write fails, the worst case is an orphaned version nobody references —
    harmless. The other order risks a document marked active whose terms were
    never recorded anywhere.
    """
    owner_id = str(owner_id)
    doc = get(owner_id, str(rule_doc_id))
    live = ruledoc.activate(doc, known_condition_ids=known_condition_ids,
                            now=now)
    ver = int(live.get("version") or 1)
    frozen_key = _k_version(owner_id, rule_doc_id, ver)
    if _read(frozen_key) is not None:
        raise ValueError(
            f"version {ver} of {rule_doc_id} is already recorded and cannot "
            f"be rewritten — call next_version() to make a new one")
    _write(frozen_key, live)
    _write(_k_current(owner_id, rule_doc_id), live)
    return live


def get_version(owner_id, rule_doc_id, version):
    """A frozen activated version — what the journal points at."""
    owner_id = str(owner_id)
    return _owned(owner_id,
                  _read(_k_version(owner_id, str(rule_doc_id), version)))


def set_state(owner_id, rule_doc_id, state):
    """Pause, resume or archive. Never edits terms, only the state.

    Resuming goes back to ACTIVE without revalidating on purpose: the terms
    were already frozen and validated at activation, and re-running validation
    against a condition library that has since changed could refuse to restart
    a rule that has been running correctly all along.
    """
    if state not in ruledoc.STATES:
        raise ValueError(f"state must be one of {', '.join(ruledoc.STATES)}")
    owner_id = str(owner_id)
    doc = get(owner_id, str(rule_doc_id))
    if doc.get("state") == ruledoc.DRAFT and state == ruledoc.ACTIVE:
        raise ValueError("a draft is started with activate(), which validates "
                         "and freezes it — not by setting its state")
    out = dict(doc)
    out["state"] = state
    out["updatedAt"] = time.time()
    _write(_k_current(owner_id, rule_doc_id), out)
    return out


def next_version(owner_id, rule_doc_id, *, now=None):
    """Turn an active rule back into an editable draft at version + 1.

    The live version stays exactly where it is until the draft is activated,
    so nothing stops running while the client edits.
    """
    owner_id = str(owner_id)
    doc = get(owner_id, str(rule_doc_id))
    draft = ruledoc.next_version(doc, now=now)
    _write(_k_current(owner_id, rule_doc_id), draft)
    return draft


def active_docs(owner_id):
    return list_docs(owner_id, states=(ruledoc.ACTIVE,))
