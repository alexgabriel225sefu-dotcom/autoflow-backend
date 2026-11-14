"""A value must never travel in the URL — it stops fitting, and writes die.

WHAT HAPPENED

Upstash's REST GET form makes every command argument a path segment, so a SET
sends the whole value inside the URL. That works until the value grows. Then
the edge rejects the request and the write fails PERMANENTLY, because the
value never gets smaller on its own:

  2026-09-03T00:22:27 [Redis] command failed SET: 431 Client Error: Request
  Header Fields Too Large for url:
  https://...upstash.io/SET/evt:user:7585109158/%5B%7B%22event_id%22...

Retried at :27, :29, :32, :35 and abandoned. Every retry sends the same
oversized URL, so retrying cannot help.

WHY IT MATTERS BEYOND ONE KEY

_redis_set is not just the event log. It writes the closed-trade journal
(bounded at 500 rows), whole user records on restore, and the purge rewrite.
set_blob writes TTL'd values the same way. Percent-encoding roughly
doubles the length, so a journal of a few dozen trades already exceeds a
typical 8-16KB limit — and a failed journal write means a closed trade is
never recorded.

THE FIX

_upstash_post already existed for exactly this reason; its own docstring says
the GET form "runs into URL length limits". It was reserved for Lua scripts.
Any command carrying a caller-supplied VALUE now uses it, so length stops
being a correctness boundary. Reads and small fixed-size commands keep the GET
form: they are unaffected and the existing encoding guarantees stay tested.

Run: python tests/test_upstash_large_values.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-large-test-")

from apex import user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


gets, posts = [], []


class FakeResp:
    status_code = 200
    @staticmethod
    def raise_for_status(): pass
    @staticmethod
    def json(): return {"result": "OK"}


user_store._UPD_URL = "https://example.upstash.io"
user_store._UPD_TOKEN = "t"
user_store._BACKEND = "upstash"
user_store._USE_REDIS = True
user_store._req.get = lambda url, **kw: (gets.append(url), FakeResp())[1]
user_store._req.post = lambda url, **kw: (posts.append((url, kw.get("json"))), FakeResp())[1]


def run(fn, *a):
    gets.clear(); posts.clear()
    return fn(*a)


# A journal the size the live account actually carries.
JOURNAL = json.dumps([{
    "time": f"2026-08-{(i % 28) + 1:02d} 10:00:00", "symbol": "EURUSD",
    "side": "SELL", "entry": 1.16183, "exit": 1.15992, "grossPnl": 65.52,
    "costUsd": 1.26, "netPnl": 64.26, "balance": 3176.23, "positionId": 55913871,
    "confidence": 80, "regime": "ranging", "strategyId": "fibonacci",
    "strategyVersion": "1.0.0", "mode": "demo", "action": "CLOSE",
} for i in range(73)])

print(f"\nA 73-trade journal is {len(JOURNAL):,} chars raw "
      f"(~{len(JOURNAL) * 2:,} percent-encoded).")

print("\n1. A large SET does not put the value in the URL")
ok = run(user_store._redis_set, "forex:trades:7585109158", JOURNAL)
check("the write reports success", ok is True)
check("nothing was sent as a GET", not gets, str(gets)[:120])
check("it went out as a POST", len(posts) == 1)
check("the value is in the BODY, not the URL",
      posts and posts[0][1][:3] == ["SET", "forex:trades:7585109158", JOURNAL])
check("the URL carries no journal content",
      posts and "event" not in posts[0][0] and len(posts[0][0]) < 120,
      posts[0][0][:100] if posts else "")

print("\n2. The event journal that actually failed live")
run(user_store._redis_set, "evt:user:7585109158", JOURNAL)
check("also a POST", len(posts) == 1 and not gets)

print("\n3. Small values take the same safe path — no size threshold to tune")
run(user_store._redis_set, "forex:user:1", '{"a":1}')
check("a tiny SET is a POST too", len(posts) == 1 and not gets,
      "a length cutoff is one more number to get wrong; POST always works")

print("\n4. SET with a TTL carries its value the same way")
run(user_store.set_blob, "forex:cache:1", JOURNAL, 300)
check("set_blob with a ttl is a POST", len(posts) == 1 and not gets)
check("EX and the ttl survive as arguments",
      posts and posts[0][1][0] == "SET" and posts[0][1][3] == "EX"
      and str(posts[0][1][4]) == "300",
      str(posts[0][1][:2] + posts[0][1][3:]) if posts else "")

print("\n5. Reads still use the GET form, so the encoding rules still hold")
run(user_store._redis_get, "forex:user:7585109158")
check("GET is unchanged", len(gets) == 1 and not posts)
check("colons stay literal", gets and gets[0].endswith("/GET/forex:user:7585109158"),
      gets[0] if gets else "")

print("\n6. A refused write is still reported as a failure")
def boom(url, **kw):
    raise RuntimeError("431 Client Error: Request Header Fields Too Large")
user_store._req.post = boom
check("a POST failure returns False, never a silent success",
      user_store._redis_set("forex:trades:1", JOURNAL) is False,
      "a licence key or a closed trade must never look saved when it was not")
user_store._req.post = lambda url, **kw: (posts.append((url, kw.get("json"))), FakeResp())[1]

print("\n" + "=" * 62)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL LARGE-VALUE CHECKS PASSED - value length is no longer a correctness limit.")
