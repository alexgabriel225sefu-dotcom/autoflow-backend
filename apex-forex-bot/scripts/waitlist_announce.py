#!/usr/bin/env python3
"""Tell the early-access list that access is opening. Operator tooling.

Run on the service (it needs TOKEN_ENCRYPTION_KEY, RESEND_API_KEY and
A4T_WAITLIST_FROM_EMAIL, which only exist there). Write the message in a text
file first; this tool ships no copy of its own.

    # 1. read what would happen. Changes nothing. This is the default.
    python3 scripts/waitlist_announce.py --campaign launch-1 \\
        --subject "Apex4Traders early access is opening" \\
        --body-file /tmp/launch-1.txt --remove-contact contact@apex4traders.com

    # 2. send ONE real copy to yourself, to read it as the list will
    python3 scripts/waitlist_announce.py ...same flags... --test-to you@example.com --send

    # 3. send, in daily batches. The phrase is printed by step 1.
    python3 scripts/waitlist_announce.py ...same flags... --limit 100 \\
        --send --confirm "SEND launch-1 TO 87"

    # progress, any time
    python3 scripts/waitlist_announce.py --campaign launch-1 --status

Re-running a campaign only reaches people who have not had it. An email whose
outcome is uncertain (timeout, 5xx, a crash mid-send) is HELD, not retried:
look at it, then pass --retry-unknown. A refused one (4xx) comes back with
--retry-failed.

It prints counts and masked addresses only. Do not paste its output anywhere
that you would not paste a mailing list.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import redact                                  # noqa: E402

redact.install()

from apex.platform import waitlist_announce as A         # noqa: E402


def _remove_contact(args):
    return (args.remove_contact
            or os.getenv("A4T_WAITLIST_REMOVE_CONTACT")
            or os.getenv("A4T_WAITLIST_REPLY_TO") or "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", required=True,
                    help="a short id for this mailing, e.g. launch-1")
    ap.add_argument("--subject")
    ap.add_argument("--body-file", help="plain text, written by the owner")
    ap.add_argument("--remove-contact",
                    help="where somebody writes to be taken off the list "
                         "(or A4T_WAITLIST_REMOVE_CONTACT / A4T_WAITLIST_REPLY_TO)")
    ap.add_argument("--status", action="store_true",
                    help="counts for this campaign and nothing else")
    ap.add_argument("--limit", type=int, default=A.DEFAULT_LIMIT,
                    help=f"most emails this run (1-{A.MAX_LIMIT}, default %(default)s)")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without it, nothing is sent")
    ap.add_argument("--confirm", help='the exact phrase a dry run prints')
    ap.add_argument("--test-to", help="send one real copy to this address only")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--retry-unknown", action="store_true",
                    help="also retries entries a crashed run left 'sending'")
    ap.add_argument("--allow-copy-flags", action="store_true",
                    help="send copy the outcome-promise check flagged; only "
                         "after reading it")
    ap.add_argument("--no-lock", action="store_true",
                    help="skip the one-run-at-a-time lease. Only if you are "
                         "certain nothing else is running")
    args = ap.parse_args(argv)

    try:
        if args.status:
            st = A.status(args.campaign)
            print(f"campaign {args.campaign}: " + ", ".join(
                f"{k} {v}" for k, v in st.items()))
            return 0

        if not args.subject or not args.body_file:
            print("--subject and --body-file are required", file=sys.stderr)
            return 2
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
        contact = _remove_contact(args)

        if args.test_to:
            if not args.send:
                print("A test send is a real email to one address. "
                      "Add --send to do it.")
                return 0
            out = A.send_test(args.test_to, args.subject, body, contact,
                              allow_copy_flags=args.allow_copy_flags)
            print(f"test email to {A.mask(args.test_to)}: {out['status']}"
                  + (f" ({out['reason']})" if out.get("reason") else ""))
            return 0 if out["status"] == "sent" else 1

        r = A.run(args.campaign, args.subject, body, remove_contact=contact,
                  limit=args.limit, send=args.send, confirm=args.confirm,
                  retry_failed=args.retry_failed,
                  retry_unknown=args.retry_unknown,
                  allow_copy_flags=args.allow_copy_flags, lock=not args.no_lock)
    except A.AnnounceError as e:
        print(f"refused ({e.code}): {e.detail}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"cannot read the body file: {e.strerror}", file=sys.stderr)
        return 2

    held = r["held"]
    if r["dryRun"]:
        print(f"DRY RUN. Nothing was sent. Campaign {r['campaign']}.")
        print(f"  would send now : {r['planned']}"
              f"   (left for later runs: {r['remaining']})")
        print(f"  held back      : failed {held['failed']}, "
              f"unknown {held['unknown']}, sending {held['sending']}")
        if r["unreadable"]:
            print(f"  !! {r['unreadable']} records could not be decrypted and "
                  f"will not be written to.")
        print(f"  first, masked  : {', '.join(r['sample']) or '—'}")
        print(f"  provider ready : {'yes' if r['providerConfigured'] else 'NO'}")
        print("  reminder       : open/click tracking must be OFF at the provider.")
        print(f"\nTo send exactly this, add:  --send --confirm \"{r['confirmation']}\"")
        return 0

    print(f"campaign {r['campaign']}: sent {r['sent']}, refused {r['failed']}, "
          f"uncertain {r['unknown']}, skipped {r['skipped']}; "
          f"{r['remaining']} left for later runs.")
    if r["stopped"]:
        print("!! stopped early: three in a row did not go through. Check the "
              "provider, then run again.", file=sys.stderr)
    if r["unknown"]:
        print("!! some outcomes are uncertain. They are HELD. Check the "
              "provider's log, then --retry-unknown if they did not go out.",
              file=sys.stderr)
    return 1 if (r["failed"] or r["unknown"] or r["stopped"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
