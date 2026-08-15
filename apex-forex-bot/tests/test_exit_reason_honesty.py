"""A losing exit must not be reported as taking profit.

mean_reversion's early-exit rule fires on Bollinger position alone and never
read P&L, so every exit it triggered was labelled "taking profit" — including
exits where price had moved AGAINST the trade. Two live examples:

    SELL 0.70581 → "took profit" at 0.70583      (price went up: a loss)
    BUY  0.81320 → "taking profit" at 0.81306    (-$2.14 net)

The accounting was correct both times — the journal recorded win: false and
the right net figure. Only the sentence the user reads was false, which is
worse than a missing explanation: it teaches you to trust a number nobody is
measuring.

The band position decides WHEN to exit; that part is unchanged. Whether the
exit is a profit is a separate fact, and entryPrice is right there.

Run: python tests/test_exit_reason_honesty.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

from apex import ai  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def verdict(side, entry, now_px, bb_pos):
    """Run the rule-based mean_reversion strategy against an open position."""
    ind = {"rsi": 50, "bb_position": bb_pos, "stochRsiK": 50, "price": now_px,
           "ema50": now_px, "ema200": now_px, "bb_bandwidth": 0.5,
           "divergence": "NONE"}
    return ai.mean_reversion_signal(
        ind, open_position={"side": side, "entryPrice": entry})


print("\n── the two real trades that were mislabelled ──")
v = verdict("SELL", 0.70581, 0.70583, bb_pos=30)
check("the SELL still exits", v["action"] == "CLOSE", str(v))
check("but is no longer called profit", "taking profit" not in v["reasoning"],
      v["reasoning"])
check("it says the loss out loud", "loss" in v["reasoning"], v["reasoning"])

v = verdict("BUY", 0.81320, 0.81306, bb_pos=70)
check("the USDCHF BUY still exits", v["action"] == "CLOSE", str(v))
check("and is not called profit either", "taking profit" not in v["reasoning"],
      v["reasoning"])
check("it says the thesis broke", "thesis broke" in v["reasoning"],
      v["reasoning"])

print("\n── a genuine winner is still called a winner ──")
v = verdict("BUY", 0.81000, 0.81300, bb_pos=70)
check("BUY in profit → taking profit", "taking profit" in v["reasoning"],
      v["reasoning"])
v = verdict("SELL", 0.81300, 0.81000, bb_pos=30)
check("SELL in profit → taking profit", "taking profit" in v["reasoning"],
      v["reasoning"])

print("\n── the exit DECISION is unchanged; only the words moved ──")
for side, entry, px, bb, should_close in (
    ("BUY",  0.8100, 0.8130, 70, True),    # past the band → close
    ("BUY",  0.8100, 0.8130, 60, False),   # not past it → hold
    ("SELL", 0.8130, 0.8100, 30, True),
    ("SELL", 0.8130, 0.8100, 40, False),
):
    v = verdict(side, entry, px, bb)
    got = v["action"] == "CLOSE"
    check(f"{side} at bb {bb} → {'CLOSE' if should_close else 'HOLD'}",
          got is should_close, v["action"])

print("\n── flat, and missing data, are described honestly ──")
v = verdict("BUY", 0.81300, 0.81300, bb_pos=70)
check("an exit at the entry price is 'flat', not profit",
      "flat" in v["reasoning"] and "taking profit" not in v["reasoning"],
      v["reasoning"])

ind = {"rsi": 50, "bb_position": 70, "stochRsiK": 50, "price": 0.813,
       "ema50": 0.813, "ema200": 0.813, "bb_bandwidth": 0.5,
       "divergence": "NONE"}
v = ai.mean_reversion_signal(ind, open_position={"side": "BUY"})
check("with no entry price it still exits", v["action"] == "CLOSE", str(v))
check("and claims nothing about the outcome",
      "taking profit" not in v["reasoning"] and "loss" not in v["reasoning"],
      v["reasoning"])

v = ai.mean_reversion_signal(
    ind, open_position={"side": "BUY", "entryPrice": "not-a-number"})
check("an unparseable entry price does not crash the strategy",
      v["action"] == "CLOSE", str(v))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL EXIT-REASON CHECKS PASSED.")
