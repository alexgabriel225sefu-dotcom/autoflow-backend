"""Regression test: a trade must never be journaled with another pair's entry.

The live journal contained rows like "USDJPY entry 0.81256 exit 158.377" — the
exit is a real USDJPY price, the entry is an AUDUSD one. That happens when the
loop's focus symbol and its open_pos describe different instruments, and it
corrupts the tax export, the realised P&L and (now) the labelled data the EV
calibrator learns from.

Run: python tests/test_journal_symbol_guard.py
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

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-guard-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import user_store, user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


UID = "journal-guard-test"
user_store.clear_trades(UID)

print("\n── the exact corruption seen in production ──")
# Focus symbol says USDJPY; the position actually belongs to AUDUSD.
mismatched_pos = {
    "symbol": "AUDUSD", "side": "BUY", "entryPrice": 0.81256,
    "entrySpreadPips": 1.1, "entryConfidence": 84, "entryRegime": "trending",
    "entrySlPips": 12.0, "entryTpPips": 20.4, "entrySide": "BUY",
    "entryProbability": 0.68, "entryEvR": 0.22,
}
record = {
    "action": "CLOSE", "symbol": "USDJPY", "price": 158.377,
    "entryPrice": 0.81256, "grossPnl": 52.21, "costUsd": 1.08,
    "netPnl": 48.8, "balance": 3050.3, "time": "2026-08-07 11:02:58",
}
user_loop._log_trade(UID, record, mismatched_pos)
row = user_store.load_trades(UID)[0]

check("row is still written (accounting must not silently vanish)",
      row.get("symbol") == "USDJPY" and row.get("netPnl") == 48.8)
check("the other pair's confidence is NOT attached",
      row.get("confidence") is None, str(row.get("confidence")))
check("the other pair's regime is NOT attached", row.get("regime") is None)
check("the other pair's spread is NOT attached", row.get("spreadPips") is None)
check("the other pair's SL/TP is NOT attached",
      row.get("slPips") is None and row.get("tpPips") is None)
check("mismatched row cannot become a training label",
      __import__("apex.ev", fromlist=["ev"]).labelled_count(
          user_store.load_trades(UID)) == 0)

print("\n── a matching position still labels normally ──")
user_store.clear_trades(UID)
good_pos = {**mismatched_pos, "symbol": "USDJPY", "entryPrice": 157.9}
user_loop._log_trade(UID, record, good_pos)
row = user_store.load_trades(UID)[0]
check("confidence attached", row.get("confidence") == 84)
check("regime attached", row.get("regime") == "trending")
check("counts as a labelled example",
      __import__("apex.ev", fromlist=["ev"]).labelled_count(
          user_store.load_trades(UID)) == 1)

print("\n── symbol formatting differences are not treated as a mismatch ──")
user_store.clear_trades(UID)
user_loop._log_trade(UID, {**record, "symbol": "USD_JPY"},
                     {**good_pos, "symbol": "usdjpy"})
check("EUR_USD / eurusd / EURUSD normalise to the same instrument",
      user_store.load_trades(UID)[0].get("confidence") == 84)

print("\n── positions without a symbol are still trusted (paper mode shape) ──")
user_store.clear_trades(UID)
no_sym = {k: v for k, v in good_pos.items() if k != "symbol"}
user_loop._log_trade(UID, record, no_sym)
check("no symbol on the position → fields still copied",
      user_store.load_trades(UID)[0].get("confidence") == 84)

user_store.clear_trades(UID)

print("\n── THE ROOT CAUSE: a broker close logged under the focus symbol ──")
# Last night, live: USDCHF closed at the broker for +$24.99 while Auto-Pilot
# had already rotated the focus to AUDUSD. The journal row said
#   symbol AUDUSD · entry 0.81169 (USDCHF) · exit 0.70484 (AUDUSD)
# The guard below caught it and dropped the entry fields, so the calibrator was
# never poisoned — but the label was lost with them, which is why a clean win
# left the sample count unmoved. The fix is upstream: use the CLOSED
# position's own symbol, and refuse to pass off the focus instrument's price
# as its exit.
def broker_close_record(prev_pos, focus_symbol, focus_price):
    """Mirrors the corrected construction in _loop."""
    closed_sym = prev_pos.get("symbol") or focus_symbol
    exit_px = focus_price if _nrm(closed_sym) == _nrm(focus_symbol) else None
    return {"action": "BROKER_CLOSE", "symbol": closed_sym, "price": exit_px,
            "entryPrice": prev_pos.get("entryPrice"), "netPnl": 24.99,
            "time": "2026-08-13 03:41:23"}


def _nrm(x):
    return (x or "").upper().replace("_", "").replace("/", "").replace("-", "")


CHF_POS = {"symbol": "USDCHF", "side": "BUY", "entryPrice": 0.81169,
           "entryConfidence": 73, "entryRegime": "ranging", "entrySlPips": 35.0}

user_store.clear_trades(UID)
rec = broker_close_record(CHF_POS, "AUDUSD", 0.70484)
check("the close is filed under USDCHF, not the focus symbol",
      rec["symbol"] == "USDCHF", rec["symbol"])
check("AUDUSD's price is NOT passed off as USDCHF's exit",
      rec["price"] is None, str(rec["price"]))
user_loop._log_trade(UID, rec, CHF_POS)
row = user_store.load_trades(UID)[0]
check("no mismatch, so the entry snapshot survives",
      row.get("confidence") == 73, str(row.get("confidence")))
check("and the win finally counts toward calibration",
      __import__("apex.ev", fromlist=["ev"]).labelled_count(
          user_store.load_trades(UID)) == 1)

user_store.clear_trades(UID)
rec2 = broker_close_record(CHF_POS, "USDCHF", 0.81420)
check("when focus and position agree, the exit price is kept",
      rec2["price"] == 0.81420)

user_store.clear_trades(UID)


print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL JOURNAL SYMBOL-GUARD CHECKS PASSED.")
