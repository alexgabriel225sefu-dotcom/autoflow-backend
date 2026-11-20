"""Unknown leverage is not 30x, and it is not shared across accounts.

Run: python3 tests/test_leverage_unknown.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-lev-")
os.environ["ALLOW_PLAINTEXT_DEV_STORAGE"] = "true"
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

from apex import user_loop                                           # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


class Cfg:
    def __init__(self, account, token, leverage=30, explicit=False):
        self.CTRADER_ACCOUNT_ID = account
        self.CTRADER_ENV = "demo"
        self.CTRADER_ACCESS_TOKEN = token
        self.LEVERAGE = leverage
        self.LEVERAGE_EXPLICIT = explicit


class Broker:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.calls = 0

    def leverage_for(self, symbol):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


user_loop._LEV_CACHE.clear()

print("\n[1] a failed read is unknown, not 30")
cfg = Cfg("111", "token-a")
broker = Broker(error=RuntimeError("Trading account is not authorized"))
got = user_loop.leverage_for_symbol(broker, cfg, "EURUSD")
check("returns None", got is None, str(got))
check("does not cache 30", 30 not in (item[1] for item in user_loop._LEV_CACHE.values()))
again = Broker(value=20)
# The failure is remembered briefly so the next tick does not ask again.
check("the unknown answer is reused for this account",
      user_loop.leverage_for_symbol(again, cfg, "EURUSD") is None)
check("and the broker was not asked again", again.calls == 0, str(again.calls))

print("\n[2] another account does not inherit it")
other = Broker(value=5)
other_cfg = Cfg("222", "token-b")
check("the other account reads its own leverage",
      user_loop.leverage_for_symbol(other, other_cfg, "EURUSD") == 5.0)
check("it asked its own broker", other.calls == 1, str(other.calls))

print("\n[3] a new token on the same account asks again")
user_loop._LEV_CACHE.clear()
first = Broker(value=30)
user_loop.leverage_for_symbol(first, Cfg("111", "token-old"), "XAUUSD")
refreshed = Broker(value=10)
check("a refreshed token is not the previous session",
      user_loop.leverage_for_symbol(refreshed, Cfg("111", "token-new"), "XAUUSD") == 10.0)

print("\n[4] an explicit client setting still wins without a broker")
check("explicit",
      user_loop.leverage_for_symbol(None, Cfg("111", "t", leverage=7, explicit=True),
                                    "EURUSD") == 7.0)

print("\n[5] a successful reading expires, and a failed refresh is not the old number")
user_loop._LEV_CACHE.clear()
cfg = Cfg("333", "token-c")
high = Broker(value=30)
check("first read",
      user_loop.leverage_for_symbol(high, cfg, "EURUSD", now=1000) == 30.0)
lower = Broker(value=5)
check("inside the freshness window the broker is not asked again",
      user_loop.leverage_for_symbol(lower, cfg, "EURUSD", now=1000 + 30) == 30.0
      and lower.calls == 0)
check("after the window the new broker value replaces it",
      user_loop.leverage_for_symbol(
          lower, cfg, "EURUSD",
          now=1000 + user_loop._LEV_SUCCESS_TTL_S) == 5.0)
dead = Broker(error=RuntimeError("account not authorized"))
check("a refresh that fails does not keep the previous leverage",
      user_loop.leverage_for_symbol(
          dead, cfg, "EURUSD",
          now=1000 + 2 * user_loop._LEV_SUCCESS_TTL_S) is None)
forever = ("333", "demo", __import__("hashlib").sha256(b"token-c").hexdigest()[:16],
           "EURUSD")
user_loop._LEV_CACHE[forever] = (None, 30.0)
check("an entry with no expiry is not treated as still true",
      user_loop.leverage_for_symbol(Broker(value=8), cfg, "EURUSD", now=5000) == 8.0)

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
