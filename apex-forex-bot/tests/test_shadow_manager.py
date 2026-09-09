"""The exit policy gets changed on evidence, not on an argument.

The live policy — break-even at 1R then a 1R trail — produces a 60% win rate at
a profit factor of 1.10 on the live account, because it caps winners near 1R
while losers run the full stop. That is a good enough reason to want it
changed and not a good enough reason to change it: replacing one untested
policy with another is not an improvement, it is a different bet.

So §46's shadow mode runs the thesis-driven manager beside the live one on the
same positions at the same moments, writes what it WOULD have proposed, and
changes nothing. After a fortnight of those events the operator has a
comparison instead of an opinion.

The properties this file holds are the ones that make that safe:

  * it is off unless switched on (§72);
  * it cannot amend a stop or close a position;
  * it never invents a thesis for a position that predates one (§24);
  * a bug inside it cannot take the trading loop down.

Run: python tests/test_shadow_manager.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
EVENTS = open(os.path.join(ROOT, "apex", "trade_events.py"),
              encoding="utf-8").read()

_tree = ast.parse(LOOP)
_shadow = next((n for n in ast.walk(_tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_shadow_manage"),
               None)

print("\n1. It is off unless the operator switches it on")
check("there is an explicit switch", "def _shadow_pm_on" in LOOP)
check("...read from the environment", 'os.getenv("SHADOW_POSITION_MANAGER"' in LOOP)
check("...defaulting to off", 'os.getenv("SHADOW_POSITION_MANAGER", "")' in LOOP,
      "it writes journal events per tick; nobody starts paying for that by "
      "accident")
check("the loop honours the switch", "if open_pos and _shadow_pm_on():" in LOOP)

print("\n2. It cannot act")
check("the shadow function exists", _shadow is not None)
_calls = {n.func.attr for n in ast.walk(_shadow)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check(f"it calls nothing that executes ({sorted(_calls)})",
      not (_calls & {"amend_sltp", "force_close", "close_position",
                     "place_order", "authorize_order", "authorize_close",
                     "update"}),
      "it decorates the journal and nothing else")
check("it takes no broker argument",
      "broker" not in [a.arg for a in _shadow.args.args],
      str([a.arg for a in _shadow.args.args]))
check("the live policy call is untouched",
      "moved = _manage_trailing(" in LOOP,
      "shadow mode must not change what actually happens")
check("...and runs regardless of the shadow",
      LOOP.index("if open_pos and _shadow_pm_on():")
      < LOOP.index("if open_pos and not cfg.PAPER_TRADING:"),
      "the shadow runs first and cannot short-circuit the real one")

print("\n3. It never invents a thesis")
_src = ast.get_source_segment(LOOP, _shadow) or ""
check("a position with no recorded entry or stop is skipped",
      "if entry is None or stop is None:" in _src and "return" in _src,
      "reconstructing one would be the retrospective invention §24 forbids")
check("...and the reconstruction it does make is from RECORDED fields only",
      'pos.get("entryPrice")' in _src and 'pos.get("initialStop")' in _src)
check("the comment says why", "retrospective invention" in _src)

print("\n4. A bug in it cannot take the loop down")
_handlers = [n for n in ast.walk(_shadow) if isinstance(n, ast.Try)]
check("the whole body is wrapped", bool(_handlers))
check("...and the failure is printed, not raised",
      any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
          for t in _handlers for h in t.handlers),
      "this decorates a journal; it must not delay a real stop amendment")

print("\n5. It records only what is worth comparing")
check("a plain HOLD is not written",
      "if not prop.acts and prop.reason != _pm.THESIS_INVALIDATED:" in _src,
      "recording every hold would bury the evidence in noise")
check("...but a disagreement is", "_te.MANAGEMENT_SHADOW" in _src)
check("the event names the live policy it is being compared against",
      '"livePolicy": "trailing+breakeven"' in _src)
check("...and marks itself as shadow", '"shadow": True' in _src)

print("\n6. The event type is registered")
for name in ("SETUP_DETECTED", "CANDIDATES_RANKED", "DECISION_RECORDED",
             "THESIS_CREATED", "THESIS_EVALUATED", "MANAGEMENT_PROPOSED",
             "MANAGEMENT_SHADOW", "AI_REJECTED"):
    check(f"{name} is declared", f"{name} = " in EVENTS)
    check(f"...and accepted by the journal",
          EVENTS.count(name) >= 2,
          "declared but absent from _TYPES would be silently dropped")

print("\n7. The thresholds are configuration, not constants")
check("the protect trigger is configurable",
      'getattr(cfg, "SHADOW_PROTECT_FROM_R", 1.0)' in _src)
check("the trail distance is configurable",
      'getattr(cfg, "SHADOW_PROTECT_TRAIL_R", 1.5)' in _src)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL SHADOW-MANAGER CHECKS PASSED - it watches, and it changes nothing.")
