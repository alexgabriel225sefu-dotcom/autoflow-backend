"""Pure pre-trade risk guard evaluation. It can only return a decision.

The evaluator accepts a measured snapshot.  ``state_from_trades`` is the
read-only adapter used by the API to build that snapshot from broker deals and
the journal; it deliberately reports unreadable fields as ``None`` so the
guard blocks instead of turning a failed read into a safe-looking zero.
"""
from dataclasses import dataclass, asdict
import time
from typing import Iterable
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
            "blocks": blocks, "limits": asdict(lim),
            "state": state, "stopNewEntriesOnly": True,
            "readOnly": True}


def state_from_trades(read_result: dict[str, Any], account: dict[str, Any] | None = None,
                      *, now: float | None = None) -> dict[str, Any]:
    """Derive guard inputs from the real closed-trade read.

    ``read_result`` must be the response from ``trades_read.read``.  A failed
    response leaves all measured values unknown.  Balance is required for the
    loss fractions; no guessed currency or initial balance is introduced.
    """
    if not isinstance(read_result, dict) or read_result.get("status") != "ok":
        return {"source": "closed trades and account read", "readable": False,
                "readError": (read_result or {}).get("reason", "trades could not be read")
                if isinstance(read_result, dict) else "trades could not be read",
                "weeklyLossFraction": None, "drawdownFraction": None,
                "consecutiveLosses": None, "tradesToday": None,
                "slippagePips": None}
    rows = [r for r in (read_result.get("trades") or []) if isinstance(r, dict)]
    balance = _number((account or {}).get("balance"))
    if balance is None or balance <= 0:
        return {"source": "closed trades and account read", "readable": False,
                "readError": "account balance could not be read",
                "weeklyLossFraction": None, "drawdownFraction": None,
                "consecutiveLosses": _consecutive_losses(rows),
                "tradesToday": _trades_today(rows, now=now),
                "slippagePips": None}
    now_ts = time.time() if now is None else float(now)
    weekly = [r for r in rows if _number(r.get("closedAt")) is not None
              and now_ts - float(r["closedAt"]) <= 7 * 86400]
    weekly_loss = max(0.0, -sum((_number(r.get("net")) or 0.0) for r in weekly))
    equity = float(balance)
    peak = equity
    max_dd = 0.0
    for row in sorted(rows, key=lambda r: _number(r.get("closedAt")) or 0):
        net = _number(row.get("net"))
        if net is None:
            continue
        equity += net
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return {"source": "closed trades and account read", "readable": True,
            "weeklyLossFraction": weekly_loss / balance,
            "drawdownFraction": max_dd,
            "consecutiveLosses": _consecutive_losses(rows),
            "tradesToday": _trades_today(rows, now=now),
            "slippagePips": None}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _consecutive_losses(rows: Iterable[dict[str, Any]]) -> int | None:
    ordered = sorted((r for r in rows if _number(r.get("closedAt")) is not None),
                     key=lambda r: float(r["closedAt"]), reverse=True)
    count = 0
    seen = False
    for row in ordered:
        net = _number(row.get("net"))
        if net is None:
            return None if not seen else count
        seen = True
        if net < 0:
            count += 1
        else:
            break
    return count if seen else None


def _trades_today(rows: Iterable[dict[str, Any]], *, now: float | None = None) -> int | None:
    now_ts = time.time() if now is None else float(now)
    day = time.gmtime(now_ts)[:3]
    count = 0
    for row in rows:
        stamp = _number(row.get("closedAt"))
        if stamp is None:
            continue
        if time.gmtime(stamp)[:3] == day:
            count += 1
    return count
