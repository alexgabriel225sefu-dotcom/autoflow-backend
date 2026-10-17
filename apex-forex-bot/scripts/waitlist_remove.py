#!/usr/bin/env python3
"""Take addresses off the early-access list. Operator tooling, run on the
server.

    python3 scripts/waitlist_remove.py a@b.com c@d.com      # ask first
    python3 scripts/waitlist_remove.py --yes a@b.com        # do not ask
    python3 scripts/waitlist_remove.py --suffix .invalid    # every match

WHY THIS EXISTS

Two reasons, and the second is the one that cannot wait.

The list fills with addresses this product's own testing put there, and a
sign-up that was never a person still counts in the only conversion number
the advertising can be judged by.

And somebody who asked to be told when access opens may ask to be forgotten.
A list you can only add to is not a list you can honestly promise to delete
from, whatever the privacy page says.

WHY A SCRIPT AND NOT AN ENDPOINT

The sign-up form is unauthenticated. A public route that deleted by address
would let anyone remove anyone — and, by the difference between "removed"
and "was not there", read the list back one address at a time. This is
reachable only from a shell on the service, which is where the encryption
key lives anyway.

It prints the addresses it is about to remove, because confirming a deletion
you cannot see is not confirming anything. Do not paste its output anywhere.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import redact                                  # noqa: E402

redact.install()

from apex.platform import waitlist as W                  # noqa: E402


def _matching(suffix):
    """Every address on the list ending in `suffix`.

    Read from the export rather than guessed, so the script can only remove
    something that is actually there and the operator sees the real list
    before anything happens.
    """
    return sorted(e["email"] for e in W.export()["entries"]
                  if e["email"].endswith(suffix))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("emails", nargs="*", help="addresses to remove")
    ap.add_argument("--suffix",
                    help="also remove every address ending in this, e.g. "
                         "'@apex4traders.invalid' for test sign-ups")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    args = ap.parse_args()

    targets = list(args.emails)
    if args.suffix:
        targets += [a for a in _matching(args.suffix) if a not in targets]

    if not targets:
        print("Nothing to remove.", file=sys.stderr)
        # Not a failure: "the suffix matched nobody" is a legitimate answer,
        # and a non-zero exit would make a scheduled cleanup look broken.
        return 0

    print(f"{len(targets)} address(es) to remove from the early-access list:")
    for a in targets:
        print(f"  {a}")

    if not args.yes:
        # Deletion is the one thing here that cannot be undone — the record is
        # gone and the address was never stored anywhere else.
        reply = input("\nRemove these? Type 'yes' to confirm: ").strip()
        if reply != "yes":
            print("Nothing was removed.")
            return 1

    removed = absent = refused = 0
    for a in targets:
        try:
            out = W.remove(a)
        except W.WaitlistError as e:
            # One bad address must not abandon the rest: the others were
            # named by the operator and are still waiting to be removed.
            print(f"  refused {a}: {e.code}", file=sys.stderr)
            refused += 1
            continue
        if out["status"] == "removed":
            removed += 1
        else:
            absent += 1

    print(f"\nremoved {removed}, already absent {absent}, refused {refused}")
    print(f"{W.count()} remain on the list")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
