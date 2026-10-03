"""The platform's own notification centre. Nothing here reaches Telegram.

WHY THIS IS NOT THE JOURNAL

The journal is evidence: every evaluation, including the thousands that hold.
A notification is an interruption — something a person should look at. Writing
one per evaluation would bury the two that mattered under the ones that did
not, and a notification centre nobody reads is worse than none, because its
silence starts to look like reassurance.

So they are separate stores with separate retention, and only a caller that
has decided something is worth a person's attention writes here.

DELIVERY IS IN-PLATFORM, DELIBERATELY

The old product pushed everything through a Telegram bot, which made Telegram
load-bearing for knowing your account had been disconnected. A client with no
Telegram must still learn that. So notifications live here and are read
through the API; email can be added later as an ADDITIONAL channel, never as
the only one.
"""

import time
import uuid

from apex import user_store
from apex.platform import store as _store

# What a notification can be about. Small on purpose: a type nobody can filter
# on is not a type, and every one of these maps to a screen a client can act
# on.
ORDER = "order"          # an order was sent, confirmed or refused
RULE = "rule"            # a rule was activated, paused, or refused to run
ACCOUNT = "account"      # a broker account connected, dropped, needs reauth
RISK = "risk"            # a risk limit fired
SYSTEM = "system"        # platform-level, e.g. a licence about to lapse
TYPES = (ORDER, RULE, ACCOUNT, RISK, SYSTEM)

# Severity, so the UI can be loud about the right things without parsing text.
INFO = "info"
WARNING = "warning"
CRITICAL = "critical"
LEVELS = (INFO, WARNING, CRITICAL)

MAX_NOTIFICATIONS = 500
_LOCK_TTL_S = 10


class NotificationNotFound(LookupError):
    """No such notification for this owner."""


def _k(owner):
    return f"{_store._ns()}:{_store._P}:notify:{owner}"


def _k_lock(owner):
    return f"{_store._ns()}:{_store._P}:notifylock:{owner}"


def _read_all(owner):
    raw = _store._read(_k(owner))
    return raw if isinstance(raw, list) else []


def _mutate(owner, fn):
    """Read-modify-write under a lock where a shared backend allows one.

    Without one — development only — two processes could interleave and lose
    a write. Said plainly rather than left for someone to find.
    """
    token = uuid.uuid4().hex
    got = user_store.claim_value(_k_lock(owner), token, ttl_s=_LOCK_TTL_S)
    try:
        rows = fn(_read_all(owner))
        _store._write(_k(owner), rows[:MAX_NOTIFICATIONS])
        return rows
    finally:
        if got:
            try:
                user_store.release_claim(_k_lock(owner), token)
            except Exception:
                pass


def notify(user_id, *, type, title, body="", level=INFO, link=None,
           correlation_id=None, ts=None):
    """Record something a person should see. Returns the notification."""
    if type not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}, "
                         f"got {type!r}")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}")
    if not title:
        raise ValueError("a notification without a title cannot be read")
    row = {
        "id": uuid.uuid4().hex,
        "userId": str(user_id),
        "type": type,
        "level": level,
        "title": str(title)[:200],
        "body": str(body or "")[:1000],
        "link": link,
        "correlationId": correlation_id,
        "ts": float(ts if ts is not None else time.time()),
        "readAt": None,
    }
    _mutate(str(user_id), lambda rows: [row] + rows)
    return row


def query(user_id, *, type=None, unread_only=False, limit=50, offset=0):
    """A page, newest first, with the unread count alongside.

    The count is over EVERYTHING unread, not just this page — a badge that
    only counted the current page would go down when a client paginated.
    """
    owner = str(user_id)
    if type is not None and type not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    rows = [r for r in _read_all(owner) if str(r.get("userId")) == owner]
    unread = sum(1 for r in rows if not r.get("readAt"))
    if type is not None:
        rows = [r for r in rows if r.get("type") == type]
    if unread_only:
        rows = [r for r in rows if not r.get("readAt")]
    page = rows[offset:offset + limit]
    return {"status": "ok", "notifications": page, "total": len(rows),
            "unread": unread, "limit": limit, "offset": offset,
            "hasMore": offset + len(page) < len(rows)}


def mark_read(user_id, notification_id, *, now=None):
    """Mark one as read. Raises when it is not this client's."""
    owner = str(user_id)
    seen = {"hit": False}
    stamp = float(now if now is not None else time.time())

    def _apply(rows):
        out = []
        for r in rows:
            if (r.get("id") == str(notification_id)
                    and str(r.get("userId")) == owner):
                seen["hit"] = True
                # Already-read stays at its first timestamp: re-reading a
                # notification does not make it newly read.
                r = dict(r, readAt=r.get("readAt") or stamp)
            out.append(r)
        return out

    _mutate(owner, _apply)
    if not seen["hit"]:
        raise NotificationNotFound("no such notification")
    return query(owner, limit=1)


def mark_all_read(user_id, *, type=None, now=None):
    """Mark everything (or everything of one type) as read."""
    owner = str(user_id)
    if type is not None and type not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    stamp = float(now if now is not None else time.time())
    count = {"n": 0}

    def _apply(rows):
        out = []
        for r in rows:
            if (str(r.get("userId")) == owner and not r.get("readAt")
                    and (type is None or r.get("type") == type)):
                count["n"] += 1
                r = dict(r, readAt=stamp)
            out.append(r)
        return out

    _mutate(owner, _apply)
    return {"status": "ok", "marked": count["n"],
            "unread": query(owner, limit=1)["unread"]}


def unread_count(user_id):
    owner = str(user_id)
    return sum(1 for r in _read_all(owner)
               if str(r.get("userId")) == owner and not r.get("readAt"))
