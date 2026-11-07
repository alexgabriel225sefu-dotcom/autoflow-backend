"""The stop-loss travels WITH the market order, not one round trip after it.

The cTrader Open API ProtoOANewOrderReq (read from the vendored descriptor,
not guessed) defines `relativeStopLoss` (19) and `relativeTakeProfit` (20) as
int64 distances in 1/100000 of a price unit. The broker rejects a relative
value that is not a whole number of the symbol's ticks ("invalid precision",
which is what broke gold before), so the distance is rounded to the symbol's
digits first.

The absolute post-fill amend stays as the verifying fallback. When the broker
explicitly rejects the order carrying the relative fields (nothing filled), it
is resent once without them. When nothing can attach the stop, the safety
close is retried and the UNPROTECTED outcome is logged loudly.

Also covered here, because they live on the same wire message:
  * every engine order carries the engine's `label`, so the engine can tell
    its own positions from manual ones (weekend flatten);
  * LIVE accounts get a non-zero slippage ceiling by default; demo is unchanged.

Run: python tests/test_ctrader_sltp_on_order.py
"""
import contextlib
import io
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")

from apex import config as cfg  # noqa: E402
from apex.brokers import ctrader  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


FILLED = ctrader.ProtoOAExecutionEvent(
    executionType=ctrader.ProtoOAExecutionType.ORDER_FILLED)


class _Conn:
    def __init__(self, *responses):
        self.sent = []
        self.responses = list(responses)

    def _request(self, req, *a, **k):
        self.sent.append(req)
        r = self.responses.pop(0) if self.responses else FILLED
        if isinstance(r, Exception):
            raise r
        return r


def _broker(conn, symbol="EURUSD", bid=1.16170, ask=1.16180, digits=5,
            env="demo", quote=True):
    b = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False, SYMBOL=symbol, CTRADER_ACCOUNT_ID=123,
        CTRADER_ENV=env))
    b._conn = lambda: conn
    b._ctid = lambda: 123
    b._symbol_id = lambda instrument: 7
    b._vol_rules = lambda sid: (1, 1)
    b._digits = lambda instrument: digits
    b.get_open_position = lambda instrument=None: {"positionId": 456,
                                                   "stopLoss": 1.0}

    def _q(instrument=None):
        if not quote:
            raise RuntimeError("no quote")
        return (bid, ask)
    b.get_bid_ask = _q
    return b


def _new_orders(conn):
    return [r for r in conn.sent if type(r).__name__ == "ProtoOANewOrderReq"]


def _amends(conn):
    return [r for r in conn.sent if type(r).__name__ == "ProtoOAAmendPositionSLTPReq"]


_real_slip = cfg.CTRADER_MAX_SLIPPAGE_POINTS
cfg.CTRADER_MAX_SLIPPAGE_POINTS = 0
try:
    print("\n0. The protocol really has these fields (descriptor introspection)")
    names = {f.name for f in ctrader.ProtoOANewOrderReq.DESCRIPTOR.fields}
    check("relativeStopLoss is a NewOrderReq field", "relativeStopLoss" in names)
    check("relativeTakeProfit is a NewOrderReq field", "relativeTakeProfit" in names)
    check("label is a NewOrderReq field", "label" in names)

    print("\n1. A BUY carries SL/TP distances from the ASK, in 1e-5 units")
    c = _Conn()
    b = _broker(c)
    b.place_order("BUY", 1000, "EURUSD", sl=1.16030, tp=1.16480)
    req = _new_orders(c)[0]
    check("relativeStopLoss = 150 points (0.00150 * 1e5)",
          req.relativeStopLoss == 150, str(req.relativeStopLoss))
    check("relativeTakeProfit = 300 points",
          req.relativeTakeProfit == 300, str(req.relativeTakeProfit))
    check("no ABSOLUTE stop on a market order (the protocol refuses it)",
          not req.HasField("stopLoss") and not req.HasField("takeProfit"))
    check("the post-fill amend still runs as the verifying fallback",
          len(_amends(c)) == 1, str(len(_amends(c))))
    check("...with the exact absolute prices",
          _amends(c) and abs(_amends(c)[0].stopLoss - 1.16030) < 1e-9
          and abs(_amends(c)[0].takeProfit - 1.16480) < 1e-9)

    print("\n2. A SELL measures from the BID")
    c = _Conn()
    _broker(c).place_order("SELL", 1000, "EURUSD", sl=1.16320, tp=1.15870)
    req = _new_orders(c)[0]
    check("relativeStopLoss = 150", req.relativeStopLoss == 150,
          str(req.relativeStopLoss))
    check("relativeTakeProfit = 300", req.relativeTakeProfit == 300,
          str(req.relativeTakeProfit))

    print("\n3. Gold (2 digits): the distance is a whole number of ticks")
    c = _Conn()
    _broker(c, symbol="XAUUSD", bid=4040.10, ask=4040.40, digits=2).place_order(
        "BUY", 1, "XAUUSD", sl=4001.987654, tp=4100.0)
    req = _new_orders(c)[0]
    check("relativeStopLoss is a multiple of 1000 (0.01 * 1e5)",
          req.relativeStopLoss > 0 and req.relativeStopLoss % 1000 == 0,
          str(req.relativeStopLoss))
    check("...and equals 38.41 * 1e5", req.relativeStopLoss == 3_841_000,
          str(req.relativeStopLoss))

    print("\n4. No quote -> no relative fields, the amend still protects")
    c = _Conn()
    _broker(c, quote=False).place_order("BUY", 1000, "EURUSD",
                                        sl=1.16030, tp=1.16480)
    req = _new_orders(c)[0]
    check("no relative stop without a reference price",
          not req.HasField("relativeStopLoss"))
    check("the amend is still sent", len(_amends(c)) == 1)

    print("\n5. A stop on the wrong side is never sent as a relative distance")
    c = _Conn()
    _broker(c).place_order("BUY", 1000, "EURUSD", sl=1.17000, tp=1.16480)
    check("a BUY stop above the ask is not encoded",
          not _new_orders(c)[0].HasField("relativeStopLoss"))

    print("\n6. Explicit rejection of the protected order -> one resend without")
    rejected = ctrader.ProtoOAExecutionEvent(
        executionType=ctrader.ProtoOAExecutionType.ORDER_REJECTED,
        errorCode="TRADING_BAD_STOPS")
    c = _Conn(rejected)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        res = _broker(c).place_order("BUY", 1000, "EURUSD",
                                     sl=1.16030, tp=1.16480)
    orders = _new_orders(c)
    check("two order requests went out", len(orders) == 2, str(len(orders)))
    check("the second has no relative stop",
          len(orders) == 2 and not orders[1].HasField("relativeStopLoss"))
    check("the result is a fill, protected by the amend",
          res.get("status") == "FILLED" and len(_amends(c)) == 1, str(res))
    check("the resend is logged", "without" in out.getvalue().lower(),
          out.getvalue()[-300:])

    print("\n7. A timeout is NOT resent (it may have reached the broker)")
    c = _Conn(TimeoutError("no terminal execution event"))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _broker(c).place_order("BUY", 1000, "EURUSD", sl=1.16030)
        check("a timeout propagates", False)
    except TimeoutError:
        check("a timeout propagates", True)
    check("...after exactly one order request", len(_new_orders(c)) == 1,
          str(len(_new_orders(c))))

    print("\n8. Unprotected: the safety close is retried, and it shouts")
    c = _Conn(FILLED, RuntimeError("amend 1"), RuntimeError("amend 2"),
              RuntimeError("amend 3"))
    b = _broker(c)
    b.get_open_position = lambda instrument=None: {"positionId": 456}
    calls = []

    def _close_fails_twice(instrument=None):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("close failed")
        return {"status": "FILLED", "fillPrice": 1.1617}
    b.close_position = _close_fails_twice
    with contextlib.redirect_stdout(io.StringIO()):
        res = b.place_order("BUY", 1000, "EURUSD", sl=1.16030)
    check("the third close attempt succeeds -> SAFETY_CLOSED",
          res.get("status") == "SAFETY_CLOSED", str(res))
    check("three close attempts were made", len(calls) == 3, str(len(calls)))

    c = _Conn(FILLED, RuntimeError("a"), RuntimeError("b"), RuntimeError("c"))
    b = _broker(c)
    b.get_open_position = lambda instrument=None: {"positionId": 456}
    calls2 = []
    b.close_position = lambda instrument=None: (calls2.append(1), (_ for _ in ()).throw(
        RuntimeError("close failed")))[1]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        res = b.place_order("BUY", 1000, "EURUSD", sl=1.16030)
    check("every close failing -> UNPROTECTED", res.get("status") == "UNPROTECTED",
          str(res))
    check("...after the full retry budget", len(calls2) == 3, str(len(calls2)))
    check("...logged loudly", "UNPROTECTED" in out.getvalue()
          and "CRITICAL" in out.getvalue(), out.getvalue()[-300:])

    print("\n9. Every engine order carries the engine label")
    c = _Conn()
    _broker(c).place_order("BUY", 1000, "EURUSD", sl=1.16030)
    check("label is the engine label",
          _new_orders(c)[0].label == ctrader.ENGINE_ORDER_LABEL,
          repr(_new_orders(c)[0].label))

    print("\n10. Slippage: live gets a sane default, demo stays MARKET")
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = 0
    c = _Conn()
    _broker(c, env="demo").place_order("BUY", 1000, "EURUSD")
    check("demo with no setting stays MARKET",
          _new_orders(c)[0].orderType == ctrader.ProtoOAOrderType.MARKET)
    c = _Conn()
    _broker(c, env="live").place_order("BUY", 1000, "EURUSD")
    req = _new_orders(c)[0]
    check("live with no setting becomes MARKET_RANGE",
          req.orderType == ctrader.ProtoOAOrderType.MARKET_RANGE,
          str(req.orderType))
    check("...with the live default ceiling",
          req.slippageInPoints == cfg.CTRADER_MAX_SLIPPAGE_POINTS_LIVE > 0,
          f"{req.slippageInPoints} vs {cfg.CTRADER_MAX_SLIPPAGE_POINTS_LIVE}")
    check("the live default is sane (1..100 points)",
          1 <= cfg.CTRADER_MAX_SLIPPAGE_POINTS_LIVE <= 100)
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = 12
    c = _Conn()
    _broker(c, env="live").place_order("BUY", 1000, "EURUSD")
    check("an explicit operator setting still wins on live",
          _new_orders(c)[0].slippageInPoints == 12,
          str(_new_orders(c)[0].slippageInPoints))
    check("the effective value helper agrees",
          ctrader.effective_slippage_points(SimpleNamespace(CTRADER_ENV="live")) == 12)
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = 0
    check("helper: live default", ctrader.effective_slippage_points(
        SimpleNamespace(CTRADER_ENV="live")) == cfg.CTRADER_MAX_SLIPPAGE_POINTS_LIVE)
    check("helper: demo is 0", ctrader.effective_slippage_points(
        SimpleNamespace(CTRADER_ENV="demo")) == 0)
finally:
    cfg.CTRADER_MAX_SLIPPAGE_POINTS = _real_slip

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL CHECKS PASSED - the stop travels with the order.")
