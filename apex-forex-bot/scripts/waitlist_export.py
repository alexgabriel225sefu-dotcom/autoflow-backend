#!/usr/bin/env python3
"""Read the early-access list. Operator tooling, run on the server.

    python3 scripts/waitlist_export.py            # a count and the addresses
    python3 scripts/waitlist_export.py --count    # the number only
    python3 scripts/waitlist_export.py --csv      # email,joinedAt,source

WHY A SCRIPT AND NOT AN ENDPOINT

There is no admin role in this platform. Adding one so the owner can read a
mailing list would mean adding a privilege that, once it exists, is the thing
worth stealing — and it would be reachable from the internet, where this is
reachable only from a shell on the service.

The addresses are stored encrypted, so this needs TOKEN_ENCRYPTION_KEY, which
means it only works where the data lives. It prints personal data by design:
do not paste its output anywhere, and do not redirect it into the repository.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import redact                                  # noqa: E402

redact.install()

from apex.platform import waitlist as W                  # noqa: E402


def _when(stamp):
    if not stamp:
        return "—"
    return datetime.fromtimestamp(int(stamp), timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", action="store_true",
                    help="print the number of sign-ups and nothing else")
    ap.add_argument("--csv", action="store_true",
                    help="machine-readable, for an import elsewhere")
    args = ap.parse_args()

    if args.count:
        print(W.count())
        return 0

    dump = W.export()
    entries = dump["entries"]

    if args.csv:
        print("email,joinedAt,source")
        for e in entries:
            # No quoting games: an address containing a comma would not have
            # passed validation, and a source is one of three known words.
            print(f"{e['email']},{e['joinedAt']},{e['source']}")
    else:
        print(f"{len(entries)} on the early-access list\n")
        width = max((len(e["email"]) for e in entries), default=5)
        for e in entries:
            print(f"  {e['email']:<{width}}  {_when(e['joinedAt'])}  "
                  f"{e['source']}")

    # An index entry whose record is gone is reported, never quietly dropped:
    # a list that silently loses people looks exactly like a list nobody
    # joined.
    bad = 0
    if dump["unresolved"]:
        print(f"\n!! {len(dump['unresolved'])} index entries have no record. "
              f"Somebody joined and their record is missing.", file=sys.stderr)
        bad = 1
    if dump.get("unreadable"):
        print(f"\n!! {len(dump['unreadable'])} records could not be decrypted. "
              f"TOKEN_ENCRYPTION_KEY is probably not the key they were "
              f"written with — these are real sign-ups, not empty rows.",
              file=sys.stderr)
        bad = 1
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
