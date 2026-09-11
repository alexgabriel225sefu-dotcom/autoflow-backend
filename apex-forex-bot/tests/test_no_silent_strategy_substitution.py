"""The substitution cannot be reintroduced anywhere, by anyone, later.

WHY THIS TEST EXISTS

Three separate places resolved an unrecognised strategy to mean reversion, and
each looked locally reasonable:

  * control_actions.coerce_setting()  stored the value unchecked
  * user_loop._rule_signal()          fell through when no module existed
  * ai.signal_for_mode()              defaulted its lookup twice over

Each was fixed on its own, and each has its own behavioural test. But the
pattern is what keeps coming back: `.get(x, DEFAULT)` on a strategy map, or an
`or "mean_reversion"`, is a natural thing to type and reads as defensive
programming. It is the opposite. A default here means the account trades a
method the client did not choose, under the name they did.

So this test is about the SHAPE of the code, not one instance of it. It walks
the AST of the three modules and fails on any dictionary lookup against a
strategy map that carries a fallback. AST rather than text search: a comment
mentioning the old pattern, or a string in a docstring explaining why it was
removed, must not trip it — only a real expression that would execute.

WHAT TO DO IF THIS FAILS

Do not add the file to an exclusion list. The question to answer is "what
should happen when the strategy is unknown", and the answer this codebase has
settled on is an explicit HOLD that names the mode. If a new call site truly
needs a default, it needs a reviewed exception, not a quiet .get().

Run: python tests/test_no_silent_strategy_substitution.py
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


# Maps whose VALUES select behaviour — an engine or a strategy module. A
# fallback lookup into one of these answers "which strategy?" with "a different
# one", which is the defect.
#
# _MODE_INTRO is deliberately NOT here: its values are prompt sentences, so a
# default there substitutes prose, not a strategy. It gets its own rule in
# section 5 instead, because it caused the same bug by a different route —
# `if mode not in _MODE_INTRO: mode = "mean_reversion"` rewrote the mode before
# signal_for_mode could refuse it.
STRATEGY_MAPS = {"STRATEGY_MODES", "_REGISTRY", "_STRATEGY_MODES"}
FILES = ("apex/ai.py", "apex/user_loop.py", "apex/control_actions.py",
         "apex/strategy_api.py")

# Concrete strategy names. Assigning one of these to the variable that selects
# the strategy is the rewrite this file forbids.
STRATEGY_NAMES = {"mean_reversion", "trend", "breakout", "fibonacci", "fvg",
                  "ifvg", "liquidity_sweep", "supply_demand", "evc"}

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
from apex import ai as _ai  # noqa: E402


def _map_name(node):
    """The identifier being subscripted or .get()-ed, if it is a strategy map."""
    if isinstance(node, ast.Name):
        return node.id if node.id in STRATEGY_MAPS else None
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in STRATEGY_MAPS else None
    return None


print("\n1. No strategy-map lookup carries a silent fallback")
for rel in FILES:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        check(f"{rel} exists", False, "file moved or renamed")
        continue
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # MAP.get(key, DEFAULT) — two args is the fallback form
        if (isinstance(fn, ast.Attribute) and fn.attr == "get"
                and _map_name(fn.value) and len(node.args) == 2):
            offenders.append(
                f"{_map_name(fn.value)}.get(..., <default>) line {node.lineno}")
    check(f"{rel}: no MAP.get(key, default) on a strategy map",
          not offenders, "; ".join(offenders))

print("\n2. The specific regression that shipped: `or \"mean_reversion\"`")
for rel in FILES:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        continue
    tree = ast.parse(open(path, encoding="utf-8").read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str) \
                        and v.value in ("mean_reversion", "trend", "breakout"):
                    bad.append(f"or {v.value!r} at line {node.lineno}")
    check(f"{rel}: no `or <strategy>` default in an executable expression",
          not bad, "; ".join(bad))

print("\n3. The AST walk really would catch it (the check is not vacuous)")
# A test that can only pass is worth nothing. This proves the detector fires,
# using the exact code that used to ship.
_OLD = ('def signal_for_mode(mode, ind, strat=None, open_position=None):\n'
        '    m = STRATEGY_MODES.get((mode or "mean_reversion").lower(),\n'
        '                           STRATEGY_MODES["mean_reversion"])\n'
        '    return m["engine"](ind, strat, open_position)\n')
_tree = ast.parse(_OLD)
_hits = [n for n in ast.walk(_tree)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "get" and _map_name(n.func.value)
         and len(n.args) == 2]
check("the old two-arg .get() is detected", len(_hits) == 1, str(len(_hits)))
_ors = [n for n in ast.walk(_tree) if isinstance(n, ast.BoolOp)
        and isinstance(n.op, ast.Or)
        and any(isinstance(v, ast.Constant) and v.value == "mean_reversion"
                for v in n.values)]
check("the old `or \"mean_reversion\"` is detected", len(_ors) == 1,
      str(len(_ors)))

print("\n4. A comment or docstring about the old pattern must NOT trip it")
# ai.signal_for_mode's docstring quotes the removed code verbatim, because the
# reason it was removed is worth more than the two lines it replaced. A
# text-matching test would force that explanation to be deleted or mangled.
_DOC = ('def f():\n'
        '    """Used to be STRATEGY_MODES.get(m, STRATEGY_MODES["x"]).\n\n'
        '    And `or "mean_reversion"` before that.\n    """\n'
        '    return 1\n')
_t = ast.parse(_DOC)
_h = [n for n in ast.walk(_t)
      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
      and n.func.attr == "get" and _map_name(n.func.value)]
check("prose describing the defect is not flagged as the defect", _h == [],
      str(_h))
check("...and ai.py's docstring does quote it, so this matters",
      'STRATEGY_MODES.get((mode or "mean_reversion").lower()' in
      open(os.path.join(ROOT, "apex", "ai.py"), encoding="utf-8").read(),
      "if this stops being true the guard above is untested in practice")

print("\n5. No function rewrites its own `mode` to a strategy literal")
# The fourth instance of this bug was not a map lookup at all. get_signal did:
#     if mode not in _MODE_INTRO: mode = "mean_reversion"
# one line above the signal_for_mode() call, so the refusal added there never
# fired on the path every AI-confirmed entry takes. Assigning a strategy name
# to the variable that selects the strategy is the shape to forbid.
for rel in FILES:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        continue
    tree = ast.parse(open(path, encoding="utf-8").read())
    rewrites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt, val = node.targets[0], node.value
        if (isinstance(tgt, ast.Name) and tgt.id in ("mode", "active_mode",
                                                     "strategy", "strat_mode")
                and isinstance(val, ast.Constant)
                and isinstance(val.value, str)
                and val.value in STRATEGY_NAMES):
            rewrites.append(f"{tgt.id} = {val.value!r} at line {node.lineno}")
    check(f"{rel}: no `mode = \"<strategy>\"` rewrite", not rewrites,
          "; ".join(rewrites))

print("\n6. _MODE_INTRO covers every mode, so the prompt cannot KeyError")
# With the rewrite gone, _MODE_INTRO[mode] is reached only after
# signal_for_mode returned BUY/SELL — which means the mode is in
# STRATEGY_MODES. Equality is what makes the bare subscript safe, and what
# forces a new strategy to bring its prompt intro with it.
check("_MODE_INTRO keys == STRATEGY_MODES keys",
      set(_ai._MODE_INTRO) == set(_ai.STRATEGY_MODES),
      f"only in MODES: {sorted(set(_ai.STRATEGY_MODES) - set(_ai._MODE_INTRO))}; "
      f"only in INTRO: {sorted(set(_ai._MODE_INTRO) - set(_ai.STRATEGY_MODES))}")

print("\n7. The four fixed call sites still behave, end to end")
from apex import ai, control_actions  # noqa: E402

try:
    control_actions.coerce_setting("strategy", "trend_following")
    _wrote = True
except ValueError:
    _wrote = False
check("A: an unknown strategy cannot be written", not _wrote)
check("C: an unknown mode is not answered by an engine",
      ai.signal_for_mode("trend_following", {}, {}, None).get("action")
      == "HOLD")
check("C: and the refusal names it",
      "trend_following" in
      ai.signal_for_mode("trend_following", {}, {}, None).get("reasoning", ""))
check("B is covered by its own test",
      os.path.exists(os.path.join(ROOT, "tests",
                                  "test_unknown_strategy_holds.py")),
      "user_loop._rule_signal is a closure; that test execs its real source")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - the substitution has no way back in.")
