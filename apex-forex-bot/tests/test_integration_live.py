"""Integration checks that need a REAL shared backend, not a stub.

Everything here was previously asserted only in unit form, against fakes. A
fake cannot tell you whether `SET NX` actually excludes a second container,
whether an encrypted credential survives a backup/restore round trip, or
whether a compare-and-set really rejects a stale write — those are properties
of Redis and of the wire format, not of our call sites.

So this file boots a real `redis-server` on a spare port and drives the actual
modules against it, including a genuine multi-PROCESS race: two `acquire()`
calls inside one process are the same holder and both legitimately succeed
(that is a lease renewal), which is exactly the mistake that made an earlier
version of this test pass while proving nothing.

SKIPS, loudly, when redis-server is not on PATH. A skipped check is reported
as a skip and never as a pass.

Run: python tests/test_integration_live.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []
skipped = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name}  → {detail}")
    if not cond:
        failures.append(name)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


print("\n🔌  INTEGRATION — REAL REDIS\n")

if not shutil.which("redis-server"):
    print("  ⏭  redis-server not on PATH — these checks CANNOT run here.")
    print("     They are not passing; they are unrun. Install redis-server to")
    print("     verify multi-instance exclusion and backup/restore locally.")
    print("\n" + "=" * 50)
    print("⏭  SKIPPED (no redis-server) — nothing was verified.")
    sys.exit(0)

PORT = _free_port()
proc = subprocess.Popen(
    ["redis-server", "--port", str(PORT), "--save", "", "--appendonly", "no"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)

os.environ["REDIS_URL"] = f"redis://127.0.0.1:{PORT}/0"
os.environ["APP_ENV"] = "production"          # exercise the production path
os.environ["PRODUCT"] = "forex"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-integ-"))
os.environ.setdefault(
    "TOKEN_ENCRYPTION_KEY",
    __import__("base64").urlsafe_b64encode(os.urandom(32)).decode())

try:
    from apex import user_store, ledger, user_loop, backup, access  # noqa: E402

    def redis_cli(*args):
        subprocess.run(["redis-cli", "-p", str(PORT), *args],
                       capture_output=True)

    # ── 1. multi-instance exclusion, across real processes ───────────────
    print("1. Two containers, one account → one owner")
    worker = os.path.join(tempfile.gettempdir(), "apex_integ_worker.py")
    with open(worker, "w") as f:
        f.write(
            "import sys\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "from apex import ownership, ledger\n"
            "uid = sys.argv[1]\n"
            "got = ownership.acquire(uid)\n"
            "ok, why, _ = ledger.claim(user_id=uid, symbol='EURUSD', side='BUY',\n"
            "                          units=7000, sl=1.0, tp=1.1)\n"
            "print(f'{got}|{ownership.holds(uid)}|{ok}')\n")

    env = dict(os.environ)
    outs = []
    procs = [subprocess.Popen([sys.executable, worker, "900001"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=env, text=True) for _ in range(5)]
    for p in procs:
        outs.append((p.communicate()[0] or "").strip().splitlines()[-1:])
    rows = [o[0].split("|") for o in outs if o]
    owners = [r for r in rows if r[0] == "True"]
    orders = [r for r in rows if r[2] == "True"]
    check("five racing containers, exactly one lease", len(owners) == 1,
          f"{len(owners)} of {len(rows)} acquired")
    check("…and exactly one order got through", len(orders) == 1,
          f"{len(orders)} of {len(rows)} placed an order")
    check("every loser also reports not holding",
          all(r[1] == "False" for r in rows if r[0] == "False"),
          "a container that lost the lease must not believe it owns the account")

    # ── 2. coordination gone, live account → no order ────────────────────
    print("\n2. Redis unreachable on a live account → no new order")
    proc.terminate()
    proc.wait(timeout=10)
    time.sleep(0.5)
    ok_d, why_d, _ = ledger.claim(user_id="900002", symbol="USDJPY", side="BUY",
                                  units=1000, sl=1.0, tp=1.1, fail_closed=True)
    check("the order is refused", ok_d is False, f"{ok_d} / {why_d}")
    check("and the reason names the missing coordination",
          "COORDINATION_UNAVAILABLE" in str(why_d), why_d)
    proc = subprocess.Popen(
        ["redis-server", "--port", str(PORT), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    # ── 3. restart recovery — the broker is authoritative ────────────────
    print("\n3. Restart recovery treats the broker as the authority")
    live = {"symbol": "EURUSD", "side": "BUY", "units": 5000}
    check("broker holds a position we did not track → ADOPT",
          user_loop.recovery_verdict(live, True) == "ADOPT")
    check("broker did not answer → KEEP_TRACKED, assume nothing",
          user_loop.recovery_verdict(None, False) == "KEEP_TRACKED")
    check("broker confirms flat → CONFIRMED_CLOSED",
          user_loop.recovery_verdict(None, True) == "CONFIRMED_CLOSED")

    # ── 4. compare-and-set really rejects a stale write ──────────────────
    print("\n4. A stale write cannot clobber a live position")
    UID = "900003"
    user_store.update(UID, {"watchlist": ["EURUSD"],
                            "open_position_snapshot": None})

    # WHAT THIS COVERS, stated precisely, because the honest scope is narrower
    # than it first looks and a test that overstates itself is worse than none.
    #
    # Both writers pass a DELTA, which is what every production caller does
    # (checked: telegram, ui_state, control_actions, ctrader_oauth and
    # user_loop all build an explicit patch; the only whole-record write is
    # /reset, which is meant to wipe). These two checks verify that concurrent
    # delta writes do not lose each other, and that expect_version is actually
    # enforced rather than advisory.
    #
    # They do NOT isolate CRITICAL_FIELDS membership, and cannot: update()
    # re-reads the record itself immediately before saving, so a delta caller
    # never holds a stale copy in the first place. The window CAS closes for
    # open_position_snapshot is the microseconds between update()'s own load
    # and save — real, but not reachable deterministically from here. Removing
    # the field from CRITICAL_FIELDS leaves these checks green, and that is a
    # fact about the window, not a licence to remove it: the field is money
    # state and belongs under the same protection as every other money field.
    #
    # Neither does this cover a caller that writes back a whole previously-read
    # record. That defeats CAS by construction — it re-reads the version just
    # before writing, so the check passes and the stale payload wins. No
    # production caller does it; if one is ever added, this is the trap.
    racer = os.path.join(tempfile.gettempdir(), "apex_integ_racer.py")
    with open(racer, "w") as f:
        f.write(
            "import sys, time\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "from apex import user_store\n"
            "uid = sys.argv[1]\n"
            "user_store.load(uid)\n"              # read at v_n
            "time.sleep(2.0)\n"                   # ...the window
            "user_store.update(uid, {'watchlist': ['GBPUSD']})\n")
    a = subprocess.Popen([sys.executable, racer, UID], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)                                # land inside A's window
    user_store.update(UID, {"open_position_snapshot":
                            {"symbol": "EURUSD", "units": 5000}})
    a.wait(timeout=30)
    snap = user_store.load(UID).get("open_position_snapshot") or {}
    check("a concurrent write does not lose a live position",
          snap.get("units") == 5000,
          f"{snap} — the position was booked as flat by another writer")
    check("…and the unrelated field the other writer set is also kept",
          user_store.load(UID).get("watchlist") == ["GBPUSD"],
          "a merge that drops the other writer's change is the same bug mirrored")

    stale_v = user_store.version(UID)
    user_store.update(UID, {"watchlist": ["AUDUSD"]})
    try:
        user_store.save(UID, {"open_position_snapshot": None},
                        expect_version=stale_v)
        rejected = False
    except Exception:
        rejected = True
    check("an explicit write against a stale version is refused", rejected,
          "expect_version must not be advisory")

    # ── 5. backup → disaster → restore, reconciled field by field ────────
    print("\n5. Backup survives a total wipe, credentials and all")
    U1, U2, U3 = "900011", "900012", "900013"
    seed = {
        U1: {"active": True, "risk": 0.005, "symbol": "EURUSD",
             "ctrader_access_token": "secret-token-1",
             "license_key": "FORX-AAAA-BBBB-CCCC",
             "open_position_snapshot": {"symbol": "EURUSD", "side": "BUY",
                                        "units": 5000, "entryPrice": 1.084}},
        U2: {"active": True, "risk": 0.01, "symbol": "XAUUSD", "paper": True},
        # a paying customer whose bot is STOPPED — must not be dropped
        U3: {"active": False, "license_key": "FORX-DDDD-EEEE-FFFF"},
    }
    for uid, patch in seed.items():
        user_store.update(uid, patch)
        access.grant(uid)

    snapshot = backup.dump()
    check("the stopped customer is in the backup",
          set(snapshot["users"]) >= set(seed), sorted(snapshot["users"]))
    vok, problems = backup.verify(snapshot)
    check("verify() accepts the backup it just produced", vok is True, problems)
    check("credentials stay ENCRYPTED in the backup file",
          "secret-token-1" not in json.dumps(snapshot),
          "a backup must not be a plaintext credential file")

    redis_cli("FLUSHALL")
    check("the wipe really emptied the store",
          not user_store.load(U1).get("symbol"))

    backup.restore(snapshot)
    a = {u: user_store.load(u) for u in seed}
    check("symbol restored", a[U1].get("symbol") == "EURUSD")
    check("risk restored", a[U1].get("risk") == 0.005)
    check("licence key restored",
          a[U1].get("license_key") == "FORX-AAAA-BBBB-CCCC")
    check("broker credential decrypts after the round trip",
          a[U1].get("ctrader_access_token") == "secret-token-1",
          "the restore must re-encrypt under the same TOKEN_ENCRYPTION_KEY")
    s = a[U1].get("open_position_snapshot") or {}
    check("the open position is reconstructed exactly",
          s.get("units") == 5000 and s.get("entryPrice") == 1.084, s)
    check("paper mode is preserved", a[U2].get("paper") is True)
    check("a stopped customer is NOT silently reactivated",
          a[U3].get("active") is False, a[U3].get("active"))
    check("a stopped customer keeps their licence",
          a[U3].get("license_key") == "FORX-DDDD-EEEE-FFFF")
    check("the access list is restored",
          set(map(str, access.list_clients() or [])) >= set(seed))
finally:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        pass

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — verified against a real backend.")
