"""CFTC COT — the sign convention is the whole test.

FX futures are all quoted against the dollar: there is no EURUSD contract,
there is a EURO FX contract. Speculators being net long the Swiss franc means
the franc is strong, which means USDCHF FALLS. Get that backwards and the bot
is fed a confident, precisely wrong institutional number on every USD-base
pair — worse than feeding it nothing, because `data_quality` would report the
picture as MORE complete while it points the wrong way.

Verified against a real pull (2026-08-04): EUR net -58,091 of 799,909 OI,
CHF net -32,822 of 109,600 OI.

No network here — readings are stubbed so the test measures the arithmetic,
not the CFTC's uptime.

Run: python tests/test_cot.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import cot  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# Stub the network layer entirely.
FAKE = {}


def fake_reading(currency, now=None):
    currency = str(currency or "").upper()
    if currency == "USD":
        return {"net_pct": 0.0, "net": 0.0, "oi": 0.0, "report_date": None,
                "ts": 0.0, "numeraire": True}
    if currency not in FAKE:
        return None
    return {"net_pct": FAKE[currency], "net": FAKE[currency] * 1000,
            "oi": 1000.0, "report_date": "2026-08-04", "ts": 0.0}


cot.reading = fake_reading

print("\n── real numbers from the 2026-08-04 report ──")
FAKE.update({"EUR": -0.0726, "CHF": -0.2995, "GBP": -0.2345,
             "JPY": -0.1084, "AUD": -0.1380, "XAU": +0.5319})

check("EUR net short → EURUSD bearish",
      cot.pair_bias("EURUSD") < 0, str(cot.pair_bias("EURUSD")))
check("THE SIGN FLIP: CHF net short → USDCHF BULLISH",
      cot.pair_bias("USDCHF") > 0, str(cot.pair_bias("USDCHF")))
check("JPY net short → USDJPY bullish", cot.pair_bias("USDJPY") > 0)
check("GBP net short → GBPUSD bearish", cot.pair_bias("GBPUSD") < 0)
check("gold net long → XAUUSD bullish", cot.pair_bias("XAUUSD") > 0)

print("\n── the flip is exact, not merely the right direction ──")
check("USDCHF is the negation of a hypothetical CHFUSD",
      abs(cot.pair_bias("USDCHF") + (-0.2995 / cot._FULL_SCALE)) < 1e-9,
      str(cot.pair_bias("USDCHF")))
check("EURUSD equals EUR's own bias (USD is the numeraire)",
      abs(cot.pair_bias("EURUSD") - cot.bias("EUR")) < 1e-9)

print("\n── crosses use both legs ──")
# EUR -0.0726 vs GBP -0.2345: EUR is the less-shorted, so EURGBP is bullish.
x = cot.pair_bias("EURGBP")
check("EURGBP is positive — EUR is less shorted than GBP", x > 0, str(x))
check("and equals the difference of the legs",
      abs(x - (-0.0726 - -0.2345) / cot._FULL_SCALE) < 1e-9, str(x))
check("GBPEUR is its mirror image",
      abs(cot.pair_bias("GBPEUR") + x) < 1e-9)

print("\n── missing data produces None, never a confident zero ──")
check("a currency with no futures contract → None",
      cot.pair_bias("USDSEK") is None)
check("USDUSD (both legs the numeraire) → None, not 0.0",
      cot.pair_bias("USDUSD") is None)
check("an unfetched currency → None", cot.pair_bias("NZDUSD") is None)
check("not a 6-char pair → None", cot.pair_bias("US30") is None)
check("empty → None", cot.pair_bias("") is None)
check("None → None", cot.pair_bias(None) is None)

print("\n── extremes clamp instead of running away ──")
FAKE["CAD"] = -0.95
check("an absurd -95% net clamps to -1", cot.bias("CAD") == -1.0)
check("and USDCAD clamps to +1", cot.pair_bias("USDCAD") == 1.0)
FAKE["CAD"] = -0.4906   # the real 2026-08-04 value
check("the real CAD extreme does NOT saturate at the tuned full scale",
      -1.0 < cot.bias("CAD") < -0.9, str(cot.bias("CAD")))

print("\n── full scale keeps the tracked contracts distinguishable ──")
vals = {c: cot.bias(c) for c in ("EUR", "CHF", "GBP", "JPY", "AUD", "CAD")}
saturated = [c for c, v in vals.items() if abs(v) >= 1.0]
check("no more than one contract saturates on real data",
      len(saturated) <= 1, str(saturated))
check("CAD and CHF remain distinguishable (a 25% scale collapsed both to -1)",
      abs(vals["CAD"] - vals["CHF"]) > 0.15,
      f"CAD={vals['CAD']:.3f} CHF={vals['CHF']:.3f}")

print("\n── symbol spellings ──")
for spelling in ("EURUSD", "EUR_USD", "eur/usd", "EUR-USD"):
    check(f"{spelling} parses", cot._split(spelling) == ("EUR", "USD"))
check("explicit legs override parsing",
      cot.pair_bias("WHATEVER", legs=("EUR", "USD")) == cot.bias("EUR"))

print("\n── parsing a raw CFTC row ──")
row = {"noncomm_positions_long_all": "201847",
       "noncomm_positions_short_all": "259938",
       "open_interest_all": "799909",
       "report_date_as_yyyy_mm_dd": "2026-08-04T00:00:00.000"}
p = cot._parse_row(row)
check("net is long minus short", p["net"] == -58091)
check("net_pct divides by open interest",
      abs(p["net_pct"] - (-58091 / 799909)) < 1e-12)
check("the date is trimmed to a day", p["report_date"] == "2026-08-04")
check("zero open interest → None, not a division by zero",
      cot._parse_row({**row, "open_interest_all": "0"}) is None)
check("missing field → None", cot._parse_row({}) is None)
check("junk numbers → None",
      cot._parse_row({**row, "open_interest_all": "lots"}) is None)

print("\n── describe() never pretends ──")
check("no reading says so", "no COT reading" in cot.describe("USDSEK"))
check("a reading shows the value", "+" in cot.describe("USDCHF")
      or "-" in cot.describe("USDCHF"))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL COT CHECKS PASSED.")
