"""A deploy hands every loop to the new container in seconds, never to two.

WHAT HAPPENED (26 Nov 2026, every deploy): the incoming container's supervisor
asked for each loop once at boot, while the retiring container still held the
lease, was refused ("owned by another instance - standing down", "REFUSED
start", "Automation not reviving ... ENGINE_REFUSED"), and then slept a whole
supervisor interval (about 180s). The retiring container released its leases on
SIGTERM within seconds, so every client was unattended for about three minutes
after the old container had already let go.

THE FIX AND ITS LIMIT

While a loop waits behind another instance, `platform_server._supervise_wait`
reads that lease every few seconds (one GET) and, once the store confirms it is
gone and has stayed gone for a settle period, retries just that user. The
atomic SET NX claim in `ownership.acquire` is untouched and is still the only
thing that grants ownership: the retry changes WHEN a loop is asked for, never
WHETHER an owner is allowed. Two instances never run one user's loop.

Two real `ownership` modules (two instance ids) share one fake store that
expires keys on a fake clock. Real: `ownership`, `user_loop.start`,
`automation.supervise`, `platform_server._supervise_wait`. Substituted: the
store, the loop thread body, the clock, and `automation.start`'s preflight (as
in tests/test_supervisor_revive_stale_lease.py).

Run: python3 tests/test_deploy_handoff.py
"""
import importlib.util
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-handoff-")
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


from apex import user_loop, user_store                       # noqa: E402
from apex.platform import automation as AUTO                 # noqa: E402
from apex.platform import ctrader_link as CTL                # noqa: E402
import platform_server as PS                                 # noqa: E402


def load_instance(instance_id):
    """A second copy of apex.ownership with its own instance id and state."""
    os.environ["RENDER_INSTANCE_ID"] = instance_id
    spec = importlib.util.spec_from_file_location(
        f"ownership_{instance_id}", os.path.join(ROOT, "apex", "ownership.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.start_renewer = lambda uid, on_lost=None: None      # no real threads
    return mod


A = load_instance("instance-OLD")
B = load_instance("instance-NEW")
os.environ.pop("RENDER_INSTANCE_ID", None)

UID = "dddddddd-7777-4777-8777-dddddddddddd"
KEY = f"own:user:{UID}"


class Store:
    """One Redis, with TTLs on a fake clock and an outage switch."""

    def __init__(self):
        self.now = 1000.0
        self.kv = {}                     # key -> (value, expires_at)
        self.down = False
        self.lock = threading.Lock()
        self.wrong_grants = 0            # a claim that won over a live holder

    def _live(self, k):
        item = self.kv.get(k)
        if item and item[1] <= self.now:
            del self.kv[k]
            item = None
        return item

    def claim_value(self, k, v, ttl_s=120):
        if self.down:
            return None
        with self.lock:
            if self._live(k):
                return False
            self.kv[k] = (str(v), self.now + ttl_s)
            return True

    def renew_claim(self, k, v, ttl_s=120):
        if self.down:
            return None
        with self.lock:
            item = self._live(k)
            if item and item[0] == str(v):
                self.kv[k] = (str(v), self.now + ttl_s)
                return True
            return False

    def release_claim(self, k, v):
        if self.down:
            return None
        with self.lock:
            item = self._live(k)
            if item and item[0] == str(v):
                del self.kv[k]
                return True
            return False

    def get_blob(self, k):
        if self.down:
            return None                  # the lenient read: unreadable looks empty
        with self.lock:
            item = self._live(k)
            return item[0] if item else None

    def get_blob_strict(self, k):
        if self.down:
            raise user_store.StoreUnavailable("fake outage")
        return self.get_blob(k)

    def holder(self):
        with self.lock:
            item = self._live(KEY)
            return item[0] if item else None


S = Store()
users = {UID: {"active": True}}
_names = ("claim_value", "renew_claim", "release_claim", "get_blob",
          "get_blob_strict", "load", "update", "all_active", "_USE_REDIS")
_orig_us = {n: getattr(user_store, n) for n in _names}
_orig = {
    "start": AUTO.start, "_read": AUTO._read,
    "_licence_active": AUTO._licence_active,
    "is_platform_account": CTL.is_platform_account,
    "_loop": user_loop._loop, "_entitled": user_loop._entitled,
    "_alert_fn_for": user_loop._alert_fn_for,
    "ownership": user_loop.ownership,
}


def clean():
    S.kv.clear()
    S.down = False
    S.wrong_grants = 0
    with user_loop._lock:
        user_loop._loops.clear()
    for m in (A, B):
        m._held.clear()
        m._renewers.clear()
        m._lost.clear()
        m._shutdown.clear()
    AUTO._handoff_waiting.clear()


class Clock:
    """A fake clock whose sleep also moves the store's clock and runs events."""

    def __init__(self):
        self.t = 0.0
        self.events = []                 # (at, fn)
        self.sleeps = []
        self.on_tick = None

    def monotonic(self):
        return self.t

    def sleep(self, secs):
        self.sleeps.append(secs)
        target = self.t + secs
        for at, fn in sorted(self.events, key=lambda e: e[0]):
            if at <= target and (at, fn) in self.events:
                self.events.remove((at, fn))
                S.now += max(0.0, at - self.t)
                self.t = max(self.t, at)
                fn()
        S.now += max(0.0, target - self.t)
        self.t = target
        if self.on_tick:
            self.on_tick()


try:
    user_store._USE_REDIS = True
    for n in ("claim_value", "renew_claim", "release_claim", "get_blob", "get_blob_strict"):
        setattr(user_store, n, getattr(S, n))
    user_store.load = lambda uid: dict(users.get(str(uid), {}))
    user_store.update = lambda uid, patch, **k: users.setdefault(str(uid), {}).update(patch) or True
    user_store.all_active = lambda: [UID]
    CTL.is_platform_account = lambda uid: True
    AUTO._read = lambda uid: {"state": AUTO.RUNNING, "ruleDocId": "rule-1"}
    AUTO._licence_active = lambda uid: True
    user_loop._loop = lambda *a, **k: None
    user_loop._entitled = lambda uid: True
    user_loop._alert_fn_for = lambda uid, fn: None
    starts = []

    def shim(uid, rule_id, *, starter=None, mode_lister=None, revive=False):
        starts.append((uid, revive))
        if user_loop.start(uid) is False:
            raise AUTO.AutomationRefused(
                "ENGINE_REFUSED", "the trading engine refused to start this "
                "loop (another instance already owns this loop)")
        return {"started": True}

    AUTO.start = shim

    # ── 1. the retiring container releases on SIGTERM; the new one takes over fast
    print("\n[1] the new container takes the loop seconds after the old one lets go")
    clean()
    starts.clear()
    check("the old instance owns the loop", A.acquire(UID) is True and S.holder() == A.INSTANCE_ID)
    user_loop.ownership = B                       # this process is the NEW container
    alive, revived = AUTO.supervise()
    check("boot-time revival is refused behind the old owner", revived == 0 and not user_loop.is_running(UID))
    check("the refusal is recorded as a handoff wait", AUTO.handoff_waiting() == [UID],
          str(AUTO.handoff_waiting()))
    check("the old instance's lease was not touched", S.holder() == A.INSTANCE_ID)

    clk = Clock()
    RELEASE_AT = 12.0
    released = {}
    clk.events.append((RELEASE_AT, lambda: released.setdefault("n", A.begin_shutdown())))
    owners = []

    def watch():
        # At every step: the store has one holder, and a running loop here means
        # that holder is this container.
        owners.append((clk.t, S.holder(), user_loop.is_running(UID)))
        if user_loop.is_running(UID):
            check_once(S.holder() == B.INSTANCE_ID, "a loop runs here only while this container holds the lease")

    _bad = []

    def check_once(cond, name):
        if not cond:
            _bad.append(name)

    clk.on_tick = watch
    taken_at = {}
    real_supervise = AUTO.supervise

    def spy_supervise(**kw):
        out = real_supervise(**kw)
        if user_loop.is_running(UID):
            taken_at.setdefault("t", clk.t)
        return out

    AUTO.supervise = spy_supervise
    try:
        PS._supervise_wait(180, auto=AUTO, own=B, clock=clk.monotonic, sleep=clk.sleep,
                           poll_s=3, settle_s=5)
    finally:
        AUTO.supervise = real_supervise
    check("the old instance released its lease", released.get("n") == 1, str(released))
    check("the loop is running here now", user_loop.is_running(UID))
    check("the new container holds the lease", S.holder() == B.INSTANCE_ID, str(S.holder()))
    gap = taken_at.get("t", 999) - RELEASE_AT
    check(f"the gap after the release is the poll plus the settle, not 180s ({gap:g}s)",
          0 <= gap <= 3 + 5 + 3, str(gap))
    check("no moment had a loop here while another container held the lease", _bad == [], str(_bad))
    check("it waited out the interval only once the work was done", sum(clk.sleeps) <= 180 + 1e-6)
    check("nothing is waiting any more", AUTO.handoff_waiting() == [])

    print("\n[1b] the retired instance cannot take it back")
    check("it will not acquire", A.acquire(UID) is False)
    check("it will not renew or re-take", A.heartbeat(UID) is None)
    check("it will not place an order", A.may_trade(UID, live=False) == (False, "SHUTTING_DOWN"))
    check("the lease is still the new container's", S.holder() == B.INSTANCE_ID)

    # ── 2. the old container was killed and never released ─────────────────
    print("\n[2] an old container killed without releasing: no early takeover, then takeover at expiry")
    clean()
    starts.clear()
    A.acquire(UID)
    ttl_end = S.now + A.TTL_S
    user_loop.ownership = B
    AUTO.supervise()
    clk = Clock()
    attempts = []
    AUTO.supervise = lambda **kw: (attempts.append((clk.t, S.holder())), real_supervise(**kw))[1]
    clk.on_tick = lambda: check_once(
        not user_loop.is_running(UID) or S.now >= ttl_end, "started before the lease expired")
    _bad.clear()
    try:
        PS._supervise_wait(int(A.TTL_S + 120), auto=AUTO, own=B, clock=clk.monotonic,
                           sleep=clk.sleep, poll_s=3, settle_s=5)
    finally:
        AUTO.supervise = real_supervise
    check("no retry ran while the dead container's lease was live",
          all(h is None for _, h in attempts), str(attempts))
    check("it took over once the lease expired", user_loop.is_running(UID)
          and S.holder() == B.INSTANCE_ID)
    check("never before the expiry", _bad == [], str(_bad))
    check("after the TTL by the settle and poll at most",
          attempts and attempts[0][0] <= A.TTL_S + 3 + 5 + 3, str(attempts))

    # ── 3. the store is unreachable at the moment of the handoff ───────────
    print("\n[3] an unreachable store is not read as a free lease")
    clean()
    starts.clear()
    A.acquire(UID)
    user_loop.ownership = B
    AUTO.supervise()
    check("lease_state says unknown, not free, when the store is down",
          (setattr(S, "down", True), B.lease_state(UID))[1] == B.LEASE_UNKNOWN)
    check("and other when a live holder is read",
          (setattr(S, "down", False), B.lease_state(UID))[1] == B.LEASE_OTHER)
    A.begin_shutdown()
    clk = Clock()
    clk.events.append((2.0, lambda: setattr(S, "down", True)))     # outage after the release
    clk.events.append((40.0, lambda: setattr(S, "down", False)))   # and it comes back
    calls = []
    AUTO.supervise = lambda **kw: (calls.append((clk.t, S.down)), real_supervise(**kw))[1]
    try:
        PS._supervise_wait(120, auto=AUTO, own=B, clock=clk.monotonic, sleep=clk.sleep,
                           poll_s=3, settle_s=5)
    finally:
        AUTO.supervise = real_supervise
    check("no retry during the outage", all(not down for _, down in calls), str(calls))
    check("it took over once the store answered again", user_loop.is_running(UID)
          and S.holder() == B.INSTANCE_ID)

    # ── 4. a lease that comes back during the settle is not contested ──────
    print("\n[4] a lease taken by a third party during the settle is left alone")
    clean()
    starts.clear()
    A.acquire(UID)
    user_loop.ownership = B
    AUTO.supervise()
    A.begin_shutdown()
    clk = Clock()
    clk.events.append((4.0, lambda: S.claim_value(KEY, "instance-THIRD", ttl_s=1000)))
    calls = []
    AUTO.supervise = lambda **kw: (calls.append(kw), real_supervise(**kw))[1]
    try:
        PS._supervise_wait(60, auto=AUTO, own=B, clock=clk.monotonic, sleep=clk.sleep,
                           poll_s=3, settle_s=5)
    finally:
        AUTO.supervise = real_supervise
    check("no retry ran against the third party's lease", calls == [], str(calls))
    check("it is not running here", not user_loop.is_running(UID))
    check("the third party still holds it", S.holder() == "instance-THIRD")

    # ── 5. exactly one winner under contention ─────────────────────────────
    print("\n[5] two containers racing for one loop: exactly one wins, every time")
    wins = []
    for rnd in range(200):
        clean()
        res = {}
        gate = threading.Barrier(2)

        def go(name, mod):
            gate.wait()
            res[name] = mod.acquire(UID)

        ts = [threading.Thread(target=go, args=("a", A)), threading.Thread(target=go, args=("b", B))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        wins.append(sorted(k for k, v in res.items() if v is True))
    check("one winner in every round", all(len(w) == 1 for w in wins),
          str([w for w in wins if len(w) != 1][:3]))
    check("the fast retry does not change that: the claim is the authority",
          "claim_value(_key(user_id), INSTANCE_ID" in open(
              os.path.join(ROOT, "apex", "ownership.py"), encoding="utf-8").read())

    # ── 6. clock skew ──────────────────────────────────────────────────────
    print("\n[6] a skewed local clock cannot create a second owner")
    clean()
    A.acquire(UID)
    import time as _time
    real_time = _time.time
    _time.time = lambda: real_time() + 86400 * 3        # this container's clock runs 3 days ahead
    try:
        check("it cannot acquire a live lease", B.acquire(UID) is False)
        check("a live order is refused: the lease is read, not inferred from time",
              B.may_trade(UID, live=True) == (False, "NOT_OWNER"))
        check("the store, not any local clock, still names the old holder", S.holder() == A.INSTANCE_ID)
    finally:
        _time.time = real_time

    # ── 7. the wait is a plain sleep when nothing is waiting ───────────────
    print("\n[7] nothing waiting: one plain sleep, no polling")
    clean()
    clk = Clock()
    PS._supervise_wait(180, auto=AUTO, own=B, clock=clk.monotonic, sleep=clk.sleep,
                       poll_s=3, settle_s=5)
    check("a single sleep of the whole interval", clk.sleeps == [180], str(clk.sleeps))

    print("\n[8] the fast path is wired in, and what it may not do")
    src = open(os.path.join(ROOT, "platform_server.py"), encoding="utf-8").read()
    body = src.split("def _supervise_platform_loops(")[1]
    check("the supervisor loop uses the handoff-aware wait",
          "_supervise_wait(_SUPERVISE_INTERVAL_S" in body and "time.sleep(_SUPERVISE_INTERVAL_S)" not in body)
    wait_src = src.split("def _supervise_wait(")[1].split("\ndef ")[0]
    check("it never starts a loop itself", "user_loop" not in wait_src and "acquire" not in wait_src)
    check("it only trusts a lease the store confirmed free or ours",
          "LEASE_FREE" in wait_src and "LEASE_OURS" in wait_src and "LEASE_UNKNOWN" not in wait_src)
    check("a revival goes through automation.supervise, so the preflight still runs",
          "auto.supervise(only=free)" in wait_src)
finally:
    AUTO.start = _orig["start"]
    AUTO._read = _orig["_read"]
    AUTO._licence_active = _orig["_licence_active"]
    CTL.is_platform_account = _orig["is_platform_account"]
    user_loop._loop = _orig["_loop"]
    user_loop._entitled = _orig["_entitled"]
    user_loop._alert_fn_for = _orig["_alert_fn_for"]
    user_loop.ownership = _orig["ownership"]
    for n, f in _orig_us.items():
        setattr(user_store, n, f)
    with user_loop._lock:
        user_loop._loops.clear()

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All deploy-handoff checks passed.")
