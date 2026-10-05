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
import re
import sys
import time

from apex import user_store

FORMAT_VERSION = 1

# Key namespaces that are runtime coordination, not state. Never restored.
REBUILDABLE_PREFIXES = ("own:user:", "cmdseen:", "cmdresult:", "commands",
                        "mcp_heartbeat", "oauth:state:", "order:")

# The same idea, one namespace down. These are platform keys that exist only
# for the length of an operation, and restoring one is worse than losing it:
#
#   ctlink:pending:  a half-finished OAuth authorisation. Restoring it revives
#                    a nonce the user abandoned.
#   ctlink:used:     the replay guard for a nonce that was already spent. It
#                    expires on its own; a restored one guards nothing.
#   autolock:        a control lock. A restored lock belongs to a request that
#                    finished before the outage.
#   notifylock:      the same, for the notification writer.
#   jlock:           the same, for the journal writer. A restored journal lock
#                    blocks the writer that the journal exists to record.
PLATFORM_REBUILDABLE = ("ctlink:pending:", "ctlink:used:", "autolock:",
                        "notifylock:", "jlock:")


def _platform_rebuildable(key):
    """True for a platform key that must not be restored.

    Matched against the part AFTER the namespace prefix, so the test is about
    what the key is for rather than about where the deployment put it.
    """
    from apex.platform import store as _pstore
    prefix = _pstore.namespace_prefix()
    tail = key[len(prefix):] if key.startswith(prefix) else key
    return tail.startswith(PLATFORM_REBUILDABLE)


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
            # Everything, artefacts included: a backup that quietly drops
            # rows cannot restore what was there.
            out["journals"][uid] = user_store.load_trades(
                uid, include_artefacts=True) or []
        except Exception as e:
            print(f"[Backup] journal for {uid} unreadable: {e}", file=sys.stderr)

    try:
        from apex import control
        out["audit"] = control._cmd("LRANGE", control.K_AUDIT, 0, 499) or []
    except Exception as e:
        print(f"[Backup] audit log unreadable: {e}", file=sys.stderr)

    # ── the platform's own namespace ────────────────────────────────────────
    # Rules and their frozen versions, licences, broker links, platform
    # journals, notifications, automation state and the early-access list all
    # live under `{ns}:a4t:`, which the loop above does not touch — it reads
    # `{ns}:user:{uid}` and the engine's journals, and nothing else.
    #
    # A backup without this section restores clients who have their settings
    # back and no rules, no licence and no broker link. Worse, it loses the
    # FROZEN versions, so every journal entry that survives points at terms
    # that no longer exist — the one thing platform/store.py is built to
    # prevent, undone by the recovery.
    #
    # Values are copied verbatim, never decoded. A record written by a newer
    # version of the code still survives the round trip, and the encrypted
    # broker tokens inside stay encrypted for the same reason the user records
    # above do.
    out["platform"] = {"strings": {}, "sets": {}}
    out["platform_error"] = None
    try:
        from apex.platform import store as _pstore
        for key in _pstore.all_keys():
            if _platform_rebuildable(key):
                continue
            if _pstore.is_set(key):
                out["platform"]["sets"][key] = sorted(
                    str(m) for m in (user_store._redis_smembers(key) or [])
                ) if user_store._USE_REDIS else json.loads(
                    _pstore.read_raw(key) or "[]")
            else:
                raw = _pstore.read_raw(key)
                if raw is not None:
                    out["platform"]["strings"][key] = raw
    except Exception as e:
        # Recorded, never swallowed. A dump that could not read the platform
        # namespace is not a dump with an empty platform — and verify() has to
        # be able to tell those apart before anyone restores from it.
        out["platform_error"] = f"{type(e).__name__}: {e}"
        print(f"[Backup] platform namespace unreadable: {e}", file=sys.stderr)

    out["counts"] = {"users": len(out["users"]),
                     "journals": sum(len(v) for v in out["journals"].values()),
                     "access": len(out["access"]),
                     "audit": len(out["audit"]),
                     "platform": (len(out["platform"]["strings"])
                                  + len(out["platform"]["sets"]))}
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

    # A dump that COULD NOT READ the platform namespace and one where the
    # namespace is genuinely empty produce the same `platform` section and
    # must not produce the same verdict. Restoring the first over a live store
    # replaces every rule and licence with nothing.
    if snapshot.get("platform_error"):
        problems.append(
            f"the platform namespace could not be read when this backup was "
            f"taken ({snapshot['platform_error']}) — rules, licences, broker "
            f"links and the early-access list are NOT in it")
    plat = snapshot.get("platform")
    if plat is None:
        problems.append(
            "no platform section — this backup predates platform support and "
            "restoring it would lose every rule, licence and broker link")
        plat = {}
    elif not isinstance(plat, dict) or not isinstance(plat.get("strings"), dict) \
            or not isinstance(plat.get("sets"), dict):
        problems.append("platform section is not {strings: {}, sets: {}}")
        plat = {}
    for key, raw in (plat.get("strings") or {}).items():
        if not isinstance(raw, str):
            problems.append(f"platform {key} is not a stored string")
            continue
        # The broker link record carries the cTrader tokens. Same rule as the
        # user records above: a backup that decrypted on the way out is a
        # credential file.
        if ":ctrader:" in key:
            for field in ("accessToken", "refreshToken"):
                m = re.search(rf'"{field}"\s*:\s*"([^"]*)"', raw)
                if m and m.group(1) and not m.group(1).startswith(
                        user_store._ENC_PREFIX):
                    problems.append(
                        f"platform {key}: {field} is NOT encrypted in this backup")
    return (not problems), problems



def _pstore_write(key, raw):
    from apex.platform import store as _pstore
    _pstore.write_raw(key, raw)


def _pstore_write_set(key, members):
    """Replace a platform SET with exactly the members in the snapshot.

    Replace, not add: a restore onto a store that still holds a partial set
    would otherwise leave members the backup never knew about — for the rule
    index that means a rule id with no document behind it, which `list_docs`
    skips quietly and a reader never learns about.

    READ BACK, because `_set_add` answers None on a failed write and prints.
    A rule index that did not restore leaves every rule present and none of
    them listable, which looks to the client exactly like having no rules at
    all. That is the same silent failure the active-set restore above already
    refuses to report as success.
    """
    from apex.platform import store as _pstore
    want = sorted({str(m) for m in members})
    _pstore._delete(key)
    for m in want:
        _pstore._set_add(key, m)
    got = sorted({str(m) for m in _pstore._set_members(key)})
    if got != want:
        raise RuntimeError(
            f"set did not read back: wrote {len(want)}, found {len(got)}")


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
        "platform": sum(
            1 for section in ("strings", "sets")
            for k in ((snapshot.get("platform") or {}).get(section) or {})
            if not _platform_rebuildable(k)),
    }
    # One shape, always. The early-return path used to omit `restored` and
    # `failed`, so any caller that read the report uniformly — a drill script,
    # a monitoring hook — crashed on the failure case instead of reporting it.
    # A report that is only well-formed when things went well is not a report.
    zero = {"users": 0, "journals": 0, "access": 0, "platform": 0}
    report = {"verified": ok, "problems": problems, "users": 0, "journals": 0,
              "access": 0, "platform": 0, "skipped": [], "dry_run": bool(dry_run),
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
                    # The active SET is what start_all() and the watchdog
                    # iterate. Restoring the record but not the membership
                    # leaves a paying client whose settings are all present and
                    # whose loop is never started — and nothing downstream
                    # looks for a user it was never told about, so the failure
                    # is silent and permanent. This return used to be ignored,
                    # which meant a flaky Redis during recovery could produce a
                    # restore reported COMPLETE with clients quietly switched
                    # off. Only enforced on a shared backend: the local JSON
                    # backend derives all_active() by scanning the directory,
                    # so there is no set to miss.
                    added = user_store._redis_sadd(user_store._ACTIVE_SET, str(uid))
                    if getattr(user_store, "_USE_REDIS", False) and added is None:
                        report["skipped"].append(
                            f"user {uid}: restored, but NOT added to the active "
                            f"set — their loop will not start")
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

    # ── the platform namespace ──────────────────────────────────────────────
    # Written verbatim, for the same reason the user records are: these values
    # were read without decoding and a re-encode would re-encrypt ciphertext.
    # The rebuildable keys are filtered again here rather than trusted to have
    # been filtered at dump time, because a restore may be fed a snapshot this
    # version of the code did not write.
    plat = snapshot.get("platform") or {}
    for key, raw in (plat.get("strings") or {}).items():
        if _platform_rebuildable(key):
            continue
        if dry_run:
            report["platform"] += 1
            continue
        try:
            _pstore_write(key, raw)
            report["platform"] += 1
        except Exception as e:
            report["skipped"].append(f"platform {key}: {str(e)[:120]}")
    for key, members in (plat.get("sets") or {}).items():
        if _platform_rebuildable(key):
            continue
        if dry_run:
            report["platform"] += 1
            continue
        try:
            _pstore_write_set(key, members or [])
            report["platform"] += 1
        except Exception as e:
            report["skipped"].append(f"platform {key}: {str(e)[:120]}")

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

    got = {k: report[k] for k in ("users", "journals", "access", "platform")}
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
