"""A live price that says how old it is, and costs the broker almost nothing.

WHY THIS EXISTS

The chart said "live" and polled every 5 seconds, but it drew candles served
through a shared cache of up to a minute, and the response carried no fetched-at
time. The newest bar could lag the market and the browser could not tell. A
chart that looks live and is not is the same defect this project keeps finding
elsewhere: a screen asserting a state it has not verified.

So the price is read on its own, from the broker's spot quote, and it carries
WHEN the broker produced it. The client decides what to show from that, not
from how recently it asked.

WHAT THESE TESTS WILL NOT ACCEPT

* A quote with no age, or an old one reported as fresh.
* A failed read cached, so the next poll cannot recover when the broker does.
* One client's quote served to another.
* A request for a symbol this platform does not trade opening a broker socket.
* A burst of polls becoming a burst of broker subscriptions.

Run: python3 tests/test_platform_quote.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-quote-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import broker_read as BR                  # noqa: E402
from apex.platform import ratelimit as RL                    # noqa: E402


class _Conn(dict):
    def __init__(self, ctid=501):
        super().__init__(ctid=ctid, mode="demo", accessToken="secret-token-xyz")


class _Broker:
    def __init__(self, bid=1.1000, ask=1.1002, age=0.0, error=None):
        self.bid, self.ask, self.age, self.error = bid, ask, age, error
        self.calls = []
        self.waits = []

    def get_quote(self, symbol, wait_s=8):
        self.calls.append(symbol)
        self.waits.append(wait_s)
        if self.error:
            raise RuntimeError(self.error)
        return self.bid, self.ask, time.time() - self.age


def pause_over():
    """Let the post-failure pause elapse, without sleeping through it."""
    for k, (_until, reason) in list(BR._quote_failures.items()):
        BR._quote_failures[k] = (0.0, reason)


def read(broker, *, user="user-1", ctid=501, symbol="EURUSD"):
    BR.reset_quote_cache()
    return _read_keep(broker, user=user, ctid=ctid, symbol=symbol)


def _read_keep(broker, *, user="user-1", ctid=501, symbol="EURUSD"):
    """Like read(), but does NOT clear the cache — for the caching tests."""
    return BR.quote(user, symbol=symbol, ctid=ctid,
                    connection_fn=lambda *a, **k: _Conn(ctid),
                    broker_fn=lambda: broker)


# ── 1. a fresh quote, with its age ──────────────────────────────────────────
print("\n[1] a fresh quote carries its price and how old it is")
r = read(_Broker(bid=1.1000, ask=1.1002))
check("status ok", r.get("status") == "ok", str(r))
check("bid and ask are the broker's",
      r.get("bid") == 1.1000 and r.get("ask") == 1.1002, str(r))
check("mid is derived, not invented", abs(r.get("mid") - 1.1001) < 1e-9, str(r.get("mid")))
check("it says WHEN the broker produced it", isinstance(r.get("receivedAt"), float), str(r))
check("and how old that is", 0 <= r.get("ageSec", -1) < 2, str(r.get("ageSec")))
check("a fresh quote is not stale", r.get("stale") is False, str(r))
check("it names the instrument", r.get("symbol") == "EURUSD", str(r))

# ── 2. an old quote is reported old, not hidden and not fresh ───────────────
print("\n[2] an old quote is marked stale rather than presented as live")
r = read(_Broker(age=60.0))
check("still answered, so the screen can show what it has",
      r.get("status") == "ok", str(r))
check("with its true age", 59 <= r.get("ageSec", 0) <= 62, str(r.get("ageSec")))
check("marked stale", r.get("stale") is True, str(r))

# ── 3. failures are honest and are not cached ───────────────────────────────
print("\n[3] a failed read is unavailable, and the next poll can recover")
BR.reset_quote_cache()
broken = _Broker(error="cTrader: no spot price for EURUSD")
r = _read_keep(broken)
check("unavailable, not an empty price", r.get("status") == "unavailable", str(r))
check("with a reason", "no spot price" in str(r.get("reason")), str(r))
check("and no price fields that look like data",
      "bid" not in r and "ask" not in r, str(r))
healed = _Broker(bid=1.2000, ask=1.2002)
pause_over()
r = _read_keep(healed)
check("once the short pause is over the next read succeeds (a failure is "
      "never kept as if it were a price)",
      r.get("status") == "ok" and r.get("bid") == 1.2000, str(r))

print("\n[3b] a broker that returns no usable price is unavailable too")
for bad in ((0, 0), (None, None), (1.1, 0), (-1.0, 1.0)):
    r = read(_Broker(bid=bad[0], ask=bad[1]))
    check(f"bid/ask {bad} is refused", r.get("status") == "unavailable", str(r))

# ── 4. polling does not become broker subscriptions ─────────────────────────
print("\n[4] polls inside the TTL cost the broker nothing")
BR.reset_quote_cache()
b = _Broker()
for _ in range(5):
    _read_keep(b)
check("five polls inside the TTL make ONE broker call", len(b.calls) == 1,
      f"{len(b.calls)} calls")
r = _read_keep(b)
check("and the cached answer still reports a live age", "ageSec" in r, str(r))

print("\n[4b] and it does refresh once the TTL has passed")
_real_ttl = BR.QUOTE_CACHE_TTL_S
BR.QUOTE_CACHE_TTL_S = 0.0
try:
    BR.reset_quote_cache()
    b = _Broker()
    _read_keep(b)
    _read_keep(b)
    check("with no TTL every read reaches the broker", len(b.calls) == 2,
          f"{len(b.calls)} calls")
finally:
    BR.QUOTE_CACHE_TTL_S = _real_ttl

# ── 5. one client's quote is never served to another ────────────────────────
print("\n[5] the cache is per client, per account, per instrument")
BR.reset_quote_cache()
a = _Broker(bid=1.0, ask=1.1)
c = _Broker(bid=2.0, ask=2.1)
_read_keep(a, user="user-1")
r = _read_keep(c, user="user-2")
check("another user does not get the first user's price",
      r.get("bid") == 2.0 and len(c.calls) == 1, str(r))
r = _read_keep(c, user="user-2", ctid=502)
check("another account of the same user is separate",
      len(c.calls) == 2, f"{len(c.calls)} calls")
r = _read_keep(c, user="user-2", symbol="GBPUSD")
check("another instrument is separate", len(c.calls) == 3,
      f"{len(c.calls)} calls")

# ── 6. a bad symbol costs no broker socket ──────────────────────────────────
print("\n[6] an instrument this platform does not trade is refused up front")
opened = []
for bad in ("", "BTCUSD", "EURGBP", "../etc"):
    try:
        BR.quote("user-1", symbol=bad, ctid=501,
                 connection_fn=lambda *a, **k: opened.append("conn") or _Conn(),
                 broker_fn=lambda: opened.append("broker") or _Broker())
        check(f"{bad!r} raises ValueError", False, "returned instead")
    except ValueError:
        check(f"{bad!r} raises ValueError", True)
check("and no connection or broker was opened for any of them",
      opened == [], str(opened))

# ── 7. no credential in an error ────────────────────────────────────────────
print("\n[7] an error never carries the access token")
r = read(_Broker(error="boom secret-token-xyz boom"))
check("the token is scrubbed from the reason",
      "secret-token-xyz" not in str(r), str(r))

# ── 8. the route is metered in its own bucket ───────────────────────────────
print("\n[8] the quote route has its own rate limit")
check("it is classified as 'quote'",
      RL.classify("GET", "accounts/501/quote?symbol=EURUSD") == "quote",
      RL.classify("GET", "accounts/501/quote?symbol=EURUSD"))
check("and not charged to the historical-budget bucket",
      RL.classify("GET", "accounts/501/quote") != "candles")
# A 3-second poll is 20 requests a minute per chart. The bucket must allow
# that with room for a second tab, and must still be a real limit.
_q = RL.LIMITERS.get("quote")
check("a quote bucket exists", _q is not None)
check("it allows a 3 s poll with room for a second tab (>= 40/min)",
      _q is not None and _q.limit >= 40, str(getattr(_q, "limit", None)))
check("and it is still a real limit, not unmetered (<= 240/min)",
      _q is not None and 0 < _q.limit <= 240, str(getattr(_q, "limit", None)))

# ── 9. the chart must not be able to hold the shared socket ─────────────────
print("\n[9] the price read waits briefly for a tick, not the loop's 8 seconds")
b = _Broker()
read(b)
check("the broker was asked with a short wait", b.waits and b.waits[0] <= 3,
      str(b.waits))
check("the wait is a real number, not unlimited", b.waits and b.waits[0] > 0,
      str(b.waits))

print("\n[10] after a failure the broker is left alone for a few seconds")
# A closed market means no tick, so every poll would otherwise spend its full
# wait holding the shared socket. A short pause after a failure caps that.
BR.reset_quote_cache()
down = _Broker(error="cTrader: no spot price for EURUSD")
first = _read_keep(down)
check("the first read fails honestly", first.get("status") == "unavailable", str(first))
again = _read_keep(down)
check("the second poll, moments later, does NOT reach the broker",
      len(down.calls) == 1, f"{len(down.calls)} calls")
check("and still answers unavailable, with the same reason",
      again.get("status") == "unavailable" and "no spot price" in str(again.get("reason")),
      str(again))
pause_over()
third = _read_keep(down)
check("once the pause is over it asks the broker again", len(down.calls) == 2,
      f"{len(down.calls)} calls")

print("\n[10b] a broker that has recovered is read again as soon as the pause ends")
BR.reset_quote_cache()
flaky = _Broker(error="cTrader: no spot price for EURUSD")
_read_keep(flaky)
flaky.error = None
pause_over()
r = _read_keep(flaky)
check("the recovered broker answers ok", r.get("status") == "ok", str(r))
r = _read_keep(flaky)
check("and the failure is gone: the next read is a price, not the old error",
      r.get("status") == "ok" and "reason" not in r, str(r))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All live-quote checks passed.")
