"""One bot, three asset classes — and the lines that must still hold.

Crypto used to be refused by the forex build to keep two products apart. That
separation was protecting the wrong thing: the crypto build was a fork that
had fallen behind by every hardening fix — no order gate, no ownership lease,
no idempotency ledger, no broker-verified account mode — so "crypto has its
own bot" meant "crypto has the older bot". Merging retires the fork.

What must NOT follow from that:

  * indices, stocks and ETFs becoming tradeable by accident. They are refused
    deliberately, and not out of caution: they need per-exchange trading
    calendars and quote-currency conversion in sizing. Neither exists. The
    failure would be silent — a position sized in the wrong currency, sent to
    a closed exchange;
  * crypto skipping any safety gate the FX path clears;
  * the crypto build turning into a general one. It stays narrow, because a
    client who bought "crypto" should not find EURUSD in their journal.

WEEKEND HOURS — a recorded assumption, not a measurement. Crypto CFDs at
Pepperstone close with the forex week, so the existing global market gate and
the Friday flatten are correct for them and nothing here changes. That is the
owner's observation of one broker, not a property of crypto: a broker offering
weekend crypto would need per-instrument hours in `is_market_open` and in the
flatten window. The conservative failure mode if this assumption is wrong is
no weekend trading, which loses opportunity rather than money.

Run: python tests/test_crypto_in_forex.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-cryptofx-")

from apex import config as cfg, forex, user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


print("\n🪙  CRYPTO IN THE FOREX BOT\n")

print("1. Crypto is tradeable now")
for sym in ("BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "LTCUSD", "ADAUSD",
            "DOGEUSD", "LINKUSD", "BCHUSD", "DOTUSD"):
    check(f"{sym} accepted", forex.is_tradeable(sym) is True)

print("\n2. …alongside what it already traded")
for sym in ("EURUSD", "EUR_USD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD"):
    check(f"{sym} still accepted", forex.is_tradeable(sym) is True)

print("\n3. Indices, stocks and ETFs are still refused — on purpose")
for sym in ("US30", "NAS100", "US500", "GER40", "UK100", "JPN225",
            "AAPL", "TSLA", "NVDA", "SPY", "VWCE"):
    check(f"{sym} refused", forex.is_tradeable(sym) is False,
          "these need exchange calendars and quote-currency conversion first")
check("nonsense is refused", forex.is_tradeable("") is False
      and forex.is_tradeable("ZZ") is False
      and forex.is_tradeable(None) is False)

print("\n4. The crypto build stays narrow")
check("it still refuses forex", forex.is_crypto("EURUSD") is False)
check("it still refuses metals", forex.is_crypto("XAUUSD") is False)
check("and accepts crypto", forex.is_crypto("BTCUSD") is True)
check("the forex build blocks nothing now", cfg.CROSS_PRODUCT_BLOCK == set(),
      cfg.CROSS_PRODUCT_BLOCK)

print("\n5. Sizing works on a crypto instrument")
# BTC at 104k with a 2,000-point stop: 1% of a 3,214 account is $32.14, and
# the size has to come out sane rather than zero or the whole account.
px, stop_px = 104000.0, 2000.0
ps = forex.pip_size("BTCUSD", px)
stop_pips = stop_px / ps
units = forex.calc_units(3214.0, 0.01, stop_pips, "BTCUSD", px)
risk = units * stop_pips * forex.pip_value_per_unit("BTCUSD", px)
check("pip size is derived, not guessed at", ps > 0, ps)
check("the size is neither zero nor the whole account", 0 < units < 1, units)
check("and it risks about what was asked", 30 <= risk <= 34, f"${risk:.2f}")

print("\n6. The regime default follows the INSTRUMENT, not the build")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "user_loop.py"), encoding="utf-8").read()
seg = SRC.split("_default_mode = ")[1][:160]
check("crypto defaults to trend-following", '"trend"' in seg, seg[:80])
check("it is decided per symbol", "is_crypto(symbol)" in seg, seg[:120],)
check("forex still defaults to fading", '"mean_reversion"' in seg, seg[:160])

print("\n7. Crypto clears the same gates as everything else")
guard = SRC.split("def force_trade")[1].split("def ")[0]
check("force_trade still authorises through the gate",
      "gates.authorize_order" in guard)
check("and its product guard now names all three classes",
      "forex, metals and crypto" in guard, "the refusal must tell the truth")
check("the automatic path is unchanged", "gates.authorize_order" in SRC)

print("\n8. The scan cap was raised deliberately, not removed")
cap = SRC.split("autopilot_universe\"] if w][:")[1].split("]")[0]
check("the universe is still capped", cap.isdigit(), cap)
check("and the cap is 12", cap == "12", cap)
check("the reason is recorded next to it",
      "single socket" in SRC.split("autopilot_universe\"] if w]")[0][-700:],
      "a cap with no reason gets raised again by whoever finds it annoying")

print("\n9. Weekend behaviour is unchanged — and that is the assumption")
import datetime as _dt  # noqa: E402

sat = _dt.datetime(2026, 8, 22, 12, 0, tzinfo=_dt.timezone.utc)   # Saturday
wed = _dt.datetime(2026, 8, 19, 12, 0, tzinfo=_dt.timezone.utc)   # Wednesday
check("the market gate still closes at the weekend",
      forex.is_market_open(sat) is False,
      "crypto CFDs close with the forex week at this broker")
check("and is open midweek", forex.is_market_open(wed) is True)
check("the gate is not per-instrument (documented, revisit if a broker differs)",
      forex.is_market_open.__code__.co_argcount == 1,
      "if weekend crypto is ever offered, this is the function to change")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — one bot, FX + metals + crypto.")
