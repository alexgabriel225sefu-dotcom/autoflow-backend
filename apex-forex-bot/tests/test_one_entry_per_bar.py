"""An exact rule may enter once per signal bar, not once per tick.

WHAT WENT WRONG

An exact rule decides on a CLOSED bar and that verdict holds for the whole
next bar. The loop ticks every five minutes, and the post-loss cooldowns are
skipped for exact rules on purpose, so every stop-out left the account flat
and the next tick took the same verdict again: five XAUUSD SELLs on one 1h bar,
each stopped within minutes (-$55 in 35 minutes).

The loop is one very large function, so this pins the guard the way the other
loop contracts do: from the source, in order.

Run: python3 tests/test_one_entry_per_bar.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

_fails = []


def check(name, cond):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name}")


guard = SRC.find("already entered on this bar")
cooldown = SRC.find("Post-loss cooldown: the worst trade after a stop-out")
order = SRC.find('print(f"[UserLoop:{user_id}] ORDER {_order_line}")')
mark = SRC.find("entered_bar[_nrm(symbol)] = candles[-1].get(\"time\")")
state = SRC.find("entered_bar = {}")

check("the per-bar entry state exists", state != -1)
check("an entry is marked against its bar", mark != -1 and mark > order > 0)
check("the guard exists and sits before the cooldown block",
      guard != -1 and cooldown != -1 and guard < cooldown)

block = SRC[SRC.rfind("if entry_ok and _exact_rule and candles:", 0, guard):guard + 200]
check("it applies to exact rules only", "_exact_rule" in block)
check("it compares the last entry's bar with the current bar",
      "entered_bar.get(_nrm(symbol)) == _eb" in block)
check("it refuses the entry without alerting the client every tick",
      "entry_ok = False" in block and "alert=False" in block)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("One-entry-per-bar contract checks passed.")
