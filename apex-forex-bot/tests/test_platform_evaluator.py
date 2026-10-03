"""The evaluator and the condition library.

WHAT THIS FILE IS ACTUALLY DEFENDING

One mistake, in several disguises: answering "no" to a question the system
could not answer. Every disguise gets its own check.

  an indicator with too little history          must refuse, not report False
  a spread ceiling with no spread in the feed   must refuse, not pass
  an indicator that raises                      must refuse, not report False
  a mistyped parameter                          must refuse, even on a bar
                                                where the logic short-circuits
                                                past it
  an unknown condition id                       must refuse, not be skipped

Plus the properties that make a decision worth journalling: it is pure, it
evaluates every condition even when the outcome is already decided, and a
satisfied two-sided rule with no directional evidence refuses rather than
guessing a side.

Run: python tests/test_platform_evaluator.py
"""
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import indicators  # noqa: E402
from apex.platform import conditions as C  # noqa: E402
from apex.platform import decision as D  # noqa: E402
from apex.platform import evaluator as EV  # noqa: E402
from apex.platform import ruledoc as R  # noqa: E402
from apex.platform.snapshot import MarketSnapshot  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def passes(cid, params, snapshot):
    """The condition's verdict, with an exception turned into a value.

    A mutation that makes a condition throw would otherwise abort the whole
    script on the first call and take every later check down with it — the
    run would look like one big crash instead of naming the thing that broke.
    """
    try:
        ok, _, _ = C.evaluate_one(cid, params, snapshot)
        return ok
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def raises(exc, fn):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


# ── fixtures ────────────────────────────────────────────────────────────────
# A sine wave, not a flat line or a straight ramp. Flat candles divide by zero
# inside ATR and the Stochastic; a straight ramp never lets two moving
# averages cross, so a cross test on one would pass for the wrong reason.

def waveform(n=400, base=1.1000, amp=0.0060, period=57):
    return [base + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


def mk(closes):
    """Candles whose ranges vary, so true range is never degenerate."""
    out = []
    for i, c in enumerate(closes):
        pad = 0.0004 + 0.0002 * abs(math.sin(i / 7.0))
        out.append({"open": c - pad / 3, "high": c + pad, "low": c - pad,
                    "close": c, "volume": 1000 + i})
    return out


TS = 1758542400.0  # Mon 22 Sep 2025 12:00 UTC — a weekday, inside the
                   # London/New York overlap. TS + 3 days is a Thursday.


def snap(candles=None, *, symbol="EUR_USD", timeframe="1h", ts=TS,
         spread=1.0, positions=None, session=None):
    candles = candles if candles is not None else mk(waveform())
    return MarketSnapshot(symbol=symbol, timeframe=timeframe, candles=candles,
                          price=candles[-1]["close"], ts=ts, spread_pips=spread,
                          session=session, open_positions=positions or [])


def doc(entry, *, exit_=None, sides="BUY", symbols=("EUR_USD",),
        timeframe="1h", limits=None, schedule=None, state=R.ACTIVE):
    d = R.blank(user_id="u1", account_id="a1", symbols=list(symbols),
                timeframe=timeframe)
    d["state"] = state
    d["name"] = "test rule"
    d["sides"] = sides
    d["entry"] = entry
    d["exit"] = exit_ or {"combine": "OR", "conditions": [
        {"id": "rsi", "params": {"op": "above", "value": 70}}]}
    if limits:
        d["limits"].update(limits)
    if schedule:
        d["schedule"].update(schedule)
    return d


def AND(*cs):
    return {"combine": "AND", "conditions": list(cs)}


def OR(*cs):
    return {"combine": "OR", "conditions": list(cs)}


# Building blocks whose truth value is known without computing an indicator.
ALWAYS = {"id": "weekday", "params": {"days": [0, 1, 2, 3, 4, 5, 6]}}
NEVER = {"id": "weekday", "params": {"days": []}}          # refuses: empty
NEVER_OK = {"id": "rsi", "params": {"op": "above", "value": 100}}
# 200-period MA over a 60-bar snapshot: answerable in principle, not here.
UNKNOWABLE = {"id": "price_vs_ma", "params": {"period": 200}}
SHORT = mk(waveform(60))


print("\n1. every condition the brief names is in the library")
lib = C.available()
for want in ("price_vs_ma", "ma_cross", "rsi", "macd", "atr", "bollinger",
             "stochastic", "session", "time_window", "weekday",
             "max_positions", "spread_limit"):
    check(f"library has {want}", want in lib)
check("EMA and SMA are both selectable",
      set(C.get("price_vs_ma")["params"]["indicator"].choices) == {"ema", "sma"})
check("describe() exposes params for the UI",
      all("params" in v and "doc" in v for v in C.describe().values()))
# Concepts whose definition is not pinned down stay out until it is.
for absent in ("fvg", "fair_value_gap", "liquidity_sweep", "supply_demand"):
    check(f"{absent} is NOT exposed", absent not in lib)


print("\n2. bad parameters are refused, never defaulted away")
s = snap()
check("unknown parameter name is an error, not ignored",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("rsi", {"periods": 200}, s)))
check("wrong type is an error",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("rsi", {"period": "fourteen"}, s)))
check("out-of-range value is an error",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("rsi", {"value": 500}, s)))
check("value outside a choice list is an error",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("rsi", {"op": "sideways"}, s)))
check("unknown condition id is an error, not a skip",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("moon_phase", {}, s)))
check("a fast MA slower than the slow MA is refused",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("ma_cross",
                                    {"fast_period": 50, "slow_period": 20}, s)))
check("an empty time window is refused",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("time_window",
                                    {"from": "09:00", "to": "09:00"}, s)))
check("a malformed time is refused",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("time_window", {"from": "9am"}, s)))
check("weekday 7 is refused",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("weekday", {"days": [7]}, s)))


print("\n3. what cannot be answered is not answered 'no'")
short = snap(SHORT)
check("EMA(200) over 60 bars refuses",
      raises(C.ConditionUnavailable,
             lambda: C.evaluate_one("price_vs_ma", {"period": 200}, short)))
check("a spread ceiling with no spread in the feed refuses",
      raises(C.ConditionUnavailable,
             lambda: C.evaluate_one("spread_limit", {"max_pips": 2.0},
                                    snap(spread=None))))
passed, _, _ = C.evaluate_one("spread_limit", {"max_pips": 2.0}, snap(spread=9))
check("a spread over the ceiling is False (the ceiling works)", passed is False)


ok_lower = passes("session", {"sessions": ["london"]}, s)
ok_title = passes("session", {"sessions": ["London"]}, s)
ok_underscore = passes("session", {"sessions": ["new_york"]}, s)
check("a session name matches whatever case the form sent",
      ok_lower is True and ok_title is True, f"{ok_lower!r}/{ok_title!r}")
check("and 'new_york' matches the table's 'New York'",
      ok_underscore is True, repr(ok_underscore))
check("an unknown session name is refused, not silently never-true",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("session", {"sessions": ["atlantis"]}, s)))
check("a non-name in the session list is refused",
      raises(C.ConditionMisconfigured,
             lambda: C.evaluate_one("session", {"sessions": [7]}, s)))


print("\n4. three-valued logic — unknown is not false")
d = EV.evaluate(doc(AND(NEVER_OK, UNKNOWABLE)), short)
check("AND with a False and an Unknown holds (the False decides it)",
      d.verdict == D.HOLD, d.verdict)
d = EV.evaluate(doc(AND(ALWAYS, UNKNOWABLE)), short)
check("AND with a True and an Unknown refuses, not holds",
      d.verdict == D.REJECT and d.refusal_code == D.INSUFFICIENT_DATA,
      f"{d.verdict}/{d.refusal_code}")
d = EV.evaluate(doc(OR(ALWAYS, UNKNOWABLE)), short)
check("OR with a True and an Unknown is satisfied (the True decides it)",
      d.verdict == D.BUY, f"{d.verdict}/{d.refusal_code}")
d = EV.evaluate(doc(OR(NEVER_OK, UNKNOWABLE)), short)
check("OR with a False and an Unknown refuses, not holds",
      d.verdict == D.REJECT and d.refusal_code == D.INSUFFICIENT_DATA,
      f"{d.verdict}/{d.refusal_code}")
check("the refusal names the condition that could not be answered",
      "price_vs_ma" in d.reason or "price_vs_ma" in
      " ".join(c.condition_id for c in d.conditions))


print("\n5. a misconfigured condition refuses even when the logic "
      "short-circuits past it")
typo = {"id": "rsi", "params": {"perod": 14}}
d = EV.evaluate(doc(OR(ALWAYS, typo)), s)
check("OR does not let a satisfied condition hide a typo",
      d.verdict == D.REJECT and d.refusal_code == D.CONDITION_ERROR,
      f"{d.verdict}/{d.refusal_code}")
check("the refusal says which parameter", "perod" in d.reason, d.reason)
d = EV.evaluate(doc(AND(NEVER_OK, typo)), s)
check("AND does not let a failed condition hide a typo either",
      d.verdict == D.REJECT and d.refusal_code == D.CONDITION_ERROR,
      f"{d.verdict}/{d.refusal_code}")
d = EV.evaluate(doc(OR(ALWAYS, {"id": "nope", "params": {}})), s)
check("an unknown condition id refuses the whole rule",
      d.verdict == D.REJECT, d.verdict)


print("\n6. an indicator that raises is never read as 'condition not met'")
_real = indicators.rsi
try:
    def _boom(*a, **k):
        raise ZeroDivisionError("synthetic")
    indicators.rsi = _boom
    d = EV.evaluate(doc(AND({"id": "rsi", "params": {}})), s)
    check("an exception inside an indicator refuses",
          d.verdict == D.REJECT, f"{d.verdict}/{d.refusal_code}")
    check("and the reason carries the exception",
          "ZeroDivisionError" in d.reason, d.reason)
finally:
    indicators.rsi = _real


print("\n7. every condition is evaluated, even once the outcome is decided")
three = AND(NEVER_OK, NEVER_OK, NEVER_OK)
d = EV.evaluate(doc(three), s)
check("a decided AND still records all three results",
      len(d.conditions) == 3, str(len(d.conditions)))
check("every recorded result carries a human detail",
      all(c.detail for c in d.conditions))
d = EV.evaluate(doc(OR(ALWAYS, ALWAYS, ALWAYS)), s)
check("a decided OR still records all three results",
      len(d.conditions) == 3, str(len(d.conditions)))


print("\n8. the decision is pure")
a = EV.evaluate(doc(AND(ALWAYS)), s)
b = EV.evaluate(doc(AND(ALWAYS)), s)
check("the same inputs give the same verdict", a.verdict == b.verdict)
check("and the same reason", a.reason == b.reason)
# Built BEFORE the clock is taken away: R.blank() stamps createdAt, which is
# a legitimate clock read at authoring time. What must not read the clock is
# the EVALUATION, so only that runs under the block.
clocky = doc(AND(ALWAYS, {"id": "time_window", "params": {}},
                 {"id": "session", "params": {}}))
_t = time.time
try:
    def _no_clock():
        raise RuntimeError("the evaluator read the clock")
    time.time = _no_clock
    d = EV.evaluate(clocky, s)
    check("evaluating never calls time.time()", d.verdict in D.VERDICTS)
except RuntimeError as e:
    check("evaluating never calls time.time()", False, str(e))
finally:
    time.time = _t
# Same bar, different wall-clock day: the verdict must not move.
thursday = snap(ts=TS + 3 * 86400)
mondays_only = AND({"id": "weekday", "params": {"days": [0]}})
d1 = EV.evaluate(doc(mondays_only), s)
d2 = EV.evaluate(doc(mondays_only), thursday)
check("a Monday-only rule fires on the snapshot's Monday",
      d1.verdict == D.BUY, d1.verdict)
check("and holds on the snapshot's Thursday — the ts decides, not today",
      d2.verdict == D.HOLD, d2.verdict)


print("\n9. the snapshot has to be addressed to this rule")
d = EV.evaluate(doc(AND(ALWAYS), symbols=("GBP_USD",)), s)
check("a symbol outside the rule refuses",
      d.refusal_code == D.SYMBOL_NOT_IN_RULE, str(d.refusal_code))
d = EV.evaluate(doc(AND(ALWAYS), timeframe="4h"), s)
check("a timeframe mismatch refuses rather than answering anyway",
      d.refusal_code == D.TIMEFRAME_MISMATCH, str(d.refusal_code))
d = EV.evaluate(doc(AND(ALWAYS), state=R.DRAFT), s)
check("a draft rule does not trade",
      d.refusal_code == D.RULE_NOT_ACTIVE, str(d.refusal_code))
bad = doc(AND(ALWAYS))
bad["stopLoss"] = {"mode": "none"}
d = EV.evaluate(bad, s)
check("a rule that lost its stop refuses on every bar",
      d.refusal_code == D.RULE_INVALID, str(d.refusal_code))


print("\n10. limits block new entries and leave open positions manageable")
pos = [{"symbol": "EUR_USD", "side": "BUY", "units": 1000}]
d = EV.evaluate(doc(AND(ALWAYS), limits={"maxOpenPositions": 1}),
                snap(positions=pos, spread=99))
check("an exit is evaluated even with the spread far over the cap",
      d.verdict in (D.CLOSE, D.HOLD), f"{d.verdict}/{d.refusal_code}")
d = EV.evaluate(doc(AND(ALWAYS), limits={"maxSpreadPips": 2.0}),
                snap(spread=9.0))
check("a new entry over the spread cap is refused",
      d.refusal_code == D.SPREAD_LIMIT_EXCEEDED, str(d.refusal_code))
d = EV.evaluate(doc(AND(ALWAYS), limits={"maxSpreadPips": 2.0}),
                snap(spread=None))
check("a spread cap with no spread refuses instead of passing",
      d.verdict == D.REJECT, f"{d.verdict}/{d.refusal_code}")
d = EV.evaluate(doc(AND(ALWAYS), limits={"maxOpenPositions": 1}),
                snap(positions=[{"symbol": "EURUSD"}],
                     candles=mk(waveform())))
check("max positions blocks a second entry on the same symbol",
      d.verdict != D.BUY, f"{d.verdict}/{d.refusal_code}")
d = EV.evaluate(doc(AND(ALWAYS), schedule={"days": [6]}), s)
check("a bar outside the schedule refuses with its own code",
      d.refusal_code == D.OUTSIDE_SCHEDULE, str(d.refusal_code))
check("a schedule block is not reported as a broken rule",
      not D.is_config_error(D.OUTSIDE_SCHEDULE))
check("a broken rule IS reported as one",
      D.is_config_error(D.RULE_INVALID))


print("\n11. a two-sided rule never guesses a direction")
d = EV.evaluate(doc(AND(ALWAYS), sides="BOTH"), s)
check("BOTH with no directional condition refuses",
      d.refusal_code == D.DIRECTION_AMBIGUOUS, str(d.refusal_code))
both_ways = AND({"id": "rsi", "params": {"op": "below", "value": 100}},
                {"id": "rsi", "params": {"op": "above", "value": 0}})
d = EV.evaluate(doc(both_ways, sides="BOTH"), s)
check("BOTH with conditions arguing opposite ways refuses",
      d.refusal_code == D.DIRECTION_AMBIGUOUS, str(d.refusal_code))
d = EV.evaluate(doc(AND({"id": "rsi", "params": {"op": "below",
                                                 "value": 100}}),
                    sides="BOTH"), s)
check("BOTH with one clear direction takes it", d.verdict == D.BUY, d.verdict)
d = EV.evaluate(doc(AND({"id": "rsi", "params": {"op": "below", "value": 100}}),
                    sides="SELL"), s)
check("an explicit side wins over the conditions' bias",
      d.verdict == D.SELL, d.verdict)


print("\n12. a crossing is an event, not a state")
w = waveform(400)
f, sl = indicators.ema(w, 20), indicators.ema(w, 50)
cross_at = next(i for i in range(60, 400)
                if f[i - 1] <= sl[i - 1] and f[i] > sl[i])
at = snap(mk(w[:cross_at + 1]))
after = snap(mk(w[:cross_at + 2]))
p_at, _, _ = C.evaluate_one("ma_cross", {"direction": "up"}, at)
p_after, _, _ = C.evaluate_one("ma_cross", {"direction": "up"}, after)
check("the bar the lines cross on passes", p_at is True)
check("the very next bar does NOT (fast is still above, but nothing crossed)",
      p_after is False)
p_down, _, _ = C.evaluate_one("ma_cross", {"direction": "down"}, at)
check("and a cross up is not a cross down", p_down is False)
p_state, _, _ = C.evaluate_one("price_vs_ma", {"period": 50, "op": "above"},
                               after)
check("while the state condition does still hold on that bar",
      p_state is True)


print("\n13. the Stochastic survives a market that does not move")
flat = [{"open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1,
         "volume": 1} for _ in range(60)]
st = indicators.stochastic(flat, 14, 3, 3)
check("a flat window gives None, not ZeroDivisionError", st["k"][-1] is None)
check("and the condition refuses rather than inventing a reading",
      raises(C.ConditionUnavailable,
             lambda: C.evaluate_one("stochastic", {}, snap(flat, spread=1.0))))
ok, detail, _ = C.evaluate_one("stochastic", {"op": "below", "value": 100},
                               snap(mk(waveform())))
check("and reads normally on a moving market", ok is True, detail)


print("\n14. the reason is assembled from what was evaluated")
d = EV.evaluate(doc(AND(NEVER_OK, ALWAYS)), s)
ids = [c.condition_id for c in d.conditions]
check("the reason names every condition",
      all(i in d.reason for i in ids), d.reason)
check("a failed condition is marked as failed", "- rsi" in d.reason, d.reason)
check("a passed condition is marked as passed", "+ weekday" in d.reason,
      d.reason)
check("confidence stays None — no invented number",
      EV.evaluate(doc(AND(ALWAYS)), s).confidence is None)
check("a HOLD is not executable", not d.executable)
check("a BUY is", EV.evaluate(doc(AND(ALWAYS)), s).executable)


print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
