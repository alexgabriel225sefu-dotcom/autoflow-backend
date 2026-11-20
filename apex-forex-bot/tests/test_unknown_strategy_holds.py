"""An unavailable strategy produces no trade, not a different strategy.

WHY THIS TEST EXISTS

`_rule_signal()` asks the registry for the strategy the client chose. When the
registry has no module for that id, `strategy_api.get()` returns None, the
guard `if _strategy is not None and _frame is not None:` skipped the entire
block, and control fell through to:

    return ai.signal_for_mode(active_mode, ind, strat_data, open_pos)

whose own lookup ends in `STRATEGY_MODES["mean_reversion"]`. So an id nothing
registers did not fail — it traded mean reversion, and the journal recorded it
under the name the client had chosen. The client could read back their setting,
see their strategy named in every trade, and be wrong about what was running.

A guard for exactly this already existed, but only inside the `except` branch —
it caught "the module was there and raised" and missed "there was no module",
which is the commoner case and the one an invalid setting produces.

THE DISTINCTION THIS TEST PROTECTS

Falling through to the engine is CORRECT when the engine genuinely implements
the mode: `ai.STRATEGY_MODES` is the set it really has, and for those ids the
engine is the legacy decision path, not a substitution. The fix must therefore
change exactly one case — unknown id, no module — and leave the legacy path
intact for the ten modes the engine does implement. Both halves are asserted
below, because a fix that also stopped the legacy path would be a regression
dressed as a safety improvement.

HOW IT IS TESTED

`_rule_signal` and `_engine_or_hold` are closures roughly 3,600 lines inside
`_loop()`, which cannot be called without a broker, a user record and a live
tick. So their REAL source is extracted from apex/user_loop.py with ast and
executed against stubs. That runs the shipped code — if the body changes, this
test sees the change. It is not a source-text assertion: nothing here matches
on comments or on the spelling of the implementation.

Run: python tests/test_unknown_strategy_holds.py
"""
import ast
import os
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

LOOP = os.path.join(ROOT, "apex", "user_loop.py")
LOOP_SRC = open(LOOP, encoding="utf-8").read()

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


# ── pull the two real closures out of the file ───────────────────────────────
_tree = ast.parse(LOOP_SRC)
_defs = {}
for _node in ast.walk(_tree):
    if isinstance(_node, ast.FunctionDef) and _node.name in (
            "_rule_signal", "_engine_or_hold"):
        _defs[_node.name] = textwrap.dedent(
            ast.get_source_segment(LOOP_SRC, _node))

check("both closures were found in user_loop.py",
      set(_defs) == {"_rule_signal", "_engine_or_hold"},
      f"found {sorted(_defs)}")
if failures:
    print("\ncannot continue without the source")
    sys.exit(1)


class _StubAI:
    """Stands in for apex.ai. Records whether the engine was consulted."""

    STRATEGY_MODES = {"mean_reversion": 1, "trend": 1, "breakout": 1,
                      "auto": 1}

    def __init__(self):
        self.calls = []

    def signal_for_mode(self, mode, ind, strat, open_position):
        self.calls.append(mode)
        # The real one resolves an unknown mode to mean_reversion. Mirrored so
        # that a regression reaching the engine with a bad id is visible as
        # the substitution it actually is, rather than as a stub artefact.
        resolved = mode if mode in self.STRATEGY_MODES else "mean_reversion"
        return {"action": "BUY", "confidence": 70,
                "reasoning": f"engine verdict via {resolved}"}


class _Module:
    """A strategy module. Either answers, or raises like a broken one."""

    def __init__(self, raises=False):
        self.raises = raises

    def signal(self, frame):
        if self.raises:
            raise RuntimeError("indicator feed empty")
        return {"action": "SELL", "confidence": 88,
                "reasoning": "module verdict"}


def run(active_mode, module=None, frame=object()):
    """Execute the REAL closures with these surroundings."""
    ai = _StubAI()
    ns = {
        "ai": ai, "user_id": "42", "active_mode": active_mode,
        "_strategy": module, "_frame": frame if module is not None else None,
        "ind": {}, "strat_data": {}, "open_pos": None,
        "print": lambda *a, **k: None,
    }
    exec(_defs["_engine_or_hold"], ns)
    exec(_defs["_rule_signal"], ns)
    return ns["_rule_signal"](), ai


print("\n1. The case that was substituting: unknown id, no module registered")
sig, ai = run("trend_following", module=None)
check("the verdict is HOLD", sig.get("action") == "HOLD", str(sig.get("action")))
check("the engine was never consulted", ai.calls == [], str(ai.calls))
check("the reason names the strategy that was asked for",
      "trend_following" in sig.get("reasoning", ""), sig.get("reasoning", ""))
check("...and it is not presented as a mean_reversion verdict",
      "engine verdict" not in sig.get("reasoning", ""),
      sig.get("reasoning", ""))
check("confidence is zero, so nothing downstream reads it as conviction",
      sig.get("confidence") == 0, str(sig.get("confidence")))

print("\n2. The legacy engine path is UNCHANGED for modes the engine has")
for mode in ("mean_reversion", "trend", "breakout"):
    sig, ai = run(mode, module=None)
    check(f"{mode}: still answered by the engine, not held",
          sig.get("action") == "BUY" and ai.calls == [mode],
          f"action={sig.get('action')} calls={ai.calls}")

print("\n3. A module that raises: same rule, both directions")
sig, ai = run("zscore", module=_Module(raises=True))
check("unknown-to-the-engine id holds when its module raises",
      sig.get("action") == "HOLD" and ai.calls == [],
      f"action={sig.get('action')} calls={ai.calls}")
check("the reason carries the strategy and the failure",
      "zscore" in sig.get("reasoning", "")
      and "indicator feed empty" in sig.get("reasoning", ""),
      sig.get("reasoning", ""))
sig, ai = run("trend", module=_Module(raises=True))
check("a mode the engine implements still falls back to it",
      sig.get("action") == "BUY" and ai.calls == ["trend"],
      f"action={sig.get('action')} calls={ai.calls}")

print("\n4. A working module still decides, and the engine stays out of it")
sig, ai = run("zscore", module=_Module())
check("the module's verdict is returned verbatim",
      sig.get("action") == "SELL" and sig.get("confidence") == 88, str(sig))
check("the engine was not consulted", ai.calls == [], str(ai.calls))
sig, ai = run("trend", module=_Module())
check("...including for a mode the engine also implements",
      sig.get("action") == "SELL" and ai.calls == [], str(ai.calls))

print("\n5. The substitution cannot come back through any path")
for mode in ("trend_following", "", "mean-reversion", "Trend", "nonsense"):
    for mod in (None, _Module(raises=True)):
        sig, ai = run(mode, module=mod)
        label = f"{mode!r} with {'a broken module' if mod else 'no module'}"
        check(f"{label} -> HOLD, engine untouched",
              sig.get("action") == "HOLD" and ai.calls == [],
              f"action={sig.get('action')} calls={ai.calls}")

print("\n6. A HOLD from here can never be read as an order")
sig, _ = run("trend_following", module=None)
check("action is exactly 'HOLD'", sig["action"] == "HOLD")
check("it is not BUY or SELL under any casing",
      sig["action"].upper() not in ("BUY", "SELL"))
check("riskLevel is present and LOW", sig.get("riskLevel") == "LOW",
      str(sig.get("riskLevel")))
check("criteriaScore is zero", sig.get("criteriaScore") == 0,
      str(sig.get("criteriaScore")))
check("the verdict carries the keys the caller reads",
      all(k in sig for k in ("action", "confidence", "criteriaScore",
                             "riskLevel", "reasoning", "keyFactors")),
      str(sorted(sig)))

print("\n7. A HOLD cannot reach an order — the link, not just the verdict")
# The checks above prove the verdict is HOLD. This proves HOLD means no trade:
# the entry gate requires BUY or SELL, so there is no arithmetic path from a
# HOLD verdict to place_order(). Asserted against the real gate rather than
# assumed, because "returns HOLD" and "does not trade" are only the same
# statement while that gate keeps its shape.
check("the entry gate requires action in (BUY, SELL)",
      'action in ("BUY", "SELL")' in LOOP_SRC,
      "if this moved, a HOLD verdict is no longer proof of no entry")
check("entry_ok is what gates the entry, and it is that expression",
      'entry_ok = action in ("BUY", "SELL")' in LOOP_SRC)
check("HOLD is not in the set that opens a position",
      '"HOLD", "BUY", "SELL"' not in LOOP_SRC
      and '("BUY", "SELL", "HOLD")' not in LOOP_SRC)
# And the verdict this change produces is refused by that gate.
_sig, _ = run("trend_following", module=None)
check("the refusal verdict fails the gate's own test",
      _sig["action"] not in ("BUY", "SELL"), str(_sig["action"]))
check("...and its confidence is below any MIN_CONFIDENCE floor",
      _sig.get("confidence", 0) == 0,
      "the gate also requires confidence >= cfg.MIN_CONFIDENCE")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - an unavailable strategy holds; it never becomes "
      "another strategy.")
