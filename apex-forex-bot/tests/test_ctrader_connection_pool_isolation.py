"""The cTrader socket pool must not cross authentication boundaries."""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="a4t-pool-"))
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex.brokers import ctrader as CT  # noqa: E402


class FakeConn:
    def __init__(self, env, token, ctid):
        self.env = env
        self.access_token = token
        self.ctid = ctid
        self._sock = object()
        self.closed = False

    def close(self):
        self.closed = True
        self._sock = None


_fails = []
_real_conn = CT._Conn
_real_pool = CT._conns


def check(name, condition):
    if condition:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name}")


created = []


class Factory:
    def __init__(self, env, token, ctid):
        self.conn = FakeConn(env, token, ctid)
        created.append(self.conn)

    def connect(self):
        return self.conn


try:
    CT._conns = {}
    CT._Conn = Factory

    first = CT._conn_for("demo", "token-a", 123)
    same = CT._conn_for("demo", "token-a", 123)
    second = CT._conn_for("demo", "token-b", 123)
    other_account = CT._conn_for("demo", "token-a", 456)

    check("the same token reuses its authenticated socket", first is same)
    check("a different token gets a separate authenticated socket",
          second is not first)
    check("a different account remains isolated", other_account is not first)
    check("the pool key contains no raw token", all(
        "token-a" not in repr(key) and "token-b" not in repr(key)
        for key in CT._conns))

    CT._drop_conn("demo", 123)
    check("dropping an account closes every token-bound socket",
          first.closed and second.closed and
          all(key[1] != 123 for key in CT._conns))

    # A slow or hanging connect for ONE account must not stall every other
    # account: connecting takes up to ~45s (TCP + app auth + account auth), and
    # the pool lock used to be held for all of it.
    import threading
    import time

    release = threading.Event()
    started = threading.Event()
    slow_created = []

    class SlowFactory:
        def __init__(self, env, token, ctid):
            self.token = token
            self.conn = FakeConn(env, token, ctid)

        def connect(self):
            if self.token == "slow-token":
                slow_created.append(self.conn)
                started.set()
                release.wait(10)
            return self.conn

    CT._conns = {}
    CT._Conn = SlowFactory
    slow_result = []
    t_slow = threading.Thread(
        target=lambda: slow_result.append(CT._conn_for("demo", "slow-token", 900)))
    t_slow.start()
    check("the slow connect has started", started.wait(2))

    t0 = time.time()
    quick = CT._conn_for("demo", "fast-token", 901)
    elapsed = time.time() - t0
    check("another account connects while a slow connect is in flight",
          quick is not None and elapsed < 1.0)

    # A second caller for the SAME slow account waits for the first and shares
    # its socket instead of opening a duplicate.
    dup_result = []
    t_dup = threading.Thread(
        target=lambda: dup_result.append(CT._conn_for("demo", "slow-token", 900)))
    t_dup.start()
    time.sleep(0.2)
    release.set()
    t_slow.join(5)
    t_dup.join(5)
    check("concurrent callers for one account share one socket",
          len(slow_created) == 1 and slow_result and dup_result
          and slow_result[0] is dup_result[0])

    # A socket closed by another thread mid-request used to surface as
    # AttributeError ('NoneType' has no attribute 'settimeout'), which the
    # read-only retry did not catch. It must be a ConnectionError, and the
    # broker must retry it once on a fresh connection.
    dead = _real_conn("demo", "t", 1)
    for call in (lambda: dead._read_frame(1), dead._recv_some,
                 lambda: dead._send(types.SimpleNamespace(
                     payloadType=0, SerializeToString=lambda: b""))):
        try:
            call()
            raised = None
        except ConnectionError:
            raised = "ConnectionError"
        except Exception as e:  # noqa: BLE001
            raised = type(e).__name__
        check("a closed socket raises ConnectionError", raised == "ConnectionError")

    class Stale:
        def _request(self, *a, **k):
            raise ConnectionError("cTrader connection closed")

    class Fresh:
        def _request(self, *a, **k):
            return "ok"

    conns = [Stale(), Fresh()]
    cfg = types.SimpleNamespace(CTRADER_ENV="demo", CTRADER_ACCESS_TOKEN="t",
                                CTRADER_ACCOUNT_ID=77)
    broker = CT.CtraderBroker(cfg)
    broker._conn = lambda: conns.pop(0)
    check("a read retries once after the socket was closed under it",
          broker._rpc(object(), object) == "ok")
finally:
    CT._Conn = _real_conn
    CT._conns = _real_pool

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for failure in _fails:
        print("  -", failure)
    raise SystemExit(1)
print("All cTrader connection-pool isolation checks passed.")
