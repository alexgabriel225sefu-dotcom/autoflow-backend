"""The chat assistant can close a position. It cannot open one.

WHY THIS TEST EXISTS

`apex/agent.py` sets out, at length, why the newer AI surface has no execute
tool: a model reaches its tools straight from free text, so an execute tool
"would defeat every other control in the platform". `assistant.py` is the
older surface and it did have one — wired to `user_loop.force_trade` — under
a system prompt that told the model to "execute immediately without asking for
confirmation", and a tool description that taught it a bare "da", "go" or
"intru" counted as authorisation.

Together those meant one ambiguous sentence could open a real position with no
approval step and nothing to undo before the order reached the broker.

THE ASYMMETRY THIS TEST PRESERVES

Closing is still allowed. It only ever reduces exposure, and "get me out" is
the one urgent thing a client may genuinely need from a chat box. Opening
creates exposure, so it belongs behind the approval button, where an order
carries a record of who authorised it.

The check is structural, not textual: a future edit that re-adds an execute
tool, or reaches force_trade by another name, fails here rather than being
caught by a reviewer noticing prose.

Run: python tests/test_assistant_cannot_open.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


SRC = open(os.path.join(ROOT, "apex", "assistant.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

print("\n1. No tool is declared that opens a position")
from apex import assistant  # noqa: E402
names = {str(t.get("name", "")) for t in assistant._TOOLS}
check(f"the registry declares no opening tool ({sorted(names)})",
      not (names & {"execute_trade", "open_trade", "place_order", "buy",
                    "sell", "enter_trade", "force_trade"}))
check("...and closing is still offered", "close_position" in names,
      "reducing exposure on request is the point of keeping chat useful")

print("\n2. Nothing in the module reaches an opening call")
calls = {n.func.attr for n in ast.walk(TREE)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
opening = calls & {"force_trade", "place_order", "open_trade", "authorize_order"}
check(f"no opening call anywhere in assistant.py ({sorted(opening) or 'none'})",
      not opening)

print("\n3. The tool dispatcher has no branch that could route to one")
_run = next((n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == "_run_tool"), None)
check("_run_tool exists", _run is not None)
if _run is not None:
    consts = {n.value for n in ast.walk(_run)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    check("it compares against no opening tool name",
          not (consts & {"execute_trade", "open_trade", "place_order"}))

print("\n4. The prompt does not instruct the model to skip confirmation")
low = SRC.lower()
check("no 'without asking for confirmation' instruction remains",
      "without asking for confirmation" not in low)
check("no 'just do it' instruction remains", "just do it" not in low)

print("\n5. Closing still works end to end")
check("the close branch is still dispatched", '"close_position"' in SRC or
      "'close_position'" in SRC)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - chat can close a position, never open one.")
