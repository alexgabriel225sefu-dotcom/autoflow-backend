"""Rate limits for the platform API. Transport-free, like the rest of it.

WHY THIS EXISTS

Every route under /api/v1/ was unmetered. Two of them matter more than the
rest:

  candles  consumes the broker's historical budget, which cTrader enforces at
           5 requests per second PER CONNECTION, shared across every client on
           that connection. One client in a loop degrades the platform for
           everyone, and the limit that protects them is here, not at cTrader.

  preview  runs the evaluator over up to 300 bars on every call.

The rest are metered because an unmetered authenticated endpoint is a way to
enumerate, and because a burst of automation start/stop is not a thing a human
does.

KEYED BY USER FIRST, THEN BY ADDRESS

An authenticated request is limited per user. A shared office or a carrier NAT
would otherwise let one client's loop lock out everybody behind the same
address. Unauthenticated routes — the OAuth callback and the payment webhook —
have no user, so they fall back to the address.

The token is never used as a key directly; only a SHA-256 prefix of it is, so
a bearer token cannot be read back out of a limiter's key set.

WHERE THE COUNTER LIVES

A fixed window held in one process is wrong the moment there are two: each
holds its own window, so the effective limit becomes the configured one times
the instance count. During a Render deploy two instances serve the same users
at once — that has been observed, not assumed.

So the counter is `user_store.incr`, a Redis/Upstash INCR with a TTL, which is
the primitive a rate limit actually needs. Read-modify-write on a blob loses
increments whenever two of anything race.

The in-memory limiter remains, for development and tests only. When there is
no shared backend the limiter still counts in memory — refusing to limit at
all would be worse — but `store_mode()` reports `memory`, and `/readyz`
refuses readiness in production on exactly that. A deployment that cannot
share a counter should be told, not quietly served.
"""

import hashlib
import os
import re
import time

from apex import user_store
from apex.http_security import RateLimiter

# Route class → (requests, window seconds). Every one is overridable by an
# environment variable so a deployment can tune without a code change.
_BUCKETS = {
    # Starting an OAuth flow or completing one. Tight: both are rare, and
    # both are the interesting ones to guess at.
    "oauth": ("RL_A4T_OAUTH_PER_MIN", 10, 60),
    # Broker reads that cost the shared historical budget.
    "candles": ("RL_A4T_CANDLES_PER_MIN", 30, 60),
    # Evaluator runs.
    "preview": ("RL_A4T_PREVIEW_PER_MIN", 20, 60),
    # Anything that changes whether money can move.
    "control": ("RL_A4T_CONTROL_PER_MIN", 20, 60),
    # Freezing a version.
    "activate": ("RL_A4T_ACTIVATE_PER_MIN", 10, 60),
    # The payment provider. Generous: it retries, and being throttled off a
    # legitimate retry is how a paying client ends up unprovisioned.
    "webhook": ("RL_A4T_WEBHOOK_PER_MIN", 120, 60),
    # Everything else: reads the dashboard polls.
    "default": ("RL_A4T_DEFAULT_PER_MIN", 240, 60),
}


def _mk(name):
    env, limit, window = _BUCKETS[name]
    try:
        limit = int(os.getenv(env) or limit)
    except (TypeError, ValueError):
        pass
    return RateLimiter(limit, window, f"a4t-{name}")


LIMITERS = {name: _mk(name) for name in _BUCKETS}

_CANDLES_RE = re.compile(r"^accounts/[A-Za-z0-9_-]{1,64}/candles$")
_PREVIEW_RE = re.compile(r"^rules/[A-Za-z0-9_-]{1,64}/preview$")
_ACTIVATE_RE = re.compile(r"^rules/[A-Za-z0-9_-]{1,64}/activate$")


def classify(method, route):
    """Which bucket a route belongs to. `route` has the /api/v1/ prefix off."""
    route = (route or "").split("?", 1)[0].strip("/")
    if route == "billing/webhook":
        return "webhook"
    if route.startswith("ctrader/"):
        # A GET of the link status is a poll — the shell and the accounts
        # page both refresh it every 60 seconds, and two open tabs would
        # exhaust a tight bucket in minutes. Sharing that budget with
        # connect, complete and disconnect meant a client who had left a tab
        # open could not disconnect their own account. The existing HTTP
        # suite caught exactly that.
        return "default" if method == "GET" else "oauth"
    if _CANDLES_RE.match(route):
        return "candles"
    if _PREVIEW_RE.match(route):
        return "preview"
    if _ACTIVATE_RE.match(route):
        return "activate"
    if route.startswith("automation"):
        # A GET of the automation state is a poll, not a control action.
        return "control" if method != "GET" else "default"
    return "default"


def key_for(client_key, auth_header):
    """The limiting key: the caller's identity if there is one, else address.

    Only a prefix of the token's digest is used. A limiter's key set is not a
    place a bearer token should be recoverable from, even in a core dump.
    """
    token = ""
    if auth_header:
        parts = str(auth_header).split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if token:
        return "u:" + hashlib.sha256(token.encode()).hexdigest()[:24]
    return "a:" + str(client_key or "unknown")


def check(method, route, *, client_key=None, auth_header=None):
    """(allowed, bucket, retry_after_seconds).

    `allowed` is True when the request may proceed. It is also True when the
    limiter cannot decide, because refusing on an internal failure would turn
    a bug in the limiter into an outage of the platform.
    """
    bucket = classify(method, route)
    limiter = LIMITERS.get(bucket) or LIMITERS["default"]
    key = key_for(client_key, auth_header)
    try:
        ok = None
        if _MODE != "memory":
            ok = _shared_check(key, limiter.limit, limiter.window_s)
        if ok is None:
            # No shared backend, or it could not answer. Counting in one
            # process is weaker than counting across all of them, and it is
            # far better than not counting. /readyz reports the degradation.
            ok = limiter.check(key)
    except Exception:
        # A bug in the limiter must not become an outage of the platform.
        return True, bucket, 0
    return bool(ok), bucket, (0 if ok else limiter.window_s)


def refusal(bucket, retry_after):
    """The platform API's own error shape, so the UI branches on a code."""
    return 429, {"ok": False, "error": {
        "code": "RATE_LIMITED",
        "message": "too many requests — wait a moment and try again",
        "bucket": bucket,
        "retryAfterSec": retry_after,
    }}


# ── where the counter lives ─────────────────────────────────────────────────

# "auto" uses the shared backend when there is one. "memory" forces the
# in-process limiter, which is a development choice and is reported as such.
_MODE = (os.getenv("RATE_LIMIT_STORE") or "auto").strip().lower()


def _shared_available():
    """Whether a cross-process counter can be reached.

    `user_store.incr` returns None both when there is no backend and when the
    command failed, and those are the same answer for this question: we cannot
    count across instances right now.
    """
    if _MODE == "memory":
        return False
    return user_store.incr(f"{_store_ns()}:rl:probe", ttl_s=60) is not None


def _store_ns():
    # Namespaced like every other key, so two products on one Redis do not
    # share a rate-limit window.
    return f"{os.getenv('PRODUCT', '').strip().lower() or 'forex'}:a4t"


def store_mode():
    """`shared`, `memory`, or `memory-forced`. Reported by /readyz."""
    if _MODE == "memory":
        return "memory-forced"
    return "shared" if _shared_available() else "memory"


def _shared_check(key, limit, window_s):
    """True/False from the shared counter, or None when it cannot answer.

    The window is a floor of the clock, so every instance agrees on which
    bucket a request belongs to without any coordination between them.
    """
    slot = int(time.time() // window_s)
    n = user_store.incr(f"{_store_ns()}:rl:{key}:{slot}", ttl_s=window_s * 2)
    if n is None:
        return None
    return n <= limit


def reset_all():
    """For tests. Production has no reason to clear a window."""
    for lim in LIMITERS.values():
        lim.reset()
