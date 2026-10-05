"""No NEW real-money order on an account whose environment nobody can confirm.

The audit's section 10 asks for a property the order gate did not have.
apex/gates.py decided `live` from the STORED paper flag:

    def _live(user):
        return not (user or {}).get("paper", True)

and never consulted apex/account_mode at all — verified by grepping the module
for "account_mode" and "UNVERIFIED" and finding neither. So an account with
paper=False and no reachable broker resolved to UNVERIFIED for display, while
the gate treated it as live and authorised new orders on it. The failure mode
is opening a real-money position while believing it is a demo.

Two rules now, and the second is the finer one:

  UNVERIFIED            no new orders at all — we do not know what this is
  LIVE from stored-env  no new orders — a stored reading is what we last
                        wrote down, and the reason that source exists is
                        that it can be stale

DEMO is deliberately exempt from the second rule. No real money is at risk,
and stopping demo trading because a status lookup timed out is a cost with no
matching danger.

CLOSES are exempt from both. An existing position must keep being managed
exactly when verification is degraded; refusing to close is the one outcome
worse than refusing to open.

Run: python tests/test_live_execution_safety.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-liveexec-")

from apex import gates, account_mode as am  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


# Entitlement is a separate gate with its own tests. Grant it here so the
# account-mode check is the thing actually under test rather than shadowed by
# an earlier refusal.
_real_entitlement = gates.live_entitlement
gates.live_entitlement = lambda uid, u=None: ("allowed", "test: entitled")

BROKERED = {"paper": False, "ctrader_account_id": 47765456,
            "ctrader_access_token": "test-token"}
GUARD = {"riskGuard": {"halted": False}}
_n = [0]


def order(user):
    """Authorise a NEW order. Symbol varies so the idempotency claim never
    masks the answer we are testing for."""
    _n[0] += 1
    return gates.authorize_order(f"live-safety-{_n[0]}", symbol="EURUSD",
                                 side="BUY", units=1000, origin="test",
                                 user=user, dash=GUARD)[0]


print("\nLIVE EXECUTION SAFETY - five cases at the order gate\n")

print("1. The gate consults the broker environment at all")
import inspect  # noqa: E402
GATES_SRC = inspect.getsource(gates)
check("gates.py references account_mode", "account_mode" in GATES_SRC,
      "the order gate never asks what kind of account this is")
check("…on the OPEN path", "ACCOUNT_MODE_UNVERIFIED" in GATES_SRC)
check("…and distinguishes a stored reading", "LIVE_MODE_UNCONFIRMED" in GATES_SRC)

print("\n2. The five cases")
CASES = (
    ("no broker credentials",     {"paper": False},                        False, "ACCOUNT_MODE_UNVERIFIED"),
    ("broker down + stored live", {**BROKERED, "ctrader_env": "live"},     False, "LIVE_MODE_UNCONFIRMED"),
    ("broker down + stored demo", {**BROKERED, "ctrader_env": "demo"},     True,  None),
    ("paper account",             {"paper": True},                         True,  None),
)
for label, user, should_allow, want_reason in CASES:
    mode, src = am.resolve(user)
    d = order(user)
    if should_allow:
        check(f"{label} ({mode}/{src}) is allowed", d.allowed, f"denied: {d.reason}")
    else:
        check(f"{label} ({mode}/{src}) is refused", not d.allowed, "it was allowed")
        check(f"…with {want_reason}", d.reason == want_reason, f"got {d.reason}")

print("\n3. A broker-confirmed reading is what unlocks real money")
# Seeded straight into the resolver's cache: that is the only state that means
# "the account answered just now", which is exactly the distinction under test.
try:
    am._store(f"{BROKERED['ctrader_account_id']}", am.LIVE)
    mode, src = am.resolve({**BROKERED, "ctrader_env": "live"})
    check("a cached broker answer reports source=broker", src == "broker", f"{mode}/{src}")
    d = order({**BROKERED, "ctrader_env": "live"})
    check("broker-confirmed LIVE may open a new order", d.allowed,
          f"denied: {d.reason} — this would stop legitimate live trading")
finally:
    for attr in ("_CACHE", "_cache"):
        if hasattr(am, attr):
            getattr(am, attr).clear()

print("\n4. Closes are never blocked by an unconfirmed environment")
# Refusing to close is worse than refusing to open: the position exists and is
# taking risk either way.
# Distinct user ids: a close carries its own idempotency claim, and reusing
# one id would answer DUPLICATE_CLOSE for the second probe — a real control,
# but not the one under test here.
for i, (label, user) in enumerate((("UNVERIFIED live account", {"paper": False}),
                                   ("stored-env live account", {**BROKERED, "ctrader_env": "live"}))):
    d = gates.authorize_close(f"close-safety-{i}", symbol="EURUSD",
                              origin="test", user=user)[0]
    check(f"close on an {label} is allowed", d.allowed, f"denied: {d.reason}")

print("\n5. The check sits on the OPEN path only")
open_src = GATES_SRC.split("def authorize_order")[1].split("def authorize_close")[0]
close_src = GATES_SRC.split("def authorize_close")[1]
check("authorize_order carries it", "ACCOUNT_MODE_UNVERIFIED" in open_src)
check("authorize_close does not", "ACCOUNT_MODE_UNVERIFIED" not in close_src,
      "a degraded lookup would prevent closing an open position")

gates.live_entitlement = _real_entitlement

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL LIVE-EXECUTION CHECKS PASSED - no real money on an unconfirmed account.")
