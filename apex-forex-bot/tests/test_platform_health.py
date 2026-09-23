"""Liveness and readiness.

WHAT THIS IS ACTUALLY FOR

A readiness probe is only worth having if it FAILS. Most of these tests exist
to prove that it refuses in the conditions that matter — no shared backend in
production, no encryption key, a development flag left on, live trading turned
on against a release that cannot do it — because a probe that answers 200 come
what may is worse than no probe at all: it converts a misconfiguration into a
silent one.

The other half proves what must NEVER be in the answer. /healthz and /readyz
are unauthenticated by necessity, so every test here that sets a variable sets
it to a sentinel value and then asserts that value appears nowhere in the JSON.

Run: python3 tests/test_platform_health.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-health-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ.setdefault("PRODUCT", "forex")

# Sentinels. Every one of these is a value a health endpoint must never echo.
SECRETS = {
    "SUPABASE_URL": "https://SENTINEL-SUPA-URL.example",
    "SUPABASE_ANON_KEY": "SENTINEL-ANON-KEY-aaaa",
    "TOKEN_ENCRYPTION_KEY": "SENTINEL-FERNET-gAAAAAbbbb",
    "CTRADER_CLIENT_ID": "SENTINEL-CT-ID-cccc",
    "CTRADER_CLIENT_SECRET": "SENTINEL-CT-SECRET-dddd",
    "CTRADER_REDIRECT_URI": "https://SENTINEL-REDIRECT.example/cb",
    "A4T_STRIPE_WEBHOOK_SECRET": "whsec_SENTINEL-eeee",
}
os.environ.update(SECRETS)

from apex import user_store                      # noqa: E402
from apex.platform import api as A               # noqa: E402
from apex.platform import health as H            # noqa: E402
from apex.platform import ratelimit as RL        # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def status_of(payload, name):
    for c in payload["checks"]:
        if c["name"] == name:
            return c["status"]
    return None


def fresh(**env):
    """Readiness computed now, under an environment overlay."""
    old = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        H.reset_cache()
        return H.ready(force=True)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        H.reset_cache()


# ── 1. liveness says only that the process is running ───────────────────────
print("\n[1] /healthz does not touch a dependency")
_real_health = user_store.redis_health


def _explode(*a, **k):
    raise RuntimeError("the shared backend is on fire")


user_store.redis_health = _explode
try:
    st, body = H.live()
    check("liveness answers 200 with the backend unreachable", st == 200, str(st))
    check("and says the process is up", body["ok"] is True and body["status"] == "ok")
    check("and reports an uptime", body["uptimeSec"] >= 0)
    check("and does NOT carry a checks list — that is readiness' job",
          "checks" not in body, json.dumps(body))
finally:
    user_store.redis_health = _real_health

# ── 2. development: degraded, but not refused ───────────────────────────────
print("\n[2] a development box is degraded, not unready")
st, body = fresh()
check("readiness answers 200 on a dev box", st == 200, str(st))
check("and calls itself degraded rather than ok",
      body["status"] == "degraded", body["status"])
check("and names the environment", body["environment"] == "development")
check("shared_store is degraded, not ok",
      status_of(body, "shared_store") == "degraded", status_of(body, "shared_store"))
check("rate_limit_store is degraded, not ok",
      status_of(body, "rate_limit_store") == "degraded",
      status_of(body, "rate_limit_store"))
check("the degraded names are listed", "shared_store" in body.get("degraded", []))
check("nothing is failing", "failed" not in body, json.dumps(body.get("failed")))

# ── 3. a missing dependency fails readiness ─────────────────────────────────
print("\n[3] a missing required dependency refuses readiness")
st, body = fresh(SUPABASE_URL=None)
check("no Supabase URL -> 503", st == 503, str(st))
check("and supabase is the failing check",
      status_of(body, "supabase") == "fail", status_of(body, "supabase"))
check("and it is named in `failed`", "supabase" in body["failed"], str(body["failed"]))
check("and ok is False", body["ok"] is False)
check("the message names the VARIABLE, not a value",
      "SUPABASE_URL" in [c for c in body["checks"] if c["name"] == "supabase"][0]["message"])

st, body = fresh(CTRADER_CLIENT_SECRET=None)
check("no cTrader secret -> 503", st == 503, str(st))
check("and ctrader_oauth fails", status_of(body, "ctrader_oauth") == "fail")

st, body = fresh(TOKEN_ENCRYPTION_KEY=None, ALLOW_PLAINTEXT_DEV_STORAGE=None)
check("no encryption key and no dev opt-in -> 503", st == 503, str(st))
check("and encryption fails", status_of(body, "encryption") == "fail")

st, body = fresh(TOKEN_ENCRYPTION_KEY=None)
check("no encryption key WITH the dev opt-in is degraded, not ok",
      status_of(body, "encryption") == "degraded", status_of(body, "encryption"))
check("and the box is still servable", st == 200, str(st))

# ── 4. production misconfiguration ──────────────────────────────────────────
# The point of the whole module. On a dev box these same conditions are a
# shrug; in production they are a refusal.
print("\n[4] production refuses what development tolerates")
st, body = fresh(APP_ENV="production")
check("production with no shared backend -> 503", st == 503, str(st))
check("and it says production", body["environment"] == "production")
check("shared_store fails", status_of(body, "shared_store") == "fail")
check("dev flags fail in production", status_of(body, "dev_flags") == "fail",
      status_of(body, "dev_flags"))
check("the dev flag names are listed so an operator can act",
      set(H.DEV_ONLY_FLAGS) & set(
          [c for c in body["checks"] if c["name"] == "dev_flags"][0].get("flags", [])))

# This is the one the brief asks for by name: production must not quietly
# rate-limit in process memory.
print("\n[4b] production does not use local memory for rate limiting")
check("store_mode reports memory when there is no shared backend",
      RL.store_mode() == "memory", RL.store_mode())
st, body = fresh(APP_ENV="production")
check("and production refuses readiness on exactly that",
      status_of(body, "rate_limit_store") == "fail",
      status_of(body, "rate_limit_store"))
check("and it is named in `failed`", "rate_limit_store" in body["failed"])
rl_check = [c for c in body["checks"] if c["name"] == "rate_limit_store"][0]
check("and the message explains the consequence, not just the state",
      "instance" in rl_check["message"], rl_check["message"])
check("and reports the mode", rl_check.get("mode") == "memory", str(rl_check.get("mode")))

# An explicit RATE_LIMIT_STORE=memory is still memory. Choosing it does not
# make it correct in production, and readiness must not treat an opt-in as an
# excuse.
print("\n[4c] forcing memory is still memory")
_mode = RL._MODE
RL._MODE = "memory"
try:
    check("store_mode says memory-forced", RL.store_mode() == "memory-forced",
          RL.store_mode())
    st, body = fresh(APP_ENV="production")
    check("production still refuses", status_of(body, "rate_limit_store") == "fail")
finally:
    RL._MODE = _mode

# ── 5. a reachable shared backend is the healthy case ───────────────────────
print("\n[5] with a shared backend, production is ready")
_counter = {"n": 0}


def _fake_health(timeout_s=3.0):
    return {"configured": True, "reachable": True, "backend": "redis",
            "latency_ms": 3, "status": "HEALTHY"}


def _fake_incr(key, ttl_s=60):
    _counter["n"] += 1
    return _counter["n"]


user_store.redis_health = _fake_health
_real_incr = user_store.incr
user_store.incr = _fake_incr
try:
    st, body = fresh(APP_ENV="production", ALLOW_LOCAL_BACKEND_DEV=None,
                     ALLOW_PLAINTEXT_DEV_STORAGE=None)
    check("production with every dependency present -> 200", st == 200,
          f"{st} {json.dumps(body.get('failed'))}")
    check("and it is ok, not degraded", body["status"] == "ok", body["status"])
    check("shared_store is ok", status_of(body, "shared_store") == "ok")
    check("rate_limit_store is ok", status_of(body, "rate_limit_store") == "ok")
    check("dev_flags is ok", status_of(body, "dev_flags") == "ok")
    check("the latency is reported so slow is visible before down",
          [c for c in body["checks"] if c["name"] == "shared_store"][0]["latencyMs"] == 3)

    # Configured but not answering is NOT the same as not configured, and it
    # must not be rendered as the milder one.
    user_store.redis_health = lambda timeout_s=3.0: {
        "configured": True, "reachable": False, "backend": "redis",
        "latency_ms": None, "status": "UNREACHABLE"}
    st, body = fresh(APP_ENV="dev")
    check("a configured backend that does not answer fails even in dev",
          status_of(body, "shared_store") == "fail", status_of(body, "shared_store"))
    check("and that refuses readiness", st == 503, str(st))
finally:
    user_store.redis_health = _real_health
    user_store.incr = _real_incr

# ── 6. live trading is asserted, not assumed ────────────────────────────────
print("\n[6] live trading is a check, not a comment")
st, body = fresh()
lt = [c for c in body["checks"] if c["name"] == "live_trading"][0]
check("it is ok while disabled", lt["status"] == "ok", lt["status"])
check("and says so explicitly", lt["enabled"] is False)
st, body = fresh(LIVE_TRADING_ENABLED="true")
check("turning it on refuses readiness", st == 503, str(st))
check("because no execution path exists for it",
      status_of(body, "live_trading") == "fail")

# ── 7. billing is skipped, not failed, while checkout is off ────────────────
print("\n[7] a disabled feature is not a broken one")
st, body = fresh()
check("billing is skipped while checkout is disabled",
      status_of(body, "billing") == "skipped", status_of(body, "billing"))
check("and skipped does not count as degraded",
      "billing" not in body.get("degraded", []))
st, body = fresh(A4T_CHECKOUT_ENABLED="true")
check("enabling checkout without a price refuses readiness", st == 503, str(st))
check("and billing is the failing check", status_of(body, "billing") == "fail")
st, body = fresh(A4T_CHECKOUT_ENABLED="true", A4T_PRICE_MINOR="1000",
                 A4T_CURRENCY="EUR", A4T_SKU="a4t-beta")
check("a fully configured checkout is ok", status_of(body, "billing") == "ok",
      json.dumps([c for c in body["checks"] if c["name"] == "billing"]))

# ── 8. NOTHING secret ever reaches the response ─────────────────────────────
# /healthz and /readyz are unauthenticated. This is the test that keeps them
# safe to leave that way.
print("\n[8] no secret, in any state, ever appears in a payload")
payloads = []
for env in ({}, {"APP_ENV": "production"}, {"A4T_CHECKOUT_ENABLED": "true"},
            {"LIVE_TRADING_ENABLED": "true"}, {"SUPABASE_URL": None}):
    payloads.append(json.dumps(fresh(**env)[1]))
payloads.append(json.dumps(H.live()[1]))
blob = "\n".join(payloads)
for name, value in SECRETS.items():
    check(f"{name}'s VALUE is absent", value not in blob)
check("no Fernet-shaped value anywhere", "gAAAAA" not in blob)
check("no whsec_ anywhere", "whsec_" not in blob)
check("but the variable NAMES are usable by an operator",
      "SUPABASE_URL" in blob, "a health check that names nothing is not actionable")

# ── 9. the answer is cached, so a probe loop is not a load test ─────────────
print("\n[9] readiness is computed at most once every few seconds")
_probes = {"n": 0}
_real_rl_mode = RL.store_mode
RL.store_mode = lambda: (_probes.__setitem__("n", _probes["n"] + 1)) or "memory"
try:
    H.reset_cache()
    H.ready()
    after_first = _probes["n"]
    H.ready()
    H.ready()
    check("three calls in a row probe the backend once",
          _probes["n"] == after_first, f"{_probes['n']} vs {after_first}")
    H.ready(force=True)
    check("force recomputes", _probes["n"] > after_first)
    H.reset_cache()
    H.ready()
    check("and so does clearing the cache", _probes["n"] > after_first + 1)
finally:
    RL.store_mode = _real_rl_mode
    H.reset_cache()

st, body = fresh()
check("the payload says when it was computed", isinstance(body.get("checkedAt"), int))

# ── 10. the authenticated diagnostics route ─────────────────────────────────
print("\n[10] /api/v1/system/status is authenticated and states capabilities")
st, out = A.handle("GET", "/api/v1/system/status", {}, None, client_key="1.2.3.4")
check("no token -> refused", st in (401, 503), str(st))
check("and not 200", st != 200, str(st))

import apex.platform.identity as _id                      # noqa: E402


class _P:
    user_id = "user-health-1"
    email = "someone@example.test"
    email_verified = True

    def as_dict(self):
        return {"userId": self.user_id}


_real_verify = _id.verify_token
_id.verify_token = lambda tok, **kw: _P()
try:
    H.reset_cache()
    st, out = A.handle("GET", "/api/v1/system/status",
                       {"Authorization": "Bearer t"}, None, client_key="1.2.3.4")
    check("an authenticated caller gets 200", st == 200, json.dumps(out)[:300])
    check("and the reply carries the platform API's own envelope",
          out.get("ok") is True, json.dumps(out)[:120])
    check("it states that live trading is off",
          out["capabilities"]["liveTrading"] is False, json.dumps(out.get("capabilities")))
    check("it states that demo automation is on",
          out["capabilities"]["demoAutomation"] is True)
    check("it states whether checkout is on",
          out["capabilities"]["checkoutEnabled"] is False)
    check("it carries the checks", isinstance(out["checks"], list) and out["checks"])
    blob = json.dumps(out)
    for name, value in SECRETS.items():
        check(f"{name}'s value is absent from the authenticated view too",
              value not in blob)
    check("and the caller's e-mail is not echoed back at them",
          "someone@example.test" not in blob, blob[:200])
finally:
    _id.verify_token = _real_verify

# ── 11. the transport mounts /healthz BEFORE the old /health prefix ─────────
# /healthz starts with /health. The older plain-text route matches on a
# prefix, so ordering is the whole correctness argument and it is not
# something a unit test of the module can see.
print("\n[11] /healthz is matched before the legacy /health prefix")
src = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
body_start = src.index("def do_GET(self):")
segment = src[body_start:body_start + 2000]
i_new = segment.find("_platform_health()")
i_old = segment.find('startswith("/health")')
check("both routes are present in do_GET", i_new >= 0 and i_old >= 0,
      f"{i_new} {i_old}")
check("and the JSON one comes first", 0 <= i_new < i_old, f"{i_new} vs {i_old}")
check("the transport answers both paths",
      '"/healthz", "/readyz"' in src)
check("and forwards no request header into the health module",
      "self.headers" not in src[src.index("def _platform_health(self):"):
                                src.index("def _platform_api(self):")])

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All health checks passed.")
