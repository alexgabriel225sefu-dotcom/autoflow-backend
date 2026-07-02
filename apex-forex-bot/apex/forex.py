"""Forex domain math — pips, position sizing, leverage, market hours.

Instruments use OANDA notation: EUR_USD, GBP_JPY, XAU_USD …
Account currency is assumed to be USD.
"""
from datetime import datetime, timezone

MAJORS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD"]


_CCY = {"EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "SEK", "NOK", "DKK",
        "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH", "CNY", "RON",
        "ILS", "THB", "RUB"}


def _norm(instrument: str) -> str:
    return (instrument or "").upper().replace("_", "").replace("/", "").replace("-", "")


def _is_fx(s: str) -> bool:
    return len(s) == 6 and s.isalpha() and s[:3] in _CCY and s[3:] in _CCY


def pip_size(instrument: str, price: float = None) -> float:
    """Pip size for ANY instrument the broker offers — clients pick freely via
    /symbol, so this can't assume FX.

    Known conventions first (FX 0.0001 / JPY 0.01, gold 0.1, silver 0.01,
    index points). Everything else (stocks, oil, gas, any crypto, exotic
    CFDs) uses a magnitude rule when the price is known: 1 pip = 4 orders of
    magnitude below the price (EURUSD 1.13→0.0001, USDJPY 150→0.01, gold
    3350→0.1, US30 44k→1, BTC 104k→10) — the same convention, generalized."""
    s = _norm(instrument)
    if s.startswith("XAU"):
        return 0.1
    if s.startswith(("XAG", "XPT", "XPD")):
        return 0.01
    if s.startswith(("US30", "US500", "USTEC", "NAS100", "SPX500", "GER40", "DE40",
                     "UK100", "JPN225", "AUS200", "HK50", "FRA40", "EUSTX50",
                     "US2000", "DJ30", "STOXX50")):
        return 1.0
    if s.endswith("JPY"):
        return 0.01
    if _is_fx(s):
        return 0.0001
    if price and price > 0:
        import math
        return 10.0 ** (math.floor(math.log10(price)) - 4)
    # No price context: coarse class guesses, then the FX default.
    if s.startswith(("BTC", "ETH", "SOL", "XRP", "LTC", "BNB", "ADA", "DOG")):
        return 1.0
    return 0.0001


def min_units(instrument: str) -> int:
    """Order floor: 0.01 lot (1,000 units) for FX; a single unit for everything
    else (oz, contracts, shares, coins) — the broker's real per-symbol minimum
    is applied at order time on top of this."""
    s = _norm(instrument)
    return 1000 if (_is_fx(s) or s.endswith("JPY")) else 1


def to_pips(price_distance: float, instrument: str, price: float = None) -> float:
    return price_distance / pip_size(instrument, price)


def from_pips(pips: float, instrument: str, price: float = None) -> float:
    return pips * pip_size(instrument, price)


def pip_value_per_unit(instrument: str, price: float,
                       quote_usd_rate: float = None) -> float:
    """Value of 1 pip for 1 unit, in USD.

    Quote=USD (EUR_USD): pip value = pip_size.
    Base=USD (USD_JPY):  pip value = pip_size / price.
    Crosses (EUR_GBP, EUR_JPY): pip value = pip_size × USD-value of the quote
    currency. Pass quote_usd_rate (e.g. GBP_USD price, or 1/USD_JPY price);
    without it the quote leg is approximated via the pair price — close for
    JPY crosses, but can undersize the risk estimate, so callers sizing real
    money on crosses should always provide the rate.
    """
    instrument = instrument.upper()
    s = instrument.replace("_", "").replace("/", "").replace("-", "")
    ps = pip_size(instrument, price)
    # USD-quoted: FX ending in USD, plus metals/indices/crypto CFDs (all
    # priced in USD at cTrader brokers) → 1 pip on 1 unit = pip size in USD.
    if s.endswith("USD") or ps >= 0.01 and not s.endswith("JPY"):
        return ps
    if s.startswith("USD"):
        return ps / price if price else ps
    if quote_usd_rate and quote_usd_rate > 0:
        return ps * quote_usd_rate
    return ps / price if price else ps


def calc_units(balance: float, risk_pct: float, stop_pips: float,
               instrument: str, price: float, leverage: float = 30,
               margin_cap: float = 0.5, mult: float = 1.0,
               quote_usd_rate: float = None) -> int:
    """Risk-based position size in units, capped by available margin.

    risk_amount = balance × risk_pct × mult
    units       = risk_amount / (stop_pips × pip_value_per_unit)
    margin cap  : units × price ≤ balance × leverage × margin_cap
    """
    if balance <= 0 or stop_pips <= 0 or price <= 0:
        return 0
    risk_amount = balance * risk_pct * mult
    pv = pip_value_per_unit(instrument, price, quote_usd_rate)
    if pv <= 0:
        return 0
    units = risk_amount / (stop_pips * pv)
    # Notional per unit in USD: USD_XXX = $1, XXX_USD = price,
    # crosses (EUR_JPY) = price × USD-value of quote (165 JPY ≈ $1.06, nu $165)
    inst = instrument.upper()
    sN = inst.replace("_", "").replace("/", "").replace("-", "")
    if sN.startswith("USD") and not sN.endswith("USD"):
        notional_per_unit = 1.0
    elif sN.endswith("USD") or (pip_size(inst, price) >= 0.01 and not sN.endswith("JPY")):
        notional_per_unit = price  # USD-quoted FX + metals/indices/crypto CFDs
    elif quote_usd_rate and quote_usd_rate > 0:
        notional_per_unit = price * quote_usd_rate
    else:
        notional_per_unit = price  # fallback conservator — supraestimează marja
    max_units = (balance * leverage * margin_cap) / notional_per_unit
    return int(max(0, min(units, max_units)))


def required_margin(units: int, instrument: str, price: float, leverage: float = 30) -> float:
    notional = units * (1.0 if instrument.upper().startswith("USD_") else price)
    return notional / leverage if leverage else notional


def pnl_usd(side: str, entry: float, exit_price: float, units: int, instrument: str,
            quote_usd_rate: float = None) -> float:
    """Realized PnL in USD for a closed position."""
    diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    pips = to_pips(diff, instrument, exit_price)
    return pips * pip_value_per_unit(instrument, exit_price, quote_usd_rate) * units


def is_market_open(now: datetime = None) -> bool:
    """Forex trades 24/5: opens Sunday 21:00 UTC, closes Friday 21:00 UTC."""
    now = now or datetime.now(timezone.utc)
    wd, hour = now.weekday(), now.hour  # Mon=0 … Sun=6
    if wd == 5:                        # Saturday
        return False
    if wd == 4 and hour >= 21:         # Friday after close
        return False
    if wd == 6 and hour < 21:          # Sunday before open
        return False
    return True


def active_sessions(now: datetime = None) -> list:
    """Which trading sessions are live (UTC approximations)."""
    now = now or datetime.now(timezone.utc)
    h = now.hour
    sessions = []
    if 22 <= h or h < 7:
        sessions.append("Sydney")
    if 0 <= h < 9:
        sessions.append("Tokyo")
    if 8 <= h < 17:
        sessions.append("London")
    if 13 <= h < 22:
        sessions.append("New York")
    return sessions


def spread_pips(bid: float, ask: float, instrument: str) -> float:
    return to_pips(ask - bid, instrument, bid)
