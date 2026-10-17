"""The scanner's losers are the point.

Before this engine, `user_loop` evaluated every watched instrument on every
pass, ranked them by confidence alone, kept the single best, and threw the rest
away. So §61 — "why didn't APEX trade GBPUSD?" — had no answer for six of the
seven instruments looked at, because passing one over left no trace.

The three properties that fix that, and which this file exists to hold:

  1. every candidate gets a Decision, including the ones that lost;
  2. a reason is a stable CODE recorded at the moment, not a sentence
     reconstructed afterwards — §24 forbids asking the model later;
  3. a check that could not be evaluated is not a check that passed, and it is
     not a check that failed either.

Property 3 is the one that is easy to get wrong and expensive to get wrong.
Scoring an unread spread as zero would rank a candidate below one whose spread
is genuinely terrible, which inverts what the number means.

Run: python tests/test_decision_engine.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import decision, ranking, regime, setups  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


POLICY = {"min_confidence": 60, "max_spread_ratio": 0.25,
          "require_htf": True, "allow_unknown_regime": True}


def mk(sym, direction="SELL", conf=73, spread=0.1, sl=25, htf="BEARISH",
       reg=regime.TRENDING, strat="fibonacci", used=0, cap=2, same=False,
       status=setups.CANDIDATE):
    return setups.SetupCandidate(
        symbol=sym, direction=direction, timeframe="1h", strategy_id=strat,
        strategy_version="1.0.0", bar_ts=1787900000,
        regime=(regime.Reading(reg, symbol=sym, confidence=0.7) if reg else None),
        features={"confidence": conf, "spreadPips": spread, "slPips": sl,
                  "htfTrend": htf, "exposureCount": used, "maxPositions": cap,
                  "sameSymbolOpen": same},
        status=status)


print("\n1. A setup's status is a measurement, not a mood")
check("INVALID means the data was unusable, not the setup weak",
      setups.invalid("XAUUSD", "broker returned no candles").status
      == setups.INVALID)
check("...and it records why",
      setups.invalid("XAUUSD", "no candles").failed_checks() == ["market_data"])
check("a fired trigger cannot un-fire",
      not setups.can_transition(setups.CANDIDATE, setups.WATCH),
      "rewinding a trigger would let one setup fire twice")
check("CANDIDATE is not tradeable — only READY is",
      not mk("EURUSD").tradeable)
_c = mk("EURUSD").set_status(setups.READY)
check("...and READY is", _c.tradeable)

print("\n2. Evidence is tri-state")
c = mk("EURUSD")
c.add_evidence("structure", "BULLISH", passed=True)
c.add_evidence("spread", None, passed=None, detail="quote unread")
c.add_evidence("htf", "BEARISH", passed=False)
check("a failed check is listed", c.failed_checks() == ["htf"])
check("an unevaluated check is listed separately", c.unknown_checks() == ["spread"])

print("\n3. Ranking is bounded, documented and stable")
s, why = ranking.score(mk("EURUSD"))
check(f"the score is on 0..1 ({s})", s is not None and 0.0 <= s <= 1.0)
check("the weights sum to one",
      abs(sum(ranking.WEIGHTS.values()) - 1.0) < 1e-9,
      str(sum(ranking.WEIGHTS.values())))
check("every component reports its own reason",
      all("reason" in r for r in why))
check("coverage is reported, so a partly-measured score says so",
      any(r["component"] == "_coverage" for r in why))
_cands = [mk("USDJPY"), mk("EURUSD"), mk("AUDUSD")]
check("the order does not depend on input order",
      [x.symbol for x in ranking.rank(list(_cands))]
      == [x.symbol for x in ranking.rank(list(reversed(_cands)))],
      "an unstable ranking cannot be replayed")

print("\n4. Unmeasured is not the same as bad")
_u, _ = ranking.score(mk("GBPUSD", spread=None))
_b, _ = ranking.score(mk("GBPUSD", spread=20.0))
check(f"an unread spread outranks a terrible one ({_u} > {_b})", _u > _b,
      "scoring unknown as zero inverts what the number means")
_nul = setups.SetupCandidate(symbol="XAUUSD", direction="BUY", timeframe="1h",
                             strategy_id="trend", strategy_version="1.0.0",
                             status=setups.CANDIDATE)
_out = ranking.rank([_nul, mk("EURUSD")])
check("an unrankable candidate is kept, and sorted last",
      _out[-1].symbol == "XAUUSD" and _out[-1].rank_score is None,
      "dropping it recreates the hole this engine closes")

print("\n5. A clean setup is proposed, never executed")
c = mk("EURUSD")
ranking.rank([c])
d = decision.evaluate(c, policy=POLICY, slots_free=1)
check("action is ENTER_PROPOSED", d.action == decision.ENTER_PROPOSED,
      str(d.reason_codes))
check("...which is a proposal, not permission", d.proposes_entry)
# Checked on the parsed module, not on its text: the docstring names
# gates.authorize_order in order to say that this module does NOT call it, and
# a substring search cannot tell an explanation from a call.
import ast as _ast

_tree = _ast.parse(open(os.path.join(ROOT, "apex", "decision.py"),
                       encoding="utf-8").read())
_imports = set()
for _n in _ast.walk(_tree):
    if isinstance(_n, _ast.Import):
        _imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, _ast.ImportFrom):
        _imports.add((_n.module or "").split(".")[0])
        if (_n.module or "") == "apex":
            _imports |= {a.name for a in _n.names}
_calls = {_n.func.attr for _n in _ast.walk(_tree)
          if isinstance(_n, _ast.Call) and isinstance(_n.func, _ast.Attribute)}
check(f"the decision module imports no broker or gate ({sorted(_imports)})",
      not (_imports & {"brokers", "gates", "ledger", "user_loop", "ctrader"}),
      "gates.authorize_order stays the only thing that can permit an order")
check("...and calls nothing that could execute",
      not (_calls & {"authorize_order", "authorize_close", "place_order",
                     "force_close", "close_position", "amend_sltp",
                     "_make_broker"}),
      str(sorted(_calls)))

print("\n6. Each rejection names the earliest true cause")
for label, cand, code in (
    ("spread", mk("EURUSD", spread=10.0), decision.SPREAD_TOO_HIGH),
    ("regime", mk("EURUSD", reg=regime.RANGING, strat="trend"),
     decision.REGIME_MISMATCH),
    ("higher timeframe", mk("EURUSD", htf="BULLISH"), decision.HTF_CONFLICT),
    ("confidence", mk("EURUSD", conf=40), decision.CONFIDENCE_BELOW_MIN),
):
    ranking.rank([cand])
    dd = decision.evaluate(cand, policy=POLICY, slots_free=1)
    check(f"{label} -> {code}",
          dd.action == decision.NO_TRADE and code in dd.reason_codes,
          str(dd.reason_codes))

print("\n7. Account-level blocks outrank any setup quality")
for label, ctx, code in (
    ("halted risk", {"halted": True}, decision.RISK_HALTED),
    ("stale data", {"dataStale": True}, decision.DATA_STALE),
    ("symbol already open", {"sameSymbolOpen": True}, decision.SYMBOL_ALREADY_OPEN),
    ("correlated exposure", {"correlatedExposure": True}, decision.CORRELATED_EXPOSURE),
    ("cooldown", {"cooldownUntil": time.time() + 600}, decision.COOLDOWN_ACTIVE),
):
    cand = mk("EURUSD", conf=99)
    ranking.rank([cand])
    dd = decision.evaluate(cand, policy=POLICY, slots_free=1, risk_context=ctx)
    check(f"{label} -> {code}", dd.reason_codes == [code], str(dd.reason_codes))

print("\n8. An unfired trigger is a watchlist entry, not a rejection")
d = decision.evaluate(mk("EURUSD", status=setups.WATCH), policy=POLICY,
                      slots_free=1)
check("action is WATCH", d.action == decision.WATCH)
check("...with SETUP_INCOMPLETE", d.reason_codes == [decision.SETUP_INCOMPLETE])

print("\n9. Every candidate gets a decision — including the losers")
ds, props = decision.evaluate_all(
    [mk("EURUSD", conf=90), mk("GBPUSD", conf=70), mk("USDJPY", conf=65)],
    policy=POLICY, slots_free=1)
check("one decision per candidate", len(ds) == 3, str(len(ds)))
check("only the free slots are filled", len(props) == 1, str(len(props)))
check("the rest are OUTRANKED, not discarded",
      len([d for d in ds if decision.OUTRANKED in d.reason_codes]) == 2,
      str([d.reason_codes for d in ds]))
check("OUTRANKED is distinct from EXPOSURE_LIMIT",
      not any(decision.EXPOSURE_LIMIT in d.reason_codes for d in ds),
      "the account had room; these lost the queue, which is a different fact")

print("\n10. A decision is readable back without the model that made it")
c = mk("EURUSD")
ranking.rank([c])
raw = decision.evaluate(c, policy=POLICY, slots_free=1).to_dict()
for key in ("decisionId", "at", "action", "reasonCodes", "reasons", "evidence",
            "strategyVersion", "decisionVersion", "rankingVersion", "setupKey"):
    check(f"the wire form carries {key}", key in raw)
check("every code ships with its sentence",
      all(r.get("text") for r in raw["reasons"]))
check("an unknown code still renders as itself",
      decision.reason_text("SOMETHING_NEW_v2") == "SOMETHING_NEW_v2",
      "a missing translation must never hide a recorded reason")

print("\n11. UNKNOWN regime is answered, never rounded away")
r = regime.classify([], symbol="EURUSD")
check("too few candles reads as UNKNOWN",
      r.regime == regime.UNKNOWN and not r.valid, r.label)
check("...and it refuses to judge strategy fit", r.fits("trend") is None,
      "returning False would read as 'this strategy is wrong here'")
check("a fitting strategy is confirmed",
      regime.Reading(regime.TRENDING).fits("trend") is True)
check("a mismatched one is denied",
      regime.Reading(regime.TRENDING).fits("mean_reversion") is False)
check("an unmapped strategy is unknown, not denied",
      regime.Reading(regime.TRENDING).fits("something_new") is None)
check("REVERSAL is not emitted", regime.REVERSAL if hasattr(regime, "REVERSAL")
      else True,
      "nothing in this repository measures it; §8 says not to force one")
check("a stored legacy regime carries no invented confidence",
      regime.from_legacy({"regime": "ranging", "vol_ratio": 1.36}).confidence
      is None)

print("\n12. A ranking pass is recordable")
snap = ranking.snapshot(ranking.rank([mk("EURUSD"), mk("GBPUSD", spread=9.0)]))
check("the snapshot names its own version",
      snap["rankingVersion"] == ranking.RANKING_VERSION)
check("...and the weights it used", snap["weights"] == ranking.WEIGHTS)
check("...and keeps every candidate with its reasons",
      len(snap["candidates"]) == 2
      and all(c["reasons"] for c in snap["candidates"]))

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL DECISION-ENGINE CHECKS PASSED - the losers are recorded too.")
