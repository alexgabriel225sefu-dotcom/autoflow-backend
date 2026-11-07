#!/usr/bin/env python3
"""A read-only check of everything that stands between one client and a live order.

RUN (in a shell on the API service, which has the real settings):
    python3 scripts/live_preflight.py <supabase-user-id>

It READS. It sets nothing, grants nothing, approves nothing, opens nothing and
places no order. It prints no secret and no variable value: each setting is
reported only as set or not set. Exit 0 means every line below is satisfied;
anything else lists what is missing. A line it could not read is "unknown",
and unknown counts as missing.

It does not replace the first real order at the smallest size, and it does not
say a live order WILL be sent: the order gate still decides each order.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OK, MISSING, UNKNOWN = "ok", "MISSING", "unknown"


def _set(name):
    return bool((os.getenv(name) or "").strip())


def collect(user_id):
    """[(label, state, detail)] for one user. Importable for tests."""
    from apex.platform import ctrader_link as link
    from apex.platform import entitlement as ent
    from apex.platform import live_gate as gate
    from apex.platform import live_pilot as pilot

    rows = []

    def add(label, state, detail=""):
        rows.append((label, state, detail))

    def guard(label, fn):
        try:
            return fn()
        except Exception as e:                                # noqa: BLE001
            add(label, UNKNOWN, f"could not be read ({type(e).__name__})")
            return None

    prod = (os.getenv("APP_ENV") or "").strip().lower() in ("prod", "production")
    add("APP_ENV is production", OK if prod else MISSING)
    add("A4T_OPERATOR_USER_IDS lists this user",
        OK if gate.is_operator(user_id) else MISSING,
        "needed to approve and to grant yourself the licence")
    sw = guard("Release switch", ent.live_execution_enabled)
    if sw is not None:
        add("Release switch (A4T_LIVE_EXECUTION)", OK if sw else MISSING,
            "closed by default; owner-only")
    la = guard("Live accounts", link.live_allowed)
    if la is not None:
        add("Live accounts allowed (APEX_ALLOW_LIVE_ACCOUNTS)", OK if la else MISSING)

    for name in ("A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS", "A4T_LIVE_PILOT_MAX_UNITS"):
        add(f"{name} is set", OK if _set(name) else MISSING)

    st = guard("Linked accounts", lambda: link.public_status(user_id))
    if st is not None:
        if not st.get("connected"):
            add("cTrader account linked", MISSING)
        else:
            add("cTrader account linked", OK)
            lives = [a for a in st.get("accounts") or [] if a.get("mode") == "live"]
            add("At least one account is reported as live by cTrader",
                OK if lives else MISSING,
                "unverified accounts do not count")
            sel = st.get("selected") or {}
            add("The selected account is live", OK if sel.get("mode") == "live" else MISSING,
                f"selected: {sel.get('ctid')} ({sel.get('mode')})" if sel else "none selected")
            if sel.get("ctid") is not None:
                refusal = pilot.check_identity(user_id, sel.get("ctid"))
                add("The selected account is in the pilot (user:account pair)",
                    OK if refusal is None else MISSING, refusal[0] if refusal else "")

    verdict = guard("Live gate", lambda: gate.public_verdict(
        user_id, release_switch=bool(sw), live_accounts_allowed=bool(la)))
    if verdict is not None:
        for c in verdict.get("conditions") or []:
            s = c.get("status")
            add(f"Gate: {c.get('code')}", OK if s == "ok" else (UNKNOWN if s == "unknown" else MISSING),
                "" if s == "ok" else (c.get("detail") or "")[:120])
    return rows


def main(argv):
    if len(argv) != 2 or not argv[1].strip():
        print(__doc__)
        return 2
    try:
        rows = collect(argv[1].strip())
    except Exception as e:                                    # noqa: BLE001
        print(f"❓ Could not start ({type(e).__name__}). Run this in a shell on the "
              "API service, which has the real settings and the shared store.")
        return 2
    width = max(len(r[0]) for r in rows)
    for label, state, detail in rows:
        mark = {"ok": "✅", "MISSING": "❌", "unknown": "❓"}[state]
        print(f"{mark} {label.ljust(width)}  {state}" + (f"   {detail}" if detail else ""))
    bad = [r for r in rows if r[1] != OK]
    print()
    if bad:
        print(f"❌ {len(bad)} of {len(rows)} lines are not satisfied. No live order is sent until they are.")
        return 1
    print("✅ Every line is satisfied. A live order is still sent only when the order gate allows it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
