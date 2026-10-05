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

    print("\n1b. The PLATFORM's own state goes in too")
    # Everything the platform is, lives under a different namespace from the
    # engine's user records. A backup that only knows about `{ns}:user:*`
    # restores clients who have no rules, no licence, no broker link and no
    # waitlist — and reports success doing it.
    from apex.platform import licence as _lic               # noqa: E402
    from apex.platform import ruledoc as _rd                # noqa: E402
    from apex.platform import store as _pstore              # noqa: E402
    from apex.platform import waitlist as _wait             # noqa: E402

    OWNER = "11111111-2222-4333-8444-555555555555"
    doc = _rd.blank(user_id=OWNER, account_id="47765456",
                    symbols=["EURUSD"], timeframe="1h")
    doc["name"] = "Backed-up rule"
    doc["entry"]["conditions"] = [{"id": "rsi", "period": 14,
                                   "op": "above", "value": 55}]
    RID = doc["ruleDocId"]
    _pstore.create(OWNER, doc)
    _pstore.activate(OWNER, RID, known_condition_ids={"rsi"})
    _lic.grant(OWNER, plan="paid_live")
    _wait.join("backed-up@example.com", source="landing")
    check("a rule exists to lose", _pstore.get(OWNER, RID)["name"] == "Backed-up rule")
    check("and a frozen version the journal points at",
          _pstore.get_version(OWNER, RID, 1)["state"] == "active")
    check("and a licence", _lic.status_for(OWNER).get("plan") == "paid_live")
    check("and somebody on the waitlist", _wait.count() >= 1)

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

    print("\n5b. So did the platform's state — rules, versions, licence, list")
    # This is the half that makes the product the product. A client whose
    # settings came back and whose RULES did not has nothing to run, and a
    # frozen version that did not come back leaves every journal entry
    # pointing at terms that no longer exist — the one thing store.py was
    # written to prevent.
    def _gone(fn):
        """A record that is absent must FAIL a check, not end the run.

        store.get() raises NotFound, which is right for the product and wrong
        here: the first missing record would abort before the others were
        asked about, and the report would name one casualty instead of all of
        them.
        """
        try:
            return fn()
        except Exception as e:
            return {"__missing__": f"{type(e).__name__}: {e}"}

    r_back = _gone(lambda: _pstore.get(OWNER, RID))
    check("the rule came back", r_back.get("name") == "Backed-up rule", r_back)
    check("with its entry conditions",
          (r_back.get("entry") or {}).get("conditions", [{}])[0].get("id") == "rsi",
          r_back.get("entry") or r_back)
    listed = _gone(lambda: [d["ruleDocId"] for d in _pstore.list_docs(OWNER)])
    check("the owner's rule index came back, so the rule is listable",
          listed == [RID], listed)
    v1 = _gone(lambda: _pstore.get_version(OWNER, RID, 1))
    check("the FROZEN version came back — the journal points at it",
          v1.get("state") == "active" and v1.get("version") == 1, v1)
    check("the licence came back",
          _lic.status_for(OWNER).get("plan") == "paid_live",
          _lic.status_for(OWNER))
    check("the waitlist came back",
          "backed-up@example.com" in [e["email"] for e in _wait.export()["entries"]],
          [e["email"] for e in _wait.export()["entries"]])

    print("\n5c. A platform lock or a half-finished OAuth is NOT restored")
    # Same rule as the ownership leases below, one namespace down. A restored
    # journal lock blocks the writer the journal exists to record, and a
    # restored OAuth nonce revives an authorisation the user walked away from.
    _pfx = _pstore.namespace_prefix()
    for tail in ("ctlink:pending:abc", "ctlink:used:abc", "autolock:u1",
                 "notifylock:u1", "jlock:u1"):
        check(f"{tail} is declared rebuildable",
              backup._platform_rebuildable(_pfx + tail), tail)
    check("a real record is NOT declared rebuildable, so the filter is not "
          "simply 'everything'",
          not backup._platform_rebuildable(_pfx + f"rule:{OWNER}:{RID}"))

    _pstore._write(_pfx + "jlock:u1", {"held": "by a request that is over"})
    _pstore._write(_pfx + "ctlink:pending:abc", {"nonce": "abandoned"})
    snap_locks = backup.dump()
    check("a lock is not even carried in the dump",
          not any("jlock:" in k for k in snap_locks["platform"]["strings"]),
          [k for k in snap_locks["platform"]["strings"] if "lock" in k])
    check("nor is a pending authorisation",
          not any("ctlink:pending:" in k for k in snap_locks["platform"]["strings"]))

    print("\n5d. The platform's own encrypted values stay encrypted")
    # The broker link record holds the cTrader tokens. The user records above
    # are already checked for this; the platform's copy is a second place the
    # same mistake can be made, and nothing was checking it.
    CT_TOKEN = "platform-ctrader-access-token"
    _pstore._write(_pfx + f"ctrader:{OWNER}", {
        "accessToken": user_store.encrypt_value(CT_TOKEN),
        "refreshToken": user_store.encrypt_value("refresh-value"),
        "ctid": 47765456, "mode": "demo"})
    snap_ct = backup.dump()
    check("the plaintext broker token appears NOWHERE in the dump",
          CT_TOKEN not in json.dumps(snap_ct),
          "a backup file would be a credential dump")
    ok_ct, _ = backup.verify(snap_ct)
    check("and a snapshot carrying encrypted tokens verifies", ok_ct)
    leaked = json.loads(json.dumps(snap_ct))
    leaked["platform"]["strings"][_pfx + f"ctrader:{OWNER}"] = json.dumps(
        {"accessToken": CT_TOKEN, "refreshToken": "x"})
    ok_leak, probs_leak = backup.verify(leaked)
    check("a snapshot with a DECRYPTED broker token is refused", not ok_leak)
    check("and says which field",
          any("accessToken is NOT encrypted" in p for p in probs_leak),
          probs_leak)

    print("\n5e. A backup with no platform section is refused, not trusted")
    # The dangerous case is not a corrupt file; it is a file written by the
    # version of this code that did not know the platform existed. Restoring
    # one would look like success and leave the product empty.
    old_style = json.loads(json.dumps(snap))
    old_style.pop("platform", None)
    ok_old, probs_old = backup.verify(old_style)
    check("a snapshot predating platform support does not verify", not ok_old)
    check("and says what would be lost",
          any("every rule, licence and broker link" in p for p in probs_old),
          probs_old)
    unread = json.loads(json.dumps(snap))
    unread["platform_error"] = "StoreUnavailable: SCAN failed"
    ok_unread, probs_unread = backup.verify(unread)
    check("a dump that COULD NOT READ the namespace is refused too",
          not ok_unread, "an unreadable namespace must not pass as an empty one")
    check("and says so", any("could not be read" in p for p in probs_unread),
          probs_unread)

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

    print("\n9. Every report has the SAME shape, especially the failures")
    # The drill script crashed on KeyError reading rep["restored"] because the
    # failed-verify path returned a shorter dict. A report that is only
    # well-formed when things went well is not a report.
    bad2 = {"format": 99, "users": {}}
    rep_bad = backup.restore(bad2)
    for k in ("verified", "problems", "expected", "restored", "failed",
              "result", "skipped", "dry_run"):
        check(f"a FAILED report still carries {k}", k in rep_bad, sorted(rep_bad))
    check("and it says FAILED", rep_bad["result"] == "FAILED", rep_bad["result"])
    check("with everything counted as failed",
          rep_bad["restored"] == {"users": 0, "journals": 0, "access": 0,
                                  "platform": 0},
          rep_bad["restored"])
    check("the DR drill ships as a runnable script",
          os.path.exists(os.path.join(
              os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
              "scripts", "dr_drill.py")))
    DR = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "scripts", "dr_drill.py"), encoding="utf-8").read()
    check("the drill refuses to call a local store a drill",
          "not a drill" in DR)
    check("it forces the local backend before restoring, so it cannot write "
          "to production", "user_store._USE_REDIS = False" in DR)
    check("and it does not drop a licence-bearing file into the repo",
          "tempfile.gettempdir()" in DR)
finally:
    user_store._DIR = _olddir
    shutil.rmtree(WORK, ignore_errors=True)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the backup restores, and stays encrypted doing it.")
