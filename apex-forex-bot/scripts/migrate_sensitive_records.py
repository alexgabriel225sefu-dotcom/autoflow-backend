"""Rewrite legacy plaintext user secrets with the active Fernet key.

Run from ``apex-forex-bot`` with the production store environment already
loaded. The script never prints record contents, tokens, or account ids.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import user_store


def migrate_platform_connections(*, strict=True):
    """Rewrap legacy cTrader link secrets in the platform namespace."""
    from apex.platform import store as platform_store

    scanned = migrated = failed = 0
    for key in platform_store.all_keys():
        if ":ctrader:" not in str(key):
            continue
        scanned += 1
        try:
            raw = platform_store._read_strict(key)
            if not isinstance(raw, dict):
                continue
            changed = False
            for field in ("accessToken", "refreshToken", "finishToken"):
                value = raw.get(field)
                if isinstance(value, str) and value and not value.startswith(user_store._ENC_PREFIX):
                    raw[field] = user_store.encrypt_value(value)
                    changed = True
            accounts = raw.get("ctrader_accounts")
            if accounts not in (None, [], {}, "") and not (
                isinstance(accounts, str) and accounts.startswith(user_store._ENC_PREFIX)
            ):
                raw["ctrader_accounts"] = user_store.encrypt_value(
                    json.dumps(accounts, separators=(",", ":"), sort_keys=True))
                changed = True
            if changed:
                platform_store._write_strict(key, raw)
                migrated += 1
        except Exception:
            failed += 1
            if strict:
                raise
    return {"scanned": scanned, "migrated": migrated, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100000,
                        help="maximum records to scan (default: 100000)")
    parser.add_argument("--best-effort", action="store_true",
                        help="continue after a record-level failure")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    result = user_store.migrate_sensitive_records(
        limit=args.limit, strict=not args.best_effort)
    result["platform"] = migrate_platform_connections(strict=not args.best_effort)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["failed"] or result["platform"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
