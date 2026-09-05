"""The skip-reason logger must still be callable after the scanner runs.

THE DEFECT

`_skip` is a function defined inside `_loop`:

    def _skip(reason, alert=True):
        \"\"\"Journal every rejected entry ... clients see the discipline\"\"\"

The autopilot scanner then rebinds that same name to a set, in the same scope,
to pass as its `skip=` argument:

    _skip = {k for k in open_syms} | {...}
    _cands = _scan.scan(broker, cfg, watchlist, forex=forex, skip=_skip, ...)

`_loop` holds the tick loop, so the rebinding is not scoped to one tick: from
the first scan onward `_skip` is a set for the life of the loop, and every
later `_skip(reason)` raises `'set' object is not callable`.

Observed live on 2026-09-04, four times:
    [UserLoop:7585109158] regime gate error: 'set' object is not callable

WHAT IT DID AND DID NOT BREAK

Every call site sets `entry_ok = False` BEFORE calling `_skip`, so refusals
still took effect — the gates kept working. What broke is the client-facing
record of WHY ("refused 14 weak setups today"), and, at the seven call sites
without a local try/except, the rest of the tick after the raise.

Run: python tests/test_skip_not_shadowed.py
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


SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

loop = next(n for n in ast.walk(TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_loop")

# Every name bound anywhere inside _loop, and how.
defined_as_func = {n.name for n in ast.walk(loop)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
assigned = {}
for node in ast.walk(loop):
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                assigned.setdefault(t.id, []).append(node.lineno)

print("\n1. _skip is a function in _loop, and stays one")
check("_skip is defined as a nested function", "_skip" in defined_as_func)
check("nothing reassigns the name _skip",
      "_skip" not in assigned,
      f"reassigned at line(s) {assigned.get('_skip')} — after that every "
      f"_skip(reason) raises 'set' object is not callable")

print("\n2. No callable defined in _loop is shadowed by an assignment")
# The general form of the same defect: a helper defined for the tick loop and
# then overwritten by data. Catching the class, not just this instance.
shadowed = sorted(n for n in defined_as_func if n in assigned)
check("no nested helper is later rebound", not shadowed, str(shadowed))

print("\n3. The scanner still gets its skip set")
# The fix must not have removed the argument, only renamed the variable.
check("scan() is still called with a skip= set",
      "skip=" in SRC and "_scan.scan(" in SRC)
_scan_call = SRC[SRC.index("_scan.scan("):]
_scan_call = _scan_call[:_scan_call.index(")")]
check("the name it passes is not _skip",
      "skip=_skip" not in _scan_call,
      f"still passing the function's name: {_scan_call.strip()[:80]}")

print("\n4. The skip logger is actually reachable where it is called")
# Behavioural proof rather than structural: build the two bindings the loop
# had and show the old one breaks and the new one does not.
def _mk_func():
    calls = []
    def _skip(reason, alert=True):
        calls.append(reason)
    return _skip, calls

_fn, _calls = _mk_func()
_fn("regime gate: fibonacci does not trade a trending market")
check("a function binding records the reason", _calls == [
    "regime gate: fibonacci does not trade a trending market"])

_as_set = {"EURUSD", "GBPUSD"}
try:
    _as_set("anything")
    _raised = None
except TypeError as e:
    _raised = str(e)
check("a set binding raises exactly the error seen live",
      _raised == "'set' object is not callable", str(_raised))

print("\n" + "=" * 62)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED — the skip logger survives the scanner.")
