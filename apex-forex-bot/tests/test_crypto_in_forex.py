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

print("\n10. Tuning follows the INSTRUMENT, not the build")
# An audit of the enabling commit found this was fixed in exactly ONE place
# (the regime default) while the documentation claimed it generally. Every
# threshold below is a case where the FX value does not merely mistune crypto
# — it disables it, silently, with the reason buried in a skip line.


class _Cfg:
    LEVERAGE = 30.0
    MARGIN_CAP = 0.5
    FLASH_SPIKE_PCT = 0.012
    PRODUCT = "forex"


_cfg = _Cfg()

# Leverage. Regulated brokers cap crypto near 1:2–1:5 while FX majors get
# 1:30, and calc_units uses leverage ONLY for the margin cap — so an assumed
# 30x on a 5x instrument makes the cap check a different question than the one
# the broker will ask.
lev_btc = user_loop.leverage_for_symbol(None, _cfg, "BTCUSD")
lev_fx = user_loop.leverage_for_symbol(None, _cfg, "EURUSD")
check("crypto falls back to crypto-grade leverage", lev_btc == 5.0, lev_btc)
check("FX keeps FX leverage", lev_fx == 30.0, lev_fx)
check("they are not the same number", lev_btc != lev_fx)

# The audit's own scenario: $3,200, 0.5% risk, BTC at 104k with a tight stop.
# At the assumed 30x the position needed 52% of the account in margin while
# the code believed it was inside its 50% cap.
_px = 104000.0
_stop_pips = 200.0 / forex.pip_size("BTCUSD", _px)
_u30 = forex.calc_units(3200.0, 0.005, _stop_pips, "BTCUSD", _px, leverage=30)
_u5 = forex.calc_units(3200.0, 0.005, _stop_pips, "BTCUSD", _px, leverage=lev_btc)
check("the margin cap binds tighter at real crypto leverage", _u5 < _u30,
      f"{_u5:.4f} vs {_u30:.4f}")
check("and the sized position fits inside the cap",
      (_u5 * _px) / lev_btc <= 3200.0 * 0.5 + 1,
      f"${(_u5 * _px) / lev_btc:,.0f} of $1,600")

# Flash-spike guard. At the FX 1.2%, ordinary BTC candles trip it — the bot
# would refuse crypto entries as a matter of course.
check("the violent-candle threshold is widened for crypto",
      user_loop.flash_spike_pct_for(_cfg, "BTCUSD") > 0.02,
      user_loop.flash_spike_pct_for(_cfg, "BTCUSD"))
check("and left alone for FX",
      user_loop.flash_spike_pct_for(_cfg, "EURUSD") == 0.012)

# Regime detection. BTC's EMA separation clears the 0.30% FX cutoff almost
# always, which would lock its regime to "trending" and stop mean-reversion
# ever firing on it.
from apex import strategies  # noqa: E402

check("regime detection accepts a symbol",
      "symbol" in strategies.detect_regime.__code__.co_varnames)
check("so does momentum", "symbol" in strategies.soros_momentum.__code__.co_varnames)
check("crypto is recognised by the threshold helper",
      strategies._crypto_thresholds("BTCUSD") is True)
check("FX is not", strategies._crypto_thresholds("EURUSD") is False)
check("and no symbol means keep the old behaviour",
      strategies._crypto_thresholds(None) is None,
      "callers that never passed one must be unaffected")

# The signal engines read the instrument off the indicator dict, because the
# strategy dispatch table has a fixed three-argument shape.
from apex import ai, indicators  # noqa: E402

check("indicators carry the symbol when given one",
      "symbol" in indicators.analyze.__code__.co_varnames)
check("the engines read it", ai._is_crypto_ind({"symbol": "BTCUSD"}) is True)
check("and answer FX correctly", ai._is_crypto_ind({"symbol": "EURUSD"}) is False)
check("with no symbol they fall back to the build flag",
      ai._is_crypto_ind({}) is (getattr(ai.cfg, "PRODUCT", "forex") == "crypto"))

LOOP_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "apex", "user_loop.py"), encoding="utf-8").read()
check("the loop passes the symbol into the indicators",
      "indicators.analyze(candles, symbol)" in LOOP_SRC)
check("and into regime detection",
      "detect_regime(candles, symbol)" in LOOP_SRC)
check("no sizing site still assumes one global leverage",
      "leverage=cfg.LEVERAGE" not in LOOP_SRC,
      "every calc_units must resolve leverage per instrument")

print("\n11. The client is asked WHAT to trade, once the account is linked")
# Asked after the connection on purpose: only then is it known which
# instruments this particular broker lists, so the answer can be honoured
# rather than promised.
from apex import telegram as tg, user_store  # noqa: E402

_sent = []
_rs, _rr = tg.send_to, tg._restart_user_loop
try:
    tg.send_to = lambda cid, txt, *a, **k: _sent.append(txt)
    tg._restart_user_loop = lambda cid: True
    user_store.save("990001", {"ctrader_access_token": "x",
                               "ctrader_account_id": 1, "style": "swing"})

    tg._OB_RENDER["method"]("990001")
    asked = _sent[-1]
    check("the question is asked before any instrument is offered",
          "What do you want to trade" in asked, asked[:120])
    for word in ("Forex", "Crypto", "Both"):
        check(f"{word} is offered", word in asked)
    check("it says the setting is changeable later", "/assets" in asked)

    # The basket must match the sentence the client was shown.
    for choice, expect_fx, expect_crypto in (("forex", True, False),
                                             ("crypto", False, True),
                                             ("both", True, True)):
        user_store.update("990001", {"asset_class": choice})
        pool = tg.candidates_for(user_store.load("990001"))
        has_fx = any(not forex.is_crypto(c) for c in pool)
        has_cr = any(forex.is_crypto(c) for c in pool)
        check(f"{choice}: FX present={expect_fx}", has_fx is expect_fx, pool[:6])
        check(f"{choice}: crypto present={expect_crypto}", has_cr is expect_crypto,
              pool[:6])

    # A truncated "both" basket must still carry both — the scan cap cuts the
    # list, and an alphabetical pool would hand a client twelve FX pairs.
    user_store.update("990001", {"asset_class": "both"})
    top = tg.candidates_for(user_store.load("990001"))[:12]
    check("a capped mixed basket still holds crypto",
          any(forex.is_crypto(c) for c in top), top)
    check("…and still holds FX", any(not forex.is_crypto(c) for c in top), top)

    # Changing it later is a real change, not a label.
    _sent.clear()
    tg._handle_assets("990001", "crypto", advance=False)
    check("/assets confirms the change",
          any("Crypto" in m for m in _sent), _sent[-1][:80] if _sent else "")
    check("and it is stored",
          user_store.load("990001").get("asset_class") == "crypto")
    check("an unknown value shows the current setting instead of setting it",
          (tg._handle_assets("990001", "bananas", advance=False) or True)
          and user_store.load("990001").get("asset_class") == "crypto")
finally:
    tg.send_to, tg._restart_user_loop = _rs, _rr

check("existing clients are not re-asked",
      tg._ob_satisfied({"strategy": "auto", "autopilot": True,
                        "ctrader_account_id": 1, "symbol": "EURUSD",
                        "risk_accepted": "2026-01-01", "style": "swing"},
                       "method") is True,
      "re-asking someone mid-trading looks like the bot resetting itself")
check("the default is everything, not forex",
      tg.asset_class_of({}) == "both",
      "narrowing an existing client silently would change what their bot does")

TG_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "apex", "telegram.py"), encoding="utf-8").read()
check("the Auto-Pilot basket is built from the preference",
      "candidates_for(user)" in TG_SRC)
check("and its cap matches the loop's", "universe[:12]" in TG_SRC,
      "a basket longer than the loop scans is a promise the bot does not keep")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — one bot, FX + metals + crypto.")
