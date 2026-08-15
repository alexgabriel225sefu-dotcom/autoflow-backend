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

# The lease must outlive whatever the loop is doing between renewals, and the
# loop tick is FIVE MINUTES. The first version renewed from the top of the tick
# with a fixed 90s TTL, so the lease was dead for 210 of every 300 seconds; the
# next heartbeat then found the key gone, read that as "another instance took
# over", and shut the loop down. One container, no competition, and it stopped
# itself every tick — the alert clients saw as OWNERSHIP_LOST.
#
# Two changes make that impossible rather than unlikely:
#   * renewal runs on its own thread, so a slow tick or a blocking broker read
#     cannot delay it;
#   * the TTL is derived from the loop interval instead of guessed, so it
#     survives several missed renewals even if that thread stalls.
def _loop_interval_s():
    try:
        from apex import config as _cfg
        return max(30, int(getattr(_cfg, "LOOP_INTERVAL_MS", 300_000) / 1000))
    except Exception:
        return 300


TTL_S = max(180, _loop_interval_s() * 2)
RENEW_EVERY_S = max(15, TTL_S // 6)     # five misses before the lease lapses

# Stable for the life of the process. RENDER_INSTANCE_ID when Render provides
# it (it appears in the logs, which makes an incident traceable to a container);
# otherwise host+pid+random, which is unique enough for the same purpose.
INSTANCE_ID = (os.getenv("RENDER_INSTANCE_ID")
               or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}")

_lock = threading.Lock()
_held = {}                          # user_id -> last successful renew ts
_renewers = {}                      # user_id -> {"alive": bool}
_lost = set()                       # users a renewer confirmed we lost


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
            # Holding the lease again makes any previous loss history. Without
            # this the flag survived the restart that fixed it: the loop broke
            # on was_lost() without going through stop(), so nothing cleared
            # the set, and every watchdog restart re-alerted and re-broke on
            # the very first tick — an OWNERSHIP_LOST message every 180s from
            # a container that had just successfully taken the lease.
            _lost.discard(user_id)
        print(f"[Ownership] {INSTANCE_ID} acquired {user_id}")
        return True
    if got is False:
        # Re-entrancy: our OWN container may already hold it from a previous
        # loop generation that has not released yet. That is not a conflict.
        if str(user_store.get_blob(_key(user_id)) or "") == INSTANCE_ID:
            with _lock:
                _held[user_id] = time.time()
                _lost.discard(user_id)
            return True
        print(f"[Ownership] {user_id} is owned by another instance — standing down")
        return False
    return None                     # could not ask


def heartbeat(user_id):
    """Renew the lease. False ONLY when another instance genuinely holds it.

    An expired key and a stolen key are not the same event, and conflating them
    is what made a single uncontended container shut itself down: the renew
    script returns 0 both when somebody else owns the key and when the key is
    simply gone. A key that is GONE is unowned, so the right move is to take it
    again — standing down hands the user to nobody.
    """
    user_id = str(user_id)
    if not shared_backed():
        return None
    ok = user_store.renew_claim(_key(user_id), INSTANCE_ID, ttl_s=TTL_S)
    if ok is True:
        with _lock:
            _held[user_id] = time.time()
        return True
    if ok is None:
        return None                 # transport failure — unknown, not lost

    # renew said no. Find out which kind of no it was.
    cur = user_store.get_blob(_key(user_id))
    if cur is None:
        # Nobody holds it. Re-acquire rather than abandon the user.
        again = user_store.claim_value(_key(user_id), INSTANCE_ID, ttl_s=TTL_S)
        if again is True:
            with _lock:
                _held[user_id] = time.time()
            print(f"[Ownership] lease for {user_id} had lapsed — reacquired")
            return True
        if again is None:
            return None
        cur = user_store.get_blob(_key(user_id))    # somebody beat us to it
    if str(cur or "") == INSTANCE_ID:
        with _lock:
            _held[user_id] = time.time()
        return True
    with _lock:
        _held.pop(user_id, None)
    print(f"[Ownership] LOST lease for {user_id} — held by {cur!r}")
    return False


def due(user_id):
    """True when the lease should be renewed now. Cheap enough to call per tick."""
    with _lock:
        last = _held.get(str(user_id))
    return last is None or (time.time() - last) >= RENEW_EVERY_S


def start_renewer(user_id, on_lost=None):
    """Renew this user's lease on a thread of its own.

    Renewal must not be driven by the trading tick. The tick is five minutes
    long and can block far longer than that inside a broker read, so a lease
    renewed from the top of the tick is a lease that spends most of its life
    expired. This thread renews on wall-clock time regardless of what the loop
    is doing, and calls `on_lost` exactly once if the lease is genuinely taken.
    """
    user_id = str(user_id)
    if not shared_backed():
        return None
    with _lock:
        if _renewers.get(user_id, {}).get("alive"):
            return None
        _renewers[user_id] = {"alive": True}

    def _run():
        while True:
            time.sleep(RENEW_EVERY_S)
            with _lock:
                if not _renewers.get(user_id, {}).get("alive"):
                    return
            try:
                if heartbeat(user_id) is False:
                    with _lock:
                        _renewers.pop(user_id, None)
                    if on_lost:
                        try:
                            on_lost(user_id)
                        except Exception as e:
                            print(f"[Ownership] on_lost failed for {user_id}: {e}")
                    return
            except Exception as e:
                # Never let the renewer die on a transient error — that would
                # silently stop renewing and lose the lease by attrition.
                print(f"[Ownership] renewer error for {user_id}: {e}")

    threading.Thread(target=_run, daemon=True,
                     name=f"lease-{user_id}").start()
    return True


def stop_renewer(user_id):
    with _lock:
        _renewers.pop(str(user_id), None)
        _lost.discard(str(user_id))


def mark_lost(user_id):
    with _lock:
        _lost.add(str(user_id))


def was_lost(user_id):
    """True only after a renewer confirmed another instance holds the lease.

    Deliberately NOT a live read. The trading loop asks this once per tick, and
    a network round trip there would make the answer depend on Redis latency at
    exactly the moment the loop is deciding whether to keep managing open
    positions. The renewer already knows.
    """
    with _lock:
        return str(user_id) in _lost


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
