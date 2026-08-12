"""CFTC Commitments of Traders — free weekly speculative positioning.

The one institutional source in the blueprint that costs nothing: the CFTC
publishes, every Friday, how large speculators were positioned the previous
Tuesday. No key, no account, no licence.

Two properties of this data decide the whole design:

FX futures are all quoted against the dollar. There is no "EURUSD" contract —
there is a EURO FX contract, and speculators being net long it means long EUR
against USD. So a pair's bias is the difference between its two legs, with USD
as the numeraire at zero. EURUSD is +EUR; USDCHF is -CHF, because speculators
being long the franc means the franc is strong and USDCHF therefore falls.
Getting that sign backwards would feed the AI a confident, precisely wrong
number, which is worse than feeding it nothing.

The data is old on arrival and there is no fixing that. Tuesday's positions
publish on Friday, so a reading is three days stale before anyone sees it and
up to ten days stale before the next one lands. It is a slow bias, not a
trigger, and `age_days` travels with every reading so a caller can weight it
accordingly rather than treating it as current.

Same fail-open contract as news.py and sentiment.py: unreachable, empty or
malformed feed means callers get None and trading is unaffected. None here is
correct and useful — institutional.build() reports it as a missing source and
degrades data_quality, which is exactly true.
"""
import threading
import time

import requests

_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
_TIMEOUT = (3.05, 10)
_TTL = 6 * 3600          # weekly data; re-checking a few times a day is ample
_RETRY_BACKOFF = 900     # after a failure, wait this long before trying again

# CFTC market names are exact strings, not patterns. Only currencies with a
# CME/ICE futures contract appear; everything else has no COT reading and must
# therefore produce None rather than a guess.
_MARKETS = {
    "EUR": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "GBP": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
    "JPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "AUD": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "CAD": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "CHF": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
    "NZD": "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "XAU": "GOLD - COMMODITY EXCHANGE INC.",
}

# Net speculative position as a share of open interest at which a reading
# counts as fully stretched. Measured against a live pull rather than guessed:
# on 2026-08-04 the eight tracked contracts ran from CAD at -49% to gold at
# +53% of open interest. An earlier 25% full scale saturated CAD, CHF, NZD and
# gold all to the same +/-1.00, which throws away the difference between
# "stretched" and "the most stretched in the set" — the part worth knowing.
# A tuning constant, not a discovered truth; the principled version is a
# percentile against this contract's own history, which needs storage.
_FULL_SCALE = 0.50

_cache = {}      # currency -> {"net_pct", "net", "oi", "report_date", "ts"}
_fetching = set()   # currencies with a refresh in flight
_retry_at = {}      # currency -> earliest next attempt after a failure
_lock = threading.Lock()


def _parse_row(row):
    try:
        long_ = float(row["noncomm_positions_long_all"])
        short = float(row["noncomm_positions_short_all"])
        oi = float(row["open_interest_all"])
        if oi <= 0:
            return None
        return {
            "net": long_ - short,
            "oi": oi,
            "net_pct": (long_ - short) / oi,
            "report_date": str(row.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "ts": time.time(),
        }
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _fetch_one(currency):
    market = _MARKETS.get(currency)
    if not market:
        return None
    try:
        r = requests.get(_URL, timeout=_TIMEOUT, headers={"User-Agent": "ApexBot/1.0"},
                         params={
                             "$select": ("market_and_exchange_names,"
                                         "report_date_as_yyyy_mm_dd,"
                                         "noncomm_positions_long_all,"
                                         "noncomm_positions_short_all,"
                                         "open_interest_all"),
                             "market_and_exchange_names": market,
                             "$order": "report_date_as_yyyy_mm_dd DESC",
                             "$limit": 1,
                         })
        r.raise_for_status()
        rows = r.json()
        return _parse_row(rows[0]) if rows else None
    except Exception as e:
        print(f"[COT] fetch failed for {currency}: {e}")
        return None


def _refresh(currencies, now=None):
    """Background refresh. Never raises into the loop, never blocks a tick.

    In-flight state and retry backoff are tracked PER CURRENCY. A single shared
    flag looked equivalent and was not: a scan across a watchlist calls this
    once per symbol in quick succession, and one global flag meant every call
    after the first was dropped as "already fetching". Only the first currency
    the bot happened to look at ever got data, and every other pair silently
    reported no COT reading forever.
    """
    now = time.time() if now is None else now
    with _lock:
        due = [c for c in currencies
               if c in _MARKETS and c not in _fetching
               and now >= _retry_at.get(c, 0.0)]
        _fetching.update(due)
    if not due:
        return

    def _run():
        for c in due:
            try:
                got = _fetch_one(c)
                with _lock:
                    if got:
                        _cache[c] = got
                        _retry_at.pop(c, None)
                    else:
                        _retry_at[c] = time.time() + _RETRY_BACKOFF
            finally:
                with _lock:
                    _fetching.discard(c)

    threading.Thread(target=_run, daemon=True).start()


def reading(currency, now=None):
    """Latest cached COT reading for one currency, or None.

    Returns cached data immediately and refreshes in the background, so a slow
    or dead CFTC endpoint can never add latency to a trading tick.
    """
    currency = str(currency or "").upper()
    if currency == "USD":
        # The numeraire. Every FX contract is priced against it, so it has no
        # net position of its own here — that is a fact about the data, not a
        # missing value, and callers treat it as exactly zero.
        return {"net_pct": 0.0, "net": 0.0, "oi": 0.0,
                "report_date": None, "ts": time.time(), "numeraire": True}
    if currency not in _MARKETS:
        return None
    now = time.time() if now is None else now
    with _lock:
        got = _cache.get(currency)
    if not got or (now - got["ts"]) > _TTL:
        _refresh([currency])
    return got


def bias(currency, now=None):
    """Speculative positioning for one currency, normalised to [-1, +1]."""
    got = reading(currency, now)
    if not got:
        return None
    return max(-1.0, min(1.0, got["net_pct"] / _FULL_SCALE))


def pair_bias(symbol, legs=None, now=None):
    """COT bias for a traded PAIR, normalised to [-1, +1], or None.

    Positive means speculators are positioned for the pair to rise. The sign
    flip on quote-currency legs is the whole point: long CHF is bearish
    USDCHF.

    Returns None unless at least one leg has real data — a pair where both
    legs are unknown has no reading, and USD/USD arithmetic on two absent
    values would otherwise produce a confident 0.0.
    """
    legs = legs or _split(symbol)
    if not legs or len(legs) != 2:
        return None
    base, quote = legs
    b, q = reading(base, now), reading(quote, now)
    if not b or not q:
        return None
    # Both legs the numeraire, or neither carrying real data → no reading.
    if b.get("numeraire") and q.get("numeraire"):
        return None
    val = (b["net_pct"] - q["net_pct"]) / _FULL_SCALE
    return max(-1.0, min(1.0, val))


def age_days(symbol, legs=None, now=None):
    """How stale the oldest leg of this pair's reading is, in days, or None.

    Exposed because a COT number without its age invites being read as current
    when it can be ten days old.
    """
    legs = legs or _split(symbol)
    if not legs:
        return None
    now = time.time() if now is None else now
    ages = []
    for c in legs:
        got = reading(c, now)
        if got and got.get("report_date"):
            try:
                t = time.mktime(time.strptime(got["report_date"], "%Y-%m-%d"))
                ages.append((now - t) / 86400.0)
            except (TypeError, ValueError):
                pass
    return round(max(ages), 1) if ages else None


def _split(symbol):
    """EURUSD / EUR_USD / eurusd → ("EUR", "USD"). None if not a 6-char pair."""
    s = "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())
    if len(s) != 6:
        return None
    return (s[:3], s[3:])


def describe(symbol):
    """One line for logs / Telegram, age included."""
    b = pair_bias(symbol)
    if b is None:
        return f"{symbol}: no COT reading"
    a = age_days(symbol)
    return (f"{symbol}: COT {b:+.2f}"
            + (f" ({a:.0f}d old)" if a is not None else ""))
