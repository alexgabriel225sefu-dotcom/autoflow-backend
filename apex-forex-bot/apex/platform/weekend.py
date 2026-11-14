"""When the forex week is shut, in UTC.

The broker feed does not publish a session calendar on the reads this
platform already makes. The clock is the session. Forex is closed from
Friday 22:00 UTC until Sunday 22:00 UTC. Callers that would place an order
treat a closed week as idle: they wait, and they do not raise.

`forex.is_market_open` uses a 21:00 edge. This window is the one the
dashboard states, and it is the one a new order must respect.
"""

from datetime import datetime, timezone

CLOSED_MESSAGE = "Market closed (weekend), reopens Sun 22:00 UTC"
_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6
_EDGE_HOUR = 22


def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    raise TypeError("now must be a datetime")


def weekend_closed(now=None):
    """True from Friday 22:00 UTC until Sunday 22:00 UTC."""
    dt = _now(now)
    wd, hour = dt.weekday(), dt.hour
    if wd == _FRIDAY and hour >= _EDGE_HOUR:
        return True
    if wd == _SATURDAY:
        return True
    if wd == _SUNDAY and hour < _EDGE_HOUR:
        return True
    return False


def weekend_status(now=None):
    """{"closed", "message"}. The message is the sentence the dashboard shows."""
    closed = weekend_closed(now)
    return {"closed": closed, "message": CLOSED_MESSAGE if closed else None}
