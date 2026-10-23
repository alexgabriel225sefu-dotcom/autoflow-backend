"""Performance API metrics never serialize an infinite profit factor."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apex.platform.api import _performance_group, _performance_summary  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)


def main():
    wins = [{"netPnl": 10, "symbol": "EURUSD", "strategyId": "momentum"},
            {"netPnl": 5, "symbol": "EURUSD", "strategyId": "momentum"}]
    summary = _performance_summary(wins)
    check("all wins explain profit factor", summary["profitFactorStatus"] == "no losing trades")
    check("all wins do not serialize Infinity", "profitFactor" not in summary)
    groups = _performance_group(wins, "symbol")
    check("instrument group is present", groups["EURUSD"]["trades"] == 2)
    check("group metrics are real", groups["EURUSD"]["winningTrades"] == 2)


if __name__ == "__main__":
    main()
