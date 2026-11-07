"""The per-client order-rate cap — §9, and the one rule it must not break.

§9: "The fallback must REFUSE, not degrade. An order-placing path that
rate-limits in one process is not rate-limited."

WHY THIS IS NOT platform/ratelimit.py

`ratelimit.py` guards the HTTP API. When the shared counter cannot answer it
falls back to an in-memory window and reports the degradation on /readyz, and
that is the right trade for a route: a per-process limit is better than none,
and the cost of getting it wrong is some extra reads.

An order path cannot make that trade. Two containers each allowing "six
orders a minute" allow twelve, and the client finds out as twelve positions.
The failure is silent, it is in the direction of more trading, and no counter
anywhere reads as wrong afterwards. So this module has NO in-memory mode: when
it cannot count across instances it refuses, and `tests/
test_platform_order_rate.py` asserts on this module's AST that no process-local
counter exists to fall back to.

WHY A SEPARATE CAP AT ALL, GIVEN THE BROKER HAS LIMITS

§9's broker-facing limits are already enforced where they belong, in
`apex/brokers/ctrader.py`, which meters two separate budgets per CONNECTION —
history and everything else, which are not the same numbers. A connection
lives inside one process, so an in-process limiter is correct for it.

That is a limit on the SOCKET, not on the client. §9's third bullet is the
other one: "A loop placing orders as fast as the API allows is the failure
mode." A runaway loop that stays politely under the broker's throughput still
opens a position every time it is allowed to, and the cap below is what stops
that being the client's problem.

THE NUMBERS

These are OURS, not the broker's — a product policy about how fast any one
client may trade, not a documented exchange limit, and they are named here
rather than guessed at a call site. They are deliberately conservative: the
cost of being too strict is a refused order and a journal line saying so,
which a client can see and an operator can raise. The cost of being too loose
is positions nobody asked for.

COUNTING HAPPENS BEFORE THE BROKER CALL

`authorize` increments, then decides. An order that is later refused by
another gate has therefore spent budget it did not use. That is the safe
direction — it can only refuse more, never less — and the alternative (count
after a confirmed fill) leaves the window between the check and the fill
uncounted, which is exactly where a retry storm lives. §6's ledger is what
stops one decision being counted twice.

See §9 of docs/LIVE_EXECUTION_SPECIFICATION.md.
"""

import os
import time

from apex import user_store
from apex.platform import store as _store

ORDER_RATE_EXCEEDED = "ORDER_RATE_EXCEEDED"
ORDER_RATE_UNAVAILABLE = "ORDER_RATE_UNAVAILABLE"


def _cap(name, default):
    """An operator-settable cap. A bad value is the default, not zero.

    A malformed env var must not be able to silently remove a limit, and it
    must not be able to silently stop all trading either — so it is ignored
    and the shipped number stands.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        print(f"[OrderRate] {name}={raw!r} is not a whole number — using "
              f"the shipped default of {default}")
        return default
    if n < 0:
        print(f"[OrderRate] {name}={n} is negative — using {default}")
        return default
    return n


# Per client, across every instance. See THE NUMBERS above.
ORDERS_PER_MINUTE = _cap("A4T_ORDERS_PER_MINUTE", 6)
ORDERS_PER_HOUR = _cap("A4T_ORDERS_PER_HOUR", 30)
ORDERS_PER_DAY = _cap("A4T_ORDERS_PER_DAY", 100)

# (name, window in seconds, cap) — ordered tightest first, so the refusal a
# client sees names the window they actually hit rather than the widest one.
_WINDOWS = (
    ("minute", 60, lambda: ORDERS_PER_MINUTE),
    ("hour", 3600, lambda: ORDERS_PER_HOUR),
    ("day", 86400, lambda: ORDERS_PER_DAY),
)


class OrderRateExceeded(RuntimeError):
    """This client has placed as many orders as this window allows.

    Deliberately NOT a subclass of, or superclass of, OrderRateUnavailable: a
    caller that cannot tell "too many" from "cannot tell" will retry the one
    it must not.
    """

    code = ORDER_RATE_EXCEEDED

    def __init__(self, message, *, window=None, cap=None):
        super().__init__(message)
        self.window = window
        self.cap = cap


class OrderRateUnavailable(RuntimeError):
    """The shared counter could not answer, so no order may be placed.

    §9: the fallback refuses. There is nothing to fall back to here on
    purpose — a per-process window would report success while two containers
    each allowed a full cap.
    """

    code = ORDER_RATE_UNAVAILABLE


def _ns():
    # Namespaced like every other key, and NOT under ratelimit's `rl:`
    # prefix: borrowing that namespace would eventually mean borrowing its
    # behaviour, which is the degradation this module exists to refuse.
    return f"{_store._ns()}:{_store._P}:orderrate"


def _slot(now, window_s):
    """Which bucket a moment belongs to.

    A floor of the clock, so every instance agrees on the boundary without
    coordinating about it — the same approach ratelimit.py uses for its
    shared windows, and the reason two containers cannot be in different
    minutes for the same request.
    """
    return int(float(now) // int(window_s))


def _key(user_id, window, slot):
    return f"{_ns()}:{user_id}:{window}:{slot}"


def authorize(user_id, *, now=None):
    """Count this order against every window, or raise.

    Returns {"allowed": True, "remaining": n, "window": name, "counts": {...}}
    where `remaining` and `window` describe the TIGHTEST window — the one that
    will refuse first, which is the only one a caller can act on.

    Raises OrderRateExceeded when a cap is reached, and
    OrderRateUnavailable when the shared counter cannot answer. Never returns
    a falsy "not allowed": an order path that can ignore a return value is an
    order path that will.
    """
    uid = str(user_id or "").strip()
    if not uid:
        # A blank key would collect every client's orders in one bucket, which
        # caps the wrong thing and uncaps each of them.
        raise ValueError(
            "an order-rate check needs the client it is for — an order "
            "counted under a blank key is an order nobody's cap sees")
    now = time.time() if now is None else float(now)

    counts = {}
    tightest = None
    for window, window_s, cap_of in _WINDOWS:
        cap = int(cap_of())
        n = user_store.incr(_key(uid, window, _slot(now, window_s)),
                            ttl_s=window_s * 2)
        if n is None:
            # Not "under the cap". The counter could not be asked, and a
            # process that carries on here is a process that is not limited.
            raise OrderRateUnavailable(
                f"the shared order counter could not answer for {uid}, so "
                f"this order is refused — a per-process count would let "
                f"every instance allow a full {window} cap of {cap}")
        counts[window] = n
        # `>` rather than `>=` because this call's own increment is included:
        # with a cap of 6, the sixth order reads n == 6 and is the last one
        # allowed. A zero cap therefore refuses the first order, which is what
        # a zero cap must mean.
        if n > cap:
            raise OrderRateExceeded(
                f"this account has placed {n - 1} order(s) in the last "
                f"{window} and the cap is {cap} per {window}",
                window=window, cap=cap)
        left = cap - n
        if tightest is None or left < tightest[1]:
            tightest = (window, left)

    return {"allowed": True, "window": tightest[0], "remaining": tightest[1],
            "counts": counts}


def peek(user_id, *, now=None):
    """What the caps are and what this client has spent, WITHOUT counting.

    For a status screen. It cannot be used to decide whether to place an
    order — between a peek and an order another instance may have spent the
    budget — so it returns no verdict, only numbers, and `authorize` remains
    the only thing that answers the question.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("an order-rate reading needs the client it is for")
    now = time.time() if now is None else float(now)
    out = {}
    for window, window_s, cap_of in _WINDOWS:
        out[window] = {"cap": int(cap_of()), "slot": _slot(now, window_s)}
    return out
