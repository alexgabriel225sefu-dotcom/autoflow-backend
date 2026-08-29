"""Trades are not independent, and the checks that know that live here.

THE GAP THIS CLOSES

The correlation guard and the position cap were real, correct, and in the wrong
place: inside `user_loop._loop`, on the autonomous path. So an autonomous entry
was checked and a manual `/buy` was not. §14 is explicit that manual, assisted,
automatic and AI-proposed all route through the same risk engine, and §31 is
explicit that

    EURUSD long + GBPUSD long + EURGBP short

must not be treated as three independent risks. Two of those are the same bet
on the dollar.

So the logic moves here, and `gates.authorize_order` calls it. Nothing is
duplicated — the loop's copy is replaced by this one, and there is exactly one
implementation for every path to reach.

WHAT IT MEASURES, AND WHAT IT CANNOT

USD direction is a real, cheap proxy for the dominant correlation in a
major-pairs book: every major has a dollar leg, and stacking four trades that
are all short USD is one position wearing four tickets.

It is a proxy, not a correlation matrix. It says nothing about EURGBP against
EURCHF, and it treats gold as its own bucket. Building a real correlation
estimate would need a covariance window this platform does not keep, and
inventing one from eight instruments of daily bars would produce a number that
looks authoritative and is not. §31 asks the engine to understand that trades
are related; it does not ask it to pretend to a precision it has not measured.

MARGIN IS REPORTED UNKNOWN, NOT GUESSED

§14 lists margin among the things to validate. `ProtoOATrader` carries balance,
leverage and bonuses — it does not carry free margin or margin level. So margin
headroom is reported as unknown rather than reconstructed from leverage and
position size, which would be a computed number presented where the client
reads a broker figure.
"""

import time

from apex import forex

# How many open positions may share one USD direction. The loop used 2 (it
# refused when `same_dir >= 2`), and that is preserved exactly — this is a move,
# not a policy change.
DEFAULT_MAX_SAME_USD_SIDE = 2

# Deny codes. Stable, because a stored decision is read back by them.
AT_POSITION_LIMIT = "AT_POSITION_LIMIT"
SYMBOL_ALREADY_OPEN = "SYMBOL_ALREADY_OPEN"
CORRELATED_EXPOSURE = "CORRELATED_EXPOSURE"
MARKET_DATA_STALE = "MARKET_DATA_STALE"

DENY_TEXT = {
    AT_POSITION_LIMIT: "the account is already holding its maximum positions",
    SYMBOL_ALREADY_OPEN: "there is already a position on this instrument",
    CORRELATED_EXPOSURE: "this would stack another position on the same "
                         "dollar bet",
    MARKET_DATA_STALE: "the market data is older than the freshness limit",
}


def _nrm(sym):
    return str(sym or "").replace("_", "").replace("/", "").upper()


def state(dash, *, max_positions=None):
    """The account's current exposure, from the dash the loop publishes.

    Reads `dash["positions"]` — the list that was never written until it was
    fixed this session, and whose absence made five separate readers see an
    empty account. It makes no broker call: a risk check must not depend on a
    network round trip, and recomputing here would be a second implementation
    of a number the loop already owns.
    """
    d = dash or {}
    rows = [p for p in (d.get("positions") or []) if p and p.get("symbol")]
    symbols, bias = set(), []
    for p in rows:
        symbols.add(_nrm(p.get("symbol")))
        try:
            bias.append(forex.usd_exposure(p["symbol"], p.get("side") or ""))
        except Exception:
            bias.append(0)
    cap = max_positions if max_positions is not None else d.get("maxpos")
    return {
        "openCount": len(rows),
        "maxPositions": cap,
        "symbols": sorted(symbols),
        "usdBias": bias,
        "usdLong": sum(1 for b in bias if b > 0),
        "usdShort": sum(1 for b in bias if b < 0),
        # §14 asks for margin. The broker does not report it; saying so is the
        # honest answer and the screen renders it as unknown.
        "marginHeadroom": None,
        "marginKnown": False,
        "at": time.time(),
    }


def check(symbol, side, exposure, *, limits=None, data_age_s=None):
    """(ok, code, detail) for one proposed entry. Never raises.

    `limits` is the operator's configuration, so nothing here is a magic
    constant:

        max_positions        int or None
        max_same_usd_side    int
        max_data_age_s       float or None — None disables the freshness check
    """
    lim = dict(limits or {})
    ex = exposure or {}
    sym = _nrm(symbol)

    # 1. Freshness. Checked first: every other number below was derived from
    #    data, and if the data is stale so are they.
    max_age = lim.get("max_data_age_s")
    if max_age and data_age_s is not None and data_age_s > float(max_age):
        return False, MARKET_DATA_STALE, (f"market data is {data_age_s:.0f}s "
                                          f"old, limit {float(max_age):.0f}s")

    # 2. Already in it. Cheapest and most decisive.
    if sym in set(ex.get("symbols") or []):
        return False, SYMBOL_ALREADY_OPEN, sym

    # 3. Room on the account.
    cap = lim.get("max_positions", ex.get("maxPositions"))
    if cap:
        try:
            if int(ex.get("openCount") or 0) >= int(cap):
                return False, AT_POSITION_LIMIT, f"{ex.get('openCount')}/{cap}"
        except (TypeError, ValueError):
            pass

    # 4. The same bet wearing another ticket.
    try:
        new_bias = forex.usd_exposure(symbol, side)
    except Exception:
        new_bias = 0
    if new_bias:
        same = sum(1 for b in (ex.get("usdBias") or []) if b == new_bias)
        cap_side = int(lim.get("max_same_usd_side", DEFAULT_MAX_SAME_USD_SIDE))
        if same >= cap_side:
            way = "long USD" if new_bias > 0 else "short USD"
            return False, CORRELATED_EXPOSURE, (f"already {same} {way} "
                                                f"position(s), limit {cap_side}")

    return True, "", ""


def deny_text(code):
    return DENY_TEXT.get(code, code)


def summary(exposure):
    """The exposure as the risk screen reads it."""
    ex = exposure or {}
    cap = ex.get("maxPositions")
    lines = [f"{ex.get('openCount', 0)}"
             + (f" of {cap}" if cap else "") + " positions open"]
    if ex.get("symbols"):
        lines.append("  " + ", ".join(ex["symbols"]))
    net = (ex.get("usdLong") or 0) - (ex.get("usdShort") or 0)
    if ex.get("usdLong") or ex.get("usdShort"):
        lines.append(f"  USD: {ex.get('usdLong', 0)} long, "
                     f"{ex.get('usdShort', 0)} short"
                     + (f" (net {'long' if net > 0 else 'short'})" if net else
                        " (balanced)"))
    if not ex.get("marginKnown"):
        lines.append("  Margin headroom: not reported by the broker")
    return "\n".join(lines)
