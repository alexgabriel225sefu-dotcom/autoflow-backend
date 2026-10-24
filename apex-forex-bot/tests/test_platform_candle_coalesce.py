"""Identical candle reads share one limiter unit. Failures never do.

The candles bucket allows 30 requests a minute per token, counted before the
handler. A chart polling every 15 seconds fits. The same query arriving again
while that read is in flight — a second tab, an aborted read the browser
already sent — used to spend another unit for the same bars.

Run: python3 tests/test_platform_candle_coalesce.py
"""
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-candles-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

from apex.platform import api as A                 # noqa: E402
from apex.platform import candle_coalesce as C     # noqa: E402
from apex.platform import identity as ID           # noqa: E402
from apex.platform import ratelimit as RL          # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class _Principal:
    def __init__(self, user_id):
        self.user_id = user_id
        self.email = "person@example.test"
        self.email_verified = True

    def as_dict(self):
        return {"userId": self.user_id, "email": self.email,
                "emailVerified": True}


def _verify(token, **_kw):
    return _Principal("user-" + token)


ID.verify_token = _verify

_calls = []


def _bars(symbol, status="ok"):
    out = {"connected": True, "status": status, "accountId": 501, "mode": "demo"}
    if status == "ok":
        out["candles"] = [{"open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
                           "time": 1}]
        out["symbol"] = symbol
        out["timeframe"] = "1h"
        out["count"] = 1
        out["requested"] = 200
    else:
        out["reason"] = "the broker did not answer"
    return out


def _candles(user_id, **kw):
    _calls.append((user_id, kw.get("symbol"), kw.get("timeframe"), kw.get("limit")))
    symbol = kw.get("symbol")
    if symbol == "BROKEN":
        return _bars(symbol, status="unavailable")
    return _bars(symbol)


A._read.candles = _candles

_limiter_checks = {"n": 0}
_real_check = RL.LIMITERS["candles"].check


def _counting_check(key):
    _limiter_checks["n"] += 1
    return _real_check(key)


RL.LIMITERS["candles"].check = _counting_check


def _get(path, token="alice"):
    return A.handle(
        "GET", "/api/v1/" + path,
        {"Authorization": f"Bearer {token}"}, None, client_key="1.2.3.4")


EUR = "accounts/501/candles?symbol=EURUSD&timeframe=1h&limit=200"
EUR_REORDERED = "accounts/501/candles?limit=200&timeframe=1h&symbol=eurusd"

print("\n[1] a repeated identical success does not spend another unit")
C.reset()
RL.reset_all()
_calls.clear()
_limiter_checks["n"] = 0
st, body = _get(EUR)
check("the first read is served", st == 200 and body.get("status") == "ok"
      and body.get("candles"), str(st))
check("the handler ran once", len(_calls) == 1, str(len(_calls)))
spent = _limiter_checks["n"]
check("and it was limited", spent == 1, str(spent))

st, again = _get(EUR)
check("the same query is served again", st == 200 and again.get("status") == "ok")
check("without a second handler call", len(_calls) == 1, str(_calls))
check("and without a second limiter unit", _limiter_checks["n"] == spent,
      str(_limiter_checks["n"]))

st, reordered = _get(EUR_REORDERED)
check("parameter order and case are the same query",
      st == 200 and len(_calls) == 1 and _limiter_checks["n"] == spent,
      f"calls={len(_calls)} units={_limiter_checks['n']}")

print("\n[2] a different query is limited on its own")
st, _ = _get("accounts/501/candles?symbol=GBPUSD&timeframe=1h&limit=200")
check("a different symbol is served", st == 200)
check("the handler ran for it", len(_calls) == 2, str(_calls))
check("and the limiter counted it", _limiter_checks["n"] == spent + 1,
      str(_limiter_checks["n"]))

st, _ = _get("accounts/502/candles?symbol=EURUSD&timeframe=1h&limit=200")
check("a different account is its own query",
      len(_calls) == 3 and _limiter_checks["n"] == spent + 2,
      f"calls={len(_calls)} units={_limiter_checks['n']}")

st, other = _get(EUR, token="bob")
check("a different caller does not receive the first caller's answer for free",
      st == 200 and len(_calls) == 4 and _limiter_checks["n"] == spent + 3,
      f"status={st} calls={len(_calls)} units={_limiter_checks['n']}")
check("and the body is still that caller's read",
      other.get("symbol") == "EURUSD", str(other)[:180])

print("\n[3] a failure is not remembered")
C.reset()
RL.reset_all()
_calls.clear()
_limiter_checks["n"] = 0
broken = "accounts/501/candles?symbol=BROKEN&timeframe=1h&limit=200"
st, body = _get(broken)
check("the broker failure is returned",
      st == 200 and body.get("status") == "unavailable", str(body)[:180])
st, body = _get(broken)
check("the next attempt is not the cached failure",
      len(_calls) == 2 and _limiter_checks["n"] == 2 and body.get("status") == "unavailable",
      f"calls={len(_calls)} units={_limiter_checks['n']} body={body.get('status')}")

print("\n[4] overlapping identical reads share one flight")
C.reset()
RL.reset_all()
_calls.clear()
_limiter_checks["n"] = 0
_entered = threading.Event()
_release = threading.Event()
_joined = {"n": 0}
_real_wait = C._Flight.wait
_real_candles = _candles


def _count_wait(self):
    _joined["n"] += 1
    return _real_wait(self)


C._Flight.wait = _count_wait


def _blocking(user_id, **kw):
    _calls.append((user_id, kw.get("symbol")))
    _entered.set()
    _release.wait(5)
    return _bars(kw.get("symbol"))


A._read.candles = _blocking
results = []


def _one():
    results.append(_get(EUR, token="carol"))


threads = [threading.Thread(target=_one) for _ in range(4)]
for t in threads:
    t.start()
check("the leader entered the handler", _entered.wait(3))
for _ in range(40):
    if _joined["n"] >= 3 and len(_calls) == 1:
        break
    threading.Event().wait(0.05)
check("the other three joined that flight", _joined["n"] == 3, str(_joined["n"]))
check("and the handler ran once", len(_calls) == 1, str(len(_calls)))
_release.set()
for t in threads:
    t.join(5)
check("all four were answered", len(results) == 4 and all(r[0] == 200 for r in results),
      str([r[0] for r in results]))
check("and the limiter was asked once", _limiter_checks["n"] == 1,
      str(_limiter_checks["n"]))
A._read.candles = _real_candles
C._Flight.wait = _real_wait

print("\n[5] once the short window passes, the same query is limited again")
C.reset()
RL.reset_all()
_calls.clear()
_limiter_checks["n"] = 0
_clock = {"t": 1_000.0}
C._now = lambda: _clock["t"]
try:
    st, _ = _get(EUR, token="dave")
    check("served at the start of the window", st == 200 and len(_calls) == 1)
    st, _ = _get(EUR, token="dave")
    check("still cached inside the window", len(_calls) == 1 and _limiter_checks["n"] == 1,
          f"calls={len(_calls)} units={_limiter_checks['n']}")
    _clock["t"] += C.TTL_S + 0.01
    st, _ = _get(EUR, token="dave")
    check("after the window it is a new limited read",
          st == 200 and len(_calls) == 2 and _limiter_checks["n"] == 2,
          f"calls={len(_calls)} units={_limiter_checks['n']}")
finally:
    C._now = C.time.monotonic

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All candle coalesce checks passed.")
