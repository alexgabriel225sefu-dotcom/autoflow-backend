"""One live worker per user, across containers — not just across threads.

The loop already carries a generation token, and that token is real: it stops
a stop()+start() restart from leaving two threads trading one account inside
ONE process. What it cannot do is see another container, and this service runs
more than one during every deploy. From the logs that motivated the order
ledger: instance 6n5hh was still running tick 101 at 18:21:07 while vvlq4 had
already started its loop at 18:21:00 — both driving the same cTrader account.

The order ledger catches the narrow case where both instances compute the SAME
intent. It cannot catch the wide one, where they diverge: A trails a stop while
B closes at market, A adopts a position B just exited, both count the same fill
against max-trades-a-day. Those need an owner, not a de-duplicator.

So: a per-user lease.

    acquire   SET NX EX — atomic, so exactly one container can win
    heartbeat renewed at a third of the TTL, from the loop's own tick
    revalidate checked again immediately before anything that moves money
    release   dropped on stop(), so a redeploy hands over in seconds

FAIL POLICY, stated plainly because it differs by consequence:

  * No shared backend at all (single-instance dev, Upstash unset) — allowed.
    A lease nobody else can contend for is not a safety property, and refusing
    would mean the bot cannot trade without Redis configured.
  * Backend configured but unreachable — the caller decides. `holds()` returns
    None for "could not ask", and the trading path treats unknown ownership as
    not-owned for LIVE accounts (fail closed, per the audit's P0-04) while
    letting demo accounts continue. A Redis outage must not be able to open a
    real-money position that a second container is also managing.
  * Lease genuinely lost — stop touching the account. Something else owns it.

The instance id is deliberately per-PROCESS, not per-user: two loops in one
container are the same owner, which is exactly what the generation token is
there to arbitrate.
"""
import os
import socket
import threading
import time
import uuid

from apex import user_store

# Long enough to ride out a slow tick and a GC pause, short enough that a
# container killed mid-deploy frees its users well inside a minute.
TTL_S = 90
RENEW_EVERY_S = TTL_S // 3          # renew at a third — two misses before loss

# Stable for the life of the process. RENDER_INSTANCE_ID when Render provides
# it (it appears in the logs, which makes an incident traceable to a container);
# otherwise host+pid+random, which is unique enough for the same purpose.
INSTANCE_ID = (os.getenv("RENDER_INSTANCE_ID")
               or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}")

_lock = threading.Lock()
_held = {}                          # user_id -> last successful renew ts


def _key(user_id):
    return f"own:user:{user_id}"


def shared_backed():
    """True when leases are visible to other containers. False means the lease
    is decorative — worth surfacing rather than assuming it protects anything."""
    return bool(getattr(user_store, "_USE_REDIS", False))


def acquire(user_id):
    """Take ownership of this user. True = ours, False = someone else's,
    None = no shared backend (uncontended, so treated as ours by callers)."""
    user_id = str(user_id)
    if not shared_backed():
        return None
    got = user_store.claim_value(_key(user_id), INSTANCE_ID, ttl_s=TTL_S)
    if got is True:
        with _lock:
            _held[user_id] = time.time()
        print(f"[Ownership] {INSTANCE_ID} acquired {user_id}")
        return True
    if got is False:
        # Re-entrancy: our OWN container may already hold it from a previous
        # loop generation that has not released yet. That is not a conflict.
        if str(user_store.get_blob(_key(user_id)) or "") == INSTANCE_ID:
            with _lock:
                _held[user_id] = time.time()
            return True
        print(f"[Ownership] {user_id} is owned by another instance — standing down")
        return False
    return None                     # could not ask


def heartbeat(user_id):
    """Renew the lease. False means it is gone and the caller must stand down."""
    user_id = str(user_id)
    if not shared_backed():
        return None
    ok = user_store.renew_claim(_key(user_id), INSTANCE_ID, ttl_s=TTL_S)
    if ok is True:
        with _lock:
            _held[user_id] = time.time()
        return True
    if ok is False:
        with _lock:
            _held.pop(user_id, None)
        print(f"[Ownership] LOST lease for {user_id} — another instance has it")
        return False
    return None                     # transport failure — unknown, not lost


def due(user_id):
    """True when the lease should be renewed now. Cheap enough to call per tick."""
    with _lock:
        last = _held.get(str(user_id))
    return last is None or (time.time() - last) >= RENEW_EVERY_S


def holds(user_id):
    """Do we own this user right now?

    True / False / None(unknown). Uses the local record when the lease was
    renewed recently, so the money path does not add a network hop to every
    order; falls through to a real read once the record is stale.
    """
    user_id = str(user_id)
    if not shared_backed():
        return None
    with _lock:
        last = _held.get(user_id)
    if last is not None and (time.time() - last) < RENEW_EVERY_S:
        return True
    cur = user_store.get_blob(_key(user_id))
    if cur is None:
        return None                 # unreadable OR expired — caller decides
    return str(cur) == INSTANCE_ID


def may_trade(user_id, live):
    """Ownership verdict for a path that is about to move money.

    Returns (ok, reason). `live` is what makes unknown ownership fatal: on a
    real-money account an unreadable lease could mean a second container is
    managing the same positions, so it fails CLOSED. A demo account continues,
    because halting a simulation on a Redis hiccup is the denial of service
    the audit's fail-closed rule is not asking for.
    """
    if not shared_backed():
        return True, "UNCONTENDED"
    v = holds(user_id)
    if v is True:
        return True, "OWNER"
    if v is False:
        return False, "NOT_OWNER"
    if live:
        return False, "OWNERSHIP_UNKNOWN"
    return True, "OWNERSHIP_UNKNOWN_DEMO"


def release(user_id):
    """Give the lease up so a replacement can start without waiting out the TTL."""
    user_id = str(user_id)
    with _lock:
        _held.pop(user_id, None)
    if not shared_backed():
        return None
    return user_store.release_claim(_key(user_id), INSTANCE_ID)
