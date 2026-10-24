"""One candle fetch must serve every account, or the product has a hard ceiling.

cTrader's Open API documentation sets the constraint:

    "5 requests per second for any historical data requests. These limits are
     per connection, no matter how many users are authorized through it."

Trendbars are historical data. Every user loop fetched its own copy of the same
bars — eight symbols in the autopilot universe, once per 300-second tick:

    (5 requests/second x 300 seconds) / 8 per user-tick = ~187 concurrent users

That is an EXTERNAL ceiling. No amount of server capacity moves it, and past
it cTrader refuses requests while the bot sees "no candles" rather than "rate
limited". The waste is total: EURUSD M5 bars are identical for every account.

These checks prove the collapse actually happens, and that it did not buy that
by returning data the caller did not ask for.

Run: python tests/test_candle_cache.py
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-candlecache-")

from apex import candle_cache as cc  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


class Broker:
    """Counts real fetches, the way the rate limiter would."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def fetch(self, n=150, delay=0.0):
        with self._lock:
            self.calls += 1
        if delay:
            time.sleep(delay)
        return [{"time": 1787835732 + i * 300, "close": 1.168 + i * 1e-5}
                for i in range(n)]


print("\nCANDLE CACHE - one fetch serves every account\n")

print("1. The collapse")
cc.reset()
b = Broker()
UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
            "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
USERS = 500
for _ in range(USERS):
    for sym in UNIVERSE:
        cc.get(b.fetch, instrument=sym, interval="M5", limit=150)

wanted = len(UNIVERSE)
check(f"{USERS} users x {len(UNIVERSE)} symbols made {b.calls} real request(s), not "
      f"{USERS * len(UNIVERSE)}", b.calls == wanted, f"got {b.calls}")
s = cc.stats()
check("the hit rate reflects it", s["hit_rate"] > 0.99, str(s))

# The number that matters: historical requests per second, at scale.
LOOP_S = 300
for users in (187, 1000, 10000):
    before = b.calls
    per_tick_uncached = users * len(UNIVERSE)
    cached_rate = wanted / max(1, cc._ttl_for("M5"))
    uncached_rate = per_tick_uncached / LOOP_S
    print(f"       {users:>5} users: {uncached_rate:8.1f} req/s uncached -> "
          f"{cached_rate:.2f} req/s cached   (cTrader allows 5)")
check("10,000 users now fit inside the 5 req/s historical budget",
      (wanted / max(1, cc._ttl_for("M5"))) < 5.0)

print("\n2. It never serves a window the caller did not ask for")
cc.reset()
b = Broker()
a1 = cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
a2 = cc.get(b.fetch, instrument="EURUSD", interval="M15", limit=150)
a3 = cc.get(b.fetch, instrument="GBPUSD", interval="M5", limit=150)
a4 = cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=50)
check("a different interval is a different entry", b.calls >= 2)
check("a different symbol is a different entry", b.calls >= 3)
check("a different bar count is a different entry", b.calls == 4, f"{b.calls} fetches")

print("\n3. Historical paging is never cached")
# A caller walking backwards through history asks a different question each
# time; caching those fills the cache with windows nobody reads twice.
cc.reset()
b = Broker()
for i in range(5):
    cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150,
           to_ts=1787000000 - i * 45000)
check("five paged windows made five fetches", b.calls == 5, f"{b.calls}")
check("and nothing was cached", cc.stats()["entries"] == 0, str(cc.stats()))

print("\n4. Entries expire")
cc.reset()
b = Broker()
cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
check("the second call was served from cache", b.calls == 1, f"{b.calls}")
with cc._lock:
    for entry in cc._entries.values():
        entry["at"] -= 10_000            # age it well past any TTL
cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
check("an expired entry refetches", b.calls == 2, f"{b.calls}")

print("\n5. Staleness is bounded whatever the configuration says")
saved = os.environ.get("CANDLE_CACHE_TTL_S")
try:
    for raw, interval, ceiling in (("99999", "M1", 15),     # quarter of 60s
                                   ("99999", "M5", 75),     # quarter of 300s
                                   ("30", "M5", 30),
                                   ("abc", "M5", 60)):
        os.environ["CANDLE_CACHE_TTL_S"] = raw
        got = cc._ttl_for(interval)
        check(f"TTL_S={raw!r} on {interval} -> {got}s (<= {ceiling}s)", got <= ceiling,
              f"got {got}")
    # Zero disables rather than meaning "forever" — the safe reading.
    os.environ["CANDLE_CACHE_TTL_S"] = "0"
    cc.reset()
    b = Broker()
    cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
    cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
    check("TTL 0 disables the cache, it does not mean forever", b.calls == 2, f"{b.calls}")
    os.environ["CANDLE_CACHE_TTL_S"] = "-5"
    cc.reset()
    b = Broker()
    cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
    cc.get(b.fetch, instrument="EURUSD", interval="M5", limit=150)
    check("a negative TTL does the same", b.calls == 2, f"{b.calls}")
finally:
    if saved is None:
        os.environ.pop("CANDLE_CACHE_TTL_S", None)
    else:
        os.environ["CANDLE_CACHE_TTL_S"] = saved

print("\n6. A thundering herd collapses onto one fetch")
# A thousand loops waking together is the exact storm the cache exists for.
cc.reset()
b = Broker()
barrier = threading.Barrier(60)


def racer():
    barrier.wait()
    cc.get(lambda: b.fetch(delay=0.05), instrument="EURUSD",
           interval="M5", limit=150)


ts = [threading.Thread(target=racer) for _ in range(60)]
for t in ts:
    t.start()
for t in ts:
    t.join(timeout=30)
check(f"60 simultaneous callers made {b.calls} fetch(es), not 60", b.calls == 1,
      f"got {b.calls}")

print("\n7. A failing fetch is never hidden")
cc.reset()
calls = {"n": 0}


def broken():
    calls["n"] += 1
    raise RuntimeError("broker refused")


try:
    cc.get(broken, instrument="EURUSD", interval="M5", limit=150)
    check("the error reaches the caller", False, "it was swallowed")
except RuntimeError:
    check("the error reaches the caller", True)
check("and nothing was cached from a failure", cc.stats()["entries"] == 0)
# The failed key must not stay locked, or every later caller hangs on it.
try:
    cc.get(broken, instrument="EURUSD", interval="M5", limit=150)
except RuntimeError:
    pass
check("a failed key does not stay locked", calls["n"] == 2, f"{calls['n']} attempts")

print("\n8. The live quote is deliberately NOT cached")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "brokers", "ctrader.py"), encoding="utf-8").read()
price_fn = SRC.split("def get_price")[1].split("\n    def ")[0]
check("get_price does not go through the cache", "candle_cache" not in price_fn,
      "a stale spread is how a trade gets taken in conditions that should refuse it")
candles_fn = SRC.split("def get_candles")[1].split("\n    def ")[0]
check("get_candles does", "candle_cache.get(" in candles_fn)
check("the real fetch is still reachable for a miss",
      "_get_candles_uncached" in SRC)

print("\n9. The cache is bounded")
cc.reset()
b = Broker()
for i in range(cc._MAX_ENTRIES + 200):
    cc.get(b.fetch, instrument=f"SYM{i}", interval="M5", limit=150)
check(f"entries stay under the cap ({cc.stats()['entries']} <= {cc._MAX_ENTRIES})",
      cc.stats()["entries"] <= cc._MAX_ENTRIES, str(cc.stats()))

cc.reset()
print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL CANDLE-CACHE CHECKS PASSED - the historical ceiling is gone.")
