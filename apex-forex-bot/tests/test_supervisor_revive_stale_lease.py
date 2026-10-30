"""The supervisor revives a loop after a stale lease, and not before.

SCENARIO (the 22/23 Oct deploys). The old container died or was recycled and
its lease on the account is still in the store. The new container's supervisor
sees an automation record that says RUNNING and no loop in memory.

  * while the stale lease is held by someone else the revival is REFUSED (the
    engine will not start a second owner), is not counted as revived, and
    leaves no half-started loop or renewer behind;
  * once the lease lapses (TTL) the next cycle revives the loop and the lease
    becomes ours;
  * a healthy loop is not touched on later cycles;
  * a stale lease that carries OUR instance id (our own previous generation)
    is re-entrant, not a conflict.

Real: `automation.supervise`, `user_loop.start`, `user_loop.is_running`,
`ownership.*`. Substituted: the shared store, the `_loop` thread body (a
no-op), the entitlement check, and `automation.start` (the preflight needs a
rule, a licence and a broker; it is replaced by a shim that calls the real
engine starter and raises ENGINE_REFUSED on False exactly as `automation.start`
does - see the `if ok is False` branch there).

Run: python3 tests/test_supervisor_revive_stale_lease.py
"""
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-stalelease-")
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


from apex import ownership, user_loop, user_store           # noqa: E402
from apex.platform import automation as AUTO                # noqa: E402
from apex.platform import ctrader_link as CTL               # noqa: E402

UID = "eeeeeeee-9999-4999-8999-eeeeeeeeeeee"
DEAD = "container-A-dead-0001"
KEY = f"own:user:{UID}"
kv, users, lock = {}, {UID: {"active": True}}, threading.Lock()


def claim_value(k, v, ttl_s=120):
    with lock:
        if k in kv:
            return False
        kv[k] = str(v)
        return True


def release_claim(k, v):
    with lock:
        if kv.get(k) != str(v):
            return False
        del kv[k]
        return True


_names = ("claim_value", "release_claim", "renew_claim", "get_blob", "load",
          "update", "all_active", "_USE_REDIS")
_orig_us = {n: getattr(user_store, n) for n in _names}
_orig = {
    "start": AUTO.start, "_read": AUTO._read,
    "is_platform_account": CTL.is_platform_account,
    "_loop": user_loop._loop, "_entitled": user_loop._entitled,
    "_alert_fn_for": user_loop._alert_fn_for,
}
renewers_started = []
_orig_start_renewer = ownership.start_renewer

try:
    user_store._USE_REDIS = True
    user_store.claim_value = claim_value
    user_store.release_claim = release_claim
    user_store.renew_claim = lambda k, v, ttl_s=120: kv.get(k) == str(v)
    user_store.get_blob = lambda k: kv.get(k)
    user_store.load = lambda uid: dict(users.get(str(uid), {}))
    user_store.update = lambda uid, patch, **k: users.setdefault(str(uid), {}).update(patch) or True
    user_store.all_active = lambda: [UID]
    CTL.is_platform_account = lambda uid: True
    AUTO._read = lambda uid: {"state": AUTO.RUNNING, "ruleDocId": "rule-1"}
    user_loop._loop = lambda *a, **k: None          # the thread body
    user_loop._entitled = lambda uid: True
    user_loop._alert_fn_for = lambda uid, fn: None
    ownership.start_renewer = lambda uid, on_lost=None: (
        renewers_started.append(uid), _orig_start_renewer.__call__(uid, on_lost=on_lost))[1]
    starts = []

    def shim(uid, rule_id, *, starter=None, mode_lister=None, revive=False):
        starts.append((uid, rule_id, revive))
        if user_loop.start(uid) is False:
            raise AUTO.AutomationRefused(
                "ENGINE_REFUSED", "the trading engine refused to start this "
                "loop — it may already be owned by another instance")
        return {"started": True}

    AUTO.start = shim

    def clean():
        kv.clear()
        renewers_started.clear()
        starts.clear()
        with user_loop._lock:
            user_loop._loops.clear()
        ownership._held.clear()
        ownership._renewers.clear()
        ownership._lost.clear()
        ownership._shutdown.clear()

    # ── 1. stale lease held by the dead container ──────────────────────────
    print("\n[1] a stale lease held by the dead container blocks the revival")
    clean()
    kv[KEY] = DEAD
    alive, revived = AUTO.supervise()
    check("the supervisor tried (the record says RUNNING)", len(starts) == 1 and starts[0][2] is True, str(starts))
    check("it is not counted as revived", revived == 0, f"revived={revived}")
    check("and nothing is counted alive either", alive == 0, f"alive={alive}")
    check("no loop is registered as running", user_loop.is_running(UID) is False)
    check("no renewer was started for a lease we do not hold", renewers_started == [],
          str(renewers_started))
    check("the dead container's lease is untouched (we did not steal it)", kv[KEY] == DEAD)
    check("the account stays marked active, so the NEXT cycle retries",
          users[UID].get("active") is True, str(users[UID]))

    print("\n[1b] a second cycle while it is still stale behaves the same")
    alive, revived = AUTO.supervise()
    check("still refused, still not counted", revived == 0 and len(starts) == 2, f"{revived} {starts}")

    # ── 2. the TTL lapses ──────────────────────────────────────────────────
    print("\n[2] once the lease lapses the next cycle revives the loop")
    del kv[KEY]                             # TTL expiry
    alive, revived = AUTO.supervise()
    check("revived", revived == 1, f"revived={revived}")
    check("the loop is registered as running", user_loop.is_running(UID) is True)
    check("the lease is now OURS", kv.get(KEY) == ownership.INSTANCE_ID, str(kv))
    check("a renewer was started to keep it", renewers_started == [UID], str(renewers_started))

    print("\n[3] a healthy loop is left alone on later cycles")
    starts.clear()
    alive, revived = AUTO.supervise()
    check("counted alive, nothing restarted", alive == 1 and revived == 0 and starts == [],
          f"alive={alive} revived={revived} starts={starts}")
    ownership.stop_renewer(UID)

    # ── 4. our own previous generation ─────────────────────────────────────
    print("\n[4] a leftover lease carrying OUR instance id is re-entrant")
    clean()
    kv[KEY] = ownership.INSTANCE_ID
    alive, revived = AUTO.supervise()
    check("revived without waiting for a TTL", revived == 1 and user_loop.is_running(UID), f"revived={revived}")
    ownership.stop_renewer(UID)
finally:
    AUTO.start = _orig["start"]
    AUTO._read = _orig["_read"]
    CTL.is_platform_account = _orig["is_platform_account"]
    user_loop._loop = _orig["_loop"]
    user_loop._entitled = _orig["_entitled"]
    user_loop._alert_fn_for = _orig["_alert_fn_for"]
    ownership.start_renewer = _orig_start_renewer
    for n, f in _orig_us.items():
        setattr(user_store, n, f)
    with user_loop._lock:
        user_loop._loops.clear()
    ownership._held.clear()
    ownership._renewers.clear()

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All stale-lease supervisor checks passed.")
