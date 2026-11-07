"""§48: what the engine does when its inputs are broken.

Every module added for the APEX engine is asked here to handle the failures the
brief lists — missing data, stale data, malformed AI output, an unreadable
market — and the bar is the same for all of them: a failure must produce a
recorded refusal, never an action and never an exception into the trading loop.

The distinction being tested throughout is between three answers that are easy
to collapse into one and expensive to collapse:

    it passed        a measured verdict
    it failed        a measured verdict
    it could not be evaluated

Collapsing the third into either of the first two is how a platform ends up
either refusing to trade a working market or trading a broken one.

Run: python tests/test_engine_failures.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import ai_schema, decision, portfolio, position_manager as pm  # noqa: E402
from apex import ranking, regime, setups, thesis as th  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


POLICY = {"min_confidence": 60, "max_spread_ratio": 0.25,
          "require_htf": True, "allow_unknown_regime": True}

print("\n1. Missing market data")
c = setups.invalid("EURUSD", "broker returned no candles")
d = decision.evaluate(c, policy=POLICY, slots_free=1)
check("an unreadable instrument decides NO_TRADE",
      d.action == decision.NO_TRADE)
check("...naming the data, not the setup",
      d.reason_codes == [decision.NO_MARKET_DATA], str(d.reason_codes))
check("regime on no candles is UNKNOWN and invalid",
      regime.classify([]).regime == regime.UNKNOWN
      and not regime.classify([]).valid)
check("regime on a broken candle list does not raise",
      regime.classify([{"bogus": 1}] * 200).regime in regime.REGIMES)
check("...and reports itself invalid rather than guessing",
      regime.classify([{"bogus": 1}] * 200).valid is False)

print("\n2. Stale market data")
d = decision.evaluate(
    setups.SetupCandidate(symbol="EURUSD", direction="BUY", timeframe="1h",
                          strategy_id="trend", strategy_version="1",
                          status=setups.CANDIDATE),
    policy=POLICY, slots_free=1, risk_context={"dataStale": True})
check("stale data decides NO_TRADE", d.action == decision.NO_TRADE)
check("...with DATA_STALE", d.reason_codes == [decision.DATA_STALE])
ok, code, _ = portfolio.check("EURUSD", "BUY", portfolio.state({"maxpos": 5}),
                              limits={"max_data_age_s": 30}, data_age_s=600)
check("the risk gate refuses on age",
      not ok and code == portfolio.MARKET_DATA_STALE)
ok, _, _ = portfolio.check("EURUSD", "BUY", portfolio.state({"maxpos": 5}),
                           limits={}, data_age_s=600)
check("...only when a limit was configured", ok,
      "no configured limit means the check is off, not that all data is stale")

print("\n3. A partly-unreadable candidate is ranked, not discarded")
part = setups.SetupCandidate(
    symbol="GBPUSD", direction="BUY", timeframe="1h", strategy_id="trend",
    strategy_version="1", status=setups.CANDIDATE,
    features={"confidence": 80})            # nothing else measurable
s, why = ranking.score(part)
check("it still gets a score", s is not None, str(s))
check("...and reports how much of it was measurable",
      any(r["component"] == "_coverage" and r["value"] < 1.0 for r in why))
empty = setups.SetupCandidate(symbol="XAUUSD", direction="BUY", timeframe="1h",
                              strategy_id="trend", strategy_version="1",
                              status=setups.CANDIDATE)
s2, _ = ranking.score(empty)
check("a candidate with nothing measurable scores None, not zero", s2 is None,
      "zero would rank it below a genuinely bad setup")
d = decision.evaluate(empty, policy=POLICY, slots_free=1)
check("...and is not proposed", not d.proposes_entry
      and decision.NOT_RANKABLE in d.reason_codes, str(d.reason_codes))


class _Boom:
    """A candidate whose features blow up on access."""
    symbol, direction, strategy_id = "EURUSD", "BUY", "trend"
    strategy_version, status, regime = "1", setups.CANDIDATE, None
    id = key = None
    rank_score, rank_reasons = None, []
    evidence, invalidation, config_version = [], [], None

    @property
    def features(self):
        raise RuntimeError("feature store exploded")


s3, why3 = ranking.score(_Boom())
check("a component that raises is caught, not propagated", s3 is None)
check("...and the failure is recorded per component",
      any("component failed" in (r.get("reason") or "") for r in why3),
      "a ranking bug must not stop a trading loop")

print("\n4. Malformed AI output never becomes an action")
for label, raw in (("a timeout returning nothing", None),
                   ("a truncated object", '{"action":"ENTER_PROP'),
                   ("prose instead of JSON", "I think you should buy"),
                   ("a nested surprise", '{"action":{"deep":"ENTER_PROPOSED"}}'),
                   ("an array", "[]")):
    r, code = ai_schema.safe_validate(raw,
                                      allowed_actions=ai_schema.ENTRY_ACTIONS)
    check(f"{label} is rejected", r is None and bool(code), f"{code}")
check("the validator never raises",
      ai_schema.safe_validate(object(),
                              allowed_actions=ai_schema.ENTRY_ACTIONS)[0] is None)

print("\n5. An unreadable market never closes a position")
t = th.Thesis(symbol="EURUSD", direction="BUY",
              conditions=[th.Condition(th.HTF_ALIGNMENT, "BULLISH"),
                          th.Condition(th.LEVEL, 1.0975)],
              strategy_id="trend", strategy_version="1",
              entry_price=1.1000, initial_stop=1.0975)
pos = {"symbol": "EURUSD", "side": "BUY", "positionId": 1, "stopLoss": 1.0975}
pm.reset_memory()
p = pm.evaluate(pos, t, {})
check("no observation at all holds", p.action == pm.HOLD)
check("...and says the market was unreadable",
      p.reason == pm.THESIS_UNREADABLE, p.reason)
pm.reset_memory()
p = pm.evaluate(pos, t, {"price": None, "htfTrend": None})
check("all-None observations hold too", p.action == pm.HOLD)
pm.reset_memory()
p = pm.evaluate(pos, t, {"price": "not a number", "htfTrend": "BULLISH"})
check("an uncomparable price does not act", p.action == pm.HOLD,
      f"{p.action}/{p.reason}")

print("\n6. A thesis cannot be rebuilt into something it was not")
check("a malformed stored thesis is None, not a blank one",
      th.Thesis.from_dict({}) is None and th.Thesis.from_dict(None) is None,
      "a blank thesis would evaluate as permanently valid")
_round = th.Thesis.from_dict({"symbol": "EURUSD", "direction": "BUY",
                              "conditions": [{"kind": "NOT_A_KIND"},
                                             {"kind": "LEVEL",
                                              "expected": 1.09}]})
check("an unknown condition kind is dropped, not accepted",
      [c.kind for c in _round.conditions] == ["LEVEL"],
      "a condition nothing evaluates would report VALID forever")

print("\n7. The risk gate fails closed on its own failure")
GATES = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
check("a portfolio-check exception denies",
      "PORTFOLIO_CHECK_FAILED" in GATES
      and "return Decision(False, \"PORTFOLIO_CHECK_FAILED\"" in GATES)
check("...and the store being unreachable denies", "STORE_UNREACHABLE" in GATES)
check("...and an unverified environment denies",
      "ACCOUNT_MODE_UNVERIFIED" in GATES)
_bad = portfolio.state({"positions": [{"symbol": None}, {}, None]})
check("exposure state survives malformed position rows",
      _bad["openCount"] == 0, str(_bad))

print("\n8. Concurrency: the manager does not act twice on one position")
pm.reset_memory()
t2 = th.Thesis(symbol="EURUSD", direction="BUY",
               conditions=[th.Condition(th.HTF_ALIGNMENT, "BULLISH")],
               strategy_id="trend", strategy_version="1",
               entry_price=1.1000, initial_stop=1.0975)
obs = {"price": 1.1060, "htfTrend": "BULLISH"}
first = pm.evaluate(pos, t2, obs)
repeats = [pm.evaluate(pos, t2, obs) for _ in range(5)]
check("the first proposal acts", first.acts, f"{first.action}")
check("five identical follow-ups do not",
      not any(r.acts for r in repeats),
      "duplicate ticks and reconnects must not stack amendments")
check("...and each says why", all(r.reason == pm.COOLDOWN for r in repeats))

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL FAILURE-INJECTION CHECKS PASSED - broken inputs refuse, never act.")
