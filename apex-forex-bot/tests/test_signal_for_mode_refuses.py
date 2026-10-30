"""signal_for_mode() answers an unknown mode with HOLD, never with another engine.

WHY THIS TEST EXISTS

The function used to be two lines:

    m = STRATEGY_MODES.get((mode or "mean_reversion").lower(),
                           STRATEGY_MODES["mean_reversion"])
    return m["engine"](ind, strat, open_position)

Both the `or` and the `.get` default land on the same place: mean reversion.
So every mode the engine did not implement — a typo, a strategy registered
only as a module, an id left over from an older build, None — was answered by
the mean reversion engine. Nothing raised, nothing was logged, and the verdict
was shaped exactly like a verdict for the mode that was asked for. It was then
journalled under that name.

That is the worst shape a bug can take: the client holds the setting they
chose, sees it named in every trade, and is wrong about what is running. Not
trading is visible in the journal as an absence. The substitution is invisible
by construction.

THE DISTINCTION THIS TEST PROTECTS

Refusing an unknown mode must not weaken a known one. All ten modes in
STRATEGY_MODES have to keep reaching their own engine — that is asserted here
by replacing each engine with a recorder and checking it was actually called,
rather than by reading the verdict, because with empty indicators every engine
honestly returns HOLD and a refusal HOLD would otherwise be indistinguishable
from a real one.

That indistinguishability is the whole point of the bug, so the test refuses to
rely on telling them apart by eye.

Run: python tests/test_signal_for_mode_refuses.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import ai  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def call(mode):
    """The verdict, with None normalised to {} so a function that returns
    nothing fails its own checks instead of raising AttributeError and hiding
    every check after it. Section 7 asserts None is never returned."""
    return ai.signal_for_mode(mode, {}, {}, None) or {}


def call_raw(mode):
    return ai.signal_for_mode(mode, {}, {}, None)


class _Recorder:
    """Replaces an engine so a CALL is observable, not just a verdict."""

    def __init__(self):
        self.calls = 0

    def __call__(self, ind, strat, open_position):
        self.calls += 1
        return {"action": "BUY", "confidence": 91, "reasoning": "recorder"}


def with_all_engines_recorded(mode):
    """Call `mode` with EVERY engine replaced. Returns (verdict, {mode: hits})."""
    rec = {k: _Recorder() for k in ai.STRATEGY_MODES}
    saved = {k: ai.STRATEGY_MODES[k]["engine"] for k in ai.STRATEGY_MODES}
    for k in ai.STRATEGY_MODES:
        ai.STRATEGY_MODES[k]["engine"] = rec[k]
    try:
        verdict = call(mode)
    finally:
        for k, fn in saved.items():
            ai.STRATEGY_MODES[k]["engine"] = fn
    return verdict, {k: r.calls for k, r in rec.items() if r.calls}


print("\n1. An unknown mode reaches NO engine at all")
for bad in ("trend_following", "nonsense", "mean-reversion", "M15", "zscore",
            "grid", "martingale"):
    verdict, hits = with_all_engines_recorded(bad)
    check(f"{bad!r}: no engine was called", hits == {}, str(hits))
    check(f"{bad!r}: the verdict is HOLD", verdict.get("action") == "HOLD",
          str(verdict.get("action")))

print("\n2. Specifically, it does not reach the mean reversion engine")
verdict, hits = with_all_engines_recorded("trend_following")
check("mean_reversion's engine was not invoked",
      hits.get("mean_reversion", 0) == 0,
      "this is the exact substitution the fix removes")
check("and the verdict is not the recorder's BUY",
      verdict.get("action") != "BUY", str(verdict))

print("\n3. Every mode the engine DOES implement still reaches its own engine")
for mode in sorted(ai.STRATEGY_MODES):
    verdict, hits = with_all_engines_recorded(mode)
    check(f"{mode}: its own engine ran, and only its own",
          hits == {mode: 1}, str(hits))
    check(f"{mode}: the engine's verdict is returned, not a refusal",
          verdict.get("action") == "BUY" and verdict.get("confidence") == 91,
          str(verdict)[:70])

print("\n4. None and empty are bad values, not a request for the default")
for empty in (None, "", "   "):
    verdict, hits = with_all_engines_recorded(empty)
    check(f"{empty!r}: no engine called", hits == {}, str(hits))
    check(f"{empty!r}: HOLD", verdict.get("action") == "HOLD",
          str(verdict.get("action")))

print("\n5. Case and padding still resolve — the fix narrowed nothing else")
for spelled, canonical in (("MEAN_REVERSION", "mean_reversion"),
                           ("  Trend  ", "trend"),
                           ("BreakOut", "breakout")):
    verdict, hits = with_all_engines_recorded(spelled)
    check(f"{spelled!r} resolves to {canonical}", hits == {canonical: 1},
          str(hits))

print("\n6. The refusal names the mode that was asked for")
for bad in ("trend_following", "zscore", "nonsense"):
    why = call(bad).get("reasoning", "")
    check(f"{bad!r} appears in its own refusal", bad in why, why[:70])
check("and the refusal does not claim to be a mean reversion read",
      "mean-reversion" not in call("trend_following").get("reasoning", ""),
      call("trend_following").get("reasoning", ""))

print("\n7. The refusal has the shape every caller reads")
v = call("trend_following")
check("action/confidence/criteriaScore/riskLevel/reasoning/keyFactors present",
      all(k in v for k in ("action", "confidence", "criteriaScore",
                           "riskLevel", "reasoning", "keyFactors")),
      str(sorted(v)))
check("confidence is 0, below every entry threshold in the codebase",
      v.get("confidence") == 0, str(v.get("confidence")))
check("criteriaScore is 0", v.get("criteriaScore") == 0)
check("action is never BUY or SELL", v["action"] not in ("BUY", "SELL"))
check("callers reading .get('action','HOLD') see HOLD either way",
      v.get("action", "HOLD") == "HOLD")
# Every caller does verdict.get(...) or verdict["action"] straight away, so
# returning nothing would be an AttributeError on a live tick rather than a
# refusal. Checked for the refusal path and for a normal one.
check("a refusal is never None", call_raw("trend_following") is not None)
check("nor is a normal verdict", call_raw("mean_reversion") is not None)
check("both are dicts", isinstance(call_raw("trend_following"), dict)
      and isinstance(call_raw("mean_reversion"), dict))

print("\n8. Every one of the six callers, exercised for real")
# Sections 1-7 prove the FUNCTION refuses. This proves the refusal is safe
# everywhere it lands. Each caller is invoked with an invalid mode and checked
# on four things: it does not raise, it yields no BUY/SELL, it produces nothing
# executable, and it keeps the invalid mode wherever its API exposes a reason.
#
# Callers are exercised, not mocked. A mock would prove the test's idea of the
# caller is safe, which is not the claim being made.
BAD = "strategie_inexistenta"

def _make_candles(n=260):
    """Candles with real movement.

    Flat candles are not a neutral fixture: ATR and range-normalised
    indicators divide by the bar range, so a constant series raises
    ZeroDivisionError inside indicators.analyze() and the caller never reaches
    the refusal this section is about. A deterministic wave keeps every
    indicator well-defined without making the test depend on random data.
    """
    import math
    out = []
    for i in range(n):
        base = 1.10 + 0.004 * math.sin(i / 9.0) + 0.00002 * i
        hi = base + 0.0012 + 0.0004 * abs(math.cos(i / 4.0))
        lo = base - 0.0012 - 0.0004 * abs(math.sin(i / 5.0))
        out.append({"open": round(base - 0.0002, 6), "high": round(hi, 6),
                    "low": round(lo, 6), "close": round(base, 6),
                    "volume": 100 + (i % 17),
                    "time": 1789000000 + i * 3600})
    return out


_candles = _make_candles()


def _market(pos=None):
    from apex import strategy_api as _sa
    return _sa.Market(_candles, symbol="EURUSD", indicators={}, strat={},
                      open_position=pos, price=1.1, balance=1000,
                      timeframe="1h")


def _module_with_bad_mode():
    """A real StrategyModule subclass whose mode is the invalid one.

    The strategy modules are imported HERE, not at the top: the registry fills
    as a side effect of importing them, and every section above this one needs
    it in whatever state it already was.
    """
    import apex.strategy_modules  # noqa: F401  (registers by import)
    from apex import strategy_api as _sa
    _trend = _sa.get("trend")
    assert _trend is not None, "registry did not populate — cannot build probe"
    base = _trend.__class__

    class _Probe(base):
        strategy_id = "probe_invalid_mode"
        strategy_version = "0.0.1-test"
        mode = BAD

    return _Probe()


def caller(name, fn, *, reason_of=None):
    """Run one caller; report raise / entry action / invalid-mode retention."""
    try:
        out = fn()
    except Exception as e:
        check(f"{name}: does not raise", False, f"{type(e).__name__}: {e}")
        return None
    check(f"{name}: does not raise", True)
    act = (out or {}).get("action") if isinstance(out, dict) else None
    check(f"{name}: no BUY/SELL", act not in ("BUY", "SELL"), f"action={act!r}")
    if reason_of is not None:
        why = reason_of(out) or ""
        check(f"{name}: the reason still names {BAD!r}", BAD in why, why[:70])
    return out


# 1 — ai.get_signal()
caller("ai.get_signal", lambda: ai.get_signal({}, 1000, None, {}, mode=BAD),
       reason_of=lambda o: o.get("reasoning", ""))

# 2-4 — the three StrategyModule entry points
_probe = _module_with_bad_mode()
caller("strategy_modules.signal", lambda: _probe.signal(_market()),
       reason_of=lambda o: o.get("reasoning", ""))

_adv = caller("strategy_modules.advise_risk",
              lambda: _probe.advise_risk(_market()))
check("strategy_modules.advise_risk: returns a multiplier, not an order",
      isinstance(_adv, dict) and "multiplier" in _adv, str(_adv)[:70])
check("...and the multiplier stays inside the clamped band",
      _adv and 0.4 <= _adv.get("multiplier", 0) <= 1.2,
      str(_adv.get("multiplier") if _adv else None))

_pos = {"side": "BUY", "entryPrice": 1.1, "quantity": 1000, "symbol": "EURUSD"}
_ex = caller("strategy_modules.exit", lambda: _probe.exit(_market(_pos)),
             reason_of=lambda o: o.get("reason", ""))
check("strategy_modules.exit: does not force an exit on a refusal",
      _ex is not None and _ex.get("exit") is False, str(_ex)[:70])

# 5 — telegram._sim_strategy(): a backtest loop. A refusal must open no trade.
from apex import telegram as _tg  # noqa: E402

_sim = None
try:
    _sim = _tg._sim_strategy(BAD, _candles, "EURUSD", 20, 40, 0.01, 1000.0)
    check("telegram._sim_strategy: does not raise", True)
except Exception as e:
    check("telegram._sim_strategy: does not raise", False,
          f"{type(e).__name__}: {e}")
check("telegram._sim_strategy: zero trades opened",
      _sim is not None and _sim.get("n") == 0, str(_sim))
check("telegram._sim_strategy: balance untouched",
      _sim is not None and abs(_sim.get("net", 1)) < 1e-9, str(_sim))

# 6 — scanner.scan_symbol(): must yield no executable setup.
from apex import scanner as _scanner, setups as _setups  # noqa: E402


class _Broker:
    def get_candles(self, symbol, timeframe, n):
        return _candles


class _Cfg:
    TIMEFRAME = "1h"
    STRATEGY = BAD
    STOP_LOSS_PIPS = 20


_cand = None
try:
    _cand = _scanner.scan_symbol(_Broker(), _Cfg(), "EURUSD")
    check("scanner.scan_symbol: does not raise", True)
except Exception as e:
    check("scanner.scan_symbol: does not raise", False,
          f"{type(e).__name__}: {e}")
check("scanner.scan_symbol: no executable setup",
      _cand is not None and _cand.status in (_setups.WATCH, _setups.INVALID),
      str(getattr(_cand, "status", None)))
check("scanner.scan_symbol: status is never READY",
      _cand is not None and _cand.status != _setups.READY,
      str(getattr(_cand, "status", None)))
check("scanner.scan_symbol: the evidence keeps the invalid mode",
      _cand is not None and BAD in str(getattr(_cand, "evidence", "")),
      str(getattr(_cand, "evidence", ""))[:80])

print("\n9. STRATEGY_MODES was left exactly as it was found")
check("all engines restored after the recorder swaps",
      all(callable(m["engine"]) and not isinstance(m["engine"], _Recorder)
          for m in ai.STRATEGY_MODES.values()))
check("the mode set is unchanged", len(ai.STRATEGY_MODES) == 10,
      str(len(ai.STRATEGY_MODES)))

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - an unknown mode gets HOLD, never another engine.")
