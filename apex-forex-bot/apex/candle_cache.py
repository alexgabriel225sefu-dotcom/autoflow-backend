"""One candle fetch serves every account, because candles are public data.

THE PROBLEM THIS SOLVES

cTrader's Open API documentation states two things that together set a hard
ceiling on how many clients this product can carry:

    "At most, you should create two connections: one for demo accounts and one
     for live accounts. Each connection can support an unlimited number of
     accounts of a certain type."

    "5 requests per second for any historical data requests. These limits are
     per connection, no matter how many users are authorized through it."

Trendbars are historical data. Every user loop asked for its own copy of the
same bars: eight symbols in the autopilot universe, once per 300-second tick.

    (5 requests/second x 300 seconds) / 8 requests per user-tick = ~187 users

That is the ceiling, and it is external — no amount of Render capacity moves
it. Worse, it is silent: past that point cTrader starts refusing requests and
the bot sees "no candles" rather than "you are rate limited".

The waste is total. EURUSD M5 bars are identical for every account on the
planet; the only per-account part of the request is which socket it travels
down. Ten thousand clients asking ten thousand times for the same public
numbers is ten thousand requests where one would do.

WHAT THIS CHANGES

One fetch per (symbol, interval, count) serves every user holding that
combination, so the historical request rate stops scaling with customers and
becomes a function of the symbol universe alone:

    8 symbols / 60-second TTL = 0.13 requests/second, at ANY number of users

The remaining per-account calls — positions, orders, account state — are not
historical and fall under the 50/second budget, which is where the ceiling
should sit.

WHAT IS DELIBERATELY NOT CACHED

Live quotes. `get_price` returns the current bid/ask and the spread check
depends on it being current; a stale spread is how a trade gets taken in
conditions that should have refused it. Only trendbars pass through here.

WHY A SHORT TTL IS SAFE HERE, AND WHERE IT WOULD NOT BE

Orders are placed as MARKET, so the broker fills at the live price whatever
the candles said. A slightly old bar therefore moves the DECISION, never the
fill. On an M5 strategy with a 300-second loop, a bar up to 60 seconds old is
well inside the resolution the strategy already works at.

The TTL is capped at a quarter of the bar period regardless of configuration,
because "cache a 1-minute bar for 5 minutes" is a different and much worse
trade than "cache a 5-minute bar for 1 minute", and the ceiling should not
depend on somebody choosing the right number.

FAILURE BEHAVIOUR

A cache miss, an expired entry, or any error inside the cache falls through to
a real fetch. This layer can make the system slower; it must never make it
answer with something it did not fetch.
"""
import os
import threading
import time

__all__ = ["get", "invalidate", "stats", "reset"]

# Seconds a fetched window stays servable. Deliberately short: the point is to
# collapse thousands of simultaneous identical requests, not to serve old data.
_DEFAULT_TTL_S = 60

# A cached window is never older than a quarter of its own bar period, so an
# M1 caller gets at most 15 seconds of staleness however this is configured.
_MAX_TTL_FRACTION = 0.25

_PERIOD_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

# Bounded so a large symbol universe cannot grow this without limit.
_MAX_ENTRIES = 512

_lock = threading.Lock()
_entries: "dict[tuple, dict]" = {}      # key -> {"candles": [...], "at": float}
_inflight: "dict[tuple, threading.Event]" = {}
_stats = {"hits": 0, "misses": 0, "coalesced": 0, "errors": 0}


def _configured_ttl() -> int:
    raw = os.getenv("CANDLE_CACHE_TTL_S")
    if raw is None or str(raw).strip() == "":
        return _DEFAULT_TTL_S
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return _DEFAULT_TTL_S
    # Zero or negative disables caching rather than meaning "forever" — the
    # safe reading of a nonsense value for a control like this.
    return max(0, value)


def _ttl_for(interval) -> int:
    """The TTL this window may actually use, after the per-period cap."""
    ttl = _configured_ttl()
    if ttl <= 0:
        return 0
    period = _PERIOD_SECONDS.get(str(interval), 300)
    return int(min(ttl, period * _MAX_TTL_FRACTION))


def _key(instrument, interval, limit, to_ts):
    # to_ts is part of the key: a caller paging backwards through history is
    # asking a different question from one asking for "now", and serving the
    # first from the second's entry would silently return the wrong window.
    return (str(instrument or "").upper(), str(interval or ""), int(limit or 0),
            int(to_ts) if to_ts else 0)


def _prune(now):
    if len(_entries) <= _MAX_ENTRIES:
        return
    for k in sorted(_entries, key=lambda k: _entries[k]["at"])[: len(_entries) // 2]:
        _entries.pop(k, None)


def get(fetch, *, instrument, interval, limit=None, to_ts=None):
    """Cached trendbars. `fetch()` is called only on a miss.

    Historical paging (`to_ts` set) is never cached: those windows are asked
    for once while building a corpus and would fill the cache with entries
    nobody reads again.

    Concurrent callers for the same key coalesce onto one fetch. Without that,
    a thousand user loops waking at the same moment produce a thousand
    simultaneous misses — the exact request storm the cache exists to prevent.
    """
    if to_ts:
        return fetch()

    ttl = _ttl_for(interval)
    if ttl <= 0:
        return fetch()

    key = _key(instrument, interval, limit, to_ts)
    now = time.time()

    with _lock:
        entry = _entries.get(key)
        if entry and (now - entry["at"]) < ttl:
            _stats["hits"] += 1
            return list(entry["candles"])
        waiter = _inflight.get(key)
        if waiter is None:
            _inflight[key] = threading.Event()
            leader = True
        else:
            leader = False
            _stats["coalesced"] += 1

    if not leader:
        # Someone else is already asking. Wait briefly, then use whatever
        # landed — and if nothing did, fetch rather than return nothing.
        waiter.wait(timeout=20)
        with _lock:
            entry = _entries.get(key)
            if entry and (time.time() - entry["at"]) < ttl:
                return list(entry["candles"])
        return fetch()

    try:
        candles = fetch()
        if candles:
            with _lock:
                _entries[key] = {"candles": list(candles), "at": time.time()}
                _prune(time.time())
        with _lock:
            _stats["misses"] += 1
        return candles
    except Exception:
        with _lock:
            _stats["errors"] += 1
        # Never swallow: the caller decides what a failed fetch means.
        raise
    finally:
        with _lock:
            ev = _inflight.pop(key, None)
        if ev:
            ev.set()


def invalidate(instrument=None):
    """Drop cached windows. No argument drops everything."""
    with _lock:
        if instrument is None:
            _entries.clear()
            return
        want = str(instrument).upper()
        for k in [k for k in _entries if k[0] == want]:
            _entries.pop(k, None)


def stats():
    with _lock:
        out = dict(_stats)
        out["entries"] = len(_entries)
        total = out["hits"] + out["misses"]
        out["hit_rate"] = round(out["hits"] / total, 4) if total else 0.0
    return out


def reset():
    """For tests."""
    with _lock:
        _entries.clear()
        _inflight.clear()
        for k in _stats:
            _stats[k] = 0
