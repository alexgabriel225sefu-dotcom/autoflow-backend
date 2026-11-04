"""Anti-overfitting guidance. Warnings are not trading recommendations."""
from typing import Any


def analyse(sample: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    conditions = sample.get("conditionCount")
    trades = sample.get("tradeCount")
    periods = sample.get("periodCount")
    if conditions is not None and int(conditions) > 8:
        warnings.append("many conditions can make a rule fragile")
    if trades is not None and int(trades) < 30:
        warnings.append("the sample contains too few trades for a stable conclusion")
    if periods is not None and int(periods) < 3:
        warnings.append("use more independent time periods before trusting the result")
    if sample.get("changedAfterLosses"):
        warnings.append("changes made after losses can fit noise rather than a durable pattern")
    if sample.get("singleSymbol"):
        warnings.append("a single symbol does not test robustness across instruments")
    return {"status": "warning" if warnings else "no_obvious_warning",
            "warnings": warnings,
            "disclaimer": "This is a diagnostic, not a prediction of future performance."}
