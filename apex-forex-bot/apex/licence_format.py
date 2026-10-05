"""What a licence key looks like, and what may be said about one out loud.

Deliberately dependency-free. Two generators mint licence keys (the licence
server and this bot's own Stripe webhook) and three places consume them, so the
format has to live somewhere every one of them can import without dragging in
the Telegram layer — the first version of this put it in apex.telegram and
broke three tests that stub that module out, which is the same coupling problem
seen from the test side.
"""
import re

__all__ = ["licence_shape_ok", "mask_licence", "LEGACY_BODY_LEN", "CURRENT_BODY_LEN"]

# The alphabet keys are drawn from: 32 symbols, with I and O removed so they
# cannot be misread as 1 and 0. Validation is deliberately wider than
# generation — an older generator DID emit I and O, and refusing those now
# would lock out customers holding a key that was legitimately issued.
_GROUP = r"[A-Z2-9]"

LEGACY_BODY_LEN = 12        # three groups of four — ~60 bits, no longer minted
CURRENT_BODY_LEN = 30       # six groups of five — 150 bits

_SHAPES = (
    # current: six five-character groups
    rf"^{{prefix}}-(?:{_GROUP}{{{{5}}}}-){{{{5}}}}{_GROUP}{{{{5}}}}$",
    # legacy: three four-character groups
    rf"^{{prefix}}-{_GROUP}{{{{4}}}}-{_GROUP}{{{{4}}}}-{_GROUP}{{{{4}}}}$",
)


def licence_shape_ok(key, prefix="FORX") -> bool:
    """True if `key` LOOKS like a licence key.

    A shape check, never an authorisation decision: it exists so an obvious
    typo fails immediately instead of after a database round trip. The
    authoritative checks are the HMAC and the licence record.

    Input is upper-cased first, because a customer pasting their key in
    lowercase has not made a security-relevant mistake.
    """
    k = str(key or "").strip().upper()
    if not k:
        return False
    pat_prefix = re.escape(str(prefix or "FORX").upper())
    return any(re.match(shape.format(prefix=pat_prefix), k) for shape in _SHAPES)


def mask_licence(key) -> str:
    """What may appear in a log, a message or an audit record.

    A licence key is an entitlement credential — whoever holds one can claim
    the product — and a log store is not a credential store. Render's log
    stream, any aggregator in front of it, a support export and a screenshot
    all outlive the incident they were captured for.

    Keeps the prefix and the first group. For a current key that discloses 25
    bits and leaves 125 unguessable; for a legacy one, 20 of 60. Neither is
    usable as a credential, and both are distinctive enough to answer "which
    licence was that" while reading a log.

    Deliberately NOT a hash. A stable digest of the key is itself a durable
    identifier an attacker can correlate across systems, and publishing one
    invites a table over a keyspace whose format we control.
    """
    k = str(key or "").strip()
    if not k:
        return "(none)"
    parts = k.split("-")
    if len(parts) < 3:
        return k[:4] + "****"          # unrecognised shape: show almost nothing
    return "-".join([parts[0], parts[1]] + ["****"] * (len(parts) - 2))
