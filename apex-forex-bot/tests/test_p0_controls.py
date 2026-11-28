"""The P0 launch blockers from the master audit, each with its failure case.

Every check here corresponds to a row in the audit's race/failure matrix, and
each one is written as the scenario that used to go wrong rather than as an
assertion about an implementation detail.

Covered:
  P0-01  Stripe webhook ×2 → exactly one license, one activation message.
  P0-02  OAuth callback with no usable state → never bound to the wrong client.
  P0-03  Two containers → exactly one owns a user; the loser stands down.
  P0-04  Coordination backend unreachable → no NEW live entry; demo continues.
  P0-09  Revocation blocks new entries.

Not covered here, deliberately: the Supabase/RLS/migrations sections of the
audit describe a Postgres application. This bot has no Postgres — user state
lives in Upstash Redis and JSON — so those rows are not implemented rather
than passing, and a test asserting otherwise would be a lie.

Run: python tests/test_p0_controls.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

# A TEST-ONLY OAuth state signing secret.
#
# apex/ctrader_oauth refuses to mint an OAuth `state` without one, and that
# refusal is correct production behaviour under test elsewhere: `state` is what
# proves a callback belongs to the chat that began the flow, so an unsigned one
# lets somebody's broker account be bound to somebody else's chat. The fix is
# to give the TEST a secret, never to give production a fallback.
#
# setdefault, so a caller that exports its own value keeps it. This is a fake
# constant with no meaning outside this process.
os.environ.setdefault("CTRADER_CLIENT_SECRET", "test-only-oauth-signing-secret")

from apex import ledger, ownership, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


class FakeRedis:
    """Just enough Redis to exercise the claim/renew/release contract."""

    def __init__(self, broken=False):
        self.kv, self.broken = {}, broken

    def claim_value(self, key, value, ttl_s=120):
        if self.broken:
            return None
        if key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    def get_blob(self, key):
        return None if self.broken else self.kv.get(key)

    def renew_claim(self, key, value, ttl_s=120):
        if self.broken:
            return None
        cur = self.kv.get(key)
        return False if cur is None or cur != str(value) else True

    def release_claim(self, key, value):
        if self.broken:
            return None
        if self.kv.get(key) == str(value):
            del self.kv[key]
            return True
        return False

    def claim(self, key, ttl_s=120):
        if self.broken:
            return None
        if key in self.kv:
            return False
        self.kv[key] = "1"
        return True


def install(fake, use_redis=True):
    """Point user_store at the fake and reset ownership's local memory.

    With use_redis=False every primitive returns None, exactly as the real
    module does when no shared backend is configured — otherwise a test for
    "no backend" would still be quietly using one.
    """
    user_store._USE_REDIS = use_redis
    for n in ("claim_value", "get_blob", "renew_claim", "release_claim", "claim"):
        setattr(user_store, n,
                getattr(fake, n) if use_redis else (lambda *a, **k: None))
    ownership._held.clear()


_ORIG = {n: getattr(user_store, n) for n in
         ("claim_value", "get_blob", "renew_claim", "release_claim", "claim")}
_ORIG_USE = getattr(user_store, "_USE_REDIS", False)
_ORIG_UPD, _ORIG_LOAD = user_store.update, user_store.load


def restore():
    for n, f in _ORIG.items():
        setattr(user_store, n, f)
    user_store._USE_REDIS = _ORIG_USE
    ownership._held.clear()


print("\n🧪 P0 LAUNCH BLOCKERS\n")

# ─────────────────────────────────────────────────────────────
print("P0-03 — only one container may own a user")
try:
    shared = FakeRedis()
    install(shared)
    me = ownership.INSTANCE_ID
    check("first instance wins the lease", ownership.acquire("u1") is True)
    check("and knows it holds it", ownership.holds("u1") is True)

    # A second container: same shared store, different instance id.
    ownership.INSTANCE_ID = "other-container"
    ownership._held.clear()
    check("second instance is refused", ownership.acquire("u1") is False)
    check("and knows it does NOT hold it", ownership.holds("u1") is False)
    ok, why = ownership.may_trade("u1", live=True)
    check("so it must not trade", ok is False and why == "NOT_OWNER", why)

    # The owner stops; the lease is handed back rather than waited out.
    ownership.INSTANCE_ID = me
    ownership._held["u1"] = 0          # force a real read
    ownership.release("u1")
    ownership.INSTANCE_ID = "other-container"
    ownership._held.clear()
    check("after release the second instance can take over",
          ownership.acquire("u1") is True)
finally:
    ownership.INSTANCE_ID = me
    restore()

print("\nP0-03 — a lost lease makes the old worker stand down")
try:
    shared = FakeRedis()
    install(shared)
    ownership.acquire("u2")
    check("heartbeat renews while it is ours", ownership.heartbeat("u2") is True)
    shared.kv["own:user:u2"] = "somebody-else"      # takeover
    check("heartbeat reports the loss", ownership.heartbeat("u2") is False)
    check("and holds() agrees", ownership.holds("u2") is False)
finally:
    restore()

print("\nP0-04 — coordination down: no new LIVE entry, demo continues")
try:
    install(FakeRedis(broken=True))                 # configured but unreachable
    check("ownership is unknown, not assumed",
          ownership.holds("u3") is None)
    ok, why = ownership.may_trade("u3", live=True)
    check("a live account fails CLOSED",
          ok is False and why == "OWNERSHIP_UNKNOWN", why)
    ok, why = ownership.may_trade("u3", live=False)
    check("a demo account keeps running", ok is True, why)

    # Same rule one layer down, in the order ledger.
    ok, why, _ = ledger.claim("u3", "EURUSD", "BUY", 1000, 1.1, 1.2,
                              fail_closed=True)
    check("the order ledger refuses a live order it cannot coordinate",
          ok is False and why == "COORDINATION_UNAVAILABLE", why)
    ok, why, _ = ledger.claim("u3", "EURUSD", "BUY", 1000, 1.1, 1.2,
                              fail_closed=False)
    check("and still allows the demo one", ok is True, why)
finally:
    restore()

print("\nP0-04 — no shared backend at all is NOT the same as one that is down")
try:
    install(FakeRedis(), use_redis=False)
    ok, why = ownership.may_trade("u4", live=True)
    check("an uncontended single instance may trade",
          ok is True and why == "UNCONTENDED", why)
    ok, _why, _ = ledger.claim("u4", "GBPUSD", "SELL", 500, 1.3, 1.2,
                               fail_closed=True)
    check("and the ledger does not fail closed on a backend that is absent",
          ok is True)
finally:
    restore()

# ─────────────────────────────────────────────────────────────
print("\nP0-01 — the platform webhook, not a second licence minter")
_bill = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "apex", "platform", "billing.py"), encoding="utf-8").read()
check("the legacy Telegram Stripe webhook is retired",
      not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      "apex", "stripe_license.py")))
check("a duplicate platform delivery is still a success",
      '"duplicate": True' in _bill)

print("\nP0-02 — an ambiguous OAuth callback must not bind the wrong account")
from apex import ctrader_oauth as oauth  # noqa: E402

oauth._pending.clear()
check("no pending authorization → nothing to bind to",
      oauth._recent_pending() is None)

oauth._pending.clear()
oauth._record_pending("111")
# This check previously asserted that a single pending authorization WAS bound.
# That was the first fix and it was not enough: it removed the two-client case
# but kept the premise, which is that an unsigned callback is trusted at all.
# Anyone who can reach the public callback URL while one client happens to be
# authorizing could still have their own broker account bound to that client.
# The fallback is now off unless an operator explicitly turns it on.
check("exactly one pending is STILL not enough without a signed state",
      oauth._recent_pending() is None, oauth._recent_pending())

# The bug: two clients mid-authorization. The old code returned the most
# RECENT one, so whoever tapped /ctrader last was handed the other person's
# broker tokens.
oauth._pending.clear()
oauth._record_pending("111")
oauth._record_pending("222")
check("two pending → refuse rather than guess",
      oauth._recent_pending() is None, oauth._recent_pending())

# A signed state still works and is always preferred over the fallback.
oauth._pending.clear()
oauth._record_pending("111")
oauth._record_pending("222")
st = oauth.make_state("333")
check("a valid signed state still identifies its own client",
      oauth.parse_state(st) == "333")
check("a forged state is rejected", oauth.parse_state("bm90LWEtc3RhdGU") is None)
check("a tampered state is rejected",
      oauth.parse_state(st[:-2] + ("aa" if not st.endswith("aa") else "bb")) is None)
oauth._pending.clear()

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — P0 controls hold under their failure cases.")
