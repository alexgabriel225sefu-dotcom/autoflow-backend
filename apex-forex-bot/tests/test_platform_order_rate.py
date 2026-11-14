"""The per-client order-rate cap §9 requires, and the one rule it must not break.

§9: "The fallback must REFUSE, not degrade. An order-placing path that
rate-limits in one process is not rate-limited."

That sentence is the whole module. `platform/ratelimit.py` guards the HTTP API
and falls back to an in-memory counter when the shared store cannot answer,
reporting the degradation on /readyz — the right trade for a route, because a
per-process limit is better than none and the worst case is some extra reads.

An order path cannot make that trade. Two containers each allowing "six orders
a minute" allow twelve, and the client discovers it as twelve positions. So
this limiter has no in-memory mode at all: when it cannot count across
instances it REFUSES, and the absence of a fallback is asserted on the
module's AST rather than left as a thing nobody added.

WHAT IS ALREADY DONE ELSEWHERE, AND NOT RETESTED HERE

§9's broker-facing limits live in `apex/brokers/ctrader.py`, which meters two
separate budgets (`_hist_limit`, `_other_limit`) per CONNECTION — the scope
the broker meters, and a scope that lives inside one process, so an
in-process limiter is correct there. tests/test_ctrader_rate_limit.py covers
it. This file is only about the per-client cap, which is the cross-process
one.

Run: python3 tests/test_platform_order_rate.py
"""
import ast
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-orderrate-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

from apex import user_store                             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def raised(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except exc as e:
        return e


def attempt(fn, *a, **kw):
    """The return value, or whatever was raised.

    Used wherever a defect could change WHICH exception comes out. `raised()`
    catches one type, so anything else propagates and kills the run — and a
    dead run reports no failing check by name, which reads like a test that
    proved nothing. This keeps the verdict legible.
    """
    try:
        return fn(*a, **kw)
    except BaseException as e:                               # noqa: BLE001
        return e


# ── a shared counter, and a switch to make it unreachable ───────────────────
class FakeCounter:
    """`incr` with the tri-state user_store gives: a number, or None.

    None is the case the whole module is about. user_store.incr returns it
    both when there is no backend and when the command failed, and for "can
    we count across instances right now" those are the same answer.
    """

    def __init__(self):
        self.counts = {}
        self.down = False
        self.calls = 0

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        user_store.incr = self.incr

    def incr(self, key, ttl_s=60):
        self.calls += 1
        if self.down:
            return None
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


FAKE = FakeCounter()
FAKE.install()

from apex.platform import order_rate as OR             # noqa: E402

U1 = "1111aaaa-2222-4333-8444-111155556666"
U2 = "2222bbbb-3333-4444-8555-222266667777"
NOW = 1_760_000_000.0


def reset():
    FAKE.counts.clear()
    FAKE.down = False


# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] a client inside the cap is allowed, and counted")
reset()
_a = attempt(OR.authorize, U1, now=NOW)
check("the first order is allowed",
      isinstance(_a, dict) and _a.get("allowed") is True,
      f"{type(_a).__name__}: {_a}")
check("and it says what is left in the tightest window",
      isinstance(_a.get("remaining"), int) and _a["remaining"] >= 0, str(_a))
check("counting happened in the shared counter", FAKE.calls > 0,
      "a cap that consults nothing is not a cap")

print("\n[2] over the cap, it refuses and names the window")
reset()
_per_min = OR.ORDERS_PER_MINUTE
for _ in range(_per_min):
    OR.authorize(U1, now=NOW)
_e = raised(OR.OrderRateExceeded, OR.authorize, U1, now=NOW)
check(f"the order after {_per_min} in one minute is refused", _e is not None)
check("and the refusal names which window was hit",
      "minute" in str(_e).lower(), str(_e))
check("and carries a code a review can count",
      getattr(_e, "code", None) == OR.ORDER_RATE_EXCEEDED,
      str(getattr(_e, "code", None)))

print("\n[3] the cap is PER CLIENT — one client cannot spend another's")
reset()
for _ in range(OR.ORDERS_PER_MINUTE):
    OR.authorize(U1, now=NOW)
check("the first client is now at its limit",
      raised(OR.OrderRateExceeded, OR.authorize, U1, now=NOW) is not None)
_other = attempt(OR.authorize, U2, now=NOW)
check("a different client is unaffected",
      isinstance(_other, dict) and _other.get("allowed") is True,
      f"{type(_other).__name__}: {_other} — one shared bucket caps the "
      f"wrong thing and uncaps every client in it")

print("\n[4] the window moves on")
reset()
for _ in range(OR.ORDERS_PER_MINUTE):
    OR.authorize(U1, now=NOW)
check("still refused inside the same minute",
      raised(OR.OrderRateExceeded, OR.authorize, U1, now=NOW) is not None)
_later = attempt(OR.authorize, U1, now=NOW + 61)
check("allowed again in the next minute",
      isinstance(_later, dict) and _later.get("allowed") is True,
      f"{type(_later).__name__}: {_later} — a window that never rolls over "
      f"is a one-time allowance, not a rate")
# Measured from the start of a window rather than from NOW, which is 20s into
# its own minute — an assertion that assumed otherwise would be testing the
# fixture's alignment instead of the slot arithmetic.
_aligned = OR._slot(NOW, 60) * 60
check("the window is a floor of the clock, so every instance agrees on "
      "which bucket a request belongs to without coordinating",
      OR._slot(_aligned, 60) == OR._slot(_aligned + 59, 60)
      and OR._slot(_aligned, 60) != OR._slot(_aligned + 60, 60),
      f"{OR._slot(_aligned, 60)} / {OR._slot(_aligned + 59, 60)} / "
      f"{OR._slot(_aligned + 60, 60)}")

print("\n[5] the longer windows are separate caps, not the same one twice")
reset()
check("an hour cap exists and is above the minute cap",
      OR.ORDERS_PER_HOUR > OR.ORDERS_PER_MINUTE,
      f"{OR.ORDERS_PER_MINUTE}/min vs {OR.ORDERS_PER_HOUR}/hour")
check("a day cap exists and is above the hour cap",
      OR.ORDERS_PER_DAY > OR.ORDERS_PER_HOUR,
      f"{OR.ORDERS_PER_HOUR}/hour vs {OR.ORDERS_PER_DAY}/day")
# Spread the orders so the minute cap never trips, and only the hour cap can.
reset()
_t = NOW
for i in range(OR.ORDERS_PER_HOUR):
    OR.authorize(U1, now=_t)
    _t += 61 if (i + 1) % OR.ORDERS_PER_MINUTE == 0 else 0
_eh = raised(OR.OrderRateExceeded, OR.authorize, U1, now=_t)
check("the hour cap refuses even when the minute cap would allow it",
      _eh is not None and "hour" in str(_eh).lower(), str(_eh))


# ═══════════════════════════════════════════════════════════════════════════
print("\n[6] §9: the fallback REFUSES, it does not degrade")
reset()
FAKE.down = True
_u = attempt(OR.authorize, U1, now=NOW)
check("with no shared counter, an order is REFUSED",
      isinstance(_u, OR.OrderRateUnavailable),
      f"{type(_u).__name__}: {_u} — an order path that rate-limits in one "
      f"process is not rate-limited; two containers would each allow the "
      f"whole cap, and nothing afterwards reads as wrong")
check("the refusal says the counter could not answer, not that the cap was hit",
      "could not" in str(_u).lower() or "unavailable" in str(_u).lower(),
      str(_u))
check("and it is a DIFFERENT exception from being over the cap",
      not issubclass(OR.OrderRateUnavailable, OR.OrderRateExceeded)
      and not issubclass(OR.OrderRateExceeded, OR.OrderRateUnavailable),
      "a caller that cannot tell 'too many' from 'cannot tell' will retry "
      "the one it must not")
FAKE.down = False
_back = attempt(OR.authorize, U1, now=NOW)
check("and it works again once the counter answers",
      isinstance(_back, dict) and _back.get("allowed") is True,
      f"{type(_back).__name__}: {_back}")

print("\n[7] there is no in-memory mode to fall back TO")
_src = open(os.path.join(ROOT, "apex", "platform", "order_rate.py"),
            encoding="utf-8").read()
_tree = ast.parse(_src)
_attrs = {n.attr for n in ast.walk(_tree) if isinstance(n, ast.Attribute)}
_names = {n.id for n in ast.walk(_tree) if isinstance(n, ast.Name)}
# MODULE level only. A dict built inside a function is an accumulator that
# dies with the call; one at module level survives between calls, which is
# what a process-local counter is and what §9 forbids. Walking the whole tree
# cannot tell the two apart, so this reads the module body directly.
_module_state = [n for n in _tree.body
                 if isinstance(n, (ast.Assign, ast.AnnAssign))
                 and isinstance(getattr(n, "value", None),
                                (ast.Dict, ast.List, ast.Set))]
check("the module keeps no dict, list or set of its own between calls",
      not _module_state,
      f"{[getattr(t, 'id', '?') for n in _module_state for t in getattr(n, 'targets', [])]}"
      f" — a process-local counter is the degradation §9 forbids")
check("it does not import the API limiter's in-memory buckets",
      "ratelimit" not in (_attrs | _names),
      "the API limiter degrades on purpose; borrowing it would import that "
      "behaviour into the order path")
check("it counts with the shared INCR and nothing else",
      "incr" in _attrs, str(sorted(_attrs)[:10]))
check("and it never reads a plain blob to count with",
      "get_blob" not in _attrs and "set_blob" not in _attrs,
      "a GET-then-SET counter is not atomic across instances")

print("\n[8] it is separate from the API rate limiter")
from apex.platform import ratelimit as RL              # noqa: E402

check("the API limiter still has its memory fallback, which is correct for it",
      RL.store_mode() in ("shared", "memory", "memory-forced"),
      str(RL.store_mode()))
check("the order cap's keys do not collide with the API limiter's",
      not OR._key(U1, "minute", OR._slot(NOW, 60)).startswith(
          f"{RL._store_ns()}:rl:"),
      OR._key(U1, "minute", OR._slot(NOW, 60)))
check("an order key names the client and the window",
      U1 in OR._key(U1, "minute", OR._slot(NOW, 60))
      and "minute" in OR._key(U1, "minute", OR._slot(NOW, 60)))

print("\n[9] it places nothing and reaches no broker")
check("it names no execution module",
      not ({"bridge", "execution"} & (_attrs | _names)),
      str(sorted({"bridge", "execution"} & (_attrs | _names))))
check("and no broker-mutating operation",
      not ({"place_order", "close_position", "amend_sltp", "submit"}
           & (_attrs | _names)))

print("\n[10] a cap of zero is a stop, not an unlimited pass")
reset()
_saved = OR.ORDERS_PER_MINUTE
OR.ORDERS_PER_MINUTE = 0
try:
    check("a zero cap refuses every order",
          raised(OR.OrderRateExceeded, OR.authorize, U1, now=NOW) is not None,
          "a falsy limit read as 'no limit' turns a stop into a free pass")
finally:
    OR.ORDERS_PER_MINUTE = _saved

print("\n[12] a cap an operator mistyped falls back to the shipped number")
# The dangerous direction is specific: a malformed value read as "no limit"
# removes the cap, and the deployment that mistyped it is exactly the one
# nobody is watching. Falling back to the shipped number is visible in the
# logs and safe in the direction that matters.
_ENV = "A4T_ORDERS_PER_MINUTE"
_had = os.environ.get(_ENV)
try:
    for bad in ("not-a-number", "6.5", "-5", "", "   "):
        os.environ[_ENV] = bad
        check(f"{bad!r} falls back to the shipped cap, never to no cap",
              OR._cap(_ENV, 6) == 6, str(OR._cap(_ENV, 6)))
    os.environ[_ENV] = "3"
    check("and a valid value IS honoured, so the fallback is not a no-op",
          OR._cap(_ENV, 6) == 3, str(OR._cap(_ENV, 6)))
    os.environ[_ENV] = "0"
    check("including zero, which is an operator stopping all order flow",
          OR._cap(_ENV, 6) == 0, str(OR._cap(_ENV, 6)))
finally:
    if _had is None:
        os.environ.pop(_ENV, None)
    else:
        os.environ[_ENV] = _had
check("an unset cap uses the shipped number", OR._cap(_ENV, 6) == 6,
      str(OR._cap(_ENV, 6)))


print("\n[11] a client id is required — an uncounted order is uncapped")
reset()
for bad in ("", None, "   "):
    check(f"{bad!r} is refused rather than counted under a blank key",
          raised(ValueError, OR.authorize, bad, now=NOW) is not None)


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All order-rate invariants hold.")
