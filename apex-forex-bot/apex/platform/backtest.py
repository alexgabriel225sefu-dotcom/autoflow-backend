"""Deterministic, hypothetical backtest engine over supplied candles only."""
from typing import Any, Callable

from apex import forex


def run(candles: list[dict[str, Any]], *, signal: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
        initial_balance: float | None = None, spread_pips: float = 0.0,
        commission: float = 0.0, slippage_pips: float = 0.0,
        latency_bars: int = 0, max_bars: int = 5000,
        symbol: str | None = None) -> dict[str, Any]:
    """Cost-adjusted hypothetical results over supplied candles.

    P&L here is in PRICE POINTS per unit (exit minus entry). Spread and
    slippage are given in pips and converted to price distance with the
    instrument's own pip size, so they need `symbol`. `commission` is read in
    the same price-point unit. Latency is recorded as an assumption and is
    NOT applied; the result says so.
    """
    if not isinstance(candles, list) or not candles:
        raise ValueError("at least one candle is required")
    if signal is None:
        raise ValueError("no strategy was supplied: a backtest needs a rule or "
                         "strategy to run, and none is attached to this request")
    cost_pips = abs(float(spread_pips)) + abs(float(slippage_pips))
    if cost_pips and not symbol:
        raise ValueError("a symbol is required to convert spread and slippage "
                         "from pips to price")
    if len(candles) > max_bars:
        raise ValueError("candle limit exceeded")
    balance = float(initial_balance) if initial_balance is not None else None
    trades: list[dict[str, Any]] = []
    skipped = 0
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict) or any(k not in candle for k in ("open", "high", "low", "close")):
            skipped += 1
            continue
        decision = signal(candle) if signal else None
        if not decision:
            continue
        entry = decision.get("entry", candle.get("open"))
        exit_price = decision.get("exit", candle.get("close"))
        if entry is None or exit_price is None:
            skipped += 1
            continue
        direction = 1 if str(decision.get("side", "BUY")).upper() == "BUY" else -1
        pnl = (float(exit_price) - float(entry)) * direction
        if cost_pips:
            pnl -= forex.from_pips(cost_pips, symbol.replace("_", "").upper(),
                                   float(entry))
        pnl -= abs(float(commission))
        trades.append({"index": index, "pnl": round(pnl, 8), "hypothetical": True,
                       "latencyBars": max(0, int(latency_bars))})
        if balance is not None:
            balance += pnl
    total = sum(t["pnl"] for t in trades)
    return {"status": "ok", "hypothetical": True, "trades": trades,
            "tradeCount": len(trades), "skippedCandles": skipped,
            "totalPnl": round(total, 8), "endingBalance": balance,
            "assumptions": {"spreadPips": spread_pips, "commission": commission,
                            "slippagePips": slippage_pips, "latencyBars": latency_bars},
            "unit": "price points per unit",
            "notModelled": _not_modelled(latency_bars)}


def _not_modelled(latency_bars):
    out = ["swap", "partial fills", "trading sessions", "news and weekend filters",
           "rejected orders", "bid and ask beyond the supplied spread",
           "missing or stale data", "market impact", "future conditions"]
    if latency_bars:
        out.insert(0, "latency (recorded as an assumption, not applied)")
    else:
        out.insert(0, "latency")
    return out
