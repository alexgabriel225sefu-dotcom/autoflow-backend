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

EMAIL DELIVERY

A first sign-up can send one plain transactional email through the configured
provider. Delivery is best-effort: the address is recorded before any provider
call, and a provider failure must never turn a recorded sign-up into a browser
error. Repeat sign-ups never send again.
"""

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request

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

# What the visitor trades on. A closed set for the same reason SOURCES is one:
# a free string from a public form is something somebody else chooses and we
# later read back as if we had.
#
# This exists to answer a question the product cannot otherwise answer without
# guessing — which platform to support next, and whether MetaTrader is worth
# its cost at all. It is volunteered, never required, and never inferred.
PLATFORMS = ("ctrader", "mt4", "mt5", "other")

# The broker cannot be a closed set — there are hundreds, and the useful
# answer is the long tail. So it is free text, bounded hard: long enough for
# "IC Markets (Global)", short enough that the field is not storage.
MAX_BROKER = 60

# A single HTTPS call is enough; no SDK dependency for a launch-list email.
EMAIL_PROVIDER = "resend"
RESEND_ENDPOINT = "https://api.resend.com/emails"
EMAIL_TIMEOUT_SEC = 3
DELIVERY_SENT = "sent"
DELIVERY_FAILED = "failed"
DELIVERY_NOT_CONFIGURED = "not_configured"


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


def _platform(value):
    """One of PLATFORMS, or None. Never a string somebody else chose."""
    v = (value or "").strip().lower()
    return v if v in PLATFORMS else None


def _broker(value):
    """A broker name as typed, bounded, or None.

    Kept as written rather than normalised to a known list: the point of
    asking is to find out which brokers exist in this market, and folding
    anything unrecognised into "other" would delete the answer.
    """
    v = " ".join((value or "").split())[:MAX_BROKER]
    return v or None


def email_config_status():
    """Readiness-safe status for waitlist email delivery.

    The values name configuration variables but never their values. A fully
    absent provider is acceptable during development and beta preparation, but
    a partial configuration is a real operator error.
    """
    key = bool((os.getenv("RESEND_API_KEY") or "").strip())
    sender = bool((os.getenv("A4T_WAITLIST_FROM_EMAIL") or "").strip())
    reply_to = bool((os.getenv("A4T_WAITLIST_REPLY_TO") or "").strip())
    missing = []
    if not key:
        missing.append("RESEND_API_KEY")
    if not sender:
        missing.append("A4T_WAITLIST_FROM_EMAIL")
    configured = not missing
    partial = bool(key or sender or reply_to) and not configured
    return {
        "provider": EMAIL_PROVIDER,
        "configured": configured,
        "partial": partial,
        "missing": missing,
    }


def _delivery(status, *, now=None, reason=None):
    out = {"provider": EMAIL_PROVIDER, "status": status}
    if now is not None:
        out["attemptedAt"] = int(now)
    if reason:
        out["reason"] = reason
    return out


def _placeholder_email(address):
    sender = (os.getenv("A4T_WAITLIST_FROM_EMAIL") or "").strip()
    payload = {
        "from": sender,
        "to": [address],
        "subject": "Apex4Traders early access",
        "text": (
            "You are on the Apex4Traders early access list. "
            "Demo access opens first. Live trading is not enabled in this "
            "release."
        ),
    }
    reply_to = (os.getenv("A4T_WAITLIST_REPLY_TO") or "").strip()
    if reply_to:
        payload["reply_to"] = reply_to
    return payload


def _post_resend(payload):
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        RESEND_ENDPOINT, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "apex4traders-waitlist/1.0",
        })
    with urllib.request.urlopen(req, timeout=EMAIL_TIMEOUT_SEC) as resp:  # nosec B310 - fixed HTTPS endpoint
        body = resp.read(1024 * 64).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        provider_id = parsed.get("id") if isinstance(parsed, dict) else None
        return provider_id


def send_waitlist_email(address, *, now=None, post=None):
    """Best-effort transactional email. Never raises with an address in it."""
    stamp = int(now if now is not None else time.time())
    cfg = email_config_status()
    if not cfg["configured"]:
        return _delivery(DELIVERY_NOT_CONFIGURED)
    try:
        provider_id = (post or _post_resend)(_placeholder_email(address))
    except urllib.error.HTTPError as exc:
        return _delivery(DELIVERY_FAILED, now=stamp, reason=f"HTTP_{exc.code}")
    except Exception as exc:
        return _delivery(DELIVERY_FAILED, now=stamp,
                         reason=type(exc).__name__)
    out = _delivery(DELIVERY_SENT, now=stamp)
    if provider_id:
        out["providerId"] = str(provider_id)[:80]
    return out


def _record_delivery(key, rec, delivery):
    current = _store._read(key) or rec
    updated = dict(current)
    updated["emailDelivery"] = delivery
    _store._write(key, updated)
    return updated


def join(email, *, source="direct", platform=None, broker=None, now=None):
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
        # The same person answering a question they skipped. Only ABSENT
        # fields are filled: a second call cannot rewrite what somebody
        # already said, and cannot clear it either. This exists because the
        # form asks about platform and broker AFTER the sign-up has
        # succeeded — a question on the way in costs conversions, and the
        # answer is worth less than the address.
        added = {}
        plat = _platform(platform)
        if plat and not existing.get("platform"):
            added["platform"] = plat
        brk = _broker(broker)
        if brk and not existing.get("broker"):
            added["broker"] = brk
        if added:
            _store._write(key, dict(existing, **added))
        return {"status": "already", "joinedAt": existing.get("joinedAt"),
                "answered": bool(added)}

    rec = {
        "email": user_store.encrypt_value(address),
        "joinedAt": stamp,
        "source": src,
    }
    # Only written when answered. An absent key and an empty string are
    # different facts: "did not say" is not "uses no broker", and an export
    # that cannot tell them apart cannot count either.
    plat = _platform(platform)
    if plat:
        rec["platform"] = plat
    brk = _broker(broker)
    if brk:
        rec["broker"] = brk
    _store._write(key, rec)
    # The index is written AFTER the record, so a failure between the two
    # leaves an address stored and unlisted rather than listed and absent.
    # An export that misses somebody is a bug to find; an export that names
    # somebody whose record does not exist is a bug that looks like data.
    _store._set_add(_k_index(), key)

    outcome = {"status": "added", "joinedAt": stamp}
    # Delivery is best-effort and first-join-only. The browser answer above is
    # already decided, so a provider outage cannot turn a recorded sign-up into
    # a visible error. The record is updated with the result so the operator can
    # see who was sent, who failed, and who was never attempted.
    delivery = send_waitlist_email(address, now=stamp)
    _record_delivery(key, rec, delivery)
    return outcome


def remove(email):
    """Take an address off the list. Operator tooling — never an API route.

    WHY THIS EXISTS

    Somebody who asked to be told when access opens may ask to be forgotten,
    and until now there was nowhere in this product to do it. A list you can
    only add to is not a list you can honestly promise to delete from.

    It is also what removes the sign-ups this product's own testing left in
    the list: an address that was never a person still counts in the only
    conversion number the advertising can be judged by.

    NOT AN ENDPOINT, on purpose. The form is unauthenticated, and a public
    route that deletes by address would let anyone remove anyone — and, by
    the difference between "removed" and "was not there", read the list back
    one address at a time.

    Returns {"status": "removed"|"absent"}. The record is deleted BEFORE the
    index entry, the reverse of `join`: a failure between the two leaves an
    index entry with no record, which `export` already reports as unresolved,
    rather than a listed address that is still stored and invisible.
    """
    address = normalise(email)
    key = _key(address)
    removed = _store._delete(key)
    _store._set_remove(_k_index(), key)
    return {"status": "removed" if removed else "absent"}


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
        delivery = rec.get("emailDelivery") or {}
        delivery_status = delivery.get("status") or "unknown"
        out.append({
            "email": address,
            "joinedAt": rec.get("joinedAt"),
            "source": rec.get("source"),
            "platform": rec.get("platform"),
            "broker": rec.get("broker"),
            "emailDelivery": delivery_status,
        })
    out.sort(key=lambda r: r.get("joinedAt") or 0)
    delivery = {"sent": [], "failed": [], "neverAttempted": [], "unknown": []}
    for entry in out:
        status = entry.get("emailDelivery")
        if status == DELIVERY_SENT:
            delivery["sent"].append(entry["email"])
        elif status == DELIVERY_FAILED:
            delivery["failed"].append(entry["email"])
        elif status == DELIVERY_NOT_CONFIGURED:
            delivery["neverAttempted"].append(entry["email"])
        else:
            delivery["unknown"].append(entry["email"])
    return {"entries": out, "unresolved": missing, "unreadable": unreadable,
            "delivery": delivery}


def tally():
    """What the list says about platforms and brokers.

    The whole reason the two fields exist. Counts only what people actually
    answered: "did not say" is its own bucket rather than being folded into
    the smallest one, because a question most people skipped is a weaker
    answer than the raw counts would suggest and the reader has to be able
    to see that.
    """
    dump = export()
    plats, brokers, said = {}, {}, 0
    for e in dump["entries"]:
        p = e.get("platform")
        if p:
            said += 1
            plats[p] = plats.get(p, 0) + 1
        b = (e.get("broker") or "").strip()
        if b:
            brokers[b.lower()] = brokers.get(b.lower(), 0) + 1
    return {
        "total": len(dump["entries"]),
        "answered": said,
        "platforms": dict(sorted(plats.items(), key=lambda kv: -kv[1])),
        "brokers": dict(sorted(brokers.items(), key=lambda kv: -kv[1])),
        "delivery": {k: len(v) for k, v in dump.get("delivery", {}).items()},
        "unresolved": dump["unresolved"],
        "unreadable": dump.get("unreadable", []),
    }


def public_result(outcome):
    """What may be returned to a browser. Carries no address, ever."""
    return {"status": outcome.get("status")}
