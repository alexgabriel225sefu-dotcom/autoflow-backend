"""A restore that lost records must never read like a restore that did not.

The round trip is already covered by test_backup_restore.py: write state, dump,
destroy, restore, compare. This file covers the case that actually hurts —
restore ran, most of it worked, and the report was believed.

The failure chain being guarded:

    disaster
        ↓
    restore runs
        ↓
    record 51 of 100 fails to write
        ↓
    report says "restored"
        ↓
    application starts
        ↓
    49 clients have no licence, no risk config, no broker link
        ↓
    the bot trades for the ones that survived and silently ignores the rest

Every check below asserts the SAFETY OUTCOME — "this is not COMPLETE" — rather
than "an exception was raised". A restore is allowed to fail. It is not allowed
to fail quietly.

Run: python tests/test_restore_integrity.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-restore-")
# Encryption ON, as in every real deployment. verify() refuses a snapshot whose
# credentials are plaintext — correctly — so a test that seeded plaintext would
# be exercising that refusal instead of the restore path it means to cover.
from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

from apex import access, backup, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# ── Production-like state ────────────────────────────────────────────────────
# Not one toy user: the point is that a PARTIAL restore is only visible when
# there is more than one record to lose.
USERS = {
    "5001": {"active": True, "paper": False, "license_key": "FORX-AAAA-1111-AAAA",
             "ctrader_account_id": "47765456", "ctrader_env": "demo",
             "ctrader_access_token": "tok-a", "risk": 0.005, "maxpos": 2,
             "automation": "full", "strategy": "zscore", "max_dd_pct": 25},
    "5002": {"active": True, "paper": False, "license_key": "FORX-BBBB-2222-BBBB",
             "ctrader_account_id": "47818148", "ctrader_env": "live",
             "ctrader_access_token": "tok-b", "risk": 0.01, "maxpos": 4,
             "automation": "approval", "strategy": "trend", "max_dd_pct": 20},
    "5003": {"active": False, "paper": True, "license_key": "FORX-CCCC-3333-CCCC",
             "risk": 0.02, "maxpos": 1, "automation": "signals",
             "strategy": "breakout", "max_dd_pct": 15},
}
JOURNALS = {
    "5001": [{"time": "2026-08-14 10:00:00", "symbol": "EURUSD", "netPnl": 12.5,
              "balance": 1012.5, "action": "CLOSE"},
             {"time": "2026-08-14 12:00:00", "symbol": "XAUUSD", "netPnl": -4.0,
              "balance": 1008.5, "action": "CLOSE"}],
    "5002": [{"time": "2026-08-14 11:00:00", "symbol": "GBPUSD", "netPnl": 3.0,
              "balance": 2003.0, "action": "CLOSE"}],
}


def seed():
    for uid, rec in USERS.items():
        user_store.save(uid, dict(rec))
        # dump() collects the UNION of active users and granted access, so a
        # paused client is only in scope because they are still entitled. 5003
        # is paused on purpose: without the grant it would be out of scope by
        # design, and this test would be quietly backing up two users while
        # claiming three.
        access.grant(uid)
        user_store.clear_trades(uid)
        for row in JOURNALS.get(uid, []):
            user_store.append_trade(uid, row)


def wipe():
    for uid in USERS:
        try:
            os.remove(user_store._path(uid))
        except OSError:
            pass
        try:
            user_store.clear_trades(uid)
        except Exception:
            pass


print("\n🧪 RESTORE INTEGRITY — a partial restore is not a restore\n")

print("1. Full disaster-recovery cycle, end to end")
seed()
snap = backup.dump()
check("the snapshot holds every user", len(snap["users"]) >= 3, len(snap["users"]))
ok, problems = backup.verify(snap)
check("and it verifies before we trust it", ok, "; ".join(problems[:2]))

wipe()
check("the state really is gone", not user_store.load("5001"))

rep = backup.restore(snap)
check("restore reports COMPLETE", rep["result"] == "COMPLETE",
      f"{rep['result']} skipped={rep['skipped'][:2]}")
check("expected and restored counts AGREE",
      rep["expected"] == rep["restored"], f"{rep['expected']} vs {rep['restored']}")
check("nothing counted as failed", sum(rep["failed"].values()) == 0, rep["failed"])

print("\n2. Content, not counts — the fields a client cannot re-enter")
for uid, orig in USERS.items():
    back = user_store.load(uid) or {}
    check(f"user {uid}: licence survived",
          back.get("license_key") == orig["license_key"])
    check(f"user {uid}: risk config survived",
          back.get("risk") == orig["risk"] and back.get("maxpos") == orig["maxpos"])
    check(f"user {uid}: automation level survived",
          back.get("automation") == orig["automation"])
    check(f"user {uid}: live/paper state survived",
          back.get("paper") is orig["paper"])
    if orig.get("ctrader_account_id"):
        check(f"user {uid}: broker account survived",
              back.get("ctrader_account_id") == orig["ctrader_account_id"])
        check(f"user {uid}: broker ENVIRONMENT survived",
              back.get("ctrader_env") == orig["ctrader_env"],
              "restoring a live account as demo, or the reverse, is the worst "
              "possible silent outcome")
check("journal rows restored for 5001", len(user_store.load_trades("5001")) == 2)


# ── Failure injection ────────────────────────────────────────────────────────
def restore_with(patch_name, replacement, target=user_store):
    """Run a restore with one persistence call sabotaged."""
    wipe()
    orig = getattr(target, patch_name)
    setattr(target, patch_name, replacement)
    try:
        return backup.restore(snap)
    finally:
        setattr(target, patch_name, orig)


print("\n3. A persistence write failure during restore is NEVER 'COMPLETE'")
_real_append = user_store.append_trade


def _append_fails_for_5001(uid, row):
    if str(uid) == "5001":
        raise OSError("disk full")
    return _real_append(uid, row)


rep2 = restore_with("append_trade", _append_fails_for_5001)
check("a journal write failure → not COMPLETE", rep2["result"] != "COMPLETE",
      rep2["result"])
check("...and the missing rows are COUNTED, not just logged",
      rep2["failed"]["journals"] > 0, rep2["failed"])
check("...and the affected user is named",
      any("5001" in s for s in rep2["skipped"]), rep2["skipped"][:3])
check("...and the report says plainly this is not a successful restore",
      "NOT a successful restore" in str(rep2.get("detail", "")), rep2.get("detail"))

print("\n4. A record that writes but cannot be read back is a LOST record")
_real_load = user_store.load


def _load_loses_5002(uid, *a, **k):
    if str(uid) == "5002":
        return {}
    return _real_load(uid, *a, **k)


rep3 = restore_with("load", _load_loses_5002)
check("a silent write loss → not COMPLETE", rep3["result"] != "COMPLETE",
      rep3["result"])
check("...the user count is CORRECTED downward, not left optimistic",
      rep3["restored"]["users"] < rep3["expected"]["users"],
      f"{rep3['restored']} vs {rep3['expected']}")
check("...and the readback failure is reported",
      any("5002" in s for s in rep3["skipped"]), rep3["skipped"][:3])

print("\n5. A user restored WITHOUT their active-set membership is a lost client")
# Found while writing this file. The record round-trips, the readback passes,
# and the restore said COMPLETE — but start_all() and the watchdog both iterate
# the active SET, so a client whose membership did not write is simply never
# started. Nothing downstream looks for a user it was never told about.
_saved = {k: getattr(user_store, k) for k in
          ("_USE_REDIS", "_redis_set", "_redis_sadd", "load")}
_fake = {}       # the shared store, standing in for Redis


def _fake_set(key, val):
    _fake[key] = val
    return True


def _sadd_fails(key, member):
    return None                      # exactly what a flaky Redis returns


def _fake_load(uid, *a, **k):
    raw = _fake.get(f"{user_store._NS}:user:{uid}")
    return json.loads(raw) if raw else {}


wipe()
_fake.clear()
# A shared backend has to be faked rather than merely flagged: flipping
# _USE_REDIS alone also switches the WRITE path, which then fails first and
# never reaches the active-set branch this is about.
user_store._USE_REDIS = True
user_store._redis_set = _fake_set
user_store._redis_sadd = _sadd_fails
user_store.load = _fake_load
try:
    rep_sadd = backup.restore(snap)
finally:
    for k, v in _saved.items():
        setattr(user_store, k, v)
check("the records themselves DID restore — this is not a write failure",
      rep_sadd["restored"]["users"] == rep_sadd["expected"]["users"],
      f"{rep_sadd['restored']} vs {rep_sadd['expected']}")
check("a failed active-set write → not COMPLETE",
      rep_sadd["result"] != "COMPLETE", rep_sadd["result"])
check("...and it says the loop will not start",
      any("will not start" in s for s in rep_sadd["skipped"]),
      rep_sadd["skipped"][:2])
check("...naming the affected users",
      any("5001" in s for s in rep_sadd["skipped"]), rep_sadd["skipped"][:2])
# The local backend has no set to miss, so it must NOT be failed for this.
wipe()
user_store._redis_sadd = _sadd_fails
try:
    rep_local = backup.restore(snap)
finally:
    user_store._redis_sadd = _saved["_redis_sadd"]
check("but the LOCAL backend is not punished for a set it does not use",
      rep_local["result"] == "COMPLETE", rep_local["result"])

print("\n6. Losing EVERY user is FAILED, not merely PARTIAL")


def _load_loses_all(uid, *a, **k):
    return {}


rep4 = restore_with("load", _load_loses_all)
check("total loss → FAILED", rep4["result"] == "FAILED", rep4["result"])

print("\n7. A snapshot that does not verify writes NOTHING")
bad = json.loads(json.dumps(snap))
bad["format"] = "not-a-real-version"
wipe()
rep5 = backup.restore(bad)
check("an unverifiable snapshot → FAILED", rep5["result"] == "FAILED", rep5["result"])
check("...and it says nothing was written",
      "nothing was written" in str(rep5.get("detail", "")), rep5.get("detail"))
check("...and nothing WAS written", not user_store.load("5001"))
check("the failure report still has the full shape a caller reads uniformly",
      all(k in rep5 for k in ("expected", "restored", "failed", "result")),
      "a report that is only well-formed on success is not a report")

print("\n8. The report is machine-checkable, so a script cannot ignore it")
check("every result is one of three known states",
      {rep["result"], rep2["result"], rep3["result"], rep4["result"],
       rep5["result"]} <= {"COMPLETE", "PARTIAL", "FAILED"})
check("the CLI exits non-zero on anything but COMPLETE",
      "return 0 if rep.get(\"result\") == \"COMPLETE\" else 1"
      in open(os.path.join(os.path.dirname(os.path.dirname(
          os.path.abspath(__file__))), "apex", "backup.py"),
          encoding="utf-8").read())

print("\n9. Recovery must not resurrect runtime coordination state")
# A restored lease claims a user for a container that no longer exists and
# locks out the one that does — the recovery becomes the outage.
BSRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "backup.py"), encoding="utf-8").read()
# Body only — the docstring NAMES these prefixes to say they are excluded, so a
# whole-file substring search would flag the very sentence promising the fix.
_restore_src = BSRC[BSRC.index("def restore("):]
_restore_body = _restore_src[_restore_src.index('"""', _restore_src.index('"""') + 3):]
for never in backup.REBUILDABLE_PREFIXES:
    check(f"restore never writes {never!r}", never not in _restore_body)
check("the rebuildable set is declared once, not re-listed per caller",
      len(backup.REBUILDABLE_PREFIXES) >= 5)
check("and the snapshot never carried them either",
      not any(str(k).startswith(("own:", "cmdseen:", "oauth:"))
              for k in (snap.get("users") or {})))

print("\n10. After a restore the BROKER is authoritative, not local state")
wipe()
backup.restore(snap)
from apex import ops_api  # noqa: E402

# 5003 has no broker link at all: the honest answer is "cannot reconcile",
# never a cheerful RECONCILED.
r = ops_api.broker_reconcile("5003")
check("a user with no broker link does not report RECONCILED",
      r.get("status") != "RECONCILED", str(r)[:160])
check("the reconcile verdicts are named, not normalised away",
      "EXTERNAL_OR_UNRECONCILED_POSITION" in
      open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "ops_api.py"), encoding="utf-8").read())
check("restore tells the operator to reconcile before trusting it",
      any("reconcile" in str(s).lower() for s in (rep.get("next_steps") or [])),
      str(rep.get("next_steps"))[:200])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — a restore that lost records says so.")
