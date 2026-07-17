"""Broker safety tests — TD rate-limit retry, cross-pair sizing.
No network: HTTP calls are monkeypatched.

Run: python tests/test_brokers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PAPER_TRADING"] = "true"

from apex import config as cfg, forex  # noqa: E402
from apex.brokers import twelvedata  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


print("\n🧪 BROKER SAFETY TESTS\n")

print("1. Twelve Data: retry la rate-limit")
calls = {"n": 0}


def fake_get_429(url, params=None, timeout=None):
    calls["n"] += 1
    if calls["n"] < 3:
        return FakeResponse({"code": 429, "message": "out of credits"})
    return FakeResponse({"price": "1.0850"})


_real_get = twelvedata.requests.get
_real_sleep = twelvedata.time.sleep
twelvedata.requests.get = fake_get_429
twelvedata.time.sleep = lambda s: None
try:
    data = twelvedata._get_with_retry("http://x/price", {}, timeout=5)
finally:
    twelvedata.requests.get = _real_get
    twelvedata.time.sleep = _real_sleep

check("retry până la succes", data.get("price") == "1.0850", data)
check("a încercat de 3 ori", calls["n"] == 3, calls["n"])

print("\n2. Cross-pair sizing (EUR_JPY)")
pv = forex.pip_value_per_unit("EUR_JPY", 165.0, quote_usd_rate=1 / 155.0)
check("pip value cu rata corectă", abs(pv - 0.01 / 155.0) < 1e-12, pv)
units = forex.calc_units(1000, 0.02, 15, "EUR_JPY", 165.0, quote_usd_rate=1 / 155.0)
check("sizing realist (~14k unități, nu 90)", 13000 < units < 15000, units)
units_fb = forex.calc_units(1000, 0.02, 15, "EUR_JPY", 165.0)
check("fallback fără rată e conservator", units_fb <= units, (units_fb, units))
check("majors neschimbate",
      12000 < forex.calc_units(1000, 0.02, 15, "EUR_USD", 1.08) < 14500)

print("\n3. PnL cu rata cross")
pnl = forex.pnl_usd("BUY", 165.00, 165.30, 10000, "EUR_JPY", quote_usd_rate=1 / 155.0)
check("30 pips × 10k unități EUR_JPY ≈ $19.35", abs(pnl - 19.35) < 0.1, pnl)

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — broker safety works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
