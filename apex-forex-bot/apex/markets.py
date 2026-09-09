"""The market snapshot behind the Markets screen and Home's overview.

One fetch serves every client. That is not an optimisation, it is the
constraint the whole module exists for: cTrader's documented limit is

    "5 requests per second for any historical data requests. These limits are
     per connection, no matter how many users are authorized through it."

Daily bars are historical. Eight instruments fetched per user, per screen
open, would spend the entire allowance on a handful of people looking at the
same eight numbers — the identical waste candle_cache was built to end for
the trading loop. So the snapshot is built once, cached, and handed to
everyone who asks until it goes stale.

Nothing here is derived, smoothed or filled in. A symbol whose bars the
broker did not return is reported as unavailable; it never borrows the last
price it had, and it never appears with a zero.
"""

import threading
import time

from apex import config as cfg

# Long enough that a screen open costs nothing, short enough that the number
# on Home is recognisably today's. Daily-change is not a tick feed; a client
# watching a price move opens the chart, which has its own live path.
_TTL_S = 20

# Instruments the platform actually trades. Markets does not advertise a
# symbol the execution engine would refuse.
_METALS = ("XAUUSD", "XAGUSD")

_lock = threading.Lock()
_cache = {"at": 0.0, "rows": None}


def universe():
    """(forex, metals) — what the platform trades, split for the UI."""
    all_syms = [s.strip().upper() for s in (cfg.AUTOPILOT_UNIVERSE or []) if s.strip()]
    forex = [s for s in all_syms if s not in _METALS]
    metals = [s for s in all_syms if s in _METALS]
    return forex, metals


def _row(broker, symbol):
    """One instrument, or an explicit unavailable.

    Change is measured against the previous daily bar's close, which is what
    "today" means to a trader looking at a forex quote. Two bars is the
    smallest window that answers it, and asking for more would spend the
    historical allowance to draw the same percentage.
    """
    try:
        # Straight to the broker: ctrader.get_candles already routes through
        # candle_cache, so the sharing this module needs is where it belongs —
        # one layer, keyed on the instrument. Wrapping it again here would key
        # a second cache on arguments the inner fetch never receives.
        bars = broker.get_candles(symbol, "1d", 2) or []
    except Exception as e:
        return {"symbol": symbol, "available": False, "reason": str(e)[:80]}
    if len(bars) < 2:
        return {"symbol": symbol, "available": False, "reason": "no daily bars"}
    prev_close = bars[-2].get("close")
    last = bars[-1].get("close")
    if not prev_close or last is None:
        return {"symbol": symbol, "available": False, "reason": "incomplete bar"}
    try:
        change_pct = (float(last) - float(prev_close)) / float(prev_close) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return {"symbol": symbol, "available": False, "reason": "unusable bar"}
    return {
        "symbol": symbol,
        "available": True,
        "price": float(last),
        "changePct": round(change_pct, 2),
        "prevClose": float(prev_close),
    }


def snapshot(broker, *, force=False):
    """Every tradeable instrument with its last close and change on the day.

    Shared across clients and rebuilt at most every _TTL_S seconds. A failure
    to rebuild keeps serving the previous snapshot rather than blanking the
    screen — but the payload carries `asOf`, so the UI can say how old it is
    instead of presenting a stale number as live.
    """
    now = time.time()
    with _lock:
        fresh = _cache["rows"] is not None and (now - _cache["at"]) < _TTL_S
        if fresh and not force:
            return {"rows": _cache["rows"], "asOf": int(_cache["at"]), "cached": True}

    forex, metals = universe()
    rows = [_row(broker, s) for s in (forex + metals)]

    if not any(r.get("available") for r in rows):
        # Every instrument failed — that is a broker problem, not eight
        # separate symbol problems. Keep whatever we last had and say when it
        # was from; an empty Markets screen is indistinguishable from a broker
        # with nothing listed.
        with _lock:
            if _cache["rows"] is not None:
                return {"rows": _cache["rows"], "asOf": int(_cache["at"]),
                        "cached": True, "stale": True}
        return {"rows": rows, "asOf": int(now), "cached": False}

    with _lock:
        _cache["rows"] = rows
        _cache["at"] = now
    return {"rows": rows, "asOf": int(now), "cached": False}


def reset():
    """Drop the shared snapshot. For tests."""
    with _lock:
        _cache["rows"] = None
        _cache["at"] = 0.0
