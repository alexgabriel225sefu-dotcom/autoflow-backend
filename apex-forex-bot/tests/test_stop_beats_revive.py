"""A Stop the client pressed is not undone by the supervisor reviving the loop.

THE FINDING (independent security review, 23 Oct 2026, automation.py stop)

`stop()` halted the loop first and wrote STOPPED last, without taking the start
lock. A supervisor cycle that had already picked the account up saw the record
still saying RUNNING and the loop gone, and restarted it. The late STOPPED
write then reported "Automation is stopped" over a loop that was trading again.
On the Emergency button that is the worst possible answer.

WHAT THESE TESTS WILL NOT ACCEPT

* A revive that lands while a stop is halting the loop.
* A revive that was already starting when the stop arrived, and that then
  writes RUNNING over the stop.
* A revive of an account whose record says STOPPED.
* A stop whose halt FAILED leaving the record saying STOPPED over a loop that
  may still be running.

Run: python3 tests/test_stop_beats_revive.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-stoprevive-")
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

from apex import user_store                             # noqa: E402
from apex.brokers import ctrader as _ct_broker          # noqa: E402
from apex.platform import automation as AU              # noqa: E402
from apex.platform import ctrader_link as CL            # noqa: E402
from apex.platform import plans as _plans               # noqa: E402
from apex.platform import ruledoc as _rd                # noqa: E402
from apex.platform import store as _store              # noqa: E402

_ct_broker.list_accounts = lambda token: [{"ctid": 901, "live": False}]

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def fresh_user(n):
    """A connected demo account with an active rule, from scratch."""
    uid = f"dddd0000-0000-4000-8000-{n:012d}"
    begun = CL.begin(uid)
    state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
    CL.handle_callback({"code": "c", "state": state},
                       exchanger=lambda c, u: {"accessToken": "TOK",
                                               "refreshToken": "REF",
                                               "expiresIn": 2592000})
    CL.complete(uid, begun["nonce"],
                lister=lambda a: [{"ctid": 901, "live": False}])
    CL.select_account(uid, 901)
    _plans.start_trial(uid)
    user_store.save(uid, {"symbol": "GBPUSD", "timeframe": "5m"})
    doc = _rd.blank(user_id=uid, account_id="901", symbols=["EURUSD"],
                    timeframe="4h")
    doc["name"] = "stop beats revive"
    doc["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                                   "value": 30}]
    doc["sides"] = "BUY"
    doc["sizing"] = {"mode": _rd.SIZING_RISK, "riskPercent": 0.25,
                     "fixedVolume": None}
    doc["stopLoss"] = {"mode": "pips", "atrMultiple": None, "pips": 77}
    doc["takeProfit"] = {"mode": "pips", "rr": None, "pips": 155}
    doc["limits"] = {"maxOpenPositions": 1, "maxDailyTrades": 2,
                     "maxExposurePercent": None, "maxSpreadPips": None,
                     "onLimit": "block"}
    rid = doc["ruleDocId"]
    _store.create(uid, doc)
    _store.activate(uid, rid, known_condition_ids={"rsi"})
    return uid, rid


def state_of(uid):
    return AU._read(uid).get("state")


def active_of(uid):
    return (user_store.load(uid) or {}).get("active")


def ok_starter(uid):
    user_store.update(uid, {"active": True})      # what user_loop.start does
    return True


# ── 1. control: a revive DOES happen when the record says RUNNING ───────────
print("\n[1] control: a supervisor cycle revives a RUNNING account whose loop is gone")
uid, rid = fresh_user(1)
AU.start(uid, rid, starter=ok_starter)
calls = []
_real_all = user_store.all_active
user_store.all_active = lambda: [uid]
try:
    alive, revived = AU.supervise(starter=lambda u: calls.append(u) or ok_starter(u))
    check("the harness can see a revive", revived == 1 and calls == [uid],
          f"{alive}/{revived} {calls}")

    # ── 2. the gap inside stop() ────────────────────────────────────────────
    print("\n[2] a supervisor cycle that lands WHILE stop() is halting does not revive")
    uid, rid = fresh_user(2)
    AU.start(uid, rid, starter=ok_starter)
    during = {}

    def stopper_with_supervisor_in_the_gap(u):
        # This is the instant the review found: the loop is being halted and the
        # supervisor, which took its snapshot of active accounts a moment ago,
        # looks at the account.
        during["state"] = state_of(u)
        revived_calls = []
        during["revived"] = AU.supervise(
            starter=lambda x: revived_calls.append(x) or ok_starter(x))[1]
        during["calls"] = revived_calls
        return True

    res = AU.stop(uid, stopper=stopper_with_supervisor_in_the_gap)
    check("the record already said STOPPED while the loop was being halted",
          during.get("state") == "stopped", str(during.get("state")))
    check("so the supervisor revived nothing", during.get("revived") == 0
          and during.get("calls") == [], str(during))
    check("and the stop is reported", res.get("stopped") is True, str(res))
    check("the record ends STOPPED", state_of(uid) == "stopped", state_of(uid))

    print("\n[2b] a RUNNING write that lands after the stop is repaired")
    # The last window: a start that read RUNNING just before the stop wrote
    # STOPPED, and writes RUNNING just after. stop() halts again, looks at the
    # record, and puts its own intent back.
    uid, rid = fresh_user(22)
    AU.start(uid, rid, starter=ok_starter)
    halts = []

    def stopper_late_start_overwrites(u):
        halts.append(1)
        if len(halts) == 2:                 # the settle pass: the late write lands
            rec = AU._read(u)
            rec["state"], rec["ruleDocId"] = "running", rid
            AU._write(u, rec)
        return True

    AU.stop(uid, stopper=stopper_late_start_overwrites)
    check("the record is STOPPED again", state_of(uid) == "stopped", state_of(uid))
    check("and the loop was halted once more after the overwrite",
          len(halts) >= 3, str(len(halts)))

    # ── 3. a revive already in flight when the stop arrives ─────────────────
    print("\n[3] a revive that was already starting does not write RUNNING over a stop")
    uid, rid = fresh_user(3)
    AU.start(uid, rid, starter=ok_starter)

    def starter_overtaken_by_a_stop(u):
        ok_starter(u)                               # the engine comes up ...
        AU.stop(u, stopper=lambda x: True)          # ... and the client presses Stop
        return True

    refused = None
    try:
        AU.start(uid, rid, starter=starter_overtaken_by_a_stop, revive=True)
    except AU.AutomationRefused as e:
        refused = e.code
    check("the revive gives way", refused == "STOPPED_MEANWHILE", str(refused))
    check("the record stays STOPPED", state_of(uid) == "stopped", state_of(uid))
    check("and the loop it had just started is halted again",
          active_of(uid) is False, str(active_of(uid)))

    # ── 4. a revive of an account that is already STOPPED ───────────────────
    print("\n[4] a revive never starts an account whose record says STOPPED")
    uid, rid = fresh_user(4)
    AU.start(uid, rid, starter=ok_starter)
    AU.stop(uid, stopper=lambda u: True)
    started = []
    refused = None
    try:
        AU.start(uid, rid, starter=lambda u: started.append(u) or True,
                 revive=True)
    except AU.AutomationRefused as e:
        refused = e.code
    check("refused", refused == "STOPPED_MEANWHILE", str(refused))
    check("the engine was never started", started == [], str(started))
    check("still STOPPED", state_of(uid) == "stopped")

    # ── 5. a halt that fails must not leave a false STOPPED ─────────────────
    print("\n[5] if the halt fails, the record does not claim the loop is stopped")
    uid, rid = fresh_user(5)
    AU.start(uid, rid, starter=ok_starter)

    def broken_stopper(u):
        raise RuntimeError("engine unreachable")

    raised = None
    try:
        AU.stop(uid, stopper=broken_stopper)
    except RuntimeError as e:
        raised = str(e)
    check("the failure reaches the caller", raised == "engine unreachable",
          str(raised))
    check("and the record still says RUNNING, because the loop may still be",
          state_of(uid) == "running", state_of(uid))
    check("with the rule it was running", AU._read(uid).get("ruleDocId") == rid)

    # ── 6. ordinary stop behaviour is unchanged ─────────────────────────────
    print("\n[6] ordinary behaviour is unchanged")
    uid, rid = fresh_user(6)
    AU.start(uid, rid, starter=ok_starter)
    first = AU.stop(uid, stopper=lambda u: True)
    second = AU.stop(uid, stopper=lambda u: True)
    check("stop stops", first.get("stopped") is True, str(first))
    check("a second stop is idempotent", second.get("alreadyStopped") is True
          and second.get("stopped") is False, str(second))
    check("the rule is forgotten", AU._read(uid).get("ruleDocId") is None)
    out = AU.start(uid, rid, starter=ok_starter)
    check("and a client can Start again", out.get("started") is True, str(out))
finally:
    user_store.all_active = _real_all

# ── 7. a tick that is already deciding does not send an order after a stop ──
print("\n[7] an order authorised before the stop is not sent after it")
# stop() clears a flag and hands the lease back but does not wait for a tick
# that is already running; with the lease gone a demo account is allowed
# through, so an order could open AFTER the emergency had closed everything and
# re-read an empty list. The loop asks again at the last point before the
# broker is touched. Asserted on the source of the loop, because the loop is a
# thread that needs a live broker to drive; the helper it calls is behavioural.
ul = open(os.path.join(ROOT, "apex", "user_loop.py")).read()
site = ul.index("broker.place_order(action, units, symbol, sl=sl_price, tp=tp_price)")
before = ul[:site]
guard = before.rindex("if _stop_requested(user_id):")
anchor = before.rindex("_decision, _rid = gates.authorize_order(")
check("the loop re-checks the stop flag after the gate and before the send",
      anchor < guard < site, f"{anchor} {guard} {site}")
check("and nothing between the check and the send reaches the broker",
      "place_order" not in ul[guard:site])
check("a stop requested at that point is its own outcome, not an order error",
      "except _StopBeforeSend:" in ul and "class _StopBeforeSend" in ul)
from apex import user_loop as UL                         # noqa: E402
user_store.update(uid, {"active": False})
check("the helper reads an explicit active=False as a stop",
      UL._stop_requested(uid) is True)
user_store.update(uid, {"active": True})
check("and active=True as no stop", UL._stop_requested(uid) is False)

# ── 8. a start whose two reads of the selection disagree is refused ─────────
print("\n[8] a start is refused when the broker's answer is for another account")
uid, rid = fresh_user(8)
_real_verify = CL.verify_selected_mode
started = []
try:
    CL.verify_selected_mode = lambda u, **kw: {
        "mode": "demo", "verified": True, "ctid": 999, "recorded": "demo",
        "changed": False, "reason": None}
    refused = None
    try:
        AU.start(uid, rid, starter=lambda u: started.append(u) or True)
    except AU.AutomationRefused as e:
        refused = e.code
    check("refused by name", refused == "ACCOUNT_CHANGED", str(refused))
    check("and no loop was started", started == [], str(started))
finally:
    CL.verify_selected_mode = _real_verify
out = AU.start(uid, rid, starter=ok_starter)
check("(control) with the reads in agreement the same start goes ahead",
      out.get("started") is True, str(out))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All stop-beats-revive checks passed.")
