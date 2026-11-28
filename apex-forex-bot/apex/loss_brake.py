"""Consecutive-loss brake: stop NEW entries for the rest of the trading day.

WHY THIS EXISTS

The consecutive-loss limit lived only in ``apex/platform/risk_guard.py``, a
read-only decision API. The trading loop never asked it. An exact rule skips the
post-loss cooldowns on purpose (PR #205), so a rule whose stop sat inside the
market's noise could lose ten times in a row and only the account-wide daily
loss stop ended the day.

WHAT THIS IS

A pure decision. It reads a streak the loop already measures and answers
"may a new entry be opened". It cannot close a position, place an order or
change what the client's rule decides; the loop applies the answer by skipping
the entry, with the reason it returns.

THREE INPUTS, ONE RULE

* ``known_losses``: losing closes in a row, from closes whose result was read.
* ``unread_closes``: closes since the last known win whose result could NOT be
  read. They are counted as possible losses, never as zero: the worst case is
  the safe direction for a brake that only stops entries.
* ``unreadable``: the stored streak itself is not a number. Unknown, so no
  entries today.

A brand-new account has no history, which is a streak of 0 and not unknown.
That is the same distinction PR #212 drew in ``risk_guard._consecutive_losses``.
"""
import math

from apex.platform.risk_guard import GuardLimits

DEFAULT_LIMIT = GuardLimits.max_consecutive_losses

LIMIT = "limit_reached"
UNKNOWN = "streak_unknown"


def parse_stored_count(value):
    """A persisted counter as an int, or None when it cannot be read.

    Missing, null and empty mean no history, which is 0. A bool, a negative, a
    non-integer or text that is not a number is unreadable and returns None.
    """
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number != int(number):
        return None
    return int(number)


def effective_limit(limit=None):
    """The configured limit, or the platform default when it is not usable.

    A limit of 0 or less, or one that is not a number, never switches the
    brake off: it falls back to the default.
    """
    parsed = parse_stored_count(limit)
    if limit is None or not parsed:
        return DEFAULT_LIMIT
    return parsed


def decide(known_losses, unread_closes=0, *, unreadable=False, limit=None):
    """May a new entry be opened today?

    Returns ``{"block": bool, "code": str | None, "reason": str, "worst": int | None,
    "limit": int}``. ``reason`` is client-readable and says why.
    """
    lim = effective_limit(limit)
    known = known_losses if isinstance(known_losses, int) \
        and not isinstance(known_losses, bool) and known_losses >= 0 else None
    unread = unread_closes if isinstance(unread_closes, int) \
        and not isinstance(unread_closes, bool) and unread_closes >= 0 else None
    if unreadable or known is None or unread is None:
        return {"block": True, "code": UNKNOWN, "worst": None, "limit": lim,
                "reason": ("no new entries today: the losing streak could not be "
                           "read, so the loss-streak brake stays on until tomorrow")}
    worst = known + unread
    if worst >= lim:
        extra = (f" ({unread} close{'s' if unread != 1 else ''} with an "
                 f"unreadable result counted as losses)") if unread else ""
        return {"block": True, "code": LIMIT, "worst": worst, "limit": lim,
                "reason": (f"no new entries today: {worst} losses in a row "
                           f"reached the limit of {lim}{extra}")}
    return {"block": False, "code": None, "worst": worst, "limit": lim,
            "reason": ""}
