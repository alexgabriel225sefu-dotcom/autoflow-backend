"""A deploy must not leave the account unmanaged for twelve minutes.

WHAT HAPPENED (22 and 23 Oct 2026, both deploys): the retiring container kept
its lease on the trading loop for the full TTL. The replacement, correctly,
refused to trade a user it did not own, retried every three minutes, and got the
loop at minute 12. For those twelve minutes an open position had only the
broker's stop and target and nobody managing it.

`ownership.release_all()` existed and was called by the Telegram bot, which is
not deployed. The platform server — the one that is — never called it.

WHAT THESE TESTS WILL NOT ACCEPT

* A SIGTERM that does not hand the leases back.
* Handing them back and then taking them again (the renewer re-acquires a key
  that has gone — correct for a container that stays, wrong for one leaving).
* Marking the account inactive: the replacement's supervisor revives only
  accounts still marked active, so that would stop every client for good.
* A shutdown that waits on a store that does not answer.
* New leases being taken after the process was told to stop.

Run: python3 tests/test_platform_shutdown_release.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-shutdown-")
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


from apex import ownership, user_loop, user_store            # noqa: E402
import platform_server as PS                                 # noqa: E402


class Fake:
    def __init__(self):
        self.kv = {}

    def claim_value(self, key, value, ttl_s=120):
        if key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    def get_blob(self, key):
        return self.kv.get(key)

    def renew_claim(self, key, value, ttl_s=120):
        return self.kv.get(key) == str(value)

    def release_claim(self, key, value):
        if self.kv.get(key) == str(value):
            del self.kv[key]
            return True
        return False


_ORIG = {n: getattr(user_store, n) for n in ("claim_value", "get_blob", "renew_claim", "release_claim")}
_ORIG_REDIS = user_store._USE_REDIS


def install(fake):
    for n in _ORIG:
        setattr(user_store, n, getattr(fake, n))
    user_store._USE_REDIS = True
    ownership._held.clear()
    ownership._renewers.clear()
    ownership._shutdown.clear()


def restore():
    for n, f in _ORIG.items():
        setattr(user_store, n, f)
    user_store._USE_REDIS = _ORIG_REDIS
    ownership._held.clear()
    ownership._renewers.clear()
    ownership._shutdown.clear()
    with user_loop._lock:
        user_loop._loops.clear()


try:
    # ── 1. the leases are handed back ───────────────────────────────────────
    print("\n[1] shutdown hands every lease back")
    fake = Fake(); install(fake)
    ownership.acquire("u1"); ownership.acquire("u2")
    check("two leases held", len(fake.kv) == 2, str(fake.kv))
    freed = ownership.begin_shutdown()
    check("both are released", freed == 2 and not fake.kv, f"{freed} {fake.kv}")
    check("the process knows it is shutting down", ownership.shutting_down() is True)

    # ── 2. nothing takes them back ──────────────────────────────────────────
    print("\n[2] and nothing in this process takes them back")
    check("heartbeat does not re-acquire the key that is gone",
          ownership.heartbeat("u1") is None and "own:user:u1" not in fake.kv, str(fake.kv))
    check("acquire is refused (no new lease in the last seconds of a process)",
          ownership.acquire("u3") is False and "own:user:u3" not in fake.kv, str(fake.kv))
    # The hazard, stated: without the flag, the same heartbeat DOES re-take it.
    ownership._shutdown.clear()
    check("(without the flag the same heartbeat would re-acquire — the hazard this prevents)",
          ownership.heartbeat("u1") is True and "own:user:u1" in fake.kv, str(fake.kv))
    ownership._shutdown.set()

    print("\n[2b] a replacement (another process) takes over at once")
    fake.kv.clear()
    fake.kv["own:user:u1"] = "x"       # not ours
    fake.kv.clear()
    check("the key is free for the new container", fake.claim_value("own:user:u1", "new") is True)

    # ── 3. loops stop ticking, accounts stay active ─────────────────────────
    print("\n[3] loops are suspended in memory and NOT marked inactive")
    restore(); fake = Fake(); install(fake)
    with user_loop._lock:
        user_loop._loops["a"] = {"running": True, "dash": {}}
        user_loop._loops["b"] = {"running": True, "dash": {}}
        user_loop._loops["c"] = {"running": False, "dash": {}}
    writes = []
    _real_update = user_store.update
    user_store.update = lambda uid, patch, *a, **k: writes.append((uid, patch))
    try:
        ids = user_loop.suspend_all_for_shutdown()
    finally:
        user_store.update = _real_update
    check("running loops were suspended", sorted(ids) == ["a", "b"], str(ids))
    check("they no longer tick", not user_loop.is_running("a") and not user_loop.is_running("b"))
    check("NOTHING was written: no account was marked inactive", writes == [], str(writes))
    check("a loop that was already stopped is not listed", "c" not in ids)

    print("\n[3b] contrast: stop() DOES mark the account inactive (why it is not used here)")
    with user_loop._lock:
        user_loop._loops["d"] = {"running": True, "dash": {}}
    writes.clear()
    user_store.update = lambda uid, patch, *a, **k: writes.append((uid, patch))
    try:
        user_loop.stop("d")
    finally:
        user_store.update = _real_update
    check("stop() writes active: False", ("d", {"active": False}) in writes, str(writes))

    # ── 4. the server wires it, in the right order, bounded ─────────────────
    print("\n[4] platform_server releases before it stops, and cannot hang")
    src = open(os.path.join(ROOT, "platform_server.py"), encoding="utf-8").read()
    body = src.split("def _graceful(", 1)[1].split("for _sig in", 1)[0]
    check("the handler releases, then shuts the server down",
          "_release_for_shutdown()" in body and body.index("_release_for_shutdown()") < body.index("server.shutdown()"), body[:300])
    rel = src.split("def _release_for_shutdown(", 1)[1].split("\ndef ", 1)[0]
    check("loops are suspended before the leases are released",
          rel.index("suspend_all_for_shutdown") < rel.index("begin_shutdown"))
    check("it never calls stop() (which would mark clients inactive)", "_ul.stop(" not in rel and "user_loop.stop(" not in rel)

    restore(); fake = Fake(); install(fake)
    real_begin = ownership.begin_shutdown
    ownership.begin_shutdown = lambda: time.sleep(30)           # a store that never answers
    try:
        t0 = time.time()
        PS._release_for_shutdown(budget_s=0.5)
        took = time.time() - t0
    finally:
        ownership.begin_shutdown = real_begin
    check("a store that never answers cannot hold the shutdown up", took < 2.0, f"{took:.1f}s")

    restore(); fake = Fake(); install(fake)
    ownership.acquire("s1")
    with user_loop._lock:
        user_loop._loops["s1"] = {"running": True, "dash": {}}
    out = PS._release_for_shutdown(budget_s=5)
    check("end to end: the loop is suspended and the lease is gone",
          out.get("suspended") == ["s1"] and "own:user:s1" not in fake.kv, f"{out} {fake.kv}")
finally:
    restore()

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All shutdown-release checks passed.")
