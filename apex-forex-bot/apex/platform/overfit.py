"""Anti-overfitting guidance. Warnings are not trading recommendations."""
from typing import Any


def analyse(sample: dict[str, Any]) -> dict[str, Any]:
    sample = sample if isinstance(sample, dict) else {}
    rule = sample.get("rule") if isinstance(sample.get("rule"), dict) else {}
    backtest = sample.get("backtest") if isinstance(sample.get("backtest"), dict) else {}
    trades = sample.get("trades") if isinstance(sample.get("trades"), list) else []
    versions = sample.get("versions") if isinstance(sample.get("versions"), list) else []
    warnings: list[str] = []
    conditions = _condition_count(rule)
    trade_count = backtest.get("tradeCount")
    if trade_count is None:
        trade_count = len(trades) if trades else None
    periods = _period_count(backtest.get("trades") or trades)
    if conditions is None:
        warnings.append("condition count is unknown; evidence cannot be judged")
    if trade_count is None:
        warnings.append("trade count is unknown; evidence cannot be judged")
    if periods is None:
        warnings.append("period count is unknown; evidence cannot be judged")
    if conditions is not None and int(conditions) > 8:
        warnings.append("many conditions can make a rule fragile")
    if trade_count is not None and int(trade_count) < 30:
        warnings.append("the sample contains too few trades for a stable conclusion")
    if periods is not None and int(periods) < 3:
        warnings.append("use more independent time periods before trusting the result")
    if _changed_after_loss(versions, trades or backtest.get("trades") or []):
        warnings.append("changes made after losses can fit noise rather than a durable pattern")
    symbols = rule.get("symbols") if isinstance(rule.get("symbols"), list) else []
    if len(set(str(s) for s in symbols)) <= 1:
        warnings.append("a single symbol does not test robustness across instruments")
    return {"status": "warning" if warnings else "no_obvious_warning",
            "evidence": {"conditionCount": conditions, "tradeCount": trade_count,
                          "periodCount": periods,
                          "versionCount": len(versions)},
            "warnings": warnings,
            "disclaimer": "This is a diagnostic, not a prediction of future performance."}


def _condition_count(rule: dict[str, Any]) -> int | None:
    if not rule:
        return None
    total = 0
    found = False
    for half in ("entry", "exit"):
        part = rule.get(half)
        conds = part.get("conditions") if isinstance(part, dict) else None
        if isinstance(conds, list):
            total += len(conds)
            found = True
    return total if found else None


def _period_count(rows: list[Any]) -> int | None:
    months = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = row.get("closedAt", row.get("timestamp"))
        try:
            from datetime import datetime, timezone
            months.add(datetime.fromtimestamp(float(stamp), timezone.utc).strftime("%Y-%m"))
        except (TypeError, ValueError, OverflowError):
            continue
    return len(months) if months else None


def _changed_after_loss(versions: list[Any], trades: list[Any]) -> bool:
    changes = []
    for row in versions:
        if not isinstance(row, dict):
            continue
        stamp = row.get("activatedAt", row.get("updatedAt"))
        try:
            changes.append(float(stamp))
        except (TypeError, ValueError):
            continue
    if not changes:
        return False
    for row in trades:
        if not isinstance(row, dict):
            continue
        net = row.get("net", row.get("pnl"))
        closed = row.get("closedAt", row.get("timestamp"))
        try:
            if float(net) < 0 and any(v > float(closed) for v in changes):
                return True
        except (TypeError, ValueError):
            continue
    return False
