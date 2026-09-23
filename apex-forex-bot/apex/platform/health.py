"""Liveness and readiness. Transport-free, like the rest of the platform.

TWO DIFFERENT QUESTIONS

  /healthz  is this process running? A load balancer uses it to decide whether
            to restart the container. It must not touch a dependency: a
            backend outage that restarts every instance turns a degradation
            into an outage.

  /readyz   can this process serve traffic correctly? A deploy uses it to
            decide whether to send traffic to a new instance. It checks the
            dependencies that must be right, and it is deliberately strict
            about the ones that are only acceptable on a laptop.

WHAT IS NEVER IN A RESPONSE

No secret, no key, no token, no connection string, and no value of any
environment variable. Each check reports a name, a status and a sentence.
`present`/`absent` is the whole truth a health endpoint is entitled to tell,
because these endpoints are reachable without a session — /healthz and
/readyz have to be, or the thing that probes them cannot.

WHY THE ANSWER IS CACHED

/readyz touches a dependency, and it is unauthenticated because a probe has no
session. Rate limiting it would be wrong — a refused readiness probe reads as
"not ready" and takes the instance out of rotation — so instead the answer is
computed at most once every few seconds and served from there. That bounds the
load on the backend regardless of how often anybody asks, without ever
refusing a probe.

FAILING CLOSED

`user_store._is_production()` treats anything unrecognised as production, so
an unset APP_ENV produces a strict readiness check rather than a permissive
one. A readiness probe that passes because a variable was misspelled is worse
than one that fails.
"""

import os
import time

from apex import user_store
from apex.platform import billing as _billing
from apex.platform import ratelimit as _rl

OK = "ok"
DEGRADED = "degraded"
FAIL = "fail"
SKIPPED = "skipped"

_STARTED_AT = time.time()

# How long a readiness answer is reused. Short enough that an operator does
# not chase a stale verdict, long enough that a probe loop cannot turn into a
# load test on Redis.
READY_TTL_SEC = 5.0
_ready_cache = {"at": 0.0, "value": None}


def reset_cache():
    """For tests, and for an operator who wants the answer recomputed now."""
    _ready_cache["at"] = 0.0
    _ready_cache["value"] = None

# Flags that are correct on a laptop and unacceptable on a deployment. They
# are named here rather than inline so the runbook and the check cannot drift.
DEV_ONLY_FLAGS = ("ALLOW_LOCAL_BACKEND_DEV", "ALLOW_PLAINTEXT_DEV_STORAGE")


def _set(name):
    return bool((os.getenv(name) or "").strip())


def _flag_on(name):
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def is_production():
    return user_store._is_production()


def live():
    """(status, payload). Proves the process is running and nothing else."""
    return 200, {
        "ok": True,
        "status": OK,
        "uptimeSec": round(time.time() - _STARTED_AT, 1),
    }


def _check(name, status, message, **extra):
    return dict({"name": name, "status": status, "message": message}, **extra)


def _supabase():
    """Identity. Without it the platform cannot tell who anyone is."""
    url, key = _set("SUPABASE_URL"), _set("SUPABASE_ANON_KEY")
    if url and key:
        return _check("supabase", OK, "URL and anon key are configured")
    missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_ANON_KEY", key)) if not v]
    return _check("supabase", FAIL,
                  f"not configured: {', '.join(missing)}")


def _encryption():
    """Broker tokens at rest.

    A missing key is fatal in production. In development it is only acceptable
    with the explicit opt-in, and it is still reported as degraded rather than
    ok, because "my laptop stores tokens in plaintext" should read as a
    finding even when it is a deliberate one.
    """
    if _set("TOKEN_ENCRYPTION_KEY"):
        return _check("encryption", OK, "token encryption key is present")
    if not is_production() and _flag_on("ALLOW_PLAINTEXT_DEV_STORAGE"):
        return _check("encryption", DEGRADED,
                      "no encryption key; plaintext development storage is "
                      "explicitly enabled and this must never be a deployment")
    return _check("encryption", FAIL,
                  "TOKEN_ENCRYPTION_KEY is not set, so broker tokens cannot "
                  "be stored safely")


def _shared_store():
    """Ownership, entitlement and order idempotency all depend on this."""
    h = user_store.redis_health()
    if h.get("configured") and h.get("reachable"):
        return _check("shared_store", OK,
                      "shared backend is reachable",
                      backend=h.get("backend"), latencyMs=h.get("latency_ms"))
    if h.get("configured"):
        return _check("shared_store", FAIL,
                      "a shared backend is configured but did not answer",
                      backend=h.get("backend"))
    if is_production():
        return _check("shared_store", FAIL,
                      "no shared backend: ownership, entitlement and order "
                      "idempotency would be per-container")
    return _check("shared_store", DEGRADED,
                  "no shared backend; acceptable only on a development box")


def _rate_limit_store():
    """A counter held in one process is not a limit when there are two."""
    mode = _rl.store_mode()
    if mode == "shared":
        return _check("rate_limit_store", OK, "counters are shared across instances")
    if is_production():
        return _check("rate_limit_store", FAIL,
                      f"rate limiting is using {mode}; with more than one "
                      f"instance the effective limit is the configured one "
                      f"times the instance count", mode=mode)
    return _check("rate_limit_store", DEGRADED,
                  f"rate limiting is using {mode}; development only", mode=mode)


def _ctrader():
    """OAuth. Without it no client can connect an account at all."""
    names = ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_REDIRECT_URI")
    missing = [n for n in names if not _set(n)]
    if not missing:
        return _check("ctrader_oauth", OK, "client id, secret and redirect URI are configured")
    return _check("ctrader_oauth", FAIL,
                  f"not configured: {', '.join(missing)} — clients cannot "
                  f"connect a cTrader account")


def _billing_check():
    """Only required when checkout is on. Skipped, not failed, when it is off."""
    enabled = _flag_on("A4T_CHECKOUT_ENABLED")
    if not enabled:
        return _check("billing", SKIPPED,
                      "checkout is disabled, so no payment configuration is required",
                      checkoutEnabled=False)
    missing = []
    if not _billing.configured():
        missing.append("A4T_STRIPE_WEBHOOK_SECRET")
    cfg = _billing.product_config()
    for name, value in (("A4T_PRICE_MINOR", cfg["priceMinor"]),
                        ("A4T_CURRENCY", cfg["currency"]),
                        ("A4T_SKU", cfg["sku"])):
        if value in (None, ""):
            missing.append(name)
    if missing:
        return _check("billing", FAIL,
                      f"checkout is enabled but not configured: {', '.join(missing)}",
                      checkoutEnabled=True)
    return _check("billing", OK, "checkout is enabled and configured", checkoutEnabled=True)


def _dev_flags():
    """Development opt-ins must not be set on a deployment."""
    on = [n for n in DEV_ONLY_FLAGS if _flag_on(n)]
    if not on:
        return _check("dev_flags", OK, "no development-only flags are set")
    if is_production():
        return _check("dev_flags", FAIL,
                      f"development-only flags are set in production: "
                      f"{', '.join(on)}", flags=on)
    return _check("dev_flags", DEGRADED,
                  f"development-only flags are set: {', '.join(on)}", flags=on)


def _live_trading():
    """Stated as a check so a probe can prove it, not only a comment.

    Live trading is not implemented. If a future deployment ever sets the flag
    without the implementation existing, readiness must say so loudly rather
    than let it pass unnoticed.
    """
    if _flag_on("LIVE_TRADING_ENABLED"):
        return _check("live_trading", FAIL,
                      "LIVE_TRADING_ENABLED is set, but live trading is not "
                      "implemented in this release and no execution path "
                      "exists for it", enabled=True)
    return _check("live_trading", OK,
                  "live trading is disabled, which is the only supported "
                  "setting in this release", enabled=False)


CHECKS = (_supabase, _encryption, _shared_store, _rate_limit_store,
          _ctrader, _billing_check, _dev_flags, _live_trading)


def ready(*, force=False):
    """(status, payload). 200 when every required dependency is right.

    A degraded check does not fail readiness — it is a development box saying
    so. A failed one does: 503, because sending traffic to an instance that
    cannot verify a session or cannot share a counter is worse than sending it
    nowhere.

    The answer is cached for READY_TTL_SEC; `force` recomputes it. The cached
    payload carries `checkedAt`, so a reader can see how old the verdict is
    rather than assume it is this instant's.
    """
    now = time.time()
    if not force and _ready_cache["value"] is not None \
            and now - _ready_cache["at"] < READY_TTL_SEC:
        return _ready_cache["value"]

    checks = [fn() for fn in CHECKS]
    failed = [c["name"] for c in checks if c["status"] == FAIL]
    degraded = [c["name"] for c in checks if c["status"] == DEGRADED]
    status = FAIL if failed else (DEGRADED if degraded else OK)
    payload = {
        "ok": not failed,
        "status": status,
        "environment": "production" if is_production() else "development",
        "checkedAt": int(now),
        "checks": checks,
    }
    if failed:
        payload["failed"] = failed
    if degraded:
        payload["degraded"] = degraded
    out = ((503 if failed else 200), payload)
    _ready_cache["at"] = now
    _ready_cache["value"] = out
    return out


def system_status(principal):
    """Authenticated diagnostics, for an operator looking at one deployment.

    Returns the payload only; the caller wraps it in the platform API's own
    envelope, so this route cannot drift into a shape of its own.

    Same checks as /readyz, plus the facts an operator asks for first. It
    carries no more secret material than /readyz does — being authenticated is
    not a reason to start returning keys.
    """
    _, body = ready()
    return {
        "status": body["status"],
        "environment": body["environment"],
        "checks": body["checks"],
        "uptimeSec": round(time.time() - _STARTED_AT, 1),
        "capabilities": {
            # What this release can and cannot do, from the code rather than
            # from a hopeful description of it.
            "demoAutomation": True,
            "liveTrading": False,
            "checkoutEnabled": _flag_on("A4T_CHECKOUT_ENABLED"),
        },
        "user": {"userId": principal.user_id},
    }
