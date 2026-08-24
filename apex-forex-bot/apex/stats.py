"""Performance statistics from the per-user trade journal — /stats + terminal."""
from datetime import datetime


def compute(trades, skips_today=0):
    """trades: user_store.load_trades() records (time, netPnl, balance, …)."""
    closed = [t for t in trades if isinstance(t.get("netPnl"), (int, float))]
    wins = [t for t in closed if t["netPnl"] > 0]
    losses = [t for t in closed if t["netPnl"] <= 0]
    gross_w = sum(t["netPnl"] for t in wins)
    gross_l = abs(sum(t["netPnl"] for t in losses))
    today = datetime.now().strftime("%Y-%m-%d")
    t_today = [t for t in closed if str(t.get("time", "")).startswith(today)]
    # ── equity curve: TRADING result, not account balance ──────────────
    #
    # This used to read each row's `balance` field, which is the account
    # balance at that moment — so anything that moved the balance without
    # being a trade moved the curve. A withdrawal was reported as a drawdown
    # the client never suffered, and one corrupt row could invent a peak that
    # never existed: a journal carrying four foreign rows at $470,586 beside
    # an account of ~$3,200 produced "max drawdown 99.3%" when the real figure
    # over the same trades was 0.5%.
    #
    # Rebuilding the curve from realised P&L makes it self-consistent with the
    # net-P&L figure reported beside it — the two are now the same arithmetic
    # instead of two sources free to disagree — and deposits, withdrawals and a
    # wrong balance field are all incapable of bending it.
    #
    # The anchor is what the account held before the first closed trade, taken
    # from that row so the curve is still in real dollars. If it is missing,
    # the curve starts at 0 and is a pure P&L path; the drawdown percentage is
    # then undefined rather than divided by a guess.
    anchor = None
    for t in closed:
        if isinstance(t.get("balance"), (int, float)):
            anchor = t["balance"] - t["netPnl"]
            break
    equity, run = [], (anchor if anchor is not None else 0.0)
    for t in closed:
        run += t["netPnl"]
        equity.append({"time": t.get("time"), "value": round(run, 2)})

    # Max drawdown along that curve. `peak <= 0` is skipped rather than divided
    # by: a percentage of a non-positive peak is not a number a client can act
    # on, and reporting one would be inventing a statistic.
    peak, max_dd = None, 0.0
    for p in equity:
        v = p["value"]
        peak = v if peak is None or v > peak else peak
        if peak and peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)

    # A drawdown past 100% means the curve went below zero, which a real
    # brokered account cannot do — the broker closes it out first. So the
    # journal is describing something other than one consistent account
    # (rows from elsewhere, or a corrupted P&L), and any percentage derived
    # from it is a number nobody can act on. Report it as unavailable rather
    # than print an impossible one: the same rule the trading gates use, where
    # UNKNOWN is refused instead of guessed.
    dd_pct = None if max_dd > 1.0 else round(max_dd * 100, 2)
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "profitFactor": (round(gross_w / gross_l, 2) if gross_l > 0
                         else (None if not wins else float("inf"))),
        "netPnl": round(gross_w - gross_l, 2),
        "avgWin": round(gross_w / len(wins), 2) if wins else 0.0,
        "avgLoss": round(-gross_l / len(losses), 2) if losses else 0.0,
        "best": round(max((t["netPnl"] for t in closed), default=0.0), 2),
        "worst": round(min((t["netPnl"] for t in closed), default=0.0), 2),
        "maxDrawdownPct": dd_pct,
        "today": {
            "trades": len(t_today),
            "netPnl": round(sum(t["netPnl"] for t in t_today), 2),
            "wins": len([t for t in t_today if t["netPnl"] > 0]),
            "skips": skips_today,
        },
        "equity": equity[-120:],
    }
