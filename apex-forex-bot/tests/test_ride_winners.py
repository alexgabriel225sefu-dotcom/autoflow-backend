"""Regression test: a strongly-running winner is ridden, not closed.

Live XAUUSD trade: BUY 4403.25, closed at 4407.73 for +$26.88 on a $9 risk
(SL 15 pips x $0.10 pip = $1.50 on 6 oz). That is 2.99R, so the MIN_EXIT_R
gate correctly let it through — but the reason was "price overshot past mean"
and gold kept going. Mean reversion's thesis was finished; the move was not.

Nothing in the bot ever let a winner run. This is that rule.

Safety property under test: the trade is only held when the stop has ACTUALLY
been tightened. Every failure path must fall through to a normal close — a
position that could not be protected must never be held open on intention.

Run: python tests/test_ride_winners.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SYM = "XAUUSD"
ENTRY = 4403.25
RISK = 1.50          # 15 pips of gold
CFG = types.SimpleNamespace(TRAILING_STOP=True)


class Broker:
    """Records amend_sltp calls; `ok=False` simulates a broker refusal."""

    def __init__(self, ok=True, boom=False):
        self.ok, self.boom, self.calls = ok, boom, []

    def amend_sltp(self, pid, sl=None, instrument=None):
        if self.boom:
            raise RuntimeError("connection reset")
        self.calls.append((pid, sl, instrument))
        return self.ok


def pos(side="BUY", sl=ENTRY - RISK, pid=54090394):
    return {"side": side, "entryPrice": ENTRY, "symbol": SYM,
            "stopLoss": sl, "positionId": pid}


IND_UP = {"ema50": 4400.0}      # trend behind a BUY
IND_DOWN = {"ema50": 4412.0}    # trend against a BUY

ride = user_loop._ride_instead_of_close

print("\n── the exact live trade: 2.99R with the trend still up ──")
b = Broker()
p = pos()
held = ride(b, CFG, p, SYM, 4407.73, RISK, IND_UP, "t")
check("the trade is ridden instead of closed", held is True)
check("the stop was actually moved", len(b.calls) == 1, str(b.calls))
if b.calls:
    new_sl = b.calls[0][1]
    # profit 4.48, lock 0.6 -> keep 4403.25 + 2.688 = 4405.938
    check("stop locks 60% of the open profit", abs(new_sl - 4405.938) < 0.01,
          str(new_sl))
    check("locked stop is above entry (trade can no longer lose)",
          new_sl > ENTRY)
    check("the position dict reflects the new stop",
          p["stopLoss"] == round(new_sl, 6))

print("\n── not running hard enough → close normally ──")
for r, px in ((0.0, ENTRY), (1.0, ENTRY + RISK), (1.9, ENTRY + 1.9 * RISK)):
    b = Broker()
    check(f"{r}R does not trigger a ride",
          ride(b, CFG, pos(), SYM, px, RISK, IND_UP, "t") is False)
    check(f"  and no stop was touched at {r}R", b.calls == [])
b = Broker()
check("exactly 2.0R does trigger",
      ride(b, CFG, pos(), SYM, ENTRY + 2 * RISK, RISK, IND_UP, "t") is True)

print("\n── trend no longer behind the trade → take the money ──")
b = Broker()
check("BUY with price below EMA50 is closed, not ridden",
      ride(b, CFG, pos(), SYM, 4407.73, RISK, IND_DOWN, "t") is False)
check("  no stop moved", b.calls == [])

print("\n── SELL side ──")
b = Broker()
sell = pos("SELL", sl=ENTRY + RISK)
held = ride(b, CFG, sell, SYM, ENTRY - 3 * RISK, RISK, {"ema50": 4410.0}, "t")
check("SELL 3R with price below EMA50 is ridden", held is True)
if b.calls:
    check("SELL stop locked below entry", b.calls[0][1] < ENTRY,
          str(b.calls[0][1]))
b = Broker()
check("SELL with price ABOVE EMA50 is closed",
      ride(b, CFG, pos("SELL", sl=ENTRY + RISK), SYM,
           ENTRY - 3 * RISK, RISK, {"ema50": 4380.0}, "t") is False)

print("\n── SAFETY: never hold a trade we could not protect ──")
check("broker refuses the amend → close normally",
      ride(Broker(ok=False), CFG, pos(), SYM, 4407.73, RISK, IND_UP, "t") is False)
check("broker raises → close normally",
      ride(Broker(boom=True), CFG, pos(), SYM, 4407.73, RISK, IND_UP, "t") is False)
check("broker cannot amend at all → close normally",
      ride(types.SimpleNamespace(), CFG, pos(), SYM, 4407.73, RISK,
           IND_UP, "t") is False)
check("no positionId → close normally",
      ride(Broker(), CFG, pos(pid=None), SYM, 4407.73, RISK, IND_UP, "t") is False)
check("no risk on record → close normally",
      ride(Broker(), CFG, pos(), SYM, 4407.73, None, IND_UP, "t") is False)
check("no stop on record → close normally",
      ride(Broker(), CFG, pos(sl=0), SYM, 4407.73, RISK, IND_UP, "t") is False)
check("trailing disabled → close normally",
      ride(Broker(), types.SimpleNamespace(TRAILING_STOP=False), pos(), SYM,
           4407.73, RISK, IND_UP, "t") is False)

print("\n── the trail is tighten-only ──")
b = Broker()
# Stop already ratcheted past where the ride would put it.
check("an already-tighter stop is left alone",
      ride(b, CFG, pos(sl=4407.0), SYM, 4407.73, RISK, IND_UP, "t") is False)
check("  and no amend was sent", b.calls == [])

print("\n── malformed input never holds a position open ──")
check("junk entry price",
      ride(Broker(), CFG, {"side": "BUY", "entryPrice": "x", "stopLoss": 1,
                           "positionId": 1}, SYM, 4407.73, RISK, IND_UP) is False)
check("junk price", ride(Broker(), CFG, pos(), SYM, None, RISK, IND_UP) is False)
check("no indicators at all still rides (trend check just skipped)",
      ride(Broker(), CFG, pos(), SYM, 4407.73, RISK, None, "t") is True)
check("junk ema50 is ignored rather than blocking",
      ride(Broker(), CFG, pos(), SYM, 4407.73, RISK, {"ema50": "n/a"}, "t") is True)

print("\n── RIDE_AT_R / RIDE_LOCK are tunable ──")
os.environ["RIDE_AT_R"] = "5"
check("RIDE_AT_R=5 → a 2.99R winner is closed, not ridden",
      ride(Broker(), CFG, pos(), SYM, 4407.73, RISK, IND_UP, "t") is False)
os.environ["RIDE_AT_R"] = "0"
check("RIDE_AT_R=0 disables riding entirely",
      ride(Broker(), CFG, pos(), SYM, 4407.73, RISK, IND_UP, "t") is False)
os.environ.pop("RIDE_AT_R")
os.environ["RIDE_LOCK"] = "0.9"
b = Broker()
ride(b, CFG, pos(), SYM, 4407.73, RISK, IND_UP, "t")
check("RIDE_LOCK=0.9 keeps 90% of the move",
      b.calls and abs(b.calls[0][1] - (ENTRY + 4.48 * 0.9)) < 0.01,
      str(b.calls))
os.environ["RIDE_LOCK"] = "1.5"
check("a nonsensical lock (>1) disables rather than misbehaves",
      ride(Broker(), CFG, pos(), SYM, 4407.73, RISK, IND_UP, "t") is False)
os.environ.pop("RIDE_LOCK")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL RIDE-WINNERS CHECKS PASSED.")
