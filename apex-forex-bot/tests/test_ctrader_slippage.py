"""An entry can refuse a fill that is further away than we agreed to pay.

WHY THIS TEST EXISTS

Every order this platform has ever sent was a plain MARKET order: take whatever
the book offers. On 4 September, during NFP, that meant a EURUSD stop was passed
by 11.1 pips — 51% beyond where the risk was sized — because a market order has
no opinion about price. cTrader has MARKET_RANGE, which fills only within a
stated distance of the price we decided on and otherwise REJECTS the order. A
refused entry costs nothing; a fill half a stop away costs the difference.

THE PROPERTY THAT MATTERS MOST

The range is measured from the side we would actually cross: the ask when
buying, the bid when selling. Measuring from the wrong side silently grants a
whole spread more slippage than was configured, and everything would still look
correct — the field is set, the order is a range order, the number matches the
setting. That is asserted here explicitly, in both directions.

The feature is off unless configured, so the default path is asserted too: a
zero setting must leave a plain MARKET order with no slippage fields at all.

Run: python tests/test_ctrader_slippage.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import config as cfg  # noqa: E402
from apex.brokers import ctrader  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


class _CapturingConn:
    """Records the outgoing request, then answers with a clean fill."""

    def __init__(self):
        self.sent = []

    def _request(self, req, *a, **k):
        self.sent.append(req)
        return ctrader.ProtoOAExecutionEvent(
            executionType=ctrader.ProtoOAExecutionType.ORDER_FILLED)


def _broker(bid=1.16170, ask=1.16180, quote_raises=False):
    b = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False, SYMBOL="EURUSD", CTRADER_ACCOUNT_ID=123))
    conn = _CapturingConn()
    b._conn = lambda: conn
    b._ctid = lambda: 123
    b._symbol_id = lambda instrument: 7
    b._vol_rules = lambda sid: (100_000, 100_000)
    b.get_open_position = lambda instrument=None: {"positionId": 456}

    def _quote(instrument=None):
        if quote_raises:
            raise RuntimeError("no quote")
        return (bid, ask)
    b.get_bid_ask = _quote
    return b, conn


def _order(broker, conn, side="BUY"):
    broker.place_order(side, 100_000, "EURUSD")
    return conn.sent[0]


_real = cfg.CTRADER_MAX_SLIPPAGE_POINTS
try:
    print("\n1. Off by default — nothing about the order changes")
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = 0
    b, c = _broker()
    req = _order(b, c)
    check("the order stays MARKET",
          req.orderType == ctrader.ProtoOAOrderType.MARKET,
          str(req.orderType))
    check("no slippage ceiling is sent", req.slippageInPoints == 0,
          str(req.slippageInPoints))
    check("no base price is sent", req.baseSlippagePrice == 0,
          str(req.baseSlippagePrice))

    print("\n2. Configured — the order carries the ceiling")
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = 12
    b, c = _broker()
    req = _order(b, c)
    check("the order becomes MARKET_RANGE",
          req.orderType == ctrader.ProtoOAOrderType.MARKET_RANGE,
          str(req.orderType))
    check("the ceiling is exactly what was configured",
          req.slippageInPoints == 12, str(req.slippageInPoints))
    check("a base price is sent", req.baseSlippagePrice > 0,
          str(req.baseSlippagePrice))

    print("\n3. The range is measured from the side we cross")
    b, c = _broker(bid=1.16170, ask=1.16180)
    buy = _order(b, c, "BUY")
    check(f"a BUY measures from the ASK ({buy.baseSlippagePrice})",
          abs(buy.baseSlippagePrice - 1.16180) < 1e-9,
          "measuring a buy from the bid grants a whole spread of free slippage")
    b, c = _broker(bid=1.16170, ask=1.16180)
    sell = _order(b, c, "SELL")
    check(f"a SELL measures from the BID ({sell.baseSlippagePrice})",
          abs(sell.baseSlippagePrice - 1.16170) < 1e-9,
          "measuring a sell from the ask does the same in reverse")
    check("the two are not the same price",
          buy.baseSlippagePrice != sell.baseSlippagePrice,
          "if these ever match, the side is being ignored")

    print("\n4. No quote — MARKET, not a half-built range order")
    b, c = _broker(quote_raises=True)
    req = _order(b, c)
    check("it falls back to MARKET",
          req.orderType == ctrader.ProtoOAOrderType.MARKET, str(req.orderType))
    check("...and sends no ceiling with it", req.slippageInPoints == 0,
          "a range order without a base price lets the broker pick the "
          "reference — the protection removed while appearing present")
    check("...and no base price", req.baseSlippagePrice == 0)

    print("\n5. The order still goes out, and is still one order")
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = 5
    b, c = _broker()
    b.place_order("BUY", 100_000, "EURUSD")
    check("exactly one request was sent", len(c.sent) == 1, str(len(c.sent)))
    check("it is a new-order request",
          type(c.sent[0]).__name__ == "ProtoOANewOrderReq",
          type(c.sent[0]).__name__)
finally:
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = _real

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - an entry can refuse to pay more than agreed.")
