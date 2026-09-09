"""Every open position is managed, not just the focused one.

_manage_trailing is called with the loop's FOCUSED symbol. The focus is
re-picked by the scanner, and the scanner only runs when `slot_free` —
`open_count < maxpos`. So at maxpos=2 with two positions open, the focus could
not move, and the second position had no trailing stop and no break-even for
as long as both were open.

Its original stop was still attached at the broker, so the loss was bounded.
What it lost was the upside: a winner never ratcheted, never moved to
break-even, and gave its gains back. That is invisible in a test suite and
invisible in the logs — the position simply never produces a STOP_MOVED line,
which looks exactly like a position that never moved enough to earn one.

Only positions THIS process opened are touched. entry_risk_by_sym is the
record of that, and it is the gate: a position belonging to another bot
sharing the account is left completely alone.

Run: python tests/test_multipos_management.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-mp-"))

from apex import user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name}  → {detail}")
    if not cond:
        failures.append(name)


SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

print("\n👥  EVERY POSITION, NOT JUST THE FOCUS\n")

print("1. The focus really can freeze at max positions")
# This is the precondition for the bug; if it ever stops being true the extra
# management below becomes redundant rather than wrong, and this check says so.
check("the scanner is gated on a free slot",
      "slot_free = ((open_pos is None) if cfg.PAPER_TRADING" in SRC
      and "open_count < maxpos" in SRC)
check("and the focus is only re-picked inside that gate",
      re.search(r"if watchlist and slot_free and due_to_scan", SRC) is not None)

print("\n2. Non-focused positions are managed too")
check("there is a second _manage_trailing call site",
      SRC.count("_manage_trailing(") >= 3,   # def + focused + others
      f"{SRC.count('_manage_trailing(')} occurrences")
check("it iterates the broker's own position list",
      "for _op in all_positions:" in SRC)
check("it skips the focused symbol rather than doing it twice",
      "_nrm(_osym) == _nrm(symbol)" in SRC)
check("it only touches positions this process opened",
      "_orisk = entry_risk_by_sym.get(_nrm(_osym))" in SRC
      and "if _orisk is None:" in SRC,
      "another bot's position on the same account must be left alone")
check("a price failure skips that symbol instead of the tick",
      "continue" in SRC.split("for _op in all_positions:")[1][:1600])

print("\n3. It behaves like the focused path")


class _B:
    def __init__(self, ok=True):
        self.amends = []
        self.ok = ok

    def amend_sltp(self, position_id, sl=None, tp=None, instrument=None):
        self.amends.append({"pid": position_id, "sl": sl, "tp": tp})
        return self.ok

    def get_bid_ask(self, instrument=None):
        return (1.3690, 1.3691)


class _Cfg:
    TRAILING_STOP = True
    BREAKEVEN_AT_R = 1.0
    PAPER_TRADING = False


POS = {"positionId": 77, "entryPrice": 1.36441, "stopLoss": 1.36138,
       "takeProfit": 1.37047, "side": "BUY", "symbol": "GBPUSD"}
b = _B()
moved = user_loop._manage_trailing(b, _Cfg(), dict(POS), "GBPUSD", 1.3690,
                                   initial_risk=0.00303)
check("a non-focused winner does ratchet", moved is not None, moved)
check("…and keeps its take-profit", b.amends and b.amends[-1]["tp"] == 1.37047,
      b.amends[-1] if b.amends else "no amend")
check("a losing position is left alone",
      user_loop._manage_trailing(_B(), _Cfg(), dict(POS), "GBPUSD", 1.3600,
                                 initial_risk=0.00303) is None,
      "nothing to protect below entry")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the second position is managed too.")
