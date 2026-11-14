"""close_position_by_id must classify what the broker REALLY answered.

WHY THIS FILE EXISTS

The platform Close tests mock `close_position_by_id` itself
(tests/test_platform_position_close.py), so the function that reads the
broker's execution event had no coverage at all. A read-only review before the
Monday demo found two ways it could report the wrong thing on a real account:

1. PARTIAL WHENEVER THE EVENT CARRIES A VOLUME.
   It returned PARTIAL if `position.tradeData.volume > 0`, without looking at
   the position's STATUS. cTrader's execution event for a close carries the
   position as it stands; whether a fully-closed position reports zero volume
   or the volume it had is not something this code can know from the schema.
   If it reports the original volume, EVERY successful full close shows the
   client "partially closed", releases the idempotency claim, and invites a
   second Close click on a position that is already gone.

   Whatever the broker does, "partial" can only mean the position is STILL
   OPEN. A position the broker marks CLOSED is closed.

2. AN EVENT FOR ANOTHER POSITION COULD BE TAKEN AS THE ANSWER.
   The close was accepted on a shared socket without checking that the
   returned position is the one asked about. A stop-loss or take-profit fill
   on a different position arriving in that window would have been reported
   as "Position closed". An answer that is not about the requested position
   is UNKNOWN, which keeps the claim and tells the client to check.

These tests use real protobuf messages, not dicts, because the failure was in
how a real message is read.

Run: python3 tests/test_ctrader_close_by_id_events.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex.brokers import ctrader                              # noqa: E402
from apex.ctrader_proto import OpenApiModelMessages_pb2 as M  # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class _Conn:
    def __init__(self, event=None, error=None):
        self.event, self.error = event, error

    def _request(self, *a, **kw):
        if self.error:
            raise self.error
        return self.event


def _broker(conn):
    b = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False, SYMBOL="EURUSD", CTRADER_ACCOUNT_ID=123))
    b._conn = lambda: conn
    b._ctid = lambda: 123
    b._symbol_id = lambda instrument: 7
    b._vol_rules = lambda sid: (100_000, 100_000)
    return b


ORIGINAL = 100_000          # 1000.00 units in cTrader's hundredths
PID = 4242


def _position(pid, status, volume):
    return M.ProtoOAPosition(
        positionId=pid, positionStatus=status,
        tradeData=M.ProtoOATradeData(
            symbolId=7, volume=volume, tradeSide=M.ProtoOATradeSide.BUY))


def _event(kind, position=None):
    kw = {"executionType": getattr(ctrader.ProtoOAExecutionType, kind)}
    if position is not None:
        kw["position"] = position
    return ctrader.ProtoOAExecutionEvent(**kw)


def close(event=None, error=None):
    return _broker(_Conn(event=event, error=error)).close_position_by_id(
        PID, volume=ORIGINAL)


CLOSED = M.ProtoOAPositionStatus.POSITION_STATUS_CLOSED
OPEN = M.ProtoOAPositionStatus.POSITION_STATUS_OPEN

# ── 1. a position the broker marks CLOSED is closed, whatever volume it carries
print("\n[1] a full close is FILLED however the event reports volume")
r = close(_event("ORDER_FILLED", _position(PID, CLOSED, ORIGINAL)))
check("CLOSED carrying the ORIGINAL volume is FILLED, not PARTIAL",
      r["status"] == "FILLED", str(r))
r = close(_event("ORDER_FILLED", _position(PID, CLOSED, 0)))
check("CLOSED carrying zero volume is FILLED", r["status"] == "FILLED", str(r))

# ── 2. partial means the position is STILL OPEN ─────────────────────────────
print("\n[2] a partial close is still recognised")
r = close(_event("ORDER_FILLED", _position(PID, OPEN, 40_000)))
check("OPEN with volume left is PARTIAL", r["status"] == "PARTIAL", str(r))
check("and reports the remainder in units",
      r.get("remainingVolume") == 400.0, str(r.get("remainingVolume")))
r = close(_event("ORDER_PARTIAL_FILL", _position(PID, OPEN, 40_000)))
check("ORDER_PARTIAL_FILL is PARTIAL", r["status"] == "PARTIAL", str(r))
r = close(_event("ORDER_PARTIAL_FILL"))
check("a partial fill with no position attached is still PARTIAL",
      r["status"] == "PARTIAL", str(r))

# ── 3. an answer about ANOTHER position is not our answer ───────────────────
print("\n[3] an event for a different position is UNKNOWN")
r = close(_event("ORDER_FILLED", _position(999, CLOSED, ORIGINAL)))
check("another position's fill is not reported as our close",
      r["status"] == "UNKNOWN", str(r))
check("and does not claim the position was closed",
      "closed" not in str(r.get("sentence", "")).lower()
      or "check" in str(r.get("sentence", "")).lower(), str(r))

# ── 4. what already worked still works ──────────────────────────────────────
print("\n[4] the existing outcomes are unchanged")
r = close(_event("ORDER_FILLED"))
check("a fill with no position attached is FILLED", r["status"] == "FILLED",
      str(r))
r = close(error=RuntimeError("POSITION_NOT_FOUND"))
check("POSITION_NOT_FOUND is ALREADY_CLOSED",
      r["status"] == "ALREADY_CLOSED", str(r))
r = close(_event("ORDER_REJECTED"))
check("ORDER_REJECTED is REJECTED", r["status"] == "REJECTED", str(r))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All close-by-id event checks passed.")
