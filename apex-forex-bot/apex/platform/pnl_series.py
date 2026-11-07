"""Net profit and loss over time: per UTC day, and cumulative after each close.

ONE DEFINITION, TWO CALLERS. The Trades read and the Performance read both draw
a curve, and two bucketing rules that differ by an hour at midnight would show
the same trade on different days on two pages of the same app.

WHAT GOES IN, AND WHAT DELIBERATELY DOES NOT

A trade is counted when it has a finite net result and a numeric close time
(unix seconds). Anything else is counted in `excluded` and left out, never
given a day by guesswork: the engine journal stamps its rows in server-local
text, and turning that into a UTC day would be a guess about a timezone.

`equity` is the running total of net results from the first trade in the range,
not the account balance. It starts at the first close and says nothing about
what the account held before it, which this module is not told.
"""
import math
from datetime import datetime, timezone


def _finite(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _usable(row, time_key, net_key):
    t, n = row.get(time_key), row.get(net_key)
    return _finite(t) and t > 0 and _finite(n)


def day_of(ts):
    """'YYYY-MM-DD' in UTC for a unix timestamp in seconds."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def build(rows, *, time_key="closedAt", net_key="netPnl"):
    """{"daily": [...], "equity": [...], "excluded": n} for closed trades.

    daily:  one entry per UTC day that had a close, oldest first:
            {"date", "net", "trades", "wins", "losses"}. A trade with a net of
            exactly zero is a trade, and neither a win nor a loss.
    equity: one entry per close, oldest first, ties kept in input order:
            {"t", "equity"} where equity is the running net total.
    """
    usable = [r for r in rows if _usable(r, time_key, net_key)]
    excluded = len(rows) - len(usable)
    usable.sort(key=lambda r: r[time_key])          # stable: ties keep order
    days, equity, running = {}, [], 0.0
    for r in usable:
        net = float(r[net_key])
        d = days.setdefault(day_of(r[time_key]),
                            {"net": 0.0, "trades": 0, "wins": 0, "losses": 0})
        d["net"] += net
        d["trades"] += 1
        if net > 0:
            d["wins"] += 1
        elif net < 0:
            d["losses"] += 1
        running += net
        equity.append({"t": int(r[time_key]), "equity": round(running, 2)})
    daily = [{"date": k, "net": round(v["net"], 2), "trades": v["trades"],
              "wins": v["wins"], "losses": v["losses"]}
             for k, v in sorted(days.items())]
    return {"daily": daily, "equity": equity, "excluded": excluded}
