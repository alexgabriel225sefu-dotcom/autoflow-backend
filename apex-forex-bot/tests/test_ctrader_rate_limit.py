"""The broker's request budget is spent deliberately, not by luck.

WHY THIS TEST EXISTS

cTrader meters requests against two budgets — a small one for anything that
reads stored history, a large one for everything else — and both are counted
PER CONNECTION. Not per API key, not per account. Two clients sharing a socket
share the allowance, so the ceiling stays where it is as the business grows and
only the number of things competing for it goes up.

The connector had no limiter at all. With one user that works by luck: nothing
was pacing the calls, the budget simply was not being spent fast enough to hit
the wall. The failure it invites is indirect and hard to read — a /report walks
a deal history, spends the small budget in under a second, and the trading
loop's next quote is refused for a reason that has nothing to do with trading.

WHAT IS ASSERTED

The window, not a fixed gap: a fixed 1/N spacing would delay a burst the broker
would have allowed. And the acquisition must happen BEFORE the socket lock, or
one thread waiting out a history budget would hold the connection shut against
every quote queued behind it — turning a small delay into a full stall.

Run: python tests/test_ctrader_rate_limit.py
"""
import ast
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex.brokers import ctrader  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


print("\n1. A burst the broker would allow is not delayed")
rl = ctrader._RateLimit(5, per=0.30)
t0 = time.monotonic()
for _ in range(5):
    rl.acquire()
burst = time.monotonic() - t0
check(f"five within the allowance pass immediately ({burst*1000:.0f}ms)",
      burst < 0.05,
      "a fixed 1/N gap would have cost a full window here")

print("\n2. The one past the allowance waits, and only as long as it must")
t0 = time.monotonic()
waited = rl.acquire()
elapsed = time.monotonic() - t0
check(f"the sixth blocked ({elapsed*1000:.0f}ms)", elapsed >= 0.2, f"{elapsed:.3f}s")
check("...and not much longer than the window", elapsed < 0.45, f"{elapsed:.3f}s")
check("acquire reports the wait it imposed", waited > 0, str(waited))

print("\n3. The budget refills — the limiter is not a one-shot")
time.sleep(0.32)
t0 = time.monotonic()
for _ in range(5):
    rl.acquire()
check(f"a full window is available again ({(time.monotonic()-t0)*1000:.0f}ms)",
      time.monotonic() - t0 < 0.05)

print("\n4. Sustained load is held at the rate, not merely slowed")
rl2 = ctrader._RateLimit(4, per=0.25)
t0 = time.monotonic()
for _ in range(12):
    rl2.acquire()
took = time.monotonic() - t0
check(f"12 requests at 4 per 0.25s took >= 0.5s ({took:.2f}s)", took >= 0.5, f"{took:.3f}")

print("\n5. Concurrent callers share one budget")
rl3 = ctrader._RateLimit(4, per=0.25)
done = []


def worker():
    for _ in range(3):
        rl3.acquire()
    done.append(1)


t0 = time.monotonic()
threads = [threading.Thread(target=worker) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
conc = time.monotonic() - t0
check("every thread finished", len(done) == 4)
check(f"12 acquisitions across 4 threads still took >= 0.5s ({conc:.2f}s)",
      conc >= 0.5, f"{conc:.3f}")
check("the window never held more than the allowance",
      len(rl3._hits) <= rl3._allowance, str(len(rl3._hits)))

print("\n6. History is charged to the small budget")
check("trendbars is historical",
      "ProtoOAGetTrendbarsReq" in ctrader._HISTORICAL_REQUESTS)
check("deal list is historical",
      "ProtoOADealListReq" in ctrader._HISTORICAL_REQUESTS)
check("tick data is historical",
      "ProtoOAGetTickDataReq" in ctrader._HISTORICAL_REQUESTS)
for cheap in ("ProtoOANewOrderReq", "ProtoOAReconcileReq", "ProtoOATraderReq",
              "ProtoOASubscribeSpotsReq", "ProtoOAClosePositionReq"):
    check(f"{cheap} is not charged to the small budget",
          cheap not in ctrader._HISTORICAL_REQUESTS)
check("the small budget is smaller than the other",
      ctrader._HIST_PER_SEC < ctrader._OTHER_PER_SEC,
      f"{ctrader._HIST_PER_SEC} vs {ctrader._OTHER_PER_SEC}")

print("\n7. The budget is metered per connection, as the broker meters it")
_src = open(os.path.join(ROOT, "apex", "brokers", "ctrader.py"),
            encoding="utf-8").read()
_tree = ast.parse(_src)
_init = next(n for n in ast.walk(_tree)
             if isinstance(n, ast.FunctionDef) and n.name == "__init__"
             and any("_hist_limit" in ast.dump(x) for x in ast.walk(n)))
check("each connection builds its own limiters", _init is not None)
check("they are not module-level singletons shared by every account",
      _src.count("_RateLimit(") >= 2 and "self._hist_limit = _RateLimit" in _src)

print("\n8. The wait happens before the socket lock, never while holding it")
_req = next(n for n in ast.walk(_tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_request")
_body = _req.body
_acq_at = next((i for i, st in enumerate(_body)
                if "acquire" in ast.dump(st)), None)
_lock_at = next((i for i, st in enumerate(_body)
                 if isinstance(st, ast.With) and "_lock" in ast.dump(st)), None)
check("_request acquires the budget", _acq_at is not None)
check("_request still takes the socket lock", _lock_at is not None)
check("the budget is acquired FIRST",
      _acq_at is not None and _lock_at is not None and _acq_at < _lock_at,
      f"acquire at {_acq_at}, lock at {_lock_at} — a thread waiting out the "
      f"history budget must not hold the socket shut behind it")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - the request budget is paced, per connection.")
