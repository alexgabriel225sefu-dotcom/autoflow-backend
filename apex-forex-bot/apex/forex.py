"""Forex domain math — pips, position sizing, leverage, market hours.

Instruments use underscore notation: EUR_USD, GBP_JPY, XAU_USD …
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


_METALS = {"XAU", "XAG", "XPT", "XPD"}   # gold, silver, platinum, palladium

def is_tradeable(instrument: str) -> bool:
    """What this bot trades: spot FX with a USD leg, plus metals.

    A positive allowlist, deliberately — not a list of things to block. The
    accepted set is (_CCY x _CCY with a USD leg) plus (_METALS x _CCY), and
    anything outside it is refused because it was never named, not because a
    blocklist happened to remember it. That is why no list of coins exists
    anywhere in this module: a symbol nobody allowed is already refused.

    The notes below are therefore why each class is ABSENT from the allowlist,
    not entries in a rejection table:

      * INDICES, STOCKS, ETFs — they need per-exchange trading calendars that
        do not exist here; the bot would believe Frankfurt is open at 03:00.
      * FX CROSSES WITH NO USD LEG (GBP_JPY, EUR_GBP, AUD_CHF) — `calc_units`
        needs a `quote_usd_rate` to value them and nothing passes one, so the
        margin cap read one unit of GBP_JPY as $190 rather than its true
        ~$1.21 and sized the position at about 1/31 of the intended risk.
        docs/ASSETS.md states the rule: a risk calculation quietly off by 10x
        is worse than a refused order.

    Accepts EUR_USD / EURUSD / USD_JPY / XAUUSD.
    """
    s = _norm(instrument)
    if len(s) != 6 or not s.isalpha():
        return False
    if _is_fx(s):
        return "USD" in (s[:3], s[3:])
    return s[:3] in _METALS and s[3:] in _CCY


def pip_size(instrument: str, price: float = None) -> float:
    """Pip size for ANY instrument the broker offers — clients pick freely via
    /symbol, so this can't assume FX.

    Known conventions first (FX 0.0001 / JPY 0.01, gold 0.1, silver 0.01,
    index points). Anything else uses a magnitude rule when the price is
    known: 1 pip = 4 orders of magnitude below the price (EURUSD 1.13→0.0001,
    USDJPY 150→0.01, gold 3350→0.1, US30 44k→1) — the same convention,
    generalized. Nothing outside the allowlist can be traded, but /symbol lets
    a client NAME anything, and a display path must not divide by zero."""
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
    return 0.0001


def usd_exposure(instrument: str, side: str) -> int:
    """+1 = the trade is net LONG USD, -1 = net SHORT USD, 0 = no USD leg.
    Used by the correlation guard so the bot doesn't stack many positions that
    are secretly the same macro bet (BUY EURUSD + BUY GBPUSD = both short USD)."""
    s = _norm(instrument)
    if not _is_fx(s) or "USD" not in s:
        return 0  # non-FX (metals, indices) or a cross without USD → own bucket
    if s.startswith("USD"):
        return 1 if side == "BUY" else -1     # BUY USDJPY = long USD
    if s.endswith("USD"):
        return -1 if side == "BUY" else 1     # BUY EURUSD = short USD
    return 0


def min_units(instrument: str):
    """Order floor: 0.01 lot (1,000 units) for FX. For metals one unit is one
    ounce and can be worth thousands, so the floor is a small FRACTION —
    otherwise risk-based sizing that lands below 1 unit would be forced up
    ~10x on a small account. The broker's real per-symbol minimum/step is
    applied on top of this at order time (see ctrader._vol_rules)."""
    s = _norm(instrument)
    return 1000 if (_is_fx(s) or s.endswith("JPY")) else 0.01


def safe_min_units(instrument: str, balance: float, price: float,
                   leverage: float = 30, margin_cap: float = 0.5) -> float:
    """Min units that the account can actually margin. Returns 0 if the account
    is too small for even 1 micro-lot, so the caller can skip the trade instead
    of sending a broker-rejected order."""
    floor = min_units(instrument)
    margin_needed = required_margin(floor, instrument, price, leverage)
    if margin_needed > balance * margin_cap:
        return 0
    return floor


def round_units(units: float, instrument: str):
    """FX trades in whole units (thousands); metals allow fractional size, so
    keep 2 decimals instead of truncating to int — which zeroed out any
    sub-1-unit size, e.g. 0.34 oz of gold."""
    s = _norm(instrument)
    if _is_fx(s) or s.endswith("JPY"):
        return int(units)
    return round(float(units), 2)


def lots_to_units(lots: float, instrument: str) -> float:
    """Convert lot size to units: FX 1 lot = 100,000 units; metals = units directly."""
    s = _norm(instrument)
    if _is_fx(s) or s.endswith("JPY"):
        return lots * 100_000
    return lots


def unit_label(instrument: str) -> str:
    """Human label for a manual-trade size, matching what lots_to_units actually
    does: 'lot' for FX (100,000 units each), 'oz' for metals, 'unit' for
    anything else a client names — those pass straight through as raw
    quantities, not classic 100-unit-style lots."""
    s = _norm(instrument)
    if _is_fx(s) or s.endswith("JPY"):
        return "lot"
    if s[:3] in _METALS:
        return "oz"
    return "unit"


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
    # USD-quoted: FX ending in USD, plus metals (priced in USD at cTrader
    # brokers) → 1 pip on 1 unit = pip size in USD.
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
        notional_per_unit = price  # USD-quoted FX and metals
    elif quote_usd_rate and quote_usd_rate > 0:
        notional_per_unit = price * quote_usd_rate
    else:
        notional_per_unit = price  # fallback conservator — supraestimează marja
    max_units = (balance * leverage * margin_cap) / notional_per_unit
    # Keep the fractional size — callers round per instrument (round_units).
    # int() here silently zeroed any sub-1-unit size (0.34 oz of gold → 0).
    return max(0.0, min(units, max_units))



def floor_risk_at(units: float, instrument: str, price: float,
                  stop_pips: float) -> float:
    """What taking `units` actually loses if the stop is hit, in dollars."""
    if not stop_pips:
        return 0.0
    return abs(units) * pip_value_per_unit(instrument, price) * abs(stop_pips)


def floor_risk_ok(units: float, instrument: str, price: float,
                  stop_pips: float, risk_budget_usd: float,
                  hard_ceiling_usd: float = None,
                  tolerance: float = 0.10) -> bool:
    """Is it acceptable to take `units`, given the broker's minimum lot?

    TWO different limits, and conflating them was the mistake here.

    RISK_PER_TRADE is a SIZING TARGET. It says how big a position to compute,
    not how big a position the account may ever hold. The hard limits are the
    ones the client set as limits: MAX_DAILY_LOSS_PCT and MAX_DD_PCT.

    That distinction matters because a broker minimum is not negotiable. Gold
    at this broker is 1 oz minimum; 0.5% of $3,221 over a $48 ATR stop is
    0.33 oz. There is no size that both clears the minimum and hits the
    target — the only ways to "fix" it are a tighter stop (a $16 stop on an
    instrument with a $19 ATR is inside the noise and would be stopped out for
    nothing) or refusing gold entirely. Refusing was this function's first
    answer, and it was wrong: 1 oz risks 1.49% of that account against a 4%
    daily-loss limit the client themselves set. That is a trade they can
    plainly afford.

    What was ACTUALLY wrong with the original `max(units, floor)` was not that
    it exceeded the target — it was that it did so SILENTLY and WITHOUT BOUND.
    On a small enough account or a wide enough stop it could be 10x or 50x,
    and nothing anywhere said so.

    So: exceeding the target is allowed, exceeding `hard_ceiling_usd` is not,
    and the caller discloses whenever it happens. With no ceiling given the
    target is the only limit, which keeps every existing caller strict.

    `tolerance` absorbs ordinary lot-step rounding.
    """
    if not risk_budget_usd or risk_budget_usd <= 0 or not stop_pips:
        return True
    loss = floor_risk_at(units, instrument, price, stop_pips)
    if loss <= risk_budget_usd * (1.0 + tolerance):
        return True
    if hard_ceiling_usd and hard_ceiling_usd > 0:
        return loss <= hard_ceiling_usd
    return False


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
