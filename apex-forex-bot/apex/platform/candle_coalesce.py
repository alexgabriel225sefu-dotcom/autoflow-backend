"""A short success cache and singleflight in front of the candles limiter.

The candles bucket allows 30 requests a minute per token, and it is counted
BEFORE the handler runs. A chart that polls every 15 seconds is inside that
budget. What spends it is the same query arriving again while the first is
still on the wire: a second tab, or a poll that overlapped a read the browser
had already aborted. Each of those is a fresh unit, and none of them is a
fresher bar.

This layer sits in front of that count.

  * A successful answer is remembered for a few seconds and served again
    without touching the limiter.
  * An identical query that arrives while that read is in flight shares the
    one flight, and the flight spends one unit.
  * A failure is never remembered. The next attempt is a real request and is
    limited like any other.
  * A different account, symbol, timeframe, limit or caller is a different
    query. It does not share the entry, and it spends its own unit.

Anonymous callers are not coalesced. They have no token to key on, and the
limiter is the only thing counting them.
"""

import copy
import hashlib
import re
import threading
import time
from urllib.parse import parse_qs

_PREFIX = "/api/v1/"
_ROUTE = re.compile(r"^accounts/([A-Za-z0-9_-]{1,64})/candles$")

# Shorter than the broker's own bar cache (60s). Long enough that a second
# tab, or a poll that overlapped an aborted read, reuses the answer. Shorter
# than the chart's 15s poll, so the next poll still asks and is still limited.
TTL_S = 10

# A flight that never finishes must not pin every waiter. The chart can read
# the refusal; the entry is not cached.
_WAIT_S = 20

_MAX_ENTRIES = 64

_lock = threading.Lock()
_cache: dict = {}
_flights: dict = {}


def _now():
    return time.monotonic()


def reset():
    """Drop remembered answers. In-flight reads are left to finish."""
    with _lock:
        _cache.clear()


def _token(headers):
    raw = ""
    if headers:
        raw = headers.get("Authorization") or headers.get("authorization") or ""
    parts = str(raw).split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        digest = hashlib.sha256(parts[1].strip().encode()).hexdigest()
        return digest[:24]
    return None


def key_for(method, path, headers):
    """The identity of one candle query, or None when this layer does not apply."""
    if (method or "GET").upper() != "GET":
        return None
    path = path or ""
    if not path.startswith(_PREFIX):
        return None
    rest = path[len(_PREFIX):]
    route, _, query = rest.partition("?")
    match = _ROUTE.match(route.strip("/"))
    if match is None:
        return None
    token = _token(headers)
    if token is None:
        return None
    parsed = parse_qs(query, keep_blank_values=True)
    symbol = (parsed.get("symbol") or [""])[0].strip().upper()
    timeframe = (parsed.get("timeframe") or [""])[0].strip().lower()
    limit = (parsed.get("limit") or [""])[0].strip()
    return (token, match.group(1), symbol, timeframe, limit)


def _snapshot(result):
    if (isinstance(result, tuple) and len(result) == 2
            and isinstance(result[1], dict)):
        return result[0], copy.deepcopy(result[1])
    return result


def is_success(result):
    """A candle read that actually answered. Refusals and broker failures are not."""
    if not isinstance(result, tuple) or len(result) != 2:
        return False
    status, body = result
    if status != 200 or not isinstance(body, dict) or body.get("ok") is not True:
        return False
    if body.get("status") != "ok":
        return False
    return isinstance(body.get("candles"), list)


def _lookup(key):
    item = _cache.get(key)
    if item is None:
        return None
    expires, snap = item
    if expires <= _now():
        _cache.pop(key, None)
        return None
    return _snapshot(snap)


def _store(key, snap):
    _cache[key] = (_now() + TTL_S, snap)
    if len(_cache) <= _MAX_ENTRIES:
        return
    now = _now()
    for old in [k for k, (exp, _) in _cache.items() if exp <= now]:
        _cache.pop(old, None)
    while len(_cache) > _MAX_ENTRIES:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest, None)


class _Flight:
    def __init__(self, key):
        self.key = key
        self.event = threading.Event()
        self.outcome = None
        self.exc = None

    def ok(self, result):
        snap = _snapshot(result)
        with _lock:
            if is_success(result):
                _store(self.key, snap)
            self.outcome = snap
            if _flights.get(self.key) is self:
                del _flights[self.key]
            self.event.set()

    def fail(self, exc):
        with _lock:
            self.exc = exc
            if _flights.get(self.key) is self:
                del _flights[self.key]
            self.event.set()

    def wait(self):
        if not self.event.wait(_WAIT_S):
            return 503, {"ok": False, "error": {
                "code": "UNAVAILABLE",
                "message": "the candle read did not finish in time",
            }}
        if self.exc is not None:
            raise self.exc
        return _snapshot(self.outcome)


def coalesce(method, path, headers, run):
    """Run `run` once per identical in-flight candle query.

    A fresh success is served from the short cache and `run` is not called,
    so the rate limiter is not asked. Anything that is not a candle read, and
    any failure, goes through `run`.
    """
    key = key_for(method, path, headers)
    if key is None:
        return run()
    with _lock:
        hit = _lookup(key)
        if hit is not None:
            return hit
        flight = _flights.get(key)
        if flight is None:
            flight = _Flight(key)
            _flights[key] = flight
            leader = True
        else:
            leader = False
    if not leader:
        return flight.wait()
    try:
        result = run()
    except BaseException as exc:
        flight.fail(exc)
        raise
    flight.ok(result)
    return result
