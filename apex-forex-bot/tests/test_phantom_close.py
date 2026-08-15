"""A position that vanishes because focus moved is not a position that closed.

The single-position sync reads only the instrument the loop is focused on.
Auto-Pilot rotates focus between ticks, so a live position on the previous
instrument stops appearing the moment focus moves — and `if prev_pos and not
open_pos` read that absence as a broker-side close.

Live proof, on the demo account, six seconds apart:

    14:32:56  tick 1 EURUSD px=1.15836
    14:32:56  USDCAD closed at the broker while focus moved to EURUSD
    14:32:57  ❌ EURUSD Streak: 2 losses / 0 wins | Today: 4 trades

USDCAD 54303026 was open at the broker the entire time, and the balance never
moved. The invented close booked a losing trade, took the day's count from 3
to 4, filed it under EURUSD, and called `_persist_open_snapshot(None)` — so a
still-open position lost the snapshot that carries its entry price, its
initial stop and its strategy label across a restart.

The broker had already answered the question, too: `get_closed_deal_pnl` found
no closed deal for that id, and the code fell back to a balance delta of 0.00
rather than treating "no such closed deal" as evidence.

Run: python tests/test_phantom_close.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-phantom-")

from apex import user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


USDCAD = {"symbol": "USDCAD", "side": "BUY", "units": 23000.0,
          "entryPrice": 1.38694, "positionId": 54303026}


class Broker:
    """Answers only about the symbol it is asked about — like the real one."""

    def __init__(self, open_positions, fail=False):
        self.open = {k.upper(): v for k, v in (open_positions or {}).items()}
        self.fail = fail
        self.asked = []

    def get_open_position(self, symbol):
        self.asked.append(symbol)
        if self.fail:
            raise RuntimeError("broker unreachable")
        return self.open.get((symbol or "").upper())


print("\n── the exact live scenario ──")
br = Broker({"USDCAD": USDCAD})
still = user_loop._position_still_open(br, USDCAD, "EURUSD", "u1")
check("focus on EURUSD, USDCAD open → recognised as still open", still is True)
check("it asked the broker about USDCAD, not EURUSD",
      br.asked == ["USDCAD"], str(br.asked))

print("\n── a real close is still a close ──")
br = Broker({})
check("focus moved AND the position is gone → close",
      user_loop._position_still_open(br, USDCAD, "EURUSD", "u1") is False)

br = Broker({})
check("focus never moved, position gone → close (no extra read)",
      user_loop._position_still_open(br, USDCAD, "USDCAD", "u1") is False)
check("and it did not waste a broker call", br.asked == [], str(br.asked))

check("symbol variants count as the same instrument, not a rotation",
      user_loop._position_still_open(Broker({}), USDCAD, "USD_CAD", "u1") is False)

print("\n── same pair, different trade ──")
reopened = {**USDCAD, "positionId": 99999999}
check("a NEW position on the pair does not rescue the old one",
      user_loop._position_still_open(Broker({"USDCAD": reopened}),
                                     USDCAD, "EURUSD", "u1") is False)

print("\n── unknown must never read as still-open ──")
check("a broker error → treated as closed, so an SL/TP exit is never silent",
      user_loop._position_still_open(Broker({}, fail=True),
                                     USDCAD, "EURUSD", "u1") is False)
check("a position with no symbol → treated as closed",
      user_loop._position_still_open(Broker({"USDCAD": USDCAD}),
                                     {"positionId": 1}, "EURUSD", "u1") is False)

print("\n── the guard is wired into the close path ──")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "user_loop.py"), encoding="utf-8").read()
check("the close branch consults it",
      "_position_still_open(broker, prev_pos, symbol, user_id)" in SRC)
guard = SRC.index("_position_still_open(broker, prev_pos")
close_branch = SRC.index("last_close_at = time.time()  # re-entry lock")
check("and consults it BEFORE journalling the close", guard < close_branch)
check("a phantom close no longer clears the snapshot",
      SRC.index("prev_pos = None", guard) < close_branch)

print("\n── the close is filed under its own symbol, not the focus ──")
# Scoped to the BROKER_CLOSE block. Everywhere else `symbol` IS the closed
# position's symbol — an SL/TP hit or a manual close on the focused pair —
# so a file-wide assertion would fail on correct code.
_start = SRC.index('_closed_sym = prev_pos.get("symbol")')
block = SRC[_start:SRC.index("_persist_open_snapshot(None)", _start)]
check("record_trade uses the closed position's symbol",
      "user_id=user_id, symbol=_closed_sym)" in block)
check("not the rotating focus", "symbol=symbol)" not in block)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — focus rotation no longer invents a close.")
