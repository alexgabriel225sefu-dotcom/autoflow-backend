"""Short-lived caches so the terminal cannot saturate the broker socket.

WHY THIS EXISTS, precisely. Every cTrader read in this process rides ONE pooled
socket per account, and `_Conn._request` holds a lock across the round-trip. So
concurrent reads do not go in parallel — they queue. A 1-second tick that asked
for bid/ask, the position list, a price per position and the balance was seven
serialised round-trips per second on one socket, and `/api/app/data` (candles,
positions, balance again) queued behind all of it. Observed live: `[cTrader]
balance` in the log every 2-3 seconds, and the Mini App showing "Reconnecting…
market data unavailable" on a bot that was perfectly healthy.

Polling faster does not make a shared serialised resource answer faster. It
makes it answer slower. These caches exist so a faster poll costs nothing.

THE TTLs ARE NOT ARBITRARY — each matches how fast the underlying thing really
changes:

  price      ~1s   genuinely moves tick to tick; this is what should be fresh
  positions   6s   WHICH positions exist changes when a trade opens or closes,
                   not between two polls a second apart
  balance    15s   only moves when a position CLOSES. Floating P&L is what
                   moves continuously, and that is computed from price, not
                   from a balance read

A stale price would be a lie; a 6-second-old position LIST is the same list.

Per user, in-process, and deliberately not in Redis: this is a read cache for
one process's own broker traffic, not shared state. Two instances during a
deploy each keeping their own is correct — they each have their own socket.
"""
import threading
import time

TICK_TTL_S = 1.0
POSITIONS_TTL_S = 6.0
BALANCE_TTL_S = 15.0

_lock = threading.Lock()
_tick: dict = {}
_positions: dict = {}
_balance: dict = {}


def _get(store, key, ttl):
    with _lock:
        hit = store.get(str(key))
    if not hit:
        return None
    value, at = hit
    return value if (time.time() - at) < ttl else None


def _put(store, key, value):
    with _lock:
        store[str(key)] = (value, time.time())
    return value


def get_tick(user_id):
    """The whole tick payload, if one was built within TICK_TTL_S."""
    return _get(_tick, user_id, TICK_TTL_S)


def put_tick(user_id, payload):
    return _put(_tick, user_id, payload)


def get_positions(user_id):
    """None means "ask the broker" — an empty list is a real answer (flat)."""
    return _get(_positions, user_id, POSITIONS_TTL_S)


def put_positions(user_id, positions):
    return _put(_positions, user_id, list(positions or []))


def get_balance(user_id):
    return _get(_balance, user_id, BALANCE_TTL_S)


def put_balance(user_id, balance):
    return _put(_balance, user_id, balance)


def invalidate(user_id):
    """Drop everything for one user.

    Called when something happened that makes the cached answer wrong before
    its TTL — a position opened or closed. Without this, a client could watch a
    trade close and still see it listed for six more seconds, which is exactly
    the kind of staleness a terminal must not have.
    """
    uid = str(user_id)
    with _lock:
        for store in (_tick, _positions, _balance):
            store.pop(uid, None)
