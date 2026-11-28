"""Regression: one broker-side close must be journaled exactly once.

Observed live, around a redeploy:

    17:19:47  BROKER_CLOSE GBPUSD netPnl=-10.8 side=BUY
    17:20:01  BROKER_CLOSE GBPUSD netPnl=-10.8 side=BUY price=1.34992

Two paths reach the same close: the restart recovery (persisted snapshot says
open, broker says closed) and the in-loop detection (prev_pos set, open_pos
now None). Both ran, seconds apart, and the trade was booked twice.

The duplicate row is the least of it. loss_streak counted each close twice, so
"3 consecutive losses" fired after two real ones and cut risk to a quarter for
no reason — and the duplicate becomes a second training label for a trade that
happened once, biasing the EV calibration.

Run: python tests/test_close_dedupe.py
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
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-dedupe-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import user_store, user_loop, ev  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


UID = "dedupe-test"
user_store.clear_trades(UID)

POS = {"symbol": "GBPUSD", "side": "BUY", "entryPrice": 1.350665,
       "positionId": 53865309, "openedAt": "2026-08-11 16:08:17",
       "entrySpreadPips": 0.9, "entryConfidence": 80, "entryRegime": "ranging",
       "entrySlPips": 15.0, "entryTpPips": 30.0, "entrySide": "BUY"}

# Path A — restart recovery. No exit price: P&L came from the deal history.
A = {"action": "BROKER_CLOSE", "symbol": "GBPUSD", "side": "BUY", "price": None,
     "entryPrice": 1.350665, "netPnl": -10.8, "grossPnl": -10.2, "costUsd": 0.6,
     "balance": 2986.47, "time": "2026-08-11 17:19:47"}
# Path B — in-loop detection, 14s later, same close, now with a price.
B = {**A, "price": 1.34992, "time": "2026-08-11 17:20:01"}

print("\n── the live sequence: two paths, one close ──")
first = user_loop._log_trade(UID, A, POS)
second = user_loop._log_trade(UID, B, POS)
check("first write accepted", first is True)
check("second write rejected", second is False)
check("journal holds exactly one row", len(user_store.load_trades(UID)) == 1,
      str(len(user_store.load_trades(UID))))
check("the close counts as ONE training label",
      ev.labelled_count(user_store.load_trades(UID)) == 1)

print("\n── deduped by positionId even when the numbers differ ──")
user_store.clear_trades(UID)
user_loop._log_trade(UID, A, POS)
drifted = user_loop._log_trade(
    UID, {**B, "netPnl": -10.9, "entryPrice": 1.350666}, POS)
check("same positionId is the same trade", drifted is False)
check("still one row", len(user_store.load_trades(UID)) == 1)

print("\n── without a positionId, match on symbol + entry in a window ──")
user_store.clear_trades(UID)
nopid = {k: v for k, v in POS.items() if k != "positionId"}
user_loop._log_trade(UID, A, nopid)
check("duplicate within the window rejected",
      user_loop._log_trade(UID, B, nopid) is False)
check("same close hours later is treated as a NEW trade",
      user_loop._log_trade(UID, {**B, "time": "2026-08-11 23:59:00"},
                           nopid) is True)

print("\n── genuinely different trades are never merged ──")
user_store.clear_trades(UID)
user_loop._log_trade(UID, A, nopid)
# This assertion used to read the other way, and it was wrong. Live on
# 2026-08-14 one EURUSD close was journalled twice a second apart: +$2.89 from
# the broker's own fill, then $0.00 from the balance-delta estimate. Keying the
# dedupe on P&L meant it only caught duplicates that AGREED — while the one
# worth catching is exactly the one that disagrees. Same pair, same entry,
# seconds apart: that is one trade reported twice, whatever the second path
# computed for it.
check("a duplicate whose P&L DISAGREES is still a duplicate",
      user_loop._log_trade(UID, {**B, "netPnl": -22.4}, nopid) is False)
user_store.clear_trades(UID)
user_loop._log_trade(UID, A, nopid)
check("different entry price is a new trade",
      user_loop._log_trade(UID, {**B, "entryPrice": 1.36000}, nopid) is True)
user_store.clear_trades(UID)
user_loop._log_trade(UID, A, nopid)
check("different symbol is a new trade",
      user_loop._log_trade(UID, {**B, "symbol": "EURUSD"}, nopid) is True)
# Two ids settle it the other way too: the entry price no longer gets a vote
# once the broker has named both positions, so a genuine re-entry at the same
# price is never swallowed as a duplicate.
user_store.clear_trades(UID)
user_loop._log_trade(UID, A, POS)
check("a different positionId is a different trade, same entry or not",
      user_loop._log_trade(UID, B, {**POS, "positionId": 99999999}) is True)

print("\n── a losing close is counted once by the risk ladder ──")
# _log_trade's return value is what the loop gates loss_streak on, so this is
# the property that actually protects the risk ladder.
user_store.clear_trades(UID)
streak = 0
for rec in (A, B):                       # the same loss, reported twice
    if user_loop._log_trade(UID, rec, POS):
        streak += 1
check("two reports of one loss advance the streak once", streak == 1, str(streak))

user_store.clear_trades(UID)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL CLOSE-DEDUPE CHECKS PASSED.")

