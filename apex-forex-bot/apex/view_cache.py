"""Short-lived read cache for one process's broker socket.

Every cTrader read in this process shares one connection. A poll that asks
for the same positions and balance on every tick queues behind itself. These
caches exist so a repeat read inside the TTL does not take another trip.

The TTLs match how fast the underlying thing changes:

  tick        1s   a price moves tick to tick
  positions   6s   the list changes when a trade opens or closes
  balance    15s   it moves when a position closes

Per user, in memory, not in Redis. Two instances during a deploy each have
their own socket, so each keeps its own cache. `invalidate` drops a user's
entries when a position opens or closes, which is the only event that makes
a cached list wrong before its TTL.
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
    return _get(_tick, user_id, TICK_TTL_S)


def put_tick(user_id, payload):
    return _put(_tick, user_id, payload)


def get_positions(user_id):
    """None means ask the broker. An empty list is a real flat account."""
    return _get(_positions, user_id, POSITIONS_TTL_S)


def put_positions(user_id, positions):
    return _put(_positions, user_id, list(positions or []))


def get_balance(user_id):
    return _get(_balance, user_id, BALANCE_TTL_S)


def put_balance(user_id, balance):
    return _put(_balance, user_id, balance)


def invalidate(user_id):
    """Drop one user's cached reads after a position opens or closes."""
    uid = str(user_id)
    with _lock:
        for store in (_tick, _positions, _balance):
            store.pop(uid, None)
