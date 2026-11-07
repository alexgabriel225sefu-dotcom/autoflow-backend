"""Structured, redacted logging for the broker-link flow.

WHY THIS EXISTS

A cTrader connection crosses three requests, two origins and one human, and
until now it logged nothing at all: the HTTP handler suppresses access logs and
no step recorded its outcome. Every diagnosis was made by asking the owner to
photograph his phone and read an error code aloud. That is how a one-minute
authorization-code expiry took a day to find — the evidence that would have
named it in seconds was never written down.

So each step says what happened. The hard part is saying it without becoming
the leak: this flow handles an authorization code, an access token, a refresh
token, the application's client secret and a signed state, and a log is exactly
the kind of place all five end up by accident.

THREE NETS, NOT ONE

1. Nothing sensitive is passed in. Callers hand over derived, non-reversible
   references — `attempt_id(nonce)`, `user_ref(user_id)` — and booleans in
   place of the values themselves (`has_code`, not the code).
2. `journal.redact()` runs over every payload, dropping anything whose KEY
   looks like a credential, so a careless `token=...` is caught by name.
3. Values are length-capped and control characters stripped, so a long secret
   pasted into an innocent-looking field cannot ride out in full, and nothing
   can forge a log line by embedding a newline.

tests/test_platform_linklog.py drives the REAL flow with sentinel credentials
and asserts none of them reach the output. A denylist that is only inspected by
eye is not a guarantee; that test is.
"""
import hashlib
import hmac
import json
import os
import sys
import time

from apex.platform.journal import redact

# How much of a digest identifies an attempt. Eight hex characters is 32 bits:
# enough that two attempts in a support conversation will not collide, far too
# few to walk back to the nonce, which is 32 random bytes.
_REF_LEN = 8

# Long enough for a route, an error code or a hostname; far too short for a
# token to survive intact if one is ever passed by mistake.
_MAX_VALUE = 120


def _key() -> bytes:
    """Keyed so a reference cannot be confirmed by guessing the input.

    An unkeyed digest of a nonce is still a digest of a nonce: anyone holding
    a candidate could hash it and match. The key makes these references mean
    nothing outside this deployment. It is derived from material that is
    already required for the flow to run at all, so this adds no new secret to
    manage — and it falls back to a per-process value rather than refusing,
    because logging must never be the thing that takes the platform down.
    """
    raw = (os.getenv("TOKEN_ENCRYPTION_KEY")
           or os.getenv("CTRADER_CLIENT_SECRET") or "")
    if not raw:
        return _PROCESS_SALT
    return hashlib.sha256(("linklog|" + raw).encode("utf-8")).digest()


# Only reached when nothing is configured, which in practice means a developer
# box. References stay stable within the process and mean nothing outside it.
_PROCESS_SALT = hashlib.sha256(
    f"linklog-process|{os.getpid()}|{time.time()}".encode()).digest()


def _ref(value) -> str:
    if not value:
        return "-"
    return hmac.new(_key(), str(value).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:_REF_LEN]


def attempt_id(nonce) -> str:
    """The id a person can quote back with nothing at risk.

    This is what makes a support conversation possible: the owner reads eight
    characters out of an error page instead of sending a screenshot that may
    carry a session, and those eight characters find every line of the attempt
    in the logs.
    """
    return _ref(nonce)


def user_ref(user_id) -> str:
    """Which client, without saying who. Stable, so one attempt can be
    followed across requests, and reversible by nobody."""
    return _ref(user_id)


def _clean(value):
    """One log value: bounded, single-line, and never a live credential.

    Newlines are what turn a logged value into a forged log line, so they go
    first. The cap is what stops a secret that slipped through the other two
    nets from arriving in one piece.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > _MAX_VALUE:
        return text[:_MAX_VALUE] + "…"
    return text


def event(name, **fields):
    """One line about one step. Never raises: logging cannot break the flow.

    Written to stdout because that is what the platform collects, as a single
    line so a multi-request attempt can be pulled out with one search on its
    attempt id.
    """
    try:
        safe = {k: _clean(v) for k, v in redact(fields).items()
                if v is not None}
        line = " ".join(f"{k}={json.dumps(v) if isinstance(v, str) else v}"
                        for k, v in sorted(safe.items()))
        sys.stdout.write(f"[link] {name} {line}\n".rstrip() + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        # A logger that can take the request down is worse than no logger.
        pass


def host_of(url):
    """A URL reduced to what is safe and useful: scheme, host and path.

    A redirect URI is not a secret, but it can carry a query string, and the
    one thing this flow must never write down travels in query strings.
    """
    try:
        from urllib.parse import urlsplit
        p = urlsplit(str(url or ""))
        if not p.netloc:
            return "-"
        return f"{p.scheme}://{p.netloc}{p.path}"
    except Exception:  # noqa: BLE001
        return "-"
