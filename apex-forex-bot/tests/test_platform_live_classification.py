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

# ── 6-8. the account the LOOP holds, not the one selected now ──────────────
# A loop builds its broker once and keeps that account. The checks above read
# the client's CURRENT selection, which can change under a running loop: the
# loop then classified as demo (or as the legacy bot), skipped every live gate,
# and went on placing real-money orders on the account it started with. The
# order gate is now told what the loop is bound to and judges THAT.
_only_if_live = ("LIVE_REFUSED", "LIVE_GUARD_FAILED", "NOT_OWNER",
                 "ENTITLEMENT_UNKNOWN", "LIVE_NOT_RELEASED",
                 "LIVE_MODE_UNCONFIRMED", "LIVE_NOT_ENABLED", "HALTED",
                 "NOT_ENTITLED", "MODE_UNVERIFIED", "NOT_PILOT_ACCOUNT",
                 "PILOT_UNCONFIGURED")
_real_ent = gates.live_entitlement
gates.live_entitlement = lambda uid, u=None: ("allowed", "stubbed for test")


def order(uid, units=1000, **kw):
    # `units` varies where the same demo order is placed twice: an identical
    # request inside the window is the idempotency ledger's to refuse.
    return gates.authorize_order(uid, symbol="EURUSD", side="BUY", units=units,
                                 origin="test", dash={}, **kw)


def reselect(uid, ctid, mode):
    rec = PS._read_strict(CTL._k_conn(uid))
    rec["selectedCtid"], rec["selectedMode"] = ctid, mode
    PS._write(CTL._k_conn(uid), rec)


try:
    print("\n[6] a live loop whose selected account is later changed")
    connect(LIVE_USER, CTL.LIVE)                      # selected 900001, live
    reselect(LIVE_USER, "900002", CTL.DEMO)           # the client re-selects demo
    d, rid = order(LIVE_USER, bound_account="900001", bound_env="live")
    check("the live loop's order is refused", not d.allowed,
          f"{d.reason}: {d.detail}")
    check("by name, as the account having changed",
          d.reason == "ACCOUNT_CHANGED", str(d.reason))
    check("without burning an idempotency claim", rid is None, str(rid))

    connect(LIVE_USER, CTL.LIVE)
    reselect(LIVE_USER, "900001", CTL.DEMO)           # same account, mode now reads demo
    d, rid = order(LIVE_USER, bound_account="900001", bound_env="live")
    check("a record that now says demo does not turn a live loop into a demo order",
          not d.allowed and d.reason != "AUTHORIZED",
          f"{d.reason}: {d.detail}")
    check("it is held to the live gates (a reason only reachable when live)",
          any(k in str(d.reason) for k in _only_if_live), str(d.reason))

    connect(LIVE_USER, CTL.LIVE)
    reselect(LIVE_USER, "900002", CTL.LIVE)           # another live account selected
    d, _ = order(LIVE_USER, bound_account="900001", bound_env="live")
    check("a different LIVE account selected under the loop is refused too",
          d.reason == "ACCOUNT_CHANGED", str(d.reason))

    connect(DEMO_USER, CTL.DEMO)
    d, rid = order(DEMO_USER, units=1100, bound_account="900001", bound_env="demo")
    check("a demo loop on the account that is still selected is untouched",
          d.allowed, f"{d.reason}: {d.detail}")
    d, _ = order(DEMO_USER, units=1200)
    check("and so is a caller that does not say what it is bound to",
          d.allowed, f"{d.reason}: {d.detail}")

    print("\n[7] a platform account disconnected while its loop keeps running")
    connect(LIVE_USER, CTL.LIVE)
    CTL.disconnect(LIVE_USER)
    d, rid = order(LIVE_USER, bound_account="900001", bound_env="live")
    check("a live order from a disconnected platform account is refused",
          not d.allowed and d.reason == "PLATFORM_DISCONNECTED",
          f"{d.reason}: {d.detail}")
    check("without burning a claim", rid is None, str(rid))

    user_store.save(TG_USER, {"id": TG_USER, "paper": False})
    d, _ = order(TG_USER, bound_account="123", bound_env="live")
    check("but a legacy Telegram user trading live is not mistaken for one",
          d.reason not in ("PLATFORM_DISCONNECTED", "LIVE_CLASSIFY_FAILED"),
          f"{d.reason}: {d.detail}")

    print("\n[7b] a disconnect that lands between classification and the guard")
    # Step 0 saw a connected platform account; by the time the live guard reads
    # the record the connection is gone, so the guard has "no opinion" (None).
    # That must not be read as "not mine to answer": the account IS a platform
    # one, and the loop still holds a broker session.
    import types as _types
    connect(LIVE_USER, CTL.LIVE)
    _pkg = sys.modules.get("apex.platform")
    _real_mod = sys.modules.get("apex.platform.live_execution")
    _fake = _types.ModuleType("apex.platform.live_execution")
    _fake.guard_engine_order = lambda *a, **k: None
    sys.modules["apex.platform.live_execution"] = _fake
    _had_attr = hasattr(_pkg, "live_execution")
    _old_attr = getattr(_pkg, "live_execution", None)
    setattr(_pkg, "live_execution", _fake)
    try:
        d, rid = order(LIVE_USER, units=1300, bound_account="900001",
                       bound_env="live")
    finally:
        if _real_mod is not None:
            sys.modules["apex.platform.live_execution"] = _real_mod
        else:
            sys.modules.pop("apex.platform.live_execution", None)
        if _had_attr:
            setattr(_pkg, "live_execution", _old_attr)
        else:
            delattr(_pkg, "live_execution")
    check("a guard with no opinion on a platform account refuses the order",
          not d.allowed and d.reason == "PLATFORM_DISCONNECTED",
          f"{d.reason}: {d.detail}")
    check("and burns no claim", rid is None, str(rid))

    print("\n[7c] a platform account whose record says paper=True but whose loop is bound live")
    # A platform connection always builds a non-simulated broker, so the stored
    # flag cannot make a live-bound loop simulated. The explicit-paper shortcut
    # used to skip the classification for it entirely.
    connect(LIVE_USER, CTL.LIVE)
    user_store.save(LIVE_USER, {"id": LIVE_USER, "paper": True})
    d, rid = order(LIVE_USER, units=1400, bound_account="900001", bound_env="live")
    check("it is held to the live gates (a reason only reachable when live)",
          not d.allowed and any(k in str(d.reason) for k in _only_if_live),
          f"{d.reason}: {d.detail}")
    d, rid = order(LIVE_USER, units=1500, bound_account="900001", bound_env="demo")
    check("while a paper-flagged loop bound to DEMO is still simulated and passes",
          d.allowed, f"{d.reason}: {d.detail}")
    user_store.save(LIVE_USER, {"id": LIVE_USER})

    print("\n[7d] one blip on the second read does not refuse a legacy live order")
    user_store.save(TG_USER, {"id": TG_USER, "paper": False})
    _real_strict2 = PS._read_strict
    _n = {"calls": 0}

    def _flaky(key):
        # the tombstone read in the not-a-platform-account branch fails once
        if "ctrader" in str(key) and _n["calls"] == 1:
            _n["calls"] += 1
            raise RuntimeError("transient")
        _n["calls"] += 1 if "ctrader" in str(key) else 0
        return _real_strict2(key)

    PS._read_strict = _flaky
    try:
        d, _ = order(TG_USER, units=1600, bound_account="123", bound_env="live")
    finally:
        PS._read_strict = _real_strict2
    check("the legacy order is not refused as LIVE_CLASSIFY_FAILED",
          d.reason != "LIVE_CLASSIFY_FAILED", f"{d.reason}: {d.detail}")

    print("\n[7e] an order the broker itself simulates is not refused over a store blip")
    user_store.save(TG_USER, {"id": TG_USER, "paper": True})
    _real_strict3 = PS._read_strict

    def _always_down(key):
        raise RuntimeError("redis is down")

    PS._read_strict = _always_down
    try:
        d, _ = order(TG_USER, units=1700, bound_account="123", bound_env="live",
                     bound_paper=True)
    finally:
        PS._read_strict = _real_strict3
    check("a paper order with the store down is not LIVE_CLASSIFY_FAILED",
          d.reason != "LIVE_CLASSIFY_FAILED", f"{d.reason}: {d.detail}")
    user_store.save(TG_USER, {"id": TG_USER, "paper": False})

    print("\n[7f] a stored paper flag is not the broker: a live-bound platform loop is not exempt")
    # The record says paper, the loop's broker is a real one (a platform
    # connection always builds one, bound_paper False). Neither exemption above
    # may apply: that would be real money with every live gate skipped.
    connect(LIVE_USER, CTL.LIVE)
    user_store.save(LIVE_USER, {"id": LIVE_USER, "paper": True})
    PS._read_strict = _always_down
    try:
        d, rid = order(LIVE_USER, units=1710, bound_account="900001",
                       bound_env="live", bound_paper=False)
        check("store down: refused as LIVE_CLASSIFY_FAILED, not AUTHORIZED",
              not d.allowed and d.reason == "LIVE_CLASSIFY_FAILED",
              f"{d.reason}: {d.detail}")
        d, _ = order(LIVE_USER, units=1711, bound_account="900001", bound_env="live")
        check("and so is a caller that does not say whether its broker simulates",
              not d.allowed and d.reason == "LIVE_CLASSIFY_FAILED",
              f"{d.reason}: {d.detail}")
    finally:
        PS._read_strict = _real_strict3
    CTL.disconnect(LIVE_USER)
    user_store.save(LIVE_USER, {"id": LIVE_USER, "paper": True})
    d, rid = order(LIVE_USER, units=1720, bound_account="900001",
                   bound_env="live", bound_paper=False)
    check("a disconnected platform account with a paper-flagged record: refused "
          "as PLATFORM_DISCONNECTED", not d.allowed and d.reason == "PLATFORM_DISCONNECTED",
          f"{d.reason}: {d.detail}")
    check("without burning a claim", rid is None, str(rid))
    user_store.save(LIVE_USER, {"id": LIVE_USER})

    print("\n[8] a store that cannot be read, for a live loop")
    _real_strict = PS._read_strict

    def _down(key):
        raise RuntimeError("redis is down")

    PS._read_strict = _down
    try:
        d, rid = order(TG_USER, bound_account="123", bound_env="live")
        check("is not read as 'not a platform account'",
              not d.allowed and d.reason == "LIVE_CLASSIFY_FAILED",
              f"{d.reason}: {d.detail}")
        check("and burns no claim", rid is None, str(rid))
    finally:
        PS._read_strict = _real_strict
finally:
    gates.live_entitlement = _real_ent

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All platform live-classification checks passed.")
