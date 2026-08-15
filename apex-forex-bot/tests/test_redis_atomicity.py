"""The four red items from the follow-up audit, each as its failure case.

1. Lease renewal/release must be ATOMIC. Read-then-write can hand two
   containers the same user without either seeing an error.
2. A write that did not happen must never look like one that did.
3. A buyer who has been charged must never end up unprovisioned with Stripe
   believing the event was handled.
4. A callback with no verifiable state must never link a broker account.

Run: python tests/test_redis_atomicity.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "user_store.py"), encoding="utf-8").read()

print("\n🧪 ATOMICITY, HONEST WRITES, FAIL-SAFE PROVISIONING\n")

# ─────────────────────────────────────────────────────────────
print("1. Lease renew/release are single server-side operations")
check("renew is a Lua compare-and-set",
      "_LUA_RENEW" in SRC and "redis.call('GET', KEYS[1]) == ARGV[1]" in SRC)
check("release is too", "_LUA_RELEASE" in SRC and "redis.call('DEL', KEYS[1])" in SRC)
_renew = SRC[SRC.index("def renew_claim"):SRC.index("def release_claim")]
check("renew no longer reads then writes",
      "_redis_get" not in _renew and "set_blob" not in _renew, _renew[:200])
_rel = SRC[SRC.index("def release_claim"):SRC.index("def release_claim") + 900]
check("release no longer reads then deletes", "_redis_get" not in _rel)
check("there is a transport that can carry a Lua script", "_upstash_post" in SRC)

# The scripts have to be *correct*, not just present.
class MiniRedis:
    """Runs the two scripts the way Redis would: atomically."""

    def __init__(self):
        self.kv = {}

    def eval(self, script, _n, key, val, ttl=None):
        cur = self.kv.get(key)
        if "DEL" in script:
            if cur == str(val):
                del self.kv[key]
                return 1
            return 0
        return 1 if cur == str(val) else 0


mini = MiniRedis()
_orig_backend, _orig_r, _orig_use = (
    user_store._BACKEND, getattr(user_store, "_r", None), user_store._USE_REDIS)
try:
    user_store._BACKEND, user_store._r, user_store._USE_REDIS = "redis", mini, True
    mini.kv["own:user:x"] = "me"
    check("owner can renew", user_store.renew_claim("own:user:x", "me", 90) is True)
    check("a non-owner cannot renew",
          user_store.renew_claim("own:user:x", "other", 90) is False)
    check("a non-owner cannot release",
          user_store.release_claim("own:user:x", "other") is False)
    check("and the key survives that attempt", mini.kv.get("own:user:x") == "me")
    check("the owner can release", user_store.release_claim("own:user:x", "me") is True)
    check("which actually removes it", "own:user:x" not in mini.kv)
    check("renewing a vanished lease reports loss",
          user_store.renew_claim("own:user:x", "me", 90) is False)
finally:
    user_store._BACKEND, user_store._r, user_store._USE_REDIS = (
        _orig_backend, _orig_r, _orig_use)

# ─────────────────────────────────────────────────────────────
print("\n2. A write that did not land never reports success")
_saved = {}


class DeadRedis:
    def set(self, *a, **k):
        raise RuntimeError("redis is down")

    def sadd(self, *a, **k):
        raise RuntimeError("redis is down")

    def srem(self, *a, **k):
        raise RuntimeError("redis is down")

    def get(self, *a, **k):
        raise RuntimeError("redis is down")


try:
    user_store._BACKEND, user_store._r, user_store._USE_REDIS = "redis", DeadRedis(), True
    check("_redis_set reports False, not None",
          user_store._redis_set("k", "v") is False)
    check("save() returns False when the backend is down",
          user_store.save("u9", {"license_key": "X"}) is False)
    check("update() propagates that",
          user_store.update("u9", {"risk": 0.01}) is False)
    # And the strict form refuses to let the caller carry on unaware.
    raised = False
    try:
        user_store.save("u9", {"license_key": "X"}, strict=True)
    except user_store.PersistenceError:
        raised = True
    check("strict=True raises PersistenceError", raised)
    raised = False
    try:
        user_store.update("u9", {"license_key": "X"}, strict=True)
    except user_store.PersistenceError:
        raised = True
    check("update(strict=True) raises too", raised)
finally:
    user_store._BACKEND, user_store._r, user_store._USE_REDIS = (
        _orig_backend, _orig_r, _orig_use)

check("a successful save still returns True",
      user_store.save("u_tmp_ok", {"a": 1}) is True)
try:
    os.remove(user_store._path("u_tmp_ok"))
except OSError:
    pass

# ─────────────────────────────────────────────────────────────
print("\n3. A charged buyer is never left unprovisioned and 'handled'")
from apex import stripe_license  # noqa: E402
import apex.config as _cfg  # noqa: E402
import json as _json  # noqa: E402
import types  # noqa: E402

_recs, _sent, _claims = {}, [], {}


def _load(uid):
    return dict(_recs.get(str(uid), {}))


def _claim(key, ttl_s=120):
    if key in _claims:
        return False
    _claims[key] = 1
    return True


def _set_blob(key, val, ttl_s=None):
    if ttl_s == 1:
        _claims.pop(key, None)
    return True


EVENT = {"id": "evt_9", "type": "checkout.session.completed",
         "data": {"object": {"payment_status": "paid",
                             "client_reference_id": "42", "id": "cs_9"}}}
BODY = _json.dumps(EVENT).encode()

_o = (user_store.load, user_store.update, user_store.claim, user_store.set_blob)
try:
    stripe_license._verify_signature = lambda *a, **k: True
    _cfg.STRIPE_WEBHOOK_SECRET = "whsec_test"
    fa = types.ModuleType("apex.access"); fa.grant = lambda uid: True
    ft = types.ModuleType("apex.telegram")
    ft.send_activation_sequence = lambda uid, paid=False: _sent.append(uid)
    sys.modules["apex.access"], sys.modules["apex.telegram"] = fa, ft

    user_store.load, user_store.claim, user_store.set_blob = _load, _claim, _set_blob

    def _dead_update(uid, updates, strict=False):
        if strict:
            raise user_store.PersistenceError("redis is down")
        return False
    user_store.update = _dead_update

    st, body = stripe_license.handle_webhook(BODY, "sig")
    check("a failed licence write returns 500, not 200",
          st == 500, (st, body))
    check("so Stripe will retry rather than consider it handled",
          st >= 500)
    check("and the idempotency claim was released",
          "stripe:evt:evt_9" not in _claims, list(_claims))

    # Redis comes back; the retry must now provision.
    def _ok_update(uid, updates, strict=False):
        _recs.setdefault(str(uid), {}).update(updates)
        return True
    user_store.update = _ok_update
    st2, _ = stripe_license.handle_webhook(BODY, "sig")
    check("the retry provisions the buyer", st2 == 200 and _recs["42"].get("license_key"))
    check("and messages them once", len(_sent) == 1, _sent)

    # A claim held by a failed attempt must not lock the buyer out.
    _recs.clear(); _sent.clear(); _claims["stripe:evt:evt_9"] = 1
    user_store.update = _ok_update
    st3, _ = stripe_license.handle_webhook(BODY, "sig")
    check("a stale claim with no licence still provisions",
          st3 == 200 and _recs.get("42", {}).get("license_key"), st3)

    # Once genuinely provisioned, a redelivery is a no-op.
    st4, b4 = stripe_license.handle_webhook(BODY, "sig")
    check("a real duplicate is refused", b4 == b"duplicate", b4)
    check("with no second message", len(_sent) == 1, _sent)
finally:
    sys.modules.pop("apex.access", None)
    sys.modules.pop("apex.telegram", None)
    user_store.load, user_store.update, user_store.claim, user_store.set_blob = _o

# ─────────────────────────────────────────────────────────────
print("\n4. A callback with no verifiable state links nothing")
from apex import ctrader_oauth as oauth  # noqa: E402

oauth._pending.clear()
oauth._used_states.clear()
check("the stateless fallback is OFF by default", oauth.ALLOW_STATELESS is False)

oauth._record_pending("111")
check("one pending, no state → still refused",
      oauth._recent_pending() is None)
oauth._record_pending("222")
check("two pending, no state → refused", oauth._recent_pending() is None)

# The escape hatch stays deliberate, and never guesses between two.
oauth._pending.clear()
oauth.ALLOW_STATELESS = True
try:
    oauth._record_pending("111")
    check("enabled + exactly one pending → allowed", oauth._recent_pending() == "111")
    oauth._pending.clear()
    oauth._record_pending("111")
    oauth._record_pending("222")
    check("enabled + two pending → STILL refused, no guessing",
          oauth._recent_pending() is None)
finally:
    oauth.ALLOW_STATELESS = False
    oauth._pending.clear()

print("\n   a signed state is single-use")
_oc = user_store.claim
try:
    user_store.claim = lambda *a, **k: None       # no shared backend
    oauth._used_states.clear()
    st = oauth.make_state("555")
    check("the state parses to its own client", oauth.parse_state(st) == "555")
    check("first redemption succeeds", oauth._consume_state(st) is True)
    check("a replay of the same state is refused",
          oauth._consume_state(st) is False)
    check("a different state is unaffected",
          oauth._consume_state(oauth.make_state("556")) is True)
finally:
    user_store.claim = _oc
    oauth._used_states.clear()

OSRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "ctrader_oauth.py"), encoding="utf-8").read()
check("the callback consumes the state before trusting it",
      "_consume_state(state)" in OSRC)
check("and broker credentials are written strictly",
      "strict=True" in OSRC)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — atomic leases, honest writes, safe provisioning.")
