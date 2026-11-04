"""Pure pre-trade risk guard evaluation. It can only return a decision."""
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class GuardLimits:
    weekly_loss_fraction: float = 0.05
    max_drawdown_fraction: float = 0.10
    max_consecutive_losses: int = 5
    max_symbol_exposure: float = 0.25
    max_trades_day: int = 20
    max_slippage_pips: float = 3.0
    cooldown_seconds: int = 0


def evaluate(state: dict[str, Any], limits: GuardLimits | None = None) -> dict[str, Any]:
    lim = limits or GuardLimits()
    blocks: list[dict[str, str]] = []
    def block(name: str, reason: str) -> None:
        blocks.append({"guard": name, "reason": reason})
    if state.get("stopAll") is True:
        block("stop_all", "risk guard is in stop-all mode")
    for key, threshold, name, label in (
        ("weeklyLossFraction", lim.weekly_loss_fraction, "weekly_loss", "weekly loss"),
        ("drawdownFraction", lim.max_drawdown_fraction, "drawdown", "drawdown"),
        ("symbolExposureFraction", lim.max_symbol_exposure, "symbol_exposure", "symbol exposure"),
    ):
        value = state.get(key)
        if value is None:
            block(name, f"{label} is unknown")
        elif float(value) >= threshold:
            block(name, f"{label} limit reached")
    losses = state.get("consecutiveLosses")
    if losses is None or int(losses) >= lim.max_consecutive_losses:
        block("consecutive_losses", "consecutive loss count is unknown or at its limit")
    trades = state.get("tradesToday")
    if trades is None or int(trades) >= lim.max_trades_day:
        block("trade_count", "daily trade count is unknown or at its limit")
    slip = state.get("slippagePips")
    if slip is not None and float(slip) > lim.max_slippage_pips:
        block("slippage", "observed slippage exceeds the configured limit")
    cooldown = state.get("cooldownRemainingSec")
    if cooldown is None and lim.cooldown_seconds:
        block("cooldown", "cooldown state is unknown")
    elif cooldown and float(cooldown) > 0:
        block("cooldown", "cooldown is active")
    return {"allowed": not blocks, "mode": "blocked" if blocks else "ready",
            "blocks": blocks, "limits": asdict(lim)}
