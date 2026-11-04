"""Deterministic, hypothetical backtest engine over supplied candles only."""
from typing import Any, Callable


def run(candles: list[dict[str, Any]], *, signal: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
        initial_balance: float | None = None, spread_pips: float = 0.0,
        commission: float = 0.0, slippage_pips: float = 0.0,
        latency_bars: int = 0, max_bars: int = 5000) -> dict[str, Any]:
    if not isinstance(candles, list) or not candles:
        raise ValueError("at least one candle is required")
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
        pnl -= abs(float(spread_pips)) + abs(float(slippage_pips))
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
            "notModelled": ["broker fills", "market impact", "future conditions"]}
