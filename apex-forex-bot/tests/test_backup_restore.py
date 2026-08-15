"""A backup nobody has restored is not a backup.

The audit asks for a real restore test, so this does a full round trip on the
local backend: write state, dump it, destroy the state, restore, and check that
what came back is what went in — including that credentials made the journey
still encrypted and that runtime coordination data did NOT make the journey at
all.

The two properties that matter most here are the ones that are easy to get
backwards:

  * a dump must NOT decrypt. `load()` decrypts, so a backup written through
    the normal read path would be a plaintext credential file.
  * a restore must NOT bring back ownership leases. A restored lease claims a
    user for a container that no longer exists and locks out the one that
    does, turning a recovery into an outage.

Run: python tests/test_backup_restore.py
"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
# A real key, so the round trip exercises encryption rather than skipping it.
from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

from apex import backup, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n🧪 BACKUP / RESTORE — a real round trip\n")

_olddir = user_store._DIR
WORK = tempfile.mkdtemp(prefix="apex-backup-")
user_store._DIR = WORK

TOKEN = "ctrader-secret-token-value"
UID = "7585109158"

try:
    print("1. State goes in")
    user_store.save(UID, {
        "active": True, "paper": False, "ctrader_env": "demo",
        "license_key": "FORX-AAAA-BBBB-CCCC",
        "ctrader_access_token": TOKEN,
        "ctrader_account_id": "47765456",
        "risk": 0.005, "maxpos": 2, "automation": "approval", "copilot": True,
    })
    user_store.append_trade(UID, {"time": "2026-08-15 10:00:00", "symbol": "EURUSD",
                                  "netPnl": 12.5, "side": "BUY"})
    user_store.append_trade(UID, {"time": "2026-08-15 11:00:00", "symbol": "XAUUSD",
                                  "netPnl": -4.0, "side": "SELL"})
    check("the record round-trips through the store",
          user_store.load(UID)["ctrader_access_token"] == TOKEN)
    on_disk = json.load(open(user_store._path(UID), encoding="utf-8"))
    check("and is stored ENCRYPTED, not plaintext",
          on_disk["ctrader_access_token"].startswith("enc:"),
          on_disk["ctrader_access_token"][:20])

    print("\n2. The dump does not decrypt")
    snap = backup.dump()
    check("the user is in the snapshot", UID in snap["users"])
    tok = snap["users"][UID]["ctrader_access_token"]
    check("the token is still ciphertext", tok.startswith("enc:"), tok[:20])
    check("the plaintext token appears NOWHERE in the dump",
          TOKEN not in json.dumps(snap),
          "a backup file would be a credential dump")
    check("the journal came along", len(snap["journals"][UID]) == 2)
    check("counts are reported", snap["counts"]["users"] == 1)

    print("\n3. verify() catches a backup that is not restorable")
    ok, problems = backup.verify(snap)
    check("a good snapshot verifies", ok, problems)
    bad = json.loads(json.dumps(snap))
    bad["users"][UID]["ctrader_access_token"] = "plaintext-leaked-token"
    ok, problems = backup.verify(bad)
    check("a snapshot with a DECRYPTED credential is refused", ok is False)
    check("and says which field", any("NOT encrypted" in p for p in problems), problems)
    ok, problems = backup.verify({"format": 99, "users": {}})
    check("a wrong format version is refused", ok is False)
    check("an empty snapshot is refused",
          any("zero users" in p for p in problems), problems)

    print("\n4. Destroy the state, then restore it")
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    check("the state really is gone", user_store.load(UID) == {})
    check("and so is the journal", user_store.load_trades(UID) == [])

    rep = backup.restore(snap)
    check("the restore verified", rep["verified"] is True, rep["problems"])
    check("one user restored", rep["users"] == 1, rep)
    check("both journal rows restored", rep["journals"] == 2, rep)
    check("nothing was skipped", rep["skipped"] == [], rep["skipped"])

    print("\n5. What came back is what went in")
    back = user_store.load(UID)
    check("the credential decrypts to the ORIGINAL value",
          back.get("ctrader_access_token") == TOKEN,
          "restore double-encrypted or corrupted it")
    check("the licence survived", back.get("license_key") == "FORX-AAAA-BBBB-CCCC")
    check("risk settings survived", back.get("risk") == 0.005 and back.get("maxpos") == 2)
    check("the automation level survived", back.get("automation") == "approval")
    check("live/paper state survived", back.get("paper") is False)
    check("the broker account survived", back.get("ctrader_account_id") == "47765456")
    rows = user_store.load_trades(UID)
    check("the journal survived intact", len(rows) == 2 and rows[0]["netPnl"] == 12.5,
          rows)

    print("\n6. Runtime coordination data is NOT restored")
    for prefix in ("own:user:", "cmdseen:", "cmdresult:", "mcp_heartbeat"):
        check(f"{prefix} is declared rebuildable",
              any(prefix.startswith(p) or p.startswith(prefix)
                  for p in backup.REBUILDABLE_PREFIXES), prefix)
    BSRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "apex", "backup.py"), encoding="utf-8").read()
    _restore = BSRC[BSRC.index("def restore("):BSRC.index("def _main(")]
    for never in ("own:user:", "claim_value", "renew_claim", "K_COMMANDS",
                  "K_HEART"):
        check(f"restore() never writes {never}", never not in _restore)
    check("restore() spells out the startup steps it does NOT short-circuit",
          "next_steps" in _restore and "broker wins" in _restore)
    check("ownership is acquired fresh, not restored",
          any("acquired fresh" in s for s in rep.get("next_steps", [])),
          rep.get("next_steps"))

    print("\n7. A dry run changes nothing")
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    rep2 = backup.restore(snap, dry_run=True)
    check("it reports what it would do", rep2["users"] == 1 and rep2["dry_run"])
    check("but wrote nothing", user_store.load(UID) == {})

    print("\n8. A restore reports COMPLETE, PARTIAL or FAILED — never just 'done'")
    rep3 = backup.restore(snap)
    check("a clean restore is COMPLETE", rep3["result"] == "COMPLETE", rep3)
    check("with expected and restored counts", rep3["expected"]["users"] == 1
          and rep3["restored"]["users"] == 1, rep3)
    check("and nothing failed", sum(rep3["failed"].values()) == 0, rep3["failed"])

    # A write that fails must NOT read as a successful restore.
    _set = user_store._redis_set
    _use = user_store._USE_REDIS
    try:
        user_store._USE_REDIS = True
        user_store._redis_set = lambda *a, **k: False     # write not confirmed
        user_store._redis_sadd = lambda *a, **k: None
        rep4 = backup.restore(snap)
        check("a restore whose writes fail is FAILED, not COMPLETE",
              rep4["result"] == "FAILED", rep4["result"])
        check("and it says how many are missing",
              rep4["failed"]["users"] == 1, rep4["failed"])
        check("and lists what was skipped", rep4["skipped"], rep4)
    finally:
        user_store._redis_set = _set
        user_store._USE_REDIS = _use

    # Two users, one of which cannot be read back afterwards.
    snap2 = json.loads(json.dumps(snap))
    snap2["users"]["9999"] = dict(snap2["users"][UID])
    snap2["journals"]["9999"] = []
    _load = user_store.load
    try:
        user_store.load = lambda uid: {} if str(uid) == "9999" else _load(uid)
        rep5 = backup.restore(snap2)
        check("a record that vanishes on readback makes it PARTIAL",
              rep5["result"] == "PARTIAL", rep5["result"])
        check("and the detail says not to start the app", "NOT a successful"
              in rep5.get("detail", ""), rep5.get("detail"))
    finally:
        user_store.load = _load

    BSRC2 = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "apex", "backup.py"), encoding="utf-8").read()
    check("the CLI exits non-zero on anything but COMPLETE",
          'rep.get("result") == "COMPLETE"' in BSRC2)
    check("and the restore reads records back after writing",
          "not readable after restore" in BSRC2)
finally:
    user_store._DIR = _olddir
    shutil.rmtree(WORK, ignore_errors=True)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the backup restores, and stays encrypted doing it.")
