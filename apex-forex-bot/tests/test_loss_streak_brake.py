"""The consecutive-loss limit now stops new entries in the trading loop.

WHAT WENT WRONG

An exact rule on XAUUSD 1h with a $3 stop lost ten trades in a row. The
consecutive-loss limit existed only in apex/platform/risk_guard.py, a read-only
decision API the loop never called, and exact rules skip the post-loss
cooldowns on purpose. Only the 2% daily stop ended the day.

THE BRAKE

apex/loss_brake.py is a pure decision; apex/user_loop.py applies it by refusing
the entry. It never closes a position, places an order or changes the rule.

Run: python3 tests/test_loss_streak_brake.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import loss_brake as lb  # noqa: E402
from apex.platform.risk_guard import GuardLimits  # noqa: E402

SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
BRAKE_SRC = open(os.path.join(ROOT, "apex", "loss_brake.py"), encoding="utf-8").read()

_fails = []


def check(name, cond):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name}")


print("1. The decision")
check("the default limit is the guard's own limit",
      lb.DEFAULT_LIMIT == GuardLimits.max_consecutive_losses == 5)
check("4 losses in a row still trade", not lb.decide(4)["block"])
d = lb.decide(5)
check("5 losses in a row block", d["block"] and d["code"] == lb.LIMIT)
check("the reason names the count and the limit",
      "5 losses in a row" in d["reason"] and "limit of 5" in d["reason"])
check("the reason says entries are what stops", "no new entries" in d["reason"])
check("10 losses in a row block", lb.decide(10)["block"])
check("a configured limit is used", lb.decide(3, limit=3)["block"]
      and not lb.decide(2, limit=3)["block"])
for bad in (0, -1, "x", None, True):
    check(f"a limit of {bad!r} never switches the brake off",
          lb.decide(5, limit=bad)["block"] and lb.effective_limit(bad) == 5)

print("\n2. No history is zero, not unknown (PR #212)")
check("a missing stored streak is 0", lb.parse_stored_count(None) == 0)
check("an empty stored streak is 0", lb.parse_stored_count("") == 0)
check("a brand-new account is not blocked",
      not lb.decide(lb.parse_stored_count(None),
                    lb.parse_stored_count(None))["block"])

print("\n3. Unknown is not zero")
for bad in ("abc", True, -2, 1.5, float("nan"), float("inf"), [], {}):
    check(f"a stored streak of {bad!r} is unreadable",
          lb.parse_stored_count(bad) is None)
check("numeric strings and integral floats are read",
      lb.parse_stored_count("3") == 3 and lb.parse_stored_count(4.0) == 4)
u = lb.decide(0, 0, unreadable=True)
check("an unreadable stored streak blocks, with a reason",
      u["block"] and u["code"] == lb.UNKNOWN and "could not be read" in u["reason"])
check("a streak passed in as None blocks", lb.decide(None)["block"])
check("a count passed in as text blocks", lb.decide("3")["block"])
check("unread closes count as possible losses",
      lb.decide(3, 2)["block"] and not lb.decide(3, 1)["block"])
check("...and the reason says so", "unreadable result" in lb.decide(3, 2)["reason"])
check("one unread close alone does not block a clean day", not lb.decide(0, 1)["block"])

print("\n4. The brake cannot act on anything but the entry")
check("the module imports no broker, order or close code",
      not re.search(r"^\s*(from|import)\s+apex\.(brokers|gates|ledger|automation)",
                    BRAKE_SRC, re.M))
check("it has no side effects: no I/O, no clock",
      not re.search(r"\b(open|print|time\.|datetime|requests)\b", BRAKE_SRC.split('"""', 2)[2]))

print("\n5. The loop applies it, for exact rules too")
gate = SRC.find("_lb = loss_brake.decide(")
once = SRC.find("already entered on this bar")
cooldown = SRC.find("Post-loss cooldown: the worst trade after a stop-out")
order = SRC.find('print(f"[UserLoop:{user_id}] ORDER {_order_line}")')
check("the gate exists", gate != -1)
check("it sits in the entry chain before the exact-rule bar guard and the cooldowns",
      0 < gate < once < cooldown)
check("it sits before the order is placed", gate < order)
block = SRC[SRC.rfind("if entry_ok:", 0, gate):SRC.find("# One entry per signal bar", gate)]
check("it is not conditioned on the rule being non-exact", "_exact_rule" not in block)
check("it only refuses the entry", "entry_ok = False" in block)
check("it never closes or orders",
      not re.search(r"close_position|place_order|broker\.|authorize_", block))
check("the skip is journalled with the reason", "_skip(_lb[\"reason\"]" in block)
check("the client is told once a day, with the reason",
      '"action": "STOP"' in block and '_lb["reason"]' in block
      and "lossbrake:{user_id}:{_brake_day}" in block)
check("the alert reuses an ESSENTIAL action, not a muted diagnostic",
      "SKIP_WARN" not in block)
check("the alert is not allowed to break the tick", "except Exception" in block)

print("\n6. The streak it reads is the loop's measured one")
check("unreadable stored state is parsed, not int()-ed into a crash",
      "loss_brake.parse_stored_count(user.get(\"loss_streak\"))" in SRC
      and 'int(user.get("loss_streak") or 0)' not in SRC)
check("unreadable stored state marks today as unknown",
      "streak_unreadable_day" in SRC)
check("the brake is told whether the stored streak is unreadable",
      "unreadable=(streak_unreadable_day" in block)
check("unread closes are kept and persisted",
      '"loss_streak_unread": unread_closes' in SRC)
inc = len(re.findall(r"unread_closes \+= 1", SRC))
check("every close site that can have no P&L counts it as unread", inc == 3)
wins = len(re.findall(r"unread_closes = 0   # a known win", SRC))
check("every known win clears the unread count", wins == 8)
clear = SRC[SRC.index("def _clear_stale_streak"):SRC.index("_cleared_at_start =")]
check("the new trading day clears both counters",
      "unread_closes = 0" in clear and "loss_streak = 0" in clear
      and "nonlocal loss_streak, unread_closes" in clear)
check("the day roll is still evaluated every tick",
      "if _clear_stale_streak():" in SRC)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("Loss-streak brake checks passed.")
