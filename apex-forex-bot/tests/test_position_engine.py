"""Hold a trade for a reason, not on a schedule — and never let the model lie.

THE MEASURED PROBLEM

On the live account the entry engine wins 60% of the time and the profit factor
is 1.10, because the average loss is 36% larger than the average win. The cause
is `_manage_trailing`'s policy, not its code: BREAKEVEN_AT_R=1.0 moves the stop
to entry at +1R, a 1R trail follows, and the target sits at 2.4R. A winner has
to travel 2.4R without a 1R pullback after 2R, which in a ranging market it
almost never does. The journal carries the fingerprints — USDJPY +0.26,
NZDUSD -0.56, EURUSD -1.98.

So the properties this file holds are the ones that change that outcome:

  * a pullback that breaks nothing does not close the trade;
  * a weakening thesis TIGHTENS, only an invalidated one exits;
  * an unreadable market is never a reason to act;
  * the exit reason is the condition that fired, never inferred from the P&L.

And, for the AI layer, the one rule underneath §40 and §41: a reply is checked
against the QUESTION, not just against a shape. A well-formed answer about a
different instrument is the failure a schema check alone cannot catch.

Run: python tests/test_position_engine.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import ai_schema, position_manager as pm, regime, setups  # noqa: E402
from apex import thesis as th  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def mk_thesis(target=1.1060, stop=1.0975):
    c = setups.SetupCandidate(
        symbol="EURUSD", direction="BUY", timeframe="1h",
        strategy_id="fibonacci", strategy_version="1.0.0", bar_ts=1,
        regime=regime.Reading(regime.TRENDING,
                              evidence={"structureTrend": "BULLISH"}),
        features={"htfTrend": "BULLISH"})
    return th.from_candidate(c, entry_price=1.1000, initial_stop=stop,
                             initial_target=target)


POS = {"symbol": "EURUSD", "side": "BUY", "positionId": 1, "stopLoss": 1.0975}
GOOD = {"htfTrend": "BULLISH", "structureTrend": "BULLISH", "regime": "TRENDING"}

print("\n1. The thesis is frozen at entry")
t = mk_thesis()
try:
    t.conditions = []
    check("editing a thesis raises", False, "it was allowed")
except AttributeError:
    check("editing a thesis raises", True)
check("R is measured against the INITIAL stop",
      t.r_multiple(1.1050) == 2.0 and t.r_multiple(1.0975) == -1.0,
      "deriving R from the CURRENT stop stops measuring risk the moment it "
      "ratchets past entry")
check("only measured conditions become conditions",
      sorted(c.kind for c in t.conditions)
      == ["HTF_ALIGNMENT", "LEVEL", "REGIME", "STRUCTURE"])
_bare = th.from_candidate(
    setups.SetupCandidate(symbol="GBPUSD", direction="SELL", timeframe="1h",
                          strategy_id="trend", strategy_version="1.0.0",
                          features={}),
    entry_price=1.30, initial_stop=1.305)
check("an unmeasured feature yields no condition",
      [c.kind for c in _bare.conditions] == ["LEVEL"],
      "a condition nothing evaluates would report VALID forever")

print("\n2. A held stop level is not evidence the thesis is intact")
# It holds for every trade that has simply not stopped out yet. Counting it
# would tilt every evaluation toward "still valid" and make the engine
# reluctant to call an invalidation — the exact bias being removed.
s, _f = th.evaluate(mk_thesis(), {"htfTrend": "BEARISH",
                                  "structureTrend": "BEARISH",
                                  "regime": "TRENDING", "price": 1.1010})
check("both directional conditions broken reads as INVALIDATED",
      s == th.INVALIDATED, s)

print("\n3. The scenario that was losing the money")
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.1050})
check("at +2R a protective stop is proposed",
      p.action == pm.TIGHTEN_STOP_PROPOSED and p.reason == pm.PROTECT_PROFIT,
      f"{p.action}/{p.reason}")
check("...and it sits behind price, not at it",
      p.new_stop is not None and p.new_stop < 1.1050, str(p.new_stop))
pm.reset_memory()
p2 = pm.evaluate({**POS, "stopLoss": p.new_stop}, mk_thesis(),
                 {**GOOD, "price": 1.1030})
check("a pullback that breaks nothing does NOT close the trade",
      p2.action == pm.HOLD, f"{p2.action}/{p2.reason}")

print("\n4. Weakening tightens; only invalidation exits")
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {"htfTrend": "BULLISH",
                                   "structureTrend": "BULLISH",
                                   "regime": "RANGING", "price": 1.1050})
check("a weakening thesis does not propose an exit",
      p.action != pm.EXIT_PROPOSED and p.thesis_state == th.WEAKENING,
      f"{p.action}/{p.thesis_state}")
check("...and the operator can still opt into exiting on it",
      pm.DEFAULTS["exit_on_weakening"] is False,
      "off by default, configurable per §71")
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {"htfTrend": "BEARISH",
                                   "structureTrend": "BEARISH",
                                   "regime": "TRENDING", "price": 1.1010})
check("an invalidated thesis exits", p.action == pm.EXIT_PROPOSED)
check("...naming the condition that fired",
      p.reason == pm.THESIS_INVALIDATED, p.reason)

print("\n5. The exit reason is measured, never inferred from the outcome")
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.1065})
check("price reaching a recorded target reports TARGET_REACHED",
      p.reason == pm.TARGET_REACHED, p.reason)
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(target=None), {**GOOD, "price": 1.1065})
check("the same profit with NO recorded target does not",
      p.reason != pm.TARGET_REACHED, p.reason)
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.0970})
check("price through the level reports STOP_LEVEL_BROKEN",
      p.reason == pm.STOP_LEVEL_BROKEN, p.reason)

print("\n6. Failures never cause an action")
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {})
check("an unreadable market holds", p.action == pm.HOLD)
check("...and says so", p.reason == pm.THESIS_UNREADABLE, p.reason)
pm.reset_memory()
p = pm.evaluate(POS, None, {**GOOD, "price": 1.1050})
check("a position with no thesis is held, not guessed at",
      p.action == pm.HOLD and "no thesis recorded" in p.detail,
      "inventing one would be the retrospective reconstruction §24 forbids")

print("\n7. Account limits outrank the thesis")
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.1010},
                risk_context={"riskViolation": True})
check("a risk violation exits", p.action == pm.EXIT_PROPOSED
      and p.reason == pm.RISK_VIOLATION)
pm.reset_memory()
p = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.1010},
                risk_context={"portfolioReduce": True})
check("portfolio pressure reduces", p.action == pm.REDUCE_PROPOSED
      and p.reason == pm.PORTFOLIO_RISK)

print("\n8. It does not churn")
pm.reset_memory()
a = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.1050})
b = pm.evaluate(POS, mk_thesis(), {**GOOD, "price": 1.1051})
check("the same proposal is not repeated", a.acts and not b.acts, f"{b.action}")
check("...and the repeat says why", b.reason == pm.COOLDOWN, b.reason)

print("\n9. Nothing in the management path can execute")
import ast as _ast  # noqa: E402

for mod in ("position_manager", "thesis"):
    _t = _ast.parse(open(os.path.join(ROOT, "apex", f"{mod}.py"),
                         encoding="utf-8").read())
    _imports = set()
    for _n in _ast.walk(_t):
        if isinstance(_n, _ast.Import):
            _imports |= {a.name.split(".")[0] for a in _n.names}
        elif isinstance(_n, _ast.ImportFrom):
            _imports.add((_n.module or "").split(".")[0])
            if (_n.module or "") == "apex":
                _imports |= {a.name for a in _n.names}
    _calls = {_n.func.attr for _n in _ast.walk(_t)
              if isinstance(_n, _ast.Call) and isinstance(_n.func, _ast.Attribute)}
    check(f"{mod} imports no broker or gate",
          not (_imports & {"brokers", "gates", "ledger", "user_loop", "ctrader"}),
          str(sorted(_imports)))
    check(f"{mod} calls nothing that executes",
          not (_calls & {"authorize_order", "authorize_close", "place_order",
                         "force_close", "close_position", "amend_sltp"}),
          str(sorted(_calls)))

print("\n10. An AI reply is checked against the question, not just the shape")
OK = ai_schema.ENTRY_ACTIONS
good, err = ai_schema.safe_validate(
    '{"action":"ENTER_PROPOSED","symbol":"EURUSD","direction":"BUY",'
    '"supporting_evidence":["structure held"],"reason_codes":["HTF_ALIGNED"]}',
    allowed_actions=OK, symbol="EUR_USD", direction="BUY")
check("a well-formed answer to the right question passes",
      err is None and good["action"] == "ENTER_PROPOSED", str(err))

for label, raw, code, kw in (
    ("a hallucinated symbol",
     '{"action":"ENTER_PROPOSED","symbol":"GBPUSD","supporting_evidence":["x"]}',
     ai_schema.SYMBOL_MISMATCH, {"symbol": "EURUSD"}),
    ("a reversed direction",
     '{"action":"ENTER_PROPOSED","direction":"SELL","supporting_evidence":["x"]}',
     ai_schema.DIRECTION_MISMATCH, {"direction": "BUY"}),
    ("an invented price",
     '{"action":"ENTER_PROPOSED","price":1.2345,"supporting_evidence":["x"]}',
     ai_schema.FORBIDDEN_FIELD, {}),
    ("an invented size",
     '{"action":"ENTER_PROPOSED","units":10000,"supporting_evidence":["x"]}',
     ai_schema.FORBIDDEN_FIELD, {}),
    ("an invented probability",
     '{"action":"ENTER_PROPOSED","probability":0.72,"supporting_evidence":["x"]}',
     ai_schema.FORBIDDEN_FIELD, {}),
    ("an unsupported action", '{"action":"CLOSE_EVERYTHING"}',
     ai_schema.BAD_ACTION, {}),
    ("a manage action on the entry path",
     '{"action":"EXIT_PROPOSED","supporting_evidence":["x"]}',
     ai_schema.BAD_ACTION, {}),
    ("a proposal with no evidence",
     '{"action":"ENTER_PROPOSED","symbol":"EURUSD"}',
     ai_schema.NO_EVIDENCE, {"symbol": "EURUSD"}),
    ("broken JSON", "not json at all", ai_schema.BAD_JSON, {}),
    ("an empty reply", "", ai_schema.EMPTY, {}),
    ("a non-object", "[1,2,3]", ai_schema.NOT_OBJECT, {}),
):
    _r, _c = ai_schema.safe_validate(raw, allowed_actions=OK, **kw)
    check(f"{label} -> {code}", _r is None and _c == code, f"got {_c}")

_r, _c = ai_schema.safe_validate('{"action":"NO_TRADE"}', allowed_actions=OK)
check("NO_TRADE needs no evidence — it asks for nothing to happen",
      _c is None and _r["action"] == "NO_TRADE", str(_c))
_r, _c = ai_schema.safe_validate(
    'Here:\n```json\n{"action":"WATCH"}\n```', allowed_actions=OK)
check("a fenced reply is accepted — that is a formatting habit, not an error",
      _c is None and _r["action"] == "WATCH", str(_c))
_r, _c = ai_schema.safe_validate(
    '{"action":"NO_TRADE","reason_codes":["not a code","GOOD_ONE"]}',
    allowed_actions=OK)
check("free-text masquerading as a reason code is dropped",
      _r["reason_codes"] == ["GOOD_ONE"], str(_r["reason_codes"]))
check("the forbidden list covers price, size and probability",
      {"price", "units", "probability", "stopLoss", "equity"}
      <= ai_schema.FORBIDDEN)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL POSITION-ENGINE CHECKS PASSED - held for a reason, exited for one too.")
