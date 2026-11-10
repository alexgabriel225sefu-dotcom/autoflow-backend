"""Rewrite legacy plaintext broker secrets with the active Fernet key.

The API process runs ``run_startup`` once, before it revives trading loops or
accepts requests. The same rewrite is available as a maintenance command:

    python scripts/migrate_sensitive_records.py

Neither path prints record contents, tokens, or account ids. A second run
writes nothing.
"""
import argparse
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import user_store

_PLATFORM_TOKEN_FIELDS = ("accessToken", "refreshToken", "finishToken")
_ATTEMPTS = 5


def _quiet(fn):
    """Run ``fn`` and drop whatever it prints.

    A conflict inside the user-record writer names the user id. That line is
    useful to a person running a one-off repair and is not acceptable on the
    API's boot log, which is allowed to carry counts only.
    """
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        return fn()


def _needs_platform_wrap(raw):
    if not isinstance(raw, dict):
        return False
    for field in _PLATFORM_TOKEN_FIELDS:
        value = raw.get(field)
        if isinstance(value, str) and value and not value.startswith(user_store._ENC_PREFIX):
            return True
    accounts = raw.get("ctrader_accounts")
    if accounts not in (None, [], {}, "") and not (
        isinstance(accounts, str) and accounts.startswith(user_store._ENC_PREFIX)
    ):
        return True
    return False


def _wrap_platform_record(raw):
    changed = False
    out = dict(raw)
    for field in _PLATFORM_TOKEN_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value and not value.startswith(user_store._ENC_PREFIX):
            out[field] = user_store.encrypt_value(value)
            changed = True
    accounts = out.get("ctrader_accounts")
    if accounts not in (None, [], {}, "") and not (
        isinstance(accounts, str) and accounts.startswith(user_store._ENC_PREFIX)
    ):
        out["ctrader_accounts"] = user_store.encrypt_value(
            json.dumps(accounts, separators=(",", ":"), sort_keys=True))
        changed = True
    return out, changed


def _migrate_one_platform(key, *, attempts=_ATTEMPTS):
    """Rewrap one platform record, or return False when it is already clean.

    The write lands only when the stored bytes are still the bytes we read.
    """
    from apex.platform import store as platform_store

    for _ in range(max(1, int(attempts))):
        original = platform_store.read_raw(key)
        if not original:
            return False
        try:
            raw = json.loads(original)
        except (TypeError, ValueError) as exc:
            raise ValueError("platform record is not readable JSON") from exc
        if not isinstance(raw, dict) or not _needs_platform_wrap(raw):
            return False
        updated, changed = _wrap_platform_record(raw)
        if not changed:
            return False
        new_raw = json.dumps(updated, separators=(",", ":"))
        status = platform_store.replace_if_unchanged(key, original, new_raw)
        if status == "written":
            if platform_store.read_raw(key) != new_raw:
                raise user_store.StoreUnavailable(
                    "migration write did not read back")
            return True
        if status == "conflict":
            continue
        if status == "missing":
            return False
        raise user_store.StoreUnavailable("migration write was not confirmed")
    raise user_store.ConflictError("platform record changed during migration")


def migrate_platform_connections(*, strict=True, attempts=_ATTEMPTS):
    """Rewrap legacy cTrader link secrets in the platform namespace."""
    from apex.platform import store as platform_store

    scanned = migrated = failed = 0
    try:
        keys = list(platform_store.all_keys())
    except Exception:
        if strict:
            raise
        return {"scanned": 0, "migrated": 0, "failed": 1}
    for key in keys:
        if ":ctrader:" not in str(key):
            continue
        scanned += 1
        try:
            if _migrate_one_platform(key, attempts=attempts):
                migrated += 1
        except Exception:
            failed += 1
            if strict:
                raise
    return {"scanned": scanned, "migrated": migrated, "failed": failed}


def run_startup(*, limit=100000):
    """Migrate leftover plaintext before the API serves. Never raises.

    Returns counts. Prints counts, or a skip line when there is no Fernet
    key. With no key there is nothing this can rewrite, and leaving the
    records untouched is the behaviour the process already had.
    """
    empty = {"scanned": 0, "migrated": 0, "failed": 0}
    if user_store._fernet is None:
        print("[API] sensitive-record migration skipped: "
              "encryption key is not configured")
        return {"skipped": True, "users": dict(empty), "platform": dict(empty),
                "errors": []}
    users = dict(empty)
    platform = dict(empty)
    errors = []
    try:
        users = _quiet(lambda: user_store.migrate_sensitive_records(
            limit=limit, strict=False))
    except Exception as exc:                                 # noqa: BLE001
        users["failed"] = int(users.get("failed") or 0) + 1
        errors.append(type(exc).__name__)
    try:
        platform = _quiet(lambda: migrate_platform_connections(strict=False))
    except Exception as exc:                                 # noqa: BLE001
        platform["failed"] = int(platform.get("failed") or 0) + 1
        errors.append(type(exc).__name__)
    line = ("[API] sensitive-record migration: "
            f"users scanned={users['scanned']} migrated={users['migrated']} "
            f"failed={users['failed']}; "
            f"platform scanned={platform['scanned']} migrated={platform['migrated']} "
            f"failed={platform['failed']}")
    if errors:
        line += " errors=" + ",".join(errors)
    print(line)
    return {"skipped": False, "users": users, "platform": platform,
            "errors": errors}


def _migrate_both(limit, *, strict):
    result = user_store.migrate_sensitive_records(limit=limit, strict=strict)
    result["platform"] = migrate_platform_connections(strict=strict)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100000,
                        help="maximum records to scan (default: 100000)")
    parser.add_argument("--best-effort", action="store_true",
                        help="continue after a record-level failure")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if user_store._fernet is None:
        print(json.dumps({"reason": "encryption key is not configured",
                          "skipped": True}, sort_keys=True))
        return 0
    try:
        result = _quiet(lambda: _migrate_both(
            args.limit, strict=not args.best_effort))
    except Exception as exc:                                 # noqa: BLE001
        print(json.dumps({"error": type(exc).__name__, "failed": 1},
                         sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 1 if result["failed"] or result["platform"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
