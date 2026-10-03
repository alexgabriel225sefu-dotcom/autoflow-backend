"""Early-access sign-ups, before there is anything to sell.

WHY THIS EXISTS AT ALL

Checkout is off, live execution is off, and the legal pages still carry
unfilled blockers. None of that stops somebody wanting to be told when the
product opens, and none of it has to be resolved first — an email address and
a promise to write once is the smallest honest thing this product can ask
for. It is also the only conversion an advertisement can honestly buy right
now, which is why it ships before anything that takes money.

WHAT IS STORED, AND WHAT IS NOT

The address, encrypted, and the moment it arrived. Nothing else: no name, no
IP, no referrer, no tracking id. A waitlist that quietly builds a profile is
the thing people expect and the thing we are not doing, and the cheapest way
to keep that true is to have nowhere to put it.

The storage key is a keyed hash of the normalised address, so the same person
signing up twice is one entry and the key itself does not reveal who is on
the list to anyone who can see the keyspace. The hash is keyed rather than
bare, because a bare SHA-256 of an email address is reversible in practice:
the input space is small enough to enumerate, so an unkeyed digest is a
pseudonym and not a protection.

WHAT THIS MODULE DOES NOT DO

It does not send email. There is no provider configured, and claiming a
confirmation was sent when nothing was sent would be the same class of
falsehood as a failed read rendering as a fact. The caller is told the
address is recorded, which is all that is true.
"""

import hashlib
import hmac
import os
import re
import time

from apex import user_store
from apex.platform import store as _store

# Long enough for real addresses, short enough that nobody can use the field
# as free storage. The RFC's 254-octet limit is the ceiling.
MAX_EMAIL = 254
MAX_SOURCE = 32

# Deliberately permissive and deliberately NOT an RFC 5322 parser. The only
# question worth answering here is "could this plausibly be delivered to",
# because the real test is whether the address accepts mail, which no regex
# settles. A strict pattern's failure mode is rejecting a valid address
# somebody actually has, which is worse than storing one that bounces.
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")

# Only values this product itself puts in a link. An arbitrary string here
# would be an open redirect for analytics: whatever an advertiser appended
# would be stored and later read back by somebody who trusted it.
SOURCES = ("landing", "pricing", "direct")


class WaitlistError(ValueError):
    """Refused. `code` is what the client branches on, never the message."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _secret():
    """Key material for the address hash.

    TOKEN_ENCRYPTION_KEY already exists on every deployment that can store a
    broker token, so this adds no new secret to manage. It is run through
    HMAC with a domain string so the derived key is never the same bytes as
    the key it came from — the same reasoning ctrader_link applies to its
    state-signing key.
    """
    base = (os.getenv("TOKEN_ENCRYPTION_KEY")
            or os.getenv("CTRADER_CLIENT_SECRET") or "")
    if not base:
        # No key means no pseudonymisation, and storing addresses under a
        # guessable key is worse than refusing. Deployments that can hold a
        # broker token can hold this.
        raise WaitlistError("NOT_CONFIGURED",
                            "the waitlist is not configured on this deployment")
    return hmac.new(b"apex4traders/waitlist/v1", base.encode(),
                    hashlib.sha256).digest()


def normalise(email):
    """Lower-cased and trimmed, or a refusal.

    Case is folded because `A@b.com` and `a@b.com` are one person to every
    mail server that matters, and two entries here would mean writing to them
    twice. The local part is left otherwise untouched: stripping dots or
    plus-tags is a Gmail convention, and applying it to every provider would
    merge addresses that are genuinely different people.
    """
    value = (email or "").strip()
    if not value:
        raise WaitlistError("EMAIL_REQUIRED", "an email address is required")
    if len(value) > MAX_EMAIL:
        raise WaitlistError("EMAIL_INVALID", "that address is too long")
    value = value.lower()
    if not _EMAIL.match(value):
        raise WaitlistError("EMAIL_INVALID",
                            "that does not look like an email address")
    return value


def _key(email):
    digest = hmac.new(_secret(), email.encode(), hashlib.sha256).hexdigest()
    return f"{_store._ns()}:{_store._P}:waitlist:{digest}"


def _k_index():
    return f"{_store._ns()}:{_store._P}:waitlist:index"


def join(email, *, source="direct", now=None):
    """Record an address. Idempotent, and says which it was.

    Returns {"status": "added"|"already"}. The two are distinguished for the
    UI's benefit and for nobody else's: a second sign-up is not an error and
    must not read as one, and telling somebody "you are already on the list"
    is friendlier than silently doing nothing.

    It is NOT treated as a disclosure risk. The endpoint is rate limited, and
    a visitor who can already type an address into a form learns nothing from
    being told it is on a list they just asked to join.
    """
    address = normalise(email)
    src = (source or "direct").strip().lower()[:MAX_SOURCE]
    if src not in SOURCES:
        src = "direct"
    stamp = int(now if now is not None else time.time())

    key = _key(address)
    # A strict read: if the store cannot be reached, this must not look like
    # a new sign-up and silently overwrite an existing one, nor report
    # success for something that was never written.
    existing = _store._read_strict(key)
    if existing:
        return {"status": "already", "joinedAt": existing.get("joinedAt")}

    _store._write(key, {
        "email": user_store.encrypt_value(address),
        "joinedAt": stamp,
        "source": src,
    })
    # The index is written AFTER the record, so a failure between the two
    # leaves an address stored and unlisted rather than listed and absent.
    # An export that misses somebody is a bug to find; an export that names
    # somebody whose record does not exist is a bug that looks like data.
    _store._set_add(_k_index(), key)
    return {"status": "added", "joinedAt": stamp}


def count():
    """How many addresses are on the list. Never the addresses themselves."""
    return len(_store._set_members(_k_index()))


def export():
    """Every address, decrypted. Operator tooling — never an API response.

    Returns the records whose index entry still resolves; an index entry with
    no record is reported rather than skipped, because a silent gap in an
    export is how a list quietly loses people.
    """
    out, missing, unreadable = [], [], []
    for key in sorted(_store._set_members(_k_index())):
        rec = _store._read(key)
        if not rec:
            missing.append(key)
            continue
        stored = rec.get("email") or ""
        address = user_store.decrypt_value(stored)
        # decrypt_value answers "" both for "nothing stored" and for "the key
        # is wrong or missing", and it only logs the difference. Emitting the
        # empty string as somebody's address would put a blank row in the
        # export and lose a real sign-up quietly — the export has to say it
        # could not read the record instead.
        if stored and not address:
            unreadable.append(key)
            continue
        out.append({
            "email": address,
            "joinedAt": rec.get("joinedAt"),
            "source": rec.get("source"),
        })
    out.sort(key=lambda r: r.get("joinedAt") or 0)
    return {"entries": out, "unresolved": missing, "unreadable": unreadable}


def public_result(outcome):
    """What may be returned to a browser. Carries no address, ever."""
    return {"status": outcome.get("status")}
