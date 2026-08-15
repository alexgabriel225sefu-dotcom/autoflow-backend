"""Unit tests for forex math — pips, sizing, margin, market hours.

Run: python tests/test_forex.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

from apex import forex  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0

print("\n🧪 FOREX MATH TESTS\n")
print("1. Pip size")
check("EUR_USD pip = 0.0001", forex.pip_size("EUR_USD") == 0.0001)
check("USD_JPY pip = 0.01", forex.pip_size("USD_JPY") == 0.01)
check("GBP_JPY pip = 0.01", forex.pip_size("GBP_JPY") == 0.01)

print("\n2. Pip conversion")
check("0.0050 EUR_USD = 50 pips", forex.to_pips(0.0050, "EUR_USD") == 50,
      forex.to_pips(0.0050, "EUR_USD"))
check("0.50 USD_JPY = 50 pips", forex.to_pips(0.50, "USD_JPY") == 50,
      forex.to_pips(0.50, "USD_JPY"))
check("15 pips EUR_USD = 0.0015", abs(forex.from_pips(15, "EUR_USD") - 0.0015) < 1e-12,
      forex.from_pips(15, "EUR_USD"))
check("round trip pips↔price", abs(forex.to_pips(forex.from_pips(33, "USD_JPY"), "USD_JPY") - 33) < 1e-9)

print("\n3. Pip value per unit (USD account)")
check("EUR_USD: $0.0001/unit", forex.pip_value_per_unit("EUR_USD", 1.10) == 0.0001)
v = forex.pip_value_per_unit("USD_JPY", 150.0)
check("USD_JPY: pip/price", abs(v - 0.01 / 150.0) < 1e-12, v)

print("\n4. Position sizing")
# $1000 balance, 2% risk, 15-pip stop on EUR_USD @ 1.10
# risk $20 / (15 × $0.0001) = 13,333 units; margin: 13333×1.10/30 ≈ $489 — ok at cap 0.5×1000×30
units = forex.calc_units(1000, 0.02, 15, "EUR_USD", 1.10, leverage=30)
check("risk-based size ≈ 13,333 units", 13000 <= units <= 13400, units)
loss = 15 * forex.pip_value_per_unit("EUR_USD", 1.10) * units
check("loss at SL ≈ 2% of balance", abs(loss - 20) < 0.6, loss)

# Margin cap kicks in with low leverage
capped = forex.calc_units(1000, 0.02, 5, "EUR_USD", 1.10, leverage=1, margin_cap=0.5)
check("low leverage caps the size", capped <= 1000 * 1 * 0.5 / 1.10 + 1, capped)
check("zero balance → 0 units", forex.calc_units(0, 0.02, 15, "EUR_USD", 1.10) == 0)
check("zero stop → 0 units", forex.calc_units(1000, 0.02, 0, "EUR_USD", 1.10) == 0)

print("\n5. Margin")
m = forex.required_margin(13333, "EUR_USD", 1.10, 30)
check("EUR_USD margin = units×price/lev", abs(m - 13333 * 1.10 / 30) < 0.01, m)
m = forex.required_margin(10000, "USD_JPY", 150.0, 30)
check("USD_JPY margin = units/lev", abs(m - 10000 / 30) < 0.01, m)

print("\n6. PnL")
pnl = forex.pnl_usd("BUY", 1.1000, 1.1030, 10000, "EUR_USD")
check("long EUR_USD +30 pips × 10k = $30", abs(pnl - 30) < 0.01, pnl)
pnl = forex.pnl_usd("SELL", 1.1000, 1.1030, 10000, "EUR_USD")
check("short loses the same", abs(pnl + 30) < 0.01, pnl)
pnl = forex.pnl_usd("BUY", 150.00, 150.50, 10000, "USD_JPY")
check("long USD_JPY 50 pips ≈ $33", abs(pnl - 33.22) < 0.1, pnl)

print("\n7. Market hours (UTC)")
check("Wednesday noon → open",
      forex.is_market_open(datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)))
check("Saturday → closed",
      not forex.is_market_open(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)))
check("Friday 22:00 → closed",
      not forex.is_market_open(datetime(2026, 6, 12, 22, 0, tzinfo=timezone.utc)))
check("Friday 20:00 → open",
      forex.is_market_open(datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc)))
check("Sunday 20:00 → closed",
      not forex.is_market_open(datetime(2026, 6, 14, 20, 0, tzinfo=timezone.utc)))
check("Sunday 22:00 → open",
      forex.is_market_open(datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc)))

print("\n8. Sessions")
s = forex.active_sessions(datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc))
check("14:00 UTC → London + New York", "London" in s and "New York" in s, s)
s = forex.active_sessions(datetime(2026, 6, 10, 3, 0, tzinfo=timezone.utc))
check("03:00 UTC → Tokyo + Sydney", "Tokyo" in s and "Sydney" in s, s)

print("\n9. Spread")
sp = forex.spread_pips(1.1000, 1.1002, "EUR_USD")
check("2-pip spread detected", abs(sp - 2) < 1e-9, sp)

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — forex math works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
