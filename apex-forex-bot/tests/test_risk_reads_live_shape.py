"""Risk map, risk guard and data freshness against the shape production returns.

Found on a real demo account with one protected position open:
- the risk map said "1 unreadable position" although the position had a stop,
  because nothing produced `riskToStop`;
- the read-only risk guard always blocked with "symbol exposure is unknown",
  because no caller supplied it, so automation health could not pass 75;
- the data check failed for most of every hour, because a candle is stamped
  with its bar's OPEN time and was aged as if that were the close.

Run: python3 tests/test_risk_reads_live_shape.py
"""
import os
import sys

import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-riskreads-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"

from apex.platform import broker_read as B                     # noqa: E402
from apex.platform import health_score as H                    # noqa: E402
from apex.platform import risk_guard as G                      # noqa: E402
from apex.platform import risk_map as M                        # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


class Broker:
    def __init__(self, rows):
        self.rows = rows

    def get_all_positions(self):
        return self.rows

    def get_quote(self, symbol):
        import time
        return (0.68320, 0.68325, time.time())


# The row cTrader returned on the account, before enrichment.
SELL = {"symbol": "AUDUSD", "side": "SELL", "units": 4000.0,
        "entryPrice": 0.68519, "stopLoss": 0.68719, "takeProfit": 0.67769,
        "positionId": 59741486}

print("\n[1] a position with a stop has a readable risk to that stop")
row = B._enrich_positions(Broker([dict(SELL)]))[0]
check("riskToStop is produced", row.get("riskToStop") is not None, str(row.get("riskToStop")))
check("20 pips on 4,000 units is about 8", abs((row.get("riskToStop") or 0) - 8.0) < 0.05,
      str(row.get("riskToStop")))
no_stop = B._enrich_positions(Broker([dict(SELL, stopLoss=None)]))[0]
check("no stop stays unknown, never zero", no_stop.get("riskToStop") is None)
locked = B._enrich_positions(Broker([dict(SELL, stopLoss=0.68400)]))[0]
check("a stop past the entry on the winning side risks nothing",
      locked.get("riskToStop") == 0.0, str(locked.get("riskToStop")))
buy = B._enrich_positions(Broker([dict(SELL, side="BUY", stopLoss=0.68319)]))[0]
check("a buy is measured downward", abs((buy.get("riskToStop") or 0) - 8.0) < 0.05,
      str(buy.get("riskToStop")))

print("\n[2] the risk map reads that position")
read = {"status": "ok", "positions": [row], "mode": "demo", "accountId": 1}
view = M.from_reads(read, {"status": "ok", "balance": 4462.84})
check("no unreadable position", view.get("unreadablePositions") == 0, str(view))
check("loss if every stop is hit", abs((view.get("lossIfEveryStopHit") or 0) - 8.0) < 0.05)
check("a percentage of the balance", view.get("riskFraction") is not None
      and abs(view["riskFraction"] - 8.0 / 4462.84) < 1e-4, str(view.get("riskFraction")))
unprotected = M.from_reads({"status": "ok", "positions": [no_stop]},
                           {"status": "ok", "balance": 4462.84})
check("an unprotected position is still unreadable", unprotected.get("unreadablePositions") == 1)

print("\n[3] the guard is given symbol exposure, and unknown still blocks")
TRADES = {"status": "ok", "trades": [{"closedAt": 1_700_000_000 - 3600, "net": 5.0}]}
ACC = {"balance": 4462.84}
NOW = 1_700_000_000
ready = G.evaluate(G.state_from_trades(TRADES, ACC, positions=read, now=NOW))
check("one protected position is ready", ready["allowed"] is True and ready["mode"] == "ready",
      str(ready["blocks"]))
flat = G.evaluate(G.state_from_trades(TRADES, ACC, positions={"status": "ok", "positions": []}, now=NOW))
check("no open position is ready", flat["allowed"] is True, str(flat["blocks"]))
missing = G.evaluate(G.state_from_trades(TRADES, ACC, now=NOW))
check("not supplied is unknown and blocks",
      any(b["guard"] == "symbol_exposure" for b in missing["blocks"]))
failed = G.evaluate(G.state_from_trades(TRADES, ACC, positions={"status": "unavailable"}, now=NOW))
check("a failed positions read blocks",
      any(b["guard"] == "symbol_exposure" for b in failed["blocks"]))
naked = G.evaluate(G.state_from_trades(
    TRADES, ACC, positions={"status": "ok", "positions": [no_stop]}, now=NOW))
check("a position without a stop blocks",
      any(b["guard"] == "symbol_exposure" for b in naked["blocks"]))
heavy = dict(row, riskToStop=4462.84 * 0.30)
over = G.evaluate(G.state_from_trades(
    TRADES, ACC, positions={"status": "ok", "positions": [heavy]}, now=NOW))
check("exposure over the limit blocks with 'limit reached'",
      any(b["reason"] == "symbol exposure limit reached" for b in over["blocks"]), str(over["blocks"]))
two = G.symbol_exposure_fraction(
    {"status": "ok", "positions": [dict(row, riskToStop=10.0), dict(row, riskToStop=5.0),
                                   dict(row, symbol="EURUSD", riskToStop=12.0)]}, 1000.0)
check("the largest symbol total over the balance", abs(two - 0.015) < 1e-9, str(two))
check("no balance is unknown", G.symbol_exposure_fraction(read, None) is None)

print("\n[4] a candle is stamped with its bar's open time")
HOUR = 3600
OPEN = NOW - HOUR - 19 * 60          # opened 79 minutes ago, closed 19 minutes ago
check("the close is one bar after the open", H.bar_close(OPEN, "1h") == OPEN + HOUR)
check("unreadable stays unreadable", H.bar_close(None, "1h") is None)
kw = dict(connected=True, market_open=True, session_valid=True, rule_valid=True,
          store_available=True, critical_incidents=False, timeframe="1h", now=NOW,
          positions_status="ok", positions=[row], guard=ready)
fresh = H.assemble(candle_status="ok", candle_stamp=OPEN, **kw)
check("19 minutes after the close is fresh", fresh["checks"]["data"] is True, str(fresh["checks"]))
check("everything readable scores 100", fresh["score"] == 100, str(fresh))
stale = H.assemble(candle_status="ok", candle_stamp=NOW - 3 * HOUR, **kw)
check("a bar that closed two hours ago is stale", stale["checks"]["data"] is False)
unread = H.assemble(candle_status="ok", candle_stamp=None, **kw)
check("no stamp is unknown, not fresh", unread["checks"]["data"] is None)

shutil.rmtree(_TMP, ignore_errors=True)
if _fails:
    print(f"\n{len(_fails)} FAILED:")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("\nall risk read checks passed")
