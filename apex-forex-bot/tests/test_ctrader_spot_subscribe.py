"""A repeated spot subscription must not poison the next, unrelated request.

Observed in production on 2026-10-28/29: the platform log was full of
"cTrader error: ALREADY_SUBSCRIBED" raised by positions reads and leverage
lookups. get_quote subscribes on every call, the broker answers a repeat with
an error frame, and get_quote stopped reading as soon as the price arrived, so
the error stayed in the socket and was read, and raised, by whatever request
came next.

Run: python tests/test_ctrader_spot_subscribe.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["PAPER_TRADING"] = "true"
os.environ["TELEGRAM_BOT_TOKEN"] = "test:secret-token"

from apex.brokers import ctrader  # noqa: E402
from apex.ctrader_proto.OpenApiCommonMessages_pb2 import ProtoMessage  # noqa: E402


def check(label, condition, detail=""):
    print(f"  {'✅' if condition else '❌'} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def frame(msg, cid=""):
    pm = ProtoMessage()
    pm.payloadType = msg.payloadType
    pm.payload = msg.SerializeToString()
    if cid:
        pm.clientMsgId = cid
    return pm


def spot(sid, bid, ask):
    return frame(ctrader.ProtoOASpotEvent(
        ctidTraderAccountId=1, symbolId=sid, bid=int(bid * 1e5), ask=int(ask * 1e5)))


def already_subscribed(cid):
    return frame(ctrader.ProtoOAErrorRes(
        ctidTraderAccountId=1, errorCode="ALREADY_SUBSCRIBED",
        description="An attempt to subscribe twice"), cid)


def subscribed_ok(cid):
    return frame(ctrader.ProtoOASubscribeSpotsRes(ctidTraderAccountId=1), cid)


class _Conn:
    """Serves queued frames; counts what is left unread."""

    def __init__(self, frames):
        self.frames = list(frames)
        self._lock = __import__("threading").Lock()
        self._mid = 0

    def _send(self, msg):
        self._mid += 1
        return str(self._mid)

    def _read_frame(self, timeout=15):
        if not self.frames:
            raise TimeoutError("nothing to read")
        return self.frames.pop(0)


def _broker(conn):
    b = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False, SYMBOL="XAUUSD", CTRADER_ACCOUNT_ID=1))
    b._conn = lambda: conn
    b._ctid = lambda: 1
    b._symbol_id = lambda instrument: 7
    return b


print("\n1. get_quote reads the answer to its own subscribe, whatever the order")
c = _Conn([spot(7, 4036.8, 4037.0), already_subscribed("1")])
bid, ask, _ = _broker(c).get_quote("XAUUSD")
check("the price comes back", abs(bid - 4036.8) < 1e-6 and abs(ask - 4037.0) < 1e-6, (bid, ask))
check("the price-first answer is consumed, nothing is left in the socket",
      c.frames == [], len(c.frames))

c = _Conn([already_subscribed("1"), spot(7, 4036.8, 4037.0)])
_broker(c).get_quote("XAUUSD")
check("the answer-first order leaves nothing behind either", c.frames == [], len(c.frames))

c = _Conn([spot(7, 4036.8, 4037.0), subscribed_ok("1")])
_broker(c).get_quote("XAUUSD")
check("a first, successful subscription is consumed too", c.frames == [], len(c.frames))

print("\n2. a real subscription error is still an error")
c = _Conn([frame(ctrader.ProtoOAErrorRes(
    ctidTraderAccountId=1, errorCode="SYMBOL_NOT_FOUND", description="no such symbol"), "1")])
try:
    _broker(c).get_quote("XAUUSD")
    check("raised", False, "no exception")
except RuntimeError as e:
    check("raised with the broker's code", "SYMBOL_NOT_FOUND" in str(e), str(e))

print("\n3. a request that finds a stale ALREADY_SUBSCRIBED in the socket is not failed by it")
conn = ctrader._Conn("demo", "tok", 1)
frames = [already_subscribed("99"), subscribed_ok("5")]
conn._read_frame = lambda timeout=15: frames.pop(0)
res = conn._await("5", ctrader.ProtoOASubscribeSpotsRes, timeout=5)
check("the real reply is returned", res.ctidTraderAccountId == 1, res)
check("the stale frame was skipped, not raised", frames == [], len(frames))

print("\n4. any other error is still raised by the request it answers")
conn = ctrader._Conn("demo", "tok", 1)
frames = [frame(ctrader.ProtoOAErrorRes(
    ctidTraderAccountId=1, errorCode="CH_ACCESS_TOKEN_INVALID", description="bad"), "5")]
conn._read_frame = lambda timeout=15: frames.pop(0)
try:
    conn._await("5", ctrader.ProtoOASubscribeSpotsRes, timeout=5)
    check("raised", False, "no exception")
except RuntimeError as e:
    check("raised", "CH_ACCESS_TOKEN_INVALID" in str(e), str(e))

print()
if check.failed:
    print(f"❌ {check.failed} check(s) failed")
    sys.exit(1)
print("✅ ALL CHECKS PASSED")
