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
    equity = [{"time": t.get("time"), "value": t["balance"]}
              for t in closed if isinstance(t.get("balance"), (int, float))]
    # max drawdown over the journal's equity path
    peak, max_dd = None, 0.0
    for p in equity:
        v = p["value"]
        peak = v if peak is None or v > peak else peak
        if peak:
            max_dd = max(max_dd, (peak - v) / peak)
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
        "maxDrawdownPct": round(max_dd * 100, 2),
        "today": {
            "trades": len(t_today),
            "netPnl": round(sum(t["netPnl"] for t in t_today), 2),
            "wins": len([t for t in t_today if t["netPnl"] > 0]),
            "skips": skips_today,
        },
        "equity": equity[-120:],
    }
