"""A platform account's liveness must come from the BROKER, not from a flag
nobody writes.

THE BUG, AND IT MADE EVERY LIVE GATE IN THE PRODUCT DECORATIVE

`gates.authorize_order` asks one question before almost everything else: is
real money at stake? It answered it with `_live(u)`, which is
`not u.get("paper", True)` — the user record's paper flag.

Only `telegram._handle_paper` ever writes that flag. A platform client's
record has no `paper` key at all, so the answer was False for every platform
account, whatever account they had selected at the broker.

`live` being False is what skips:

  * the broker environment check (step 2)
  * the ownership LIVE lease (step 5)
  * the ledger's fail-closed idempotency claim (step 6)
  * and the whole of step 5b — the release switch, the plan that pays for
    live, the mode as the broker reports it, the order rate limit, and §7's
    audit trail

That is the entire live-safety design, unreachable for exactly the accounts
it was written to protect.

WHY IT LOOKED FINE

No platform client can select a live account today: `select_account` refuses
while the release switch is closed. So the branch was never taken in
production and today's blast radius is nil. The day the switch opens it would
have been total, with every check reporting green — the same shape as every
other bug found this week: a mechanism that cannot fire is indistinguishable
from one that passes.

WHAT THIS FILE ASSERTS

Behaviour, not the presence of a helper. It drives the real
`gates.authorize_order` and asserts that a platform LIVE account is refused
and a platform DEMO account is not refused for a live reason — because the
second half is what Monday's demo test depends on, and a fix that protected
live money by breaking demo trading would be no fix.

Run: python3 tests/test_platform_live_classification.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-liveclass-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
# The release switch stays CLOSED, which is the state production is in and
# the state that makes the assertion below meaningful: a live platform order
# must be refused, and the only thing that can refuse it is a gate that ran.
os.environ.pop("A4T_LIVE_EXECUTION", None)

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import gates, user_store                          # noqa: E402
from apex.platform import ctrader_link as CTL               # noqa: E402
from apex.platform import store as PS                       # noqa: E402

LIVE_USER = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
DEMO_USER = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
TG_USER = "77665544"


def connect(user_id, mode):
    """A connection record as cTrader linking leaves it, minus the OAuth."""
    PS._write(CTL._k_conn(user_id), {
        "userId": user_id,
        "accessToken": "tok-not-a-real-token",
        "refreshToken": "ref-not-a-real-token",
        "expiresAt": 9_999_999_999,
        "accounts": [{"ctid": "900001", "mode": mode, "label": "acct"}],
        "selectedCtid": "900001",
        "selectedMode": mode,
    })


connect(LIVE_USER, CTL.LIVE)
connect(DEMO_USER, CTL.DEMO)

# ── 1. the classification itself ────────────────────────────────────────────
print("\n[1] liveness is read from the selected account's mode")
check("a platform LIVE account classifies live",
      gates._platform_mode(LIVE_USER) == "live",
      str(gates._platform_mode(LIVE_USER)))
check("a platform DEMO account classifies demo",
      gates._platform_mode(DEMO_USER) == "demo",
      str(gates._platform_mode(DEMO_USER)))
check("a legacy Telegram account is not a platform account at all",
      gates._platform_mode(TG_USER) is None,
      str(gates._platform_mode(TG_USER)))

print("\n[2] a mode the broker never confirmed is NOT treated as safe")
# The dangerous default. An account whose environment nobody confirmed is not
# evidence of a demo, and reading absence as DEMO is how a live order gets the
# simulation path.
PS._write(CTL._k_conn(DEMO_USER + "-x"), {
    "userId": DEMO_USER + "-x", "accessToken": "tok",
    "accounts": [], "selectedCtid": "1",
})
check("a connection with no selectedMode reads unknown, not demo",
      gates._platform_mode(DEMO_USER + "-x") == "unknown",
      str(gates._platform_mode(DEMO_USER + "-x")))

# ── 3. THE CONSEQUENCE: the gate actually refuses a live platform order ─────
print("\n[3] a live platform order is refused while the switch is closed")
# This is the half that matters. Section 1 is a claim about a helper, and a
# helper nobody consults is the bug being fixed rather than the fix.
#
# ENTITLEMENT IS STUBBED, DELIBERATELY. Without it both accounts are refused
# NOT_ENTITLED at step 1 — before liveness is consulted at all — and the
# first version of this file "passed" on exactly that: two orders denied for
# a reason that had nothing to do with what was being tested. A harness that
# cannot tell the two accounts apart produces meaningless results for both.
user_store.save(LIVE_USER, {"id": LIVE_USER})
user_store.save(DEMO_USER, {"id": DEMO_USER})
_real_ent = gates.live_entitlement
gates.live_entitlement = lambda uid, u=None: ("allowed", "stubbed for test")
try:
    d_live, rid_live = gates.authorize_order(
        LIVE_USER, symbol="EURUSD", side="BUY", units=1000,
        origin="test", dash={})
    check("it is DENIED", not d_live.allowed,
          f"{d_live.reason}: {d_live.detail}")
    check("and no idempotency claim was burned on the refusal",
          rid_live is None, str(rid_live))
    # The refusal must be one that is UNREACHABLE unless live is True. That is
    # the whole proof: these codes exist only behind `if live`, so seeing one
    # means the classification put this order on the real-money path.
    _only_if_live = ("LIVE_REFUSED", "LIVE_GUARD_FAILED", "NOT_OWNER",
                     "ENTITLEMENT_UNKNOWN", "LIVE_NOT_RELEASED",
                     "LIVE_MODE_UNCONFIRMED")
    check("for a reason only reachable when live is True",
          any(str(d_live.reason).startswith(k) or k in str(d_live.reason)
              for k in _only_if_live),
          str(d_live.reason))

    print("\n[4] and a DEMO platform order still reaches the broker path")
    # Monday's test depends on this. A fix that closed the live hole by
    # stopping demo trading would break the only thing that works today.
    d_demo, rid_demo = gates.authorize_order(
        DEMO_USER, symbol="EURUSD", side="BUY", units=1000,
        origin="test", dash={})
    check("it is AUTHORIZED", d_demo.allowed,
          f"{d_demo.reason}: {d_demo.detail}")
    check("and it did get an idempotency claim", rid_demo is not None)
finally:
    gates.live_entitlement = _real_ent

print("\n[5] a store that cannot be read is not an answer")
# "We could not tell" must never be spent as "no real money here". The
# classifier raises and the gate fails closed.
_real_read = CTL._read_conn


def _boom(uid):
    raise RuntimeError("redis is down")


CTL._read_conn = _boom
try:
    d_err, rid_err = gates.authorize_order(
        LIVE_USER, symbol="EURUSD", side="BUY", units=1000,
        origin="test", dash={})
    check("an unreadable store denies the order", not d_err.allowed,
          f"{d_err.reason}")
    check("and says so by name", d_err.reason == "LIVE_CLASSIFY_FAILED",
          str(d_err.reason))
    check("without burning a claim", rid_err is None, str(rid_err))
finally:
    CTL._read_conn = _real_read

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All platform live-classification checks passed.")
