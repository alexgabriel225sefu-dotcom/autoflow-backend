"""The account mode has to come from the broker, at the moment it matters.

§3 of docs/LIVE_EXECUTION_SPECIFICATION.md. `select_account` records what
cTrader said when the account was LINKED. For demo that is enough — being
wrong means refusing a practice account. For real money it is not: a link
record can be months old, and "is this real money?" must be answered by the
party that knows, now.

The assertions that matter here are the ones about NOT knowing. `unknown`
must never fold into demo or live, a failed read must never fall back to the
stored value, and a mode that disagrees with the record must stop rather than
adapt.

Run: python3 tests/test_platform_mode_verify.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-mode-")
os.environ["DATA_DIR"] = _TMP
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

from apex.platform import automation as AU              # noqa: E402
from apex.platform import ctrader_link as CL            # noqa: E402
from apex.platform import ruledoc as _rd                # noqa: E402
from apex.platform import store as _store               # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


USER = "dddddddd-1111-4111-8111-dddddddddddd"
DEMO_ACC = {"ctid": 801, "live": False}
LIVE_ACC = {"ctid": 802, "live": True}


def connect(accounts):
    begun = CL.begin(USER)
    state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
    CL.handle_callback({"code": "c", "state": state},
                       exchanger=lambda c, u: {"accessToken": "TOK",
                                               "refreshToken": "REF",
                                               "expiresIn": 2592000})
    return CL.complete(USER, begun["nonce"], lister=lambda a: accounts)


def select(ctid, *, allow_live=False):
    real = CL.live_allowed
    if allow_live:
        CL.live_allowed = lambda: True
    try:
        return CL.select_account(USER, ctid)
    finally:
        CL.live_allowed = real


print("\n[1] nothing connected, nothing selected")
v = CL.verify_selected_mode(USER)
check("no connection reads unknown", v["mode"] == CL.UNKNOWN, v["mode"])
check("and is not claimed as verified", v["verified"] is False)
check("and says why", "connected" in (v["reason"] or ""), str(v["reason"]))

connect([DEMO_ACC, LIVE_ACC])
v = CL.verify_selected_mode(USER)
check("connected but nothing selected is unknown too",
      v["mode"] == CL.UNKNOWN, v["mode"])
check("and says THAT, not the other thing",
      "selected" in (v["reason"] or ""), str(v["reason"]))

print("\n[2] the broker's answer is the answer")
select(801)
v = CL.verify_selected_mode(USER, lister=lambda t: [DEMO_ACC, LIVE_ACC])
check("a demo account verifies as demo", v["mode"] == CL.DEMO, v["mode"])
check("and is marked verified", v["verified"] is True)
check("and nothing changed", v["changed"] is False)

print("\n[3] a broker that will not answer is UNKNOWN, never the record")
# The whole point. Falling back to the stored value is exactly the behaviour
# this function exists to replace.
for lister, why in (
    (lambda t: (_ for _ in ()).throw(RuntimeError("socket closed")),
     "the broker raised"),
    (lambda t: [], "the broker returned nothing"),
    (lambda t: [{"ctid": 999, "live": False}], "our account is not listed"),
    (lambda t: [{"ctid": 801}], "the live flag is missing"),
):
    v = CL.verify_selected_mode(USER, lister=lister)
    check(f"unknown when {why}", v["mode"] == CL.UNKNOWN, f"{v['mode']} {v}")
    check(f"...and not verified when {why}", v["verified"] is False)
    check(f"...and NOT the recorded demo when {why}",
          v["mode"] != v["recorded"] or v["recorded"] is None,
          f"fell back to {v['recorded']!r}")
    check(f"...and not reported as a change when {why}",
          v["changed"] is False,
          "a failed read is not a mode change — it would stop a loop over a "
          "network blip")

print("\n[4] a mode that disagrees with the record is a CHANGE, and verified")
v = CL.verify_selected_mode(USER, lister=lambda t: [{"ctid": 801, "live": True}])
check("the broker's live answer wins over a recorded demo",
      v["mode"] == CL.LIVE, v["mode"])
check("it is verified", v["verified"] is True)
check("and flagged as changed", v["changed"] is True)
check("with the record still visible for the message",
      v["recorded"] == CL.DEMO, str(v["recorded"]))

print("\n[5] verification does not WRITE the mode")
# select_account stays the only writer — §3.5. If verification wrote, a
# broker blip would rewrite the client's stored account state.
before = _store._read(CL._k_conn(USER))
CL.verify_selected_mode(USER, lister=lambda t: [{"ctid": 801, "live": True}])
after = _store._read(CL._k_conn(USER))
check("the stored selectedMode is untouched",
      before.get("selectedMode") == after.get("selectedMode") == CL.DEMO,
      f"{before.get('selectedMode')} -> {after.get('selectedMode')}")

src = open(os.path.join(ROOT, "apex", "platform", "ctrader_link.py"),
           encoding="utf-8").read()
_fn = src[src.index("def verify_selected_mode("):src.index("def access_token_for(")]
check("and the function contains no write at all",
      "_store._write" not in _fn and "selectedMode\"] =" not in _fn)

print("\n[6] the start path refuses on anything but a verified demo")
_doc = _rd.blank(user_id=USER, account_id="801", symbols=["EURUSD"],
                 timeframe="1h")
_doc["name"] = "mode rule"
_doc["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                               "value": 30}]
rid = _doc["ruleDocId"]
_store.create(USER, _doc)
_store.activate(USER, rid, known_condition_ids={"rsi"})

started = []


def start_with(lister):
    started.clear()
    try:
        AU.start(USER, rid, mode_lister=lister,
                 starter=lambda uid: started.append("GO") or True)
        return None
    except AU.AutomationRefused as e:
        return e


e = start_with(lambda t: [DEMO_ACC, LIVE_ACC])
check("a verified demo account starts", e is None and "GO" in started,
      f"{e and e.code} {started}")
AU.stop(USER, stopper=lambda uid: True)

e = start_with(lambda t: (_ for _ in ()).throw(RuntimeError("down")))
check("a broker that will not answer refuses the start", e is not None)
check("with MODE_UNVERIFIED, not with a live refusal",
      e and e.code == "MODE_UNVERIFIED", e and e.code)
check("and nothing was started", "GO" not in started, str(started))
check("and the message carries the broker's reason",
      e and "RuntimeError" in str(e), str(e)[:120])

e = start_with(lambda t: [{"ctid": 801, "live": True}])
check("an account that is live at the broker refuses", e is not None)
check("and nothing was started", "GO" not in started, str(started))

print("\n[7] the stored record alone cannot authorise a start")
# The scenario §3 is about: the record says demo because that was true when
# the account was linked, and the broker now says otherwise. Without this
# check, the two locks above both pass — they both read the record.
conn = _store._read(CL._k_conn(USER))
check("the record still says demo", conn.get("selectedMode") == CL.DEMO,
      str(conn.get("selectedMode")))
e = start_with(lambda t: [{"ctid": 801, "live": True}])
check("and the start is refused anyway", e is not None,
      "the record was trusted — that is the defect §3 describes")
check("and nothing was started", "GO" not in started, str(started))

print("\n[7b] 'demo' without 'verified' is still refused")
# A mutation that dropped the `verified` test from the start path survived
# every assertion above, because no path in verify_selected_mode currently
# returns DEMO unverified — the guard is defence in depth against a future
# change, and an unproven guard is the thing this project keeps finding.
# So it is driven directly.
_real_verify = CL.verify_selected_mode
CL.verify_selected_mode = lambda uid, **kw: {
    "mode": CL.DEMO, "verified": False, "recorded": CL.DEMO,
    "ctid": 801, "at": 0.0, "reason": "stubbed: said demo, proved nothing",
    "changed": False}
try:
    e = start_with(lambda t: [DEMO_ACC])
    check("a demo answer that was not verified refuses the start",
          e is not None, "it started on an unverified mode")
    check("with MODE_UNVERIFIED", e and e.code == "MODE_UNVERIFIED",
          e and getattr(e, "code", e))
    check("and nothing was started", "GO" not in started, str(started))
finally:
    CL.verify_selected_mode = _real_verify

print("\n[8] resume re-verifies too")
# Resuming is a fresh start, not the undoing of a pause — a mode can change
# while automation sits paused.
started.clear()
AU.start(USER, rid, mode_lister=lambda t: [DEMO_ACC],
         starter=lambda uid: started.append("GO") or True)
AU.pause(USER, stopper=lambda uid: True)
try:
    AU.resume(USER, mode_lister=lambda t: [{"ctid": 801, "live": True}],
              starter=lambda uid: started.append("RESUMED") or True)
    check("resuming onto a live account is refused", False, "it resumed")
except AU.AutomationRefused as e:
    check("resuming onto a live account is refused", True)
check("and nothing was resumed", "RESUMED" not in started, str(started))
AU.stop(USER, stopper=lambda uid: True)

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All mode-verification checks passed.")
