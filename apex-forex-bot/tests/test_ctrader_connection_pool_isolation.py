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
