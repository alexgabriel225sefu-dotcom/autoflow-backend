"""The lease must not shut down the only container that is running.

This is a regression test for a live incident: a client received
`⚡ OWNERSHIP_LOST — EUR_USD` from a single-container deployment with nothing
competing for the account.

Two defects combined to cause it:

  * The TTL was a fixed 90s while the trading tick is 300s, and renewal ran
    from the top of the tick. The lease was therefore expired for 210 of every
    300 seconds.
  * `renew` returns 0 both when another instance owns the key AND when the key
    is simply gone. The loop read the second case as the first, alerted the
    client, and stopped trading. The watchdog restarted it 180s later and it
    did the same thing again.

So the lease built to prevent two owners was reliably producing zero.

What this pins:
  * the TTL always comfortably exceeds the loop tick;
  * an EXPIRED lease is reacquired, never reported as a takeover;
  * a lease genuinely held by another instance still stands the loop down;
  * renewal does not depend on the trading tick.

Run: python tests/test_lease_expiry.py
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

from apex import config as cfg, ownership, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


class Fake:
    """A store whose keys can be made to expire on command."""

    def __init__(self):
        self.kv = {}

    def claim_value(self, key, value, ttl_s=120):
        if key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    def get_blob(self, key):
        return self.kv.get(key)

    def renew_claim(self, key, value, ttl_s=120):
        return self.kv.get(key) == str(value)

    def release_claim(self, key, value):
        if self.kv.get(key) == str(value):
            del self.kv[key]
            return True
        return False


_O = {n: getattr(user_store, n) for n in
      ("claim_value", "get_blob", "renew_claim", "release_claim")}
_OU = user_store._USE_REDIS


def install(fake):
    user_store._USE_REDIS = True
    for n in _O:
        setattr(user_store, n, getattr(fake, n))
    ownership._held.clear()
    ownership._lost.clear()
    ownership._renewers.clear()


def restore():
    for n, f in _O.items():
        setattr(user_store, n, f)
    user_store._USE_REDIS = _OU
    ownership._held.clear()
    ownership._lost.clear()
    ownership._renewers.clear()


print("\n🧪 LEASE EXPIRY — the incident that produced OWNERSHIP_LOST\n")

print("1. The lease outlives the tick it has to survive")
tick = max(30, int(getattr(cfg, "LOOP_INTERVAL_MS", 300_000) / 1000))
print(f"   loop tick = {tick}s · lease TTL = {ownership.TTL_S}s "
      f"· renew every {ownership.RENEW_EVERY_S}s")
check("TTL is longer than one full tick", ownership.TTL_S > tick,
      f"TTL={ownership.TTL_S} tick={tick}")
check("with room for a slow one", ownership.TTL_S >= tick * 2)
check("renewal is far more frequent than expiry",
      ownership.RENEW_EVERY_S * 3 <= ownership.TTL_S,
      (ownership.RENEW_EVERY_S, ownership.TTL_S))
# The exact numbers that produced the incident must not be reachable again.
check("the 90s-TTL / 300s-tick combination cannot recur",
      not (ownership.TTL_S == 90 and tick == 300))

print("\n2. An EXPIRED lease is reacquired, not mourned")
try:
    fake = Fake()
    install(fake)
    check("acquired", ownership.acquire("u1") is True)
    fake.kv.clear()                       # the lease expires; nobody takes it
    res = ownership.heartbeat("u1")
    check("heartbeat does NOT report a takeover", res is not False, res)
    check("it reacquires instead", res is True and fake.kv.get("own:user:u1"))
    check("and the loop is not told to stand down",
          ownership.was_lost("u1") is False)
finally:
    restore()

print("\n3. A real takeover still stands the loop down")
try:
    fake = Fake()
    install(fake)
    ownership.acquire("u2")
    fake.kv["own:user:u2"] = "other-container"      # genuinely stolen
    check("heartbeat reports the loss", ownership.heartbeat("u2") is False)
    ownership.mark_lost("u2")
    check("and the loop is told", ownership.was_lost("u2") is True)
finally:
    restore()

print("\n3b. A loss does not outlive the restart that fixes it")
# The bug this pins: the loop breaks on was_lost() WITHOUT going through
# stop(), so nothing cleared the flag. The watchdog then restarted the loop
# every 180s, and each restart alerted and broke again on its first tick — an
# OWNERSHIP_LOST message every three minutes from a container that had just
# successfully taken the lease.
try:
    fake = Fake()
    install(fake)
    ownership.acquire("u9")
    fake.kv["own:user:u9"] = "other-container"
    ownership.heartbeat("u9")
    ownership.mark_lost("u9")
    check("the loop is told to stand down", ownership.was_lost("u9") is True)

    # The other container goes away; the watchdog restarts this one.
    fake.kv.clear()
    check("it can take the lease again", ownership.acquire("u9") is True)
    check("and the stale loss is cleared by that",
          ownership.was_lost("u9") is False,
          "restart would alert and break again on its first tick")

    # Re-entrant acquire (our own container already holds it) clears it too.
    ownership.mark_lost("u9")
    check("a re-entrant acquire also clears it",
          ownership.acquire("u9") is True and ownership.was_lost("u9") is False)
finally:
    restore()

check("the break path cleans up after itself",
      "ownership.stop_renewer(user_id)" in open(
          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "user_loop.py"), encoding="utf-8"
      ).read().split("lease taken over")[1][:1200])

print("\n4. Renewal does not depend on the trading tick")
LSRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "user_loop.py"), encoding="utf-8").read()
check("the loop no longer heartbeats inline",
      "ownership.heartbeat(" not in LSRC, "still heartbeats from the tick")
check("it only reacts to a confirmed takeover",
      "ownership.was_lost(user_id)" in LSRC)
check("and a renewer thread is started with the loop",
      "ownership.start_renewer(" in LSRC)
check("stopping the loop stops the renewer too",
      "ownership.stop_renewer(" in LSRC)

print("\n5. The renewer thread actually renews")
try:
    fake = Fake()
    install(fake)
    ownership.RENEW_EVERY_S, _real = 1, ownership.RENEW_EVERY_S
    ownership.acquire("u3")
    lost_calls = []
    ownership.start_renewer("u3", on_lost=lost_calls.append)
    import time as _t
    fake.kv.clear()                       # expire it behind the renewer's back
    _t.sleep(2.5)
    check("the renewer put the lease back", fake.kv.get("own:user:u3") is not None,
          fake.kv)
    check("without declaring it lost", lost_calls == [], lost_calls)
    fake.kv["own:user:u3"] = "someone-else"
    _t.sleep(2.5)
    check("but a real takeover IS reported", lost_calls == ["u3"], lost_calls)
finally:
    ownership.RENEW_EVERY_S = _real
    restore()

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the lease cannot stop the only running container.")
