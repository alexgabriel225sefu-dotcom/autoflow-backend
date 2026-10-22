"""A price read must not hold the shared broker socket for long.

get_quote takes the connection's lock, subscribes to spots and then WAITS for a
tick, up to 8 seconds, with the lock held. That was fine for the trading loop,
which asks occasionally. A chart polls every few seconds: on a closed market,
or an instrument that is quiet, each poll would hold the lock for the full 8 s
and the polls would queue behind one another, starving the loop's own requests
(candles, orders, closes) on the same socket.

So the wait is a parameter. The default stays 8 so the loop is unchanged, and
the chart's read passes a short one.

Run: python3 tests/test_ctrader_get_quote_wait.py
"""
import os
import sys
import threading
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex.brokers import ctrader                      # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class _SilentConn:
    """A connection on which no spot tick ever arrives (a closed market)."""

    def __init__(self):
        self._lock = threading.RLock()
        self.timeouts = []

    def _send(self, req):
        return 1

    def _read_frame(self, timeout=8):
        self.timeouts.append(timeout)
        time.sleep(0.02)
        return SimpleNamespace(payloadType=ctrader.ProtoHeartbeatEvent().payloadType,
                               payload=b"")


def broker(conn):
    b = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False, SYMBOL="EURUSD", CTRADER_ACCOUNT_ID=123))
    b._conn = lambda: conn
    b._ctid = lambda: 123
    b._symbol_id = lambda instrument: 7
    b._scale = lambda sym: 100000
    return b


print("\n[1] a short wait gives up quickly, and says there is no price")
conn = _SilentConn()
t0 = time.time()
try:
    broker(conn).get_quote("EURUSD", wait_s=0.5)
    check("it raises when no tick arrives", False, "returned a price from nothing")
except RuntimeError as e:
    check("it raises when no tick arrives", "no spot price" in str(e), str(e))
took = time.time() - t0
check("and gives up in about the wait it was given", took < 1.5, f"{took:.2f}s")
check("no single read waits longer than the wait it was given",
      conn.timeouts and max(conn.timeouts) <= 0.5 + 1e-6, str(max(conn.timeouts or [0])))

print("\n[2] the default is unchanged for the trading loop")
conn = _SilentConn()
broker(conn)       # constructing must not read anything
import inspect
sig = inspect.signature(ctrader.CtraderBroker.get_quote)
check("wait_s defaults to the original 8 seconds",
      sig.parameters["wait_s"].default == 8, str(sig))
check("get_bid_ask still takes no new argument",
      list(inspect.signature(ctrader.CtraderBroker.get_bid_ask).parameters)
      == ["self", "instrument"])

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All get_quote wait checks passed.")
