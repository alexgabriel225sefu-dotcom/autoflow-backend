"""What the closed-trade journal says, sliced the ways a client asks.

The maths already existed. ev.metrics() has computed win rate, profit factor,
expectancy and max drawdown since the walk-forward work — but only ever over
backtest R-multiples, never over the live journal, so a client could not see
any of it. This module is the missing half: it turns journal rows into those
same inputs and slices them by strategy, symbol, period and account mode.

It deliberately computes nothing ev.py already computes. A second expectancy
formula that drifts from the first is worse than no expectancy at all.

Two figures, on purpose:
  * dollars — what the client's balance actually did.
  * R — whether the edge is real. A $50 win risking $200 and a $50 win risking
    $10 are not the same trade, and only R can tell them apart.

R needs the stop distance the trade was opened with. Rows written before that
was journalled have no R, so R-based figures carry their own trade count and
never silently borrow the dollar count.
"""
from apex import ev, forex

# Rows older than the strategyId work carry no label. They are real trades and
# still belong in the totals — they are simply not attributable to a method.
UNLABELLED = "unlabelled"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None          # NaN is not a number here either


def r_multiple(row):
    """This trade's outcome in R, or None when the row cannot support one.

    R = distance travelled / distance risked. The journal stores the stop as a
    pip distance (slPips) rather than a price, which is enough: both sides of
    the ratio are pips, so the instrument's pip size cancels out.
    """
    entry, exit_, sl = _num(row.get("entry")), _num(row.get("exit")), _num(row.get("slPips"))
    if entry is None or exit_ is None or not sl or sl <= 0:
        return None
    side = (row.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        return None
    sym = row.get("symbol") or ""
    try:
        moved = forex.to_pips((exit_ - entry) if side == "BUY" else (entry - exit_),
                              sym, exit_)
    except Exception:
        return None
    return moved / sl


def _dollar_metrics(rows):
    """Win rate, profit factor, expectancy and max drawdown, in money.

    Mirrors ev.metrics' definitions exactly so the two views of the same trades
    can never tell different stories — only the unit differs.
    """
    nets = [n for n in (_num(r.get("netPnl")) for r in rows) if n is not None]
    if not nets:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "net": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
                "max_drawdown": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "best": 0.0, "worst": 0.0}
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    gross_loss = abs(sum(losses))
    equity = peak = max_dd = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": len(nets),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(nets) * 100, 1),
        "net": round(sum(nets), 2),
        "profit_factor": (round(sum(wins) / gross_loss, 2)
                          if gross_loss > 0 else (float("inf") if wins else 0.0)),
        "expectancy": round(sum(nets) / len(nets), 2),
        "max_drawdown": round(max_dd, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best": round(max(nets), 2),
        "worst": round(min(nets), 2),
    }


def summarize(rows):
    """Everything a performance screen needs, for one set of trades."""
    rows = list(rows or [])
    out = _dollar_metrics(rows)
    rs = [r for r in (r_multiple(x) for x in rows) if r is not None]
    if rs:
        # ev.metrics is the single definition of these. Do not reimplement.
        m = ev.metrics(rs)
        out["r"] = {
            "trades": m["trades"],          # its OWN count: fewer rows carry R
            "expectancy_R": m["expectancy_R"],
            "profit_factor_R": m["profit_factor"],
            "max_drawdown_R": m["max_drawdown_R"],
            "win_rate_R": round(m["win_rate"] * 100, 1),
        }
    else:
        out["r"] = None
    return out


def _split(rows, key):
    groups = {}
    for row in rows or []:
        groups.setdefault(key(row), []).append(row)
    return groups


def by_strategy(rows):
    """Per-method performance, worst first.

    With seventeen methods offered and no report saying which one works on this
    client's account, seventeen is a menu rather than an advantage.
    """
    groups = _split(rows, lambda r: r.get("strategyId") or UNLABELLED)
    return {k: summarize(v) for k, v in groups.items()}


def by_symbol(rows):
    groups = _split(rows, lambda r: r.get("symbol") or "—")
    return {k: summarize(v) for k, v in groups.items()}


def by_mode(rows):
    """Demo and live, kept apart.

    Mixing them makes the report useless exactly when it matters. Rows written
    before `mode` was journalled cannot be classified after the fact, so they
    land under `unknown` rather than being guessed into one side.
    """
    def _m(r):
        v = r.get("mode")
        return v if v in ("demo", "live") else "unknown"
    return {k: summarize(v) for k, v in _split(rows, _m).items()}


def since(rows, day):
    """Rows on or after `day` (YYYY-MM-DD). Journal times are 'YYYY-MM-DD HH:MM:SS'."""
    return [r for r in rows or [] if str(r.get("time", "")) >= str(day)]


def ranked(groups, min_trades=3):
    """(name, summary) sorted by expectancy, best first.

    Groups under `min_trades` are returned last and flagged: three trades is
    not evidence, and ranking on it would recommend a method that got lucky
    once.
    """
    def _key(item):
        _n, s = item
        thin = s["trades"] < min_trades
        return (thin, -s["expectancy"])
    out = []
    for name, s in sorted(groups.items(), key=_key):
        out.append((name, {**s, "thin": s["trades"] < min_trades}))
    return out
