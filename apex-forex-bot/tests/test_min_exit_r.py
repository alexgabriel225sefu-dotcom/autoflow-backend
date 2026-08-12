"""Regression test: strategies must not cut winners short.

A week of real trades on the live account, converted to pips:

    wins   +0.6, +1.7                    (mean 1.15 pips)
    losses -0.7, -2.4, -9.3, -10.8       (mean 5.8 pips)

SL was 15 pips and TP was 30 — 2:1 on paper, 1:5 AGAINST in reality, because
mean_reversion's "price overshot past mean" rule closed every winner the
moment price touched the Bollinger midline. At 1:5 break-even needs an 83%
win rate; the account did 33%, realised -54.55 for the week.

That rule fires on band position alone and never reads P&L. One live trade
was SOLD at 0.70581 and booked as "taking profit" at 0.70583 — price had gone
AGAINST the position.

Run: python tests/test_min_exit_r.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import forex, user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SYM = "AUDUSD"
PIP = forex.pip_size(SYM)
RISK_15 = 15 * PIP          # the account's configured 15-pip stop

blocked = user_loop._profit_too_small_to_take


def pos(side="SELL", entry=0.70581, spread=0.7):
    return {"side": side, "entryPrice": entry, "symbol": SYM,
            "entrySpreadPips": spread}


print("\n── the two exits that actually happened on the live account ──")
# SELL 0.70581 → "took profit" at 0.70583. Price moved AGAINST the position.
check("SELL closed 0.2 pips UNDERWATER is not held (thesis broke — let it out)",
      blocked(pos("SELL"), 0.70583, SYM, RISK_15) is False)
# SELL 0.70615 → closed 0.70603 = 1.2 pips, booked +2.52 on 0.42 lots.
check("SELL 'profit-take' at 1.2 pips IS blocked",
      blocked(pos("SELL", 0.70615), 0.70603, SYM, RISK_15) is True)

print("\n── the floor is the trade's own risk, not a fixed pip count ──")
check("7 pips on a 15-pip stop (0.47R) is blocked",
      blocked(pos("SELL"), 0.70581 - 7 * PIP, SYM, RISK_15) is True)
check("15 pips on a 15-pip stop (1.0R) is allowed",
      blocked(pos("SELL"), 0.70581 - 15 * PIP, SYM, RISK_15) is False)
check("20 pips on a 15-pip stop is allowed",
      blocked(pos("SELL"), 0.70581 - 20 * PIP, SYM, RISK_15) is False)
check("7 pips on a 5-pip stop (1.4R) is allowed — same pips, tighter risk",
      blocked(pos("SELL"), 0.70581 - 7 * PIP, SYM, 5 * PIP) is False)

print("\n── BUY side behaves identically ──")
check("BUY +1.2 pips is blocked",
      blocked(pos("BUY"), 0.70581 + 1.2 * PIP, SYM, RISK_15) is True)
check("BUY +15 pips is allowed",
      blocked(pos("BUY"), 0.70581 + 15 * PIP, SYM, RISK_15) is False)
check("BUY underwater is allowed out",
      blocked(pos("BUY"), 0.70581 - 3 * PIP, SYM, RISK_15) is False)

print("\n── ASYMMETRY: only profitable exits are ever blocked ──")
for loss_pips in (0.1, 0.7, 2.4, 9.3, 10.8):
    check(f"SELL {loss_pips} pips underwater exits freely",
          blocked(pos("SELL"), 0.70581 + loss_pips * PIP, SYM, RISK_15) is False)
check("exactly flat exits freely",
      blocked(pos("SELL"), 0.70581, SYM, RISK_15) is False)

print("\n── cost floor applies when no risk is pinned ──")
# No initial_risk (position adopted mid-flight): fall back to round-trip cost.
check("0.5 pips with a 0.7-pip spread is blocked (cannot pay 1.4 pips cost)",
      blocked(pos("SELL", spread=0.7), 0.70581 - 0.5 * PIP, SYM, None) is True)
check("3 pips with a 0.7-pip spread clears the cost floor",
      blocked(pos("SELL", spread=0.7), 0.70581 - 3 * PIP, SYM, None) is False)
check("no risk AND no spread on record → nothing to enforce, allow",
      blocked({"side": "SELL", "entryPrice": 0.70581, "symbol": SYM},
              0.70581 - 0.2 * PIP, SYM, None) is False)

print("\n── malformed input never blocks a close ──")
check("no entry price", blocked({"side": "SELL"}, 0.70583, SYM, RISK_15) is False)
check("no side", blocked({"entryPrice": 0.70581}, 0.70583, SYM, RISK_15) is False)
check("junk entry price",
      blocked({"side": "SELL", "entryPrice": "n/a"}, 0.70583, SYM, RISK_15) is False)
check("junk price",
      blocked(pos("SELL"), None, SYM, RISK_15) is False)
check("junk risk falls back to the cost floor",
      blocked(pos("SELL"), 0.70581 - 3 * PIP, SYM, "oops") is False)

print("\n── MIN_EXIT_R=0 disables the gate entirely ──")
os.environ["MIN_EXIT_R"] = "0"
check("1.2-pip profit-take goes through again",
      blocked(pos("SELL", 0.70615), 0.70603, SYM, RISK_15) is False)
os.environ.pop("MIN_EXIT_R")

print("\n── the numbers this changes ──")
os.environ["MIN_EXIT_R"] = "1.0"
held = [p for p in (0.6, 1.2, 1.7, 7.0)
        if blocked(pos("SELL"), 0.70581 - p * PIP, SYM, RISK_15)]
check("every winner from the losing week would now be held",
      held == [0.6, 1.2, 1.7, 7.0], str(held))
os.environ.pop("MIN_EXIT_R")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL MIN-EXIT-R CHECKS PASSED.")
