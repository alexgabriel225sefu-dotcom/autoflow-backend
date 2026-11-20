"""Candle freshness follows the market and the bar size.

A flat 120-second rule called every hourly bar stale for most of the hour,
and a Saturday bar looked like a dead broker feed. Quote safety is a
different check. The risk guard is ready only when an evaluation allowed
the next entry.

Run: python3 tests/test_health_market_freshness.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex.platform import health_score as H                    # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


NOW = 1_700_000_000

print("\n[1] an hourly bar is fresh for the hour, not for 120 seconds")
check("just closed", H.candle_freshness(NOW - 30, now=NOW, timeframe="1h",
                                         market_open=True) is True)
check("50 minutes into the hour",
      H.candle_freshness(NOW - 3000, now=NOW, timeframe="1h",
                         market_open=True) is True)
check("older than one bar plus grace",
      H.candle_freshness(NOW - 4000, now=NOW, timeframe="1h",
                         market_open=True) is False)

print("\n[2] a closed market is not a stale feed")
check("closed", H.candle_freshness(NOW - 86400, now=NOW, timeframe="1h",
                                   market_open=False) == "market_closed")
scored = H.score({
    "brokerConnected": True, "sessionValid": True, "ruleValid": True,
    "storeAvailable": True, "criticalIncidents": False,
    "dataFresh": "market_closed", "quoteSafety": "market_closed",
    "riskGuardReady": True,
})
check("market closed is not a failed check",
      scored["checks"]["data"] == "market_closed"
      and "failed" not in " ".join(scored["warnings"]))
check("it is not counted against the score", scored["score"] == 100, str(scored))

print("\n[3] quotes are separate, and an unread book is not safe")
check("stale quote fails only while the market is open",
      H.quote_safety("ok", [{"quoteStale": True, "quoteAgeSec": 40}],
                     market_open=True) is False)
check("the same quote during a closed market is not a feed failure",
      H.quote_safety("ok", [{"quoteStale": True, "quoteAgeSec": 90000}],
                     market_open=False) == "market_closed")
check("a failed position read is not safe",
      H.quote_safety("unavailable", None, market_open=True) is False)
check("no open positions is not a failure",
      H.quote_safety("ok", [], market_open=True) == "not_applicable")

print("\n[4] the risk guard is ready only when it allowed the entry")
check("allowed", H.risk_guard_ready({"allowed": True, "mode": "ready"}) is True)
check("blocked", H.risk_guard_ready({"allowed": False, "mode": "blocked"}) is False)
check("missing evaluation is not ready", H.risk_guard_ready(None) is False)
check("a true flag with the wrong mode is not ready",
      H.risk_guard_ready({"allowed": True, "mode": "blocked"}) is False)

view = H.assemble(
    connected=True, market_open=False, session_valid=True, rule_valid=True,
    store_available=True, critical_incidents=False, timeframe="1h", now=NOW,
    candle_status="ok", candle_stamp=NOW - 86400,
    positions_status="ok", positions=[{"quoteStale": True, "quoteAgeSec": 9}],
    guard={"allowed": False, "mode": "blocked"})
check("weekend assembly does not call the old bar a data failure",
      view["checks"]["data"] == "market_closed")
check("and the guard that blocked is not ready", view["checks"]["risk"] is False)

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
