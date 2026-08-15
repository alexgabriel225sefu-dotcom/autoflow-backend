"""Backup and restore for everything that cannot be rebuilt.

WHAT IS BACKED UP, and why that list and not more:

    users              settings, risk, automation level, live/paper
    licenses           the licence key on each record
    access state       who is granted
    broker metadata    account id, environment, linked accounts
    credentials        ENCRYPTED, exactly as stored — never decrypted here
    trading state      the restart snapshot the loop reconciles against
    trade journal      closed trades; the only record of what happened
    audit events       who did what through the control plane

WHAT IS DELIBERATELY NOT BACKED UP, because it is rebuildable and restoring it
would be actively wrong:

    ownership leases   a restored lease would claim a user for a container
                       that no longer exists, and block the one that does
    command queue      replaying operator commands from a backup would re-run
                       them against a different world
    replay markers     tied to command ids that no longer matter
    heartbeats         meaningless outside their moment
    dash / cache       rebuilt on the first tick

CREDENTIALS STAY ENCRYPTED. The backup carries the `enc:` ciphertext verbatim,
so a backup file is not a credential dump. It is also useless without
TOKEN_ENCRYPTION_KEY — which is the point, and the operational consequence:
LOSING THAT KEY MAKES EVERY BACKUP UNUSABLE FOR BROKER RECONNECTION. Store it
separately from the backups, or restoring gets you users who look connected and
cannot trade.

RPO / RTO. RPO is the backup interval — nothing is streamed, so a restore loses
at most one interval of settings changes and journal rows. RTO is dominated by
broker reconnection and position discovery, not by this file: writing the keys
back takes seconds, and then the loop has to reach cTrader for each user.

RESTORE ORDER matters and is enforced by `restore()`:
    1. write users, access, journals, audit
    2. do NOT write leases, queues or heartbeats
    3. the caller starts the app, which reconnects Redis
    4. the loop reconnects the broker per user
    5. the loop discovers real positions and reconciles (broker wins)
    6. loops are rebuilt from `active`
    7. entitlement is re-checked at the order gate
    8. ownership is acquired fresh
Steps 3-8 are the normal startup path. This module deliberately does not
short-circuit any of them.

Usage:
    python -m apex.backup dump  > apex-backup-2026-08-15.json
    python -m apex.backup restore < apex-backup-2026-08-15.json
    python -m apex.backup verify < apex-backup-2026-08-15.json
"""
import json
import sys
import time

from apex import user_store

FORMAT_VERSION = 1

# Key namespaces that are runtime coordination, not state. Never restored.
REBUILDABLE_PREFIXES = ("own:user:", "cmdseen:", "cmdresult:", "commands",
                        "mcp_heartbeat", "oauth:state:", "order:")


def _ns():
    return getattr(user_store, "_NS", "forex")


def dump():
    """A restorable snapshot. Credentials stay in their stored (encrypted) form.

    Reads through the RAW path on purpose: `load()` decrypts, and a backup that
    decrypts on the way out would turn every dump into a plaintext credential
    file sitting on somebody's laptop.
    """
    ns = _ns()
    out = {
        "format": FORMAT_VERSION,
        "product": ns,
        "created": int(time.time()),
        "credentials": "encrypted-at-rest; requires the same TOKEN_ENCRYPTION_KEY",
        "users": {},
        "journals": {},
        "access": [],
        "audit": [],
    }
    uids = set()
    try:
        uids |= set(user_store.all_active() or [])
    except Exception as e:
        print(f"[Backup] could not list active users: {e}", file=sys.stderr)
    try:
        from apex import access
        granted = list(access.list_clients() or []) + list(access.list_admins() or [])
        out["access"] = [str(g) for g in granted]
        uids |= {str(g) for g in granted}
    except Exception as e:
        print(f"[Backup] could not read access list: {e}", file=sys.stderr)

    for uid in sorted(str(u) for u in uids):
        raw = None
        if getattr(user_store, "_USE_REDIS", False):
            raw = user_store._redis_get(f"{ns}:user:{uid}")
        else:
            try:
                with open(user_store._path(uid), encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                raw = None
        if raw:
            try:
                out["users"][uid] = json.loads(raw)   # still encrypted
            except ValueError:
                print(f"[Backup] user {uid} is not valid JSON — skipped",
                      file=sys.stderr)
        try:
            out["journals"][uid] = user_store.load_trades(uid) or []
        except Exception as e:
            print(f"[Backup] journal for {uid} unreadable: {e}", file=sys.stderr)

    try:
        from apex import control
        out["audit"] = control._cmd("LRANGE", control.K_AUDIT, 0, 499) or []
    except Exception as e:
        print(f"[Backup] audit log unreadable: {e}", file=sys.stderr)

    out["counts"] = {"users": len(out["users"]),
                     "journals": sum(len(v) for v in out["journals"].values()),
                     "access": len(out["access"]),
                     "audit": len(out["audit"])}
    return out


def verify(snapshot):
    """Is this snapshot restorable? Returns (ok, [problems]).

    Run before trusting a backup, not after needing it.
    """
    problems = []
    if not isinstance(snapshot, dict):
        return False, ["not a JSON object"]
    if snapshot.get("format") != FORMAT_VERSION:
        problems.append(f"format {snapshot.get('format')!r}, expected {FORMAT_VERSION}")
    users = snapshot.get("users")
    if not isinstance(users, dict):
        problems.append("no users section")
        users = {}
    if not users:
        problems.append("snapshot contains zero users")
    for uid, rec in users.items():
        if not str(uid).isdigit():
            problems.append(f"user id {uid!r} is not numeric")
        if not isinstance(rec, dict):
            problems.append(f"user {uid} record is not an object")
            continue
        # A record whose credential fields were decrypted before being written
        # is a plaintext credential file. Catch it here, not in an incident.
        for f in ("ctrader_access_token", "ctrader_refresh_token"):
            v = rec.get(f)
            if isinstance(v, str) and v and not v.startswith(user_store._ENC_PREFIX):
                problems.append(f"user {uid}: {f} is NOT encrypted in this backup")
    for uid, rows in (snapshot.get("journals") or {}).items():
        if not isinstance(rows, list):
            problems.append(f"journal for {uid} is not a list")
    return (not problems), problems


def restore(snapshot, dry_run=False):
    """Write a snapshot back. Returns a report; never raises on a single record.

    Restores state only. Leases, command queues and heartbeats are NOT written:
    a restored lease claims a user for a container that no longer exists and
    locks out the one that does, which turns a recovery into an outage.
    """
    ok, problems = verify(snapshot)
    # Expected counts are computed BEFORE anything is written, so "restored"
    # can be compared against "should have been restored". Without that, a
    # restore that skipped half the users still returned a report that read
    # like success — the skipped list was there, but nothing forced anyone to
    # look at it.
    expected = {
        "users": len(snapshot.get("users") or {}),
        "journals": sum(len(v or []) for v in (snapshot.get("journals") or {}).values()),
        "access": len(snapshot.get("access") or []),
    }
    # One shape, always. The early-return path used to omit `restored` and
    # `failed`, so any caller that read the report uniformly — a drill script,
    # a monitoring hook — crashed on the failure case instead of reporting it.
    # A report that is only well-formed when things went well is not a report.
    zero = {"users": 0, "journals": 0, "access": 0}
    report = {"verified": ok, "problems": problems, "users": 0, "journals": 0,
              "access": 0, "skipped": [], "dry_run": bool(dry_run),
              "expected": expected, "restored": dict(zero),
              "failed": dict(expected), "result": "FAILED"}
    if not ok:
        report["detail"] = "snapshot did not verify; nothing was written"
        return report
    ns = _ns()

    for uid, rec in (snapshot.get("users") or {}).items():
        if dry_run:
            report["users"] += 1
            continue
        try:
            # Written RAW. save() would encrypt again over ciphertext, and the
            # second layer is not removable by the same key.
            if getattr(user_store, "_USE_REDIS", False):
                wrote = user_store._redis_set(f"{ns}:user:{uid}", json.dumps(rec))
            else:
                with open(user_store._path(uid), "w", encoding="utf-8") as f:
                    json.dump(rec, f, indent=2)
                wrote = True
            if wrote:
                report["users"] += 1
                if rec.get("active"):
                    user_store._redis_sadd(user_store._ACTIVE_SET, str(uid))
            else:
                report["skipped"].append(f"user {uid}: write not confirmed")
        except Exception as e:
            report["skipped"].append(f"user {uid}: {str(e)[:120]}")

    for uid, rows in (snapshot.get("journals") or {}).items():
        if dry_run:
            report["journals"] += len(rows or [])
            continue
        try:
            user_store.clear_trades(uid)
            for row in rows or []:
                user_store.append_trade(uid, row)
            report["journals"] += len(rows or [])
        except Exception as e:
            report["skipped"].append(f"journal {uid}: {str(e)[:120]}")

    for uid in (snapshot.get("access") or []):
        if dry_run:
            report["access"] += 1
            continue
        try:
            from apex import access
            access.grant(str(uid))
            report["access"] += 1
        except Exception as e:
            report["skipped"].append(f"access {uid}: {str(e)[:120]}")

    # READ BACK. A write that reported success and is not there is the failure
    # mode a restore cannot afford to discover later, so every user record is
    # loaded again and compared. Skipped here rather than in dry-run, which
    # wrote nothing to read.
    if not dry_run:
        for uid in (snapshot.get("users") or {}):
            try:
                if not user_store.load(uid):
                    report["skipped"].append(f"user {uid}: not readable after restore")
                    report["users"] = max(0, report["users"] - 1)
            except Exception as e:
                report["skipped"].append(f"user {uid}: readback failed ({str(e)[:80]})")
                report["users"] = max(0, report["users"] - 1)

    got = {k: report[k] for k in ("users", "journals", "access")}
    report["restored"] = got
    report["failed"] = {k: max(0, expected[k] - got[k]) for k in expected}
    total_missing = sum(report["failed"].values())
    if total_missing == 0 and not report["skipped"]:
        report["result"] = "COMPLETE"
    elif got["users"] == 0 and expected["users"] > 0:
        report["result"] = "FAILED"
    else:
        report["result"] = "PARTIAL"
        report["detail"] = (f"{total_missing} record(s) did not restore — this is "
                            f"NOT a successful restore. Investigate before "
                            f"starting the application.")
    report["next_steps"] = [
        "start the application (reconnects Redis)",
        "the loop reconnects each broker account",
        "the loop discovers real positions and reconciles — broker wins",
        "loops are rebuilt from `active`",
        "entitlement is re-checked at the order gate",
        "ownership leases are acquired fresh, never restored",
    ]
    return report


def _main(argv):
    cmd = (argv[1] if len(argv) > 1 else "").lower()
    if cmd == "dump":
        json.dump(dump(), sys.stdout, indent=2)
        return 0
    if cmd in ("restore", "verify"):
        snap = json.load(sys.stdin)
        if cmd == "verify":
            ok, problems = verify(snap)
            print(json.dumps({"ok": ok, "problems": problems}, indent=2))
            return 0 if ok else 1
        rep = restore(snap, dry_run="--dry-run" in argv)
        print(json.dumps(rep, indent=2))
        # A PARTIAL restore must not exit 0. An operator scripting this needs
        # the shell to tell them, not a field buried in JSON they may not read.
        return 0 if rep.get("result") == "COMPLETE" else 1
    print(__doc__.strip().split("Usage:")[-1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
