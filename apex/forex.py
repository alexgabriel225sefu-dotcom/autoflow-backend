"""Forex domain math — pips, position sizing, leverage, market hours.

Instruments use OANDA notation: EUR_USD, GBP_JPY, XAU_USD …
Account currency is assumed to be USD.
"""
from datetime import datetime, timezone

MAJORS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD"]


def pip_size(instrument: str) -> float:
    """0.01 for JPY-quoted pairs, 0.0001 for everything else."""
    return 0.01 if instrument.upper().endswith("_JPY") else 0.0001


def to_pips(price_distance: float, instrument: str) -> float:
    return price_distance / pip_size(instrument)


def from_pips(pips: float, instrument: str) -> float:
    return pips * pip_size(instrument)


def pip_value_per_unit(instrument: str, price: float) -> float:
    """Value of 1 pip for 1 unit, in USD.

    Quote=USD (EUR_USD): pip value = pip_size.
    Base=USD (USD_JPY):  pip value = pip_size / price.
    Crosses (EUR_GBP):   approximated with the quote leg at the given price.
    """
    instrument = instrument.upper()
    ps = pip_size(instrument)
    if instrument.endswith("_USD"):
        return ps
    if not price:
        return ps
    return ps / price


def calc_units(balance: float, risk_pct: float, stop_pips: float,
               instrument: str, price: float, leverage: float = 30,
               margin_cap: float = 0.5, mult: float = 1.0) -> int:
    """Risk-based position size in units, capped by available margin.

    risk_amount = balance × risk_pct × mult
    units       = risk_amount / (stop_pips × pip_value_per_unit)
    margin cap  : units × price ≤ balance × leverage × margin_cap
    """
    if balance <= 0 or stop_pips <= 0 or price <= 0:
        return 0
    risk_amount = balance * risk_pct * mult
    pv = pip_value_per_unit(instrument, price)
    if pv <= 0:
        return 0
    units = risk_amount / (stop_pips * pv)
    # Notional per unit in USD: 1 unit of USD_XXX = $1; otherwise ≈ price
    notional_per_unit = 1.0 if instrument.upper().startswith("USD_") else price
    max_units = (balance * leverage * margin_cap) / notional_per_unit
    return int(max(0, min(units, max_units)))


def required_margin(units: int, instrument: str, price: float, leverage: float = 30) -> float:
    notional = units * (1.0 if instrument.upper().startswith("USD_") else price)
    return notional / leverage if leverage else notional


def pnl_usd(side: str, entry: float, exit_price: float, units: int, instrument: str) -> float:
    """Realized PnL in USD for a closed position."""
    diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    pips = to_pips(diff, instrument)
    return pips * pip_value_per_unit(instrument, exit_price) * units


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
    return to_pips(ask - bid, instrument)
