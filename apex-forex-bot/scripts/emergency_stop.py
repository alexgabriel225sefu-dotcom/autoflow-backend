#!/usr/bin/env python3
"""The switch. Run this from a shell on the service.

    python3 scripts/emergency_stop.py status
    python3 scripts/emergency_stop.py halt --reason "spread blowout" --by alex
    python3 scripts/emergency_stop.py halt --scope live --reason "..." --by alex
    python3 scripts/emergency_stop.py halt --instruments EURUSD,XAUUSD \\
                                           --reason "..." --by alex
    python3 scripts/emergency_stop.py halt --users <user-id> --reason "..." --by alex
    python3 scripts/emergency_stop.py release --by alex

WHY A SCRIPT AND NOT AN ENDPOINT

A route that can stop every client in the product is a route worth attacking,
and the one person who needs it already has a shell. The API only ever READS
this state.

THE OTHER SWITCH

This one lives in the shared store: it takes effect in seconds and needs no
deploy, and it needs the store to be up. The second switch is the environment
variable `A4T_EMERGENCY_HALT`, set on the service, which works when the store
is unreachable and costs a restart. Either halts; neither can clear the other.

If the store is down and you need to stop the product NOW, do not fight this
script — set `A4T_EMERGENCY_HALT=all` on the service and let it restart.

`status` tells you which switch is holding the product down, because the
remedy is different for each.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import redact                                  # noqa: E402

redact.install()

from apex.platform import emergency as E                 # noqa: E402


def _print_state(st):
    scope = st["scope"]
    if scope == E.NONE:
        print("  running — nothing is halted")
    else:
        # Each source names its own remedy. "Held by the store" and "held by
        # the environment" need completely different actions, and an operator
        # reading this is not in a state to go and look it up.
        src = {E.SRC_ENV: f"the {E.ENV_VAR} environment variable on this "
                          f"service (unset it and restart to clear)",
               E.SRC_STORE: "the stored record (clear it with `release`)",
               E.SRC_UNCERTAIN: "the store being UNREACHABLE"}.get(
                   st["source"], st["source"])
        print(f"  HALTED — scope={scope}, held by {src}")
    if not st["storeReachable"]:
        print(f"  !! the shared store could not be read: "
              f"{st.get('storeError')}")
        print("     live accounts are refused while that is true; demo "
              "accounts keep running")
    if st.get("reason"):
        print(f"  reason: {st['reason']}")
    if st.get("by"):
        print(f"  by:     {st['by']}")
    if st["instruments"]:
        print(f"  instruments halted: {', '.join(st['instruments'])}")
    if st["users"]:
        print(f"  clients halted:     {len(st['users'])}")
    # Both halves, always, because "I released it and it is still halted" is
    # the confusing moment this exists to prevent.
    print(f"  env switch:   {st['envScope']}")
    print(f"  store switch: {st['storeScope']}")


def _csv(value):
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="what is halted, and which switch holds it")

    h = sub.add_parser("halt", help="press the stored switch")
    h.add_argument("--scope", default=E.ALL, choices=list(E.SCOPES),
                   help="all = every client; live = live accounts only; "
                        "none = only the named instruments/clients below")
    h.add_argument("--reason", required=True,
                   help="what happened. Somebody reads this at the worst "
                        "possible moment — write it for them")
    h.add_argument("--by", required=True, help="who is pressing it")
    h.add_argument("--instruments", help="comma separated, e.g. EURUSD,XAUUSD")
    h.add_argument("--users", help="comma separated client ids")

    r = sub.add_parser("release", help="clear the stored switch")
    r.add_argument("--by", required=True, help="who is clearing it")

    args = ap.parse_args()

    if args.cmd == "status":
        _print_state(E.state())
        return 0

    if args.cmd == "halt":
        st = E.halt(args.scope, reason=args.reason, by=args.by,
                    instruments=_csv(args.instruments),
                    users=_csv(args.users))
        print("\nHALT IS IN FORCE\n")
        _print_state(st)
        print("\nThis does NOT close open positions. The platform cannot "
              "place orders of any kind, including closing ones — positions "
              "stay at the broker with the stop and target they were given.")
        return 0

    st = E.release(by=args.by)
    print("\nStored switch cleared.\n")
    _print_state(st)
    if st["scope"] != E.NONE:
        # The common confusion: released, still halted, because the other
        # switch is the one holding it.
        print(f"\n!! STILL HALTED. The {E.ENV_VAR} environment variable is "
              f"set to {st['envScope']!r} on this service. Clearing the "
              f"stored record cannot and must not overrule it — unset the "
              f"variable on the service to finish.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
