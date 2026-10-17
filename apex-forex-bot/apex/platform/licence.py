"""Whether this client may run automation, filed under their platform id.

THE ONE RULE THIS FILE ENFORCES: an unknown entitlement is not an entitlement.

`status_for` returns NONE for a user with no record, and every caller treats
NONE as "may not". The tempting alternative — assume active until something
says otherwise — reads as generous and is how a platform ends up running
strangers' money for free, or worse, running it for someone the operator
meant to cut off.

The legacy entitlement in stripe_license.py is keyed by Telegram chat_id.
This is keyed by the Supabase user id, and the two are deliberately separate
stores: a client who never had Telegram must be able to hold a licence, and a
migration must be an explicit act rather than an accidental key collision.
"""

import time

from apex.platform import store as _store

NONE = "none"
ACTIVE = "active"
EXPIRED = "expired"
REVOKED = "revoked"
STATES = (NONE, ACTIVE, EXPIRED, REVOKED)


class LicenceRequired(PermissionError):
    """Raised where a licence is needed. Carries the state so the UI can say
    which of "you have none", "yours ran out" and "yours was withdrawn" it is
    — three different sentences with three different next steps."""

    def __init__(self, state, message):
        self.state = state
        super().__init__(message)


def _key(user_id):
    return f"{_store._ns()}:{_store._P}:licence:{user_id}"


def _read(user_id):
    raw = _store._read(_key(user_id))
    return raw if isinstance(raw, dict) else None


def status_for(user_id, *, now=None):
    """The client's entitlement. Never raises; never invents an active one."""
    now = time.time() if now is None else now
    rec = _read(str(user_id))
    if not rec:
        return {"state": NONE, "expiresAt": None, "plan": None}
    state = rec.get("state") or NONE
    exp = rec.get("expiresAt")
    # An expired record is reported EXPIRED rather than rewritten here. A read
    # that silently mutates storage turns a dashboard refresh into a write,
    # and makes the record's history depend on who looked at it.
    if state == ACTIVE and exp is not None and float(exp) <= now:
        state = EXPIRED
    return {"state": state, "expiresAt": exp, "plan": rec.get("plan"),
            "maskedKey": rec.get("maskedKey")}


def require(user_id, *, now=None):
    """The status, or LicenceRequired."""
    st = status_for(user_id, now=now)
    if st["state"] != ACTIVE:
        raise LicenceRequired(st["state"], {
            NONE: "this account has no licence yet",
            EXPIRED: "this licence has expired",
            REVOKED: "this licence was withdrawn",
        }.get(st["state"], "this account is not licensed"))
    return st


def grant(user_id, *, plan, expires_at=None, masked_key=None, now=None):
    """Record an entitlement. Called by the activation path, never by a
    request from the client's own browser."""
    rec = {"state": ACTIVE, "plan": plan, "expiresAt": expires_at,
           "maskedKey": masked_key,
           "grantedAt": time.time() if now is None else now}
    _store._write(_key(str(user_id)), rec)
    return rec


def revoke(user_id):
    rec = _read(str(user_id)) or {}
    rec["state"] = REVOKED
    rec["revokedAt"] = time.time()
    _store._write(_key(str(user_id)), rec)
    return rec
