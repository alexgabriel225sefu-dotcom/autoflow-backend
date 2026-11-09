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
    print(json.dumps(result, sort_keys=True))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
