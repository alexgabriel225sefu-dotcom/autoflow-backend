"""Disaster-recovery drill — run this where the production credentials live.

The automated test proves the backup CODE round-trips. Only a drill proves the
PROCEDURE does, against real data, with real volumes and real edge cases. The
gap between those two is where disaster recovery usually fails.

WHY THIS IS A SCRIPT AND NOT A TEST: it needs the production
TOKEN_ENCRYPTION_KEY and Upstash credentials to read live data. Those belong on
the deployment, not in a repository or a chat transcript, so the drill goes to
the credentials rather than the other way round.

WHAT IT TOUCHES: production is READ ONLY. The restore half writes into a
throwaway temporary directory that is deleted at the end. Nothing is written
back to Redis at any point — the script forces the local backend before
restoring, precisely so a mistake cannot reach the live store.

RUN IT:
    # On Render:  Shell tab of the apex-forex-bot service
    # Locally:    with the same env vars exported
    cd apex-forex-bot && python scripts/dr_drill.py

Exit code 0 means the drill passed. Anything else means DO NOT rely on your
backups until you have investigated.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import backup, user_store  # noqa: E402

FAIL = []


def step(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)
    return ok


def main():
    print("\n🧪 DISASTER-RECOVERY DRILL\n")
    print(f"backend = {user_store._BACKEND}   shared = {user_store._USE_REDIS}")
    if not user_store._USE_REDIS:
        print("\n⛔ This is not reading a shared store, so it is not a drill "
              "against production data. Run it where REDIS_URL or the Upstash "
              "pair is configured.")
        return 2

    print("\n1. Dump production (read only)")
    snap = backup.dump()
    step("dumped", bool(snap["users"]), json.dumps(snap["counts"]))
    if not snap["users"]:
        print("   nothing to restore — is PRODUCT set correctly?")
        return 1

    print("\n2. Verify the snapshot before trusting it")
    ok, problems = backup.verify(snap)
    step("verify passed", ok, "; ".join(problems[:3]))
    if not ok:
        print("\n⛔ The snapshot does not verify, so restoring it proves "
              "nothing. Fix the backup before continuing.")
        return 1

    print("\n3. No plaintext credential left production")
    leaked = [f"{u}.{f}" for u, rec in snap["users"].items()
              for f in ("ctrader_access_token", "ctrader_refresh_token")
              if rec.get(f) and not str(rec[f]).startswith("enc:")]
    step("every credential is ciphertext in the dump", not leaked, str(leaked[:3]))

    # Not the working directory: this file holds licence keys, and dropping it
    # into a repo checkout is how it ends up committed.
    out = os.path.join(tempfile.gettempdir(), f"dr-drill-{snap['created']}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
    print(f"   snapshot written: {out} ({os.path.getsize(out):,} bytes)")
    print("   ⚠️  delete it when you are done — it holds licence keys.")

    print("\n4. Restore into an ISOLATED target (production untouched)")
    target = tempfile.mkdtemp(prefix="apex-drill-")
    _use, _dir = user_store._USE_REDIS, user_store._DIR
    user_store._USE_REDIS = False          # belt and braces: cannot reach Redis
    user_store._DIR = target
    try:
        rep = backup.restore(snap)
        step("restore reports COMPLETE", rep["result"] == "COMPLETE", rep["result"])
        print(f"   expected {rep['expected']}")
        print(f"   restored {rep['restored']}")
        print(f"   failed   {rep['failed']}")
        for s in rep["skipped"][:5]:
            print(f"   skipped: {s}")

        print("\n5. Content, not just counts")
        for uid, orig in snap["users"].items():
            back = user_store.load(uid)
            if not step(f"user {uid} is readable", bool(back)):
                continue
            same = all(back.get(k) == orig.get(k)
                       for k in ("ctrader_account_id", "ctrader_env", "risk",
                                 "paper", "automation")
                       if k in orig)
            step(f"user {uid} settings match", same)
            tok = back.get("ctrader_access_token")
            if tok:
                step(f"user {uid} credential decrypts",
                     not str(tok).startswith("enc:"),
                     "still ciphertext — is TOKEN_ENCRYPTION_KEY the one that "
                     "wrote it?")
            rows = user_store.load_trades(uid)
            step(f"user {uid} journal restored",
                 len(rows) == len(snap["journals"].get(uid, [])),
                 f"{len(rows)} rows")
    finally:
        user_store._USE_REDIS, user_store._DIR = _use, _dir
        shutil.rmtree(target, ignore_errors=True)

    print("\n" + "=" * 50)
    if FAIL:
        print(f"❌ DRILL FAILED — {len(FAIL)} check(s). Do not rely on these "
              f"backups until this is understood.")
        return 1
    print("✅ DRILL PASSED — production data dumped, verified, restored and "
          "content-checked. Nothing was written to production.")
    print("\nNext, against a restored deployment: ops_system_health, then "
          "ops_broker_reconcile per user. The broker is authoritative.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
