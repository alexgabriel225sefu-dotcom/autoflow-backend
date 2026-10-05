"""An unknown entry risk must not silently disable the winner-cut guard.

WHAT THIS PROTECTS

_profit_too_small_to_take is the rule that stops a strategy closing a winner
for crumbs. It compares the move against max(round-trip cost, initial_risk x
MIN_EXIT_R). When initial_risk is None the max() collapses to the cost floor
alone — two or three pips — and the 1R protection is gone without a log line
or an error. The guard looks present and enforces nothing.

That is not a hypothetical path. entry_risk_by_sym is in-memory and keyed by
symbol; it is empty after every restart, and the recovery beside it reads
`open_position_snapshot`, which holds ONE position while maxpos is 2. So the
second concurrent position, and every position after a redeploy, reached this
function with initial_risk=None.

Measured on the live account the week this was written: AUDUSD risked 20 pips
and was closed at +10.5 (0.52R); GBPUSD risked 39.1 and closed at +20.6
(0.53R). Both had a 1:2 target. Winners were taken at half the risk they put
up while losers ran the full stop.

THE RULE

Risk is reconstructed, in order: the value passed in, the entry-to-initialStop
distance, the entry snapshot's slPips, then the configured stop distance. The
cost floor stays as a lower bound but is never the whole floor. An exit below
1R is refused whichever way the risk was recovered.

Losing exits are untouched: a strategy closing an underwater trade is saying
its thesis broke, and holding that to a full stop turns a small loss into a
big one.

Run: python tests/test_exit_r_floor.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ.pop("MIN_EXIT_R", None)

from apex import user_loop, forex  # noqa: E402

cut = user_loop._profit_too_small_to_take
failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


# The live AUDUSD trade, to the pip: SELL 0.71459, stop 0.71659 (20 pips),
# target 0.71059. It was closed at 0.71354 — +10.5 pips, 0.52R.
ENTRY, STOP = 0.71459, 0.71659
RISK = STOP - ENTRY
SYM = "AUDUSD"
CUT_PRICE = 0.71354                      # where it actually exited, 0.52R
PAST_1R = ENTRY - RISK * 1.05            # comfortably past 1R


def pos(**over):
    base = {"entryPrice": ENTRY, "side": "SELL", "symbol": SYM,
            "entrySpreadPips": 0.2}
    base.update(over)
    return base


print("\n1. With the risk known, the guard already works")
check("a 0.52R exit is refused", cut(pos(), CUT_PRICE, SYM, RISK) is True)
check("an exit past 1R is allowed", cut(pos(), PAST_1R, SYM, RISK) is False)

print("\n2. With the risk unknown, it must NOT fall back to the spread")
check("a 0.52R exit is still refused when initial_risk is None",
      cut(pos(initialStop=STOP), CUT_PRICE, SYM, None) is True,
      "this is the defect: the floor collapsed to ~0.4 pips of spread")

print("\n3. Every route back to the risk is used")
check("from initialStop", cut(pos(initialStop=STOP), CUT_PRICE, SYM, None) is True)
check("from entrySlPips",
      cut(pos(entrySlPips=forex.to_pips(RISK, SYM, ENTRY)), CUT_PRICE, SYM, None) is True)
check("from the configured stop when the position carries nothing",
      cut(pos(), CUT_PRICE, SYM, None) is True,
      "a position with no memory at all still gets a real floor")

print("\n4. A recovered risk still lets a genuine winner out")
check("past 1R via initialStop", cut(pos(initialStop=STOP), PAST_1R, SYM, None) is False)
check("past 1R via entrySlPips",
      cut(pos(entrySlPips=forex.to_pips(RISK, SYM, ENTRY)), PAST_1R, SYM, None) is False)

print("\n5. Losing exits are never blocked, however the risk is known")
for label, ir, p in (("known risk", RISK, ENTRY + RISK * 0.5),
                     ("unknown risk", None, ENTRY + RISK * 0.5),
                     ("flat", None, ENTRY)):
    check(f"{label}: an underwater exit passes",
          cut(pos(initialStop=STOP), p, SYM, ir) is False,
          "holding a broken thesis to the full stop turns a small loss into a big one")

print("\n6. A recovered risk is the REAL risk, not a token value")
# 0.9R must be refused and 1.1R allowed — a floor that merely beat the spread
# would let both through, so this pins the magnitude, not just the direction.
just_under = ENTRY - RISK * 0.90
just_over = ENTRY - RISK * 1.10
check("0.90R refused", cut(pos(initialStop=STOP), just_under, SYM, None) is True)
check("1.10R allowed", cut(pos(initialStop=STOP), just_over, SYM, None) is False)

print("\n7. The cost floor still applies above 1R when the spread is huge")
wide = pos(initialStop=STOP, entrySpreadPips=40.0)   # 40p spread, 20p risk
check("an exit that clears 1R but not the round trip is refused",
      cut(wide, ENTRY - RISK * 1.5, SYM, None) is True,
      "1R of a 20-pip risk is 20 pips; the round trip costs 80")

print("\n" + "=" * 60)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL EXIT-FLOOR CHECKS PASSED - unknown risk no longer disables the guard.")
