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
import math
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
    # The one unauthenticated form on the site. Tight on purpose: it is the
    # only route a stranger can write through, and the cost of being wrong is
    # a list full of addresses nobody typed. Five a minute is generous for a
    # human correcting a typo and useless for a script.
    "waitlist": ("RL_A4T_WAITLIST_PER_MIN", 5, 60),
    # Everything else: reads the dashboard polls.
    "default": ("RL_A4T_DEFAULT_PER_MIN", 240, 60),
}

# Future live-order limits. Kept separate from the HTTP route buckets because
# "a client may call the API" and "a client may send another broker order" are
# different risks. These are intentionally conservative defaults until a broker
# contract supplies the exact live numbers.
_ORDER_CLIENT_ENV = "RL_A4T_ORDER_CLIENT_PER_MIN"
_ORDER_BROKER_ENV = "RL_A4T_ORDER_BROKER_PER_SEC"
_ORDER_CLIENT_DEFAULT = 6
_ORDER_BROKER_DEFAULT = 2
_ORDER_CLIENT_WINDOW_S = 60
_ORDER_BROKER_WINDOW_S = 1


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
    if route == "waitlist":
        return "waitlist"
    if route.startswith("ctrader/"):
        # A GET of the link status is a poll — the shell and the accounts
        # page both refresh it every 60 seconds, and two open tabs would
        # exhaust a tight bucket in minutes. Sharing that budget with
        # connect, complete and disconnect meant a client who had left a tab
        # open could not disconnect their own account. The existing HTTP
        # suite caught exactly that.
        if method == "GET":
            return "default"
        # ONLY the two that actually go through cTrader's OAuth.
        #
        # Everything else under ctrader/ used to land here too, and `select`
        # is the one that made it visible: it is a client choosing which of
        # THEIR OWN already-listed accounts to use, a local store write with
        # nothing to guess at — the ctids were handed to them by this same
        # API and ownership is checked on the way in. Metering it against the
        # oauth bucket meant that a client who had just spent that budget
        # connecting could not then pick the account they had connected.
        #
        # Observed in production on 2026-10-04: POST ctrader/select answered
        # 429 with retryAfterSec=42, so the owner's phone showed
        # "No account selected" on every screen while the account sat linked
        # and unselectable. The bucket's own docstring says it is for flows
        # that are "rare, and the interesting ones to guess at". Select is
        # neither.
        if route in ("ctrader/connect", "ctrader/complete"):
            return "oauth"
        # select and disconnect: they change which account automation would
        # act on, which is exactly what the control bucket is for.
        return "control"
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
    return bool(ok), bucket, (0 if ok else _seconds_until_reset(limiter.window_s))


def _seconds_until_reset(window_s):
    """How long the caller must ACTUALLY wait, not how long a window lasts.

    The window is a floor of the clock, so it rolls at the top of the next
    one: fifty-nine seconds in, the wait is one second. This used to report
    the window length flat, so a client was told to wait a minute when the
    budget was about to come back — and a number that can be wrong by a whole
    window is worse than none, because a countdown is what a person acts on.

    Never zero: a wait of zero invites an instant retry that fails again.
    """
    remaining = window_s - (time.time() % window_s)
    return max(1, min(int(window_s), math.ceil(remaining)))


def refusal(bucket, retry_after):
    """The platform API's own error shape, so the UI branches on a code.

    The seconds go in the MESSAGE as well as the field, because the field is
    only as useful as the clients that read it, and the message is what every
    surface already displays.
    """
    wait = (f"wait {int(retry_after)}s and try again" if retry_after
            else "try again shortly")
    return 429, {"ok": False, "error": {
        "code": "RATE_LIMITED",
        "message": f"too many requests — {wait}",
        "bucket": bucket,
        "retryAfterSec": retry_after,
    }}


def order_refusal(code, message, *, gate, retry_after=0):
    """The future live-order limiter's API-neutral refusal shape."""
    return {"ok": False, "error": {
        "code": code,
        "message": message,
        "gate": gate,
        "retryAfterSec": int(retry_after or 0),
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


def _env_int(name, default):
    try:
        out = int(os.getenv(name) or default)
    except (TypeError, ValueError):
        out = default
    return max(1, out)


def _order_counter_ready():
    """A live order path must never fall back to an in-process counter."""
    if _MODE == "memory" or not user_store._USE_REDIS:
        return False, "ORDER_RATE_LIMIT_UNAVAILABLE", (
            "live order rate limits require a shared counter")
    health = user_store.redis_health()
    if not health.get("reachable"):
        return False, "ORDER_RATE_LIMIT_UNAVAILABLE", (
            "live order rate limits cannot reach the shared counter")
    return True, "OK", "shared counter reachable"


def _order_count(key, window_s, *, now=None):
    slot = int((time.time() if now is None else float(now)) // window_s)
    ttl_s = max(2, int(window_s) * 2)
    return user_store.incr(f"{_store_ns()}:order_rl:{key}:{slot}",
                           ttl_s=ttl_s)


def _order_retry_after(window_s, *, now=None):
    t = time.time() if now is None else float(now)
    remaining = window_s - (t % window_s)
    return max(1, min(int(window_s), math.ceil(remaining)))


def check_live_order_rate(user_id, account_id, *, provider="ctrader",
                          connection_id=None, now=None):
    """Fail-closed order-rate gate for the future live path.

    This is not the platform API limiter. It protects broker-facing order
    throughput, so the fallback is refusal, not a per-process memory counter.
    Demo reads, candles and previews keep using `check()` above.
    """
    if not user_id:
        raise ValueError("live order rate limit needs a user_id")
    if not account_id:
        raise ValueError("live order rate limit needs an account_id")
    ready, code, message = _order_counter_ready()
    if not ready:
        return order_refusal(code, message, gate="order_rate_store")

    client_limit = _env_int(_ORDER_CLIENT_ENV, _ORDER_CLIENT_DEFAULT)
    broker_limit = _env_int(_ORDER_BROKER_ENV, _ORDER_BROKER_DEFAULT)
    client_key = ("client:" + hashlib.sha256(
        f"{user_id}:{account_id}".encode()).hexdigest()[:32])
    broker_scope = f"{provider}:{connection_id or account_id}"
    broker_key = ("broker:" + hashlib.sha256(
        str(broker_scope).encode()).hexdigest()[:32])

    client_n = _order_count(client_key, _ORDER_CLIENT_WINDOW_S, now=now)
    if client_n is None:
        return order_refusal(
            "ORDER_RATE_LIMIT_UNAVAILABLE",
            "live order rate limits could not count this client",
            gate="client_order_rate")
    if int(client_n) > client_limit:
        return order_refusal(
            "ORDER_RATE_LIMITED",
            "too many live orders for this client — wait before retrying",
            gate="client_order_rate",
            retry_after=_order_retry_after(_ORDER_CLIENT_WINDOW_S, now=now))

    broker_n = _order_count(broker_key, _ORDER_BROKER_WINDOW_S, now=now)
    if broker_n is None:
        return order_refusal(
            "ORDER_RATE_LIMIT_UNAVAILABLE",
            "live order rate limits could not count the broker connection",
            gate="broker_order_rate")
    if int(broker_n) > broker_limit:
        return order_refusal(
            "ORDER_RATE_LIMITED",
            "too many live orders for this broker connection — wait before retrying",
            gate="broker_order_rate",
            retry_after=_order_retry_after(_ORDER_BROKER_WINDOW_S, now=now))

    return {"ok": True, "code": "ORDER_RATE_ALLOWED",
            "limits": {"client": {"count": int(client_n),
                                  "limit": client_limit,
                                  "windowSec": _ORDER_CLIENT_WINDOW_S},
                       "broker": {"count": int(broker_n),
                                  "limit": broker_limit,
                                  "windowSec": _ORDER_BROKER_WINDOW_S}}}


def reset_all():
    """For tests. Production has no reason to clear a window."""
    for lim in LIMITERS.values():
        lim.reset()
