"""A rule that asks for more than a LIVE account may carry does not start.

WHY THIS EXISTS

The platform's live risk ceiling (1% per trade, `risk_gates.PLATFORM`) was
enforced in `live_execution.place`, a door nothing in production calls. A live
order from the loop takes `live_execution.authorize_order`, which has no rule
in hand, so the ceiling was not on the path a real order takes:

* a rule asking for 5% risk reached a live broker at 5%;
* a rule with a fixed volume (which the engine cannot take) fell back to the
  ACCOUNT's own risk setting, 2.5% by default;
* an exposure ceiling, a slippage ceiling, an order expiry and "close positions
  when a limit is hit" are recorded and not applied. Saying so is honest on a
  demo account; on real money the client is relying on them.

`engine_config.live_refusals` is the check and `automation.start` asks it for a
live account only, before the start lock is taken.

WHAT THESE TESTS WILL NOT ACCEPT

* a live start above the cap, by rule or by the account's fallback;
* a live start carrying a term the engine does not apply;
* a refusal that leaves the lock held, the loop started or the account's
  settings overwritten;
* the same rule being refused on a DEMO account (the cap is for real money);
* an unreadable account record passing the check.

The three live locks are stubbed here only so a start can be attempted. Nothing
opens live execution and no environment value is set.

Run: python3 tests/test_platform_live_rule_guard.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-liverule-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/cb"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("A4T_EMERGENCY_HALT", None)

from apex import user_store                              # noqa: E402
from apex.platform import automation as AU               # noqa: E402
from apex.platform import ctrader_link as CL            # noqa: E402
from apex.platform import engine_config as EC            # noqa: E402
from apex.platform import live_pilot as _pilot          # noqa: E402
from apex.platform import plans as _plans                # noqa: E402
from apex.platform import ruledoc as _rd                 # noqa: E402
from apex.platform import store as _store                # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


USER = "eeeeeeee-2222-4222-8222-eeeeeeeeeeee"
_plans.start_trial(USER)
DEMO_ACC = {"ctid": 901, "live": False}
LIVE_ACC = {"ctid": 902, "live": True}

begun = CL.begin(USER)
state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
CL.handle_callback({"code": "c", "state": state},
                   exchanger=lambda c, u: {"accessToken": "TOK",
                                           "refreshToken": "REF",
                                           "expiresIn": 2592000})
CL.complete(USER, begun["nonce"], lister=lambda a: [DEMO_ACC, LIVE_ACC])


def select(ctid, *, allow_live=False):
    real = CL.live_allowed
    if allow_live:
        CL.live_allowed = lambda: True
    try:
        return CL.select_account(USER, ctid)
    finally:
        CL.live_allowed = real


def make_rule(name, mutate=None):
    doc = _rd.blank(user_id=USER, account_id="902", symbols=["EURUSD"],
                    timeframe="1h")
    doc["name"] = name
    doc["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                                   "value": 30}]
    if mutate:
        mutate(doc)
    _store.create(USER, doc)
    _store.activate(USER, doc["ruleDocId"], known_condition_ids={"rsi"})
    return doc["ruleDocId"]


# ── [1] the pure check ──────────────────────────────────────────────────────
print("\n[1] live_refusals, on its own")
blank = _rd.blank(user_id=USER, account_id="902", symbols=["EURUSD"],
                  timeframe="1h")
check("the builder's own default rule (1%) is allowed",
      EC.live_refusals(blank, {}) == [], str(EC.live_refusals(blank, {})))

import copy  # noqa: E402


def variant(fn):
    d = copy.deepcopy(blank)
    fn(d)
    return d


def codes(doc, acct=None):
    return [c for c, _ in EC.live_refusals(doc, acct or {})]


check("exactly at the cap is allowed (a ceiling, not a count)",
      codes(variant(lambda d: d["sizing"].update(riskPercent=1.0))) == [])
check("a rule asking for 1.01% is refused",
      codes(variant(lambda d: d["sizing"].update(riskPercent=1.01)))
      == ["LIVE_RISK_OVER_CAP"])
check("a rule asking for 5% is refused",
      codes(variant(lambda d: d["sizing"].update(riskPercent=5)))
      == ["LIVE_RISK_OVER_CAP"])


def fixed(d):
    d["sizing"] = {"mode": _rd.SIZING_FIXED, "riskPercent": None,
                   "fixedVolume": 1000}


check("a fixed volume with NO account setting falls back to the engine's "
      "2.5% and is refused",
      codes(variant(fixed)) == ["LIVE_RISK_OVER_CAP"])
check("a fixed volume on an account set to 2% is refused",
      codes(variant(fixed), {"risk": 0.02}) == ["LIVE_RISK_OVER_CAP"])
check("a fixed volume on an account set to 1% is allowed",
      codes(variant(fixed), {"risk": 0.01}) == [])
check("and the message says what to change",
      "Size the rule by risk percentage" in
      EC.live_refusals(variant(fixed), {})[0][1],
      EC.live_refusals(variant(fixed), {})[0][1])

check("an exposure ceiling is refused",
      codes(variant(lambda d: d["limits"].update(maxExposurePercent=10)))
      == ["LIVE_TERM_NOT_ENFORCED"])
check("a slippage ceiling is refused",
      codes(variant(lambda d: d["order"].update(maxSlippagePoints=5)))
      == ["LIVE_TERM_NOT_ENFORCED"])
check("an order expiry is refused",
      codes(variant(lambda d: d["order"].update(expiresAfterSec=60)))
      == ["LIVE_TERM_NOT_ENFORCED"])
check("flatten-on-limit (a stored legacy value) is refused",
      codes(variant(lambda d: d["limits"].update(onLimit="flatten")))
      == ["LIVE_TERM_NOT_ENFORCED"])
check("a spread ceiling is NOT refused: the engine applies it",
      codes(variant(lambda d: d["limits"].update(maxSpreadPips=2))) == [])
check("a daily trade cap is NOT refused: the engine applies it",
      codes(variant(lambda d: d["limits"].update(maxDailyTrades=3))) == [])
many = variant(lambda d: (d["sizing"].update(riskPercent=3),
                          d["limits"].update(maxExposurePercent=10)))
check("several problems are all reported, risk first",
      codes(many) == ["LIVE_RISK_OVER_CAP", "LIVE_TERM_NOT_ENFORCED"],
      str(codes(many)))
try:
    _junk = EC.live_refusals(None, None)
    check("junk in does not raise, and is judged as a rule with no risk "
          "stated (the engine default, over the cap)",
          [c for c, _ in _junk] == ["LIVE_RISK_OVER_CAP"], str(_junk))
except Exception as e:                                       # noqa: BLE001
    check("junk in does not raise", False, f"{type(e).__name__}: {e}")

# ── [2] through automation.start ────────────────────────────────────────────
print("\n[2] automation.start applies it to a LIVE account and only to one")
started = []


def start_with(rid, lister):
    started.clear()
    try:
        AU.start(USER, rid, mode_lister=lister,
                 starter=lambda uid: started.append("GO") or True)
        return None
    except AU.AutomationRefused as e:
        return e


def _allow_live(uid, **kw):
    return {"canAutomate": True, "reason": None, "message": "stubbed",
            "licenceState": "active"}


_real = (CL.live_allowed, AU._ent.require_automation, AU._ent.capability,
         _pilot.check_identity, AU._ent.live_readiness
         if hasattr(AU._ent, "live_readiness") else None)
CL.live_allowed = lambda: True
AU._ent.require_automation = _allow_live
AU._ent.capability = _allow_live
_pilot.check_identity = lambda uid, ctid: None
if hasattr(AU._ent, "live_readiness"):
    AU._ent.live_readiness = lambda uid: {"open": True, "status": "open",
                                         "summary": "stubbed"}
try:
    over = make_rule("five percent", lambda d: d["sizing"].update(riskPercent=5))
    expo = make_rule("exposure", lambda d: d["limits"].update(maxExposurePercent=8))
    fine = make_rule("one percent")

    select(902, allow_live=True)
    before = dict(user_store.load(USER))
    e = start_with(over, lambda t: [LIVE_ACC])
    check("a 5% rule is refused on a live account",
          e is not None and e.code == "LIVE_RISK_OVER_CAP",
          f"{e and e.code} {started}")
    check("the loop was not started", started == [], str(started))
    check("and the account's settings were not overwritten",
          {k: user_store.load(USER).get(k) for k in ("risk", "sl_pips", "active")}
          == {k: before.get(k) for k in ("risk", "sl_pips", "active")})
    check("and no state was recorded as running",
          AU.status(USER).get("state") != AU.RUNNING, str(AU.status(USER).get("state")))
    e = start_with(expo, lambda t: [LIVE_ACC])
    check("an exposure ceiling is refused on a live account",
          e is not None and e.code == "LIVE_TERM_NOT_ENFORCED",
          f"{e and e.code}")
    # The lock was never taken, so an immediate valid start is not blocked.
    e = start_with(fine, lambda t: [LIVE_ACC])
    check("a refusal holds no lock: the next valid start goes ahead",
          e is None and started == ["GO"], f"{e and e.code} {started}")
    AU.stop(USER, stopper=lambda uid: True)

    # An unreadable account record is a refusal, not a pass.
    _real_load = user_store.load
    user_store.load = lambda uid: (_ for _ in ()).throw(RuntimeError("down"))
    try:
        e = start_with(fine, lambda t: [LIVE_ACC])
    finally:
        user_store.load = _real_load
    check("an unreadable account record refuses, and says so",
          e is not None and e.code in ("LIVE_RULE_UNCHECKED", "STORE_UNAVAILABLE")
          and started == [], f"{e and e.code} {started}")

    # The same terms on a DEMO account are the old behaviour: not refused.
    select(901)
    e = start_with(over, lambda t: [DEMO_ACC])
    check("the same 5% rule still starts on a DEMO account",
          e is None and started == ["GO"], f"{e and e.code} {started}")
    AU.stop(USER, stopper=lambda uid: True)
    e = start_with(expo, lambda t: [DEMO_ACC])
    check("and so does the exposure rule",
          e is None and started == ["GO"], f"{e and e.code} {started}")
    AU.stop(USER, stopper=lambda uid: True)
finally:
    CL.live_allowed, AU._ent.require_automation, AU._ent.capability = _real[:3]
    _pilot.check_identity = _real[3]
    if _real[4] is not None:
        AU._ent.live_readiness = _real[4]

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All live rule-guard checks passed.")
