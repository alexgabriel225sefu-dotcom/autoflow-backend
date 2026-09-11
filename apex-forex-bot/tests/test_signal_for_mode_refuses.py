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

print("\n8. STRATEGY_MODES was left exactly as it was found")
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
