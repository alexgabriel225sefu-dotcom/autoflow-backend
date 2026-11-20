"""Push a message when a high-impact release is about to hit — and when it passes.

The Mini App's news panel answers "what is going on?" only while the client is
looking at it. This module is the other half: it reaches out, the way a trade
open or close does.

Two messages per event, mirroring the shape of a trade:

    NEWS_AHEAD   a high-impact release for a currency this client trades is
                 inside the guard window — the bot is about to stand aside
    NEWS_CLEAR   the window has passed and the bot is trading that pair again

NEWS_CLEAR is only ever sent for an event whose NEWS_AHEAD went out. "Back to
trading" arriving on its own, for a pause the client was never told about,
explains nothing.

What this does NOT do is report the released figure. The calendar feed
(Forex Factory's weekly JSON) carries `forecast` and `previous` and no
`actual` — not even for events three days old — so a "CPI came in at 3.1%"
message would be a promise the data cannot keep. `news.feed()` already carries
an `actual` field for any feed that does supply one; when one does, the result
message belongs here.

Volume is the thing to protect. A normal week holds ~8 high-impact releases
against ~90 low/medium ones, and the client who receives all 98 stops reading
the two that mattered — which is the exact failure `alert_policy` exists to
prevent. So: high impact only, only currencies this client actually trades,
and each event speaks at most twice, ever.

Deduplication is a Redis SET NX claim rather than in-process state, because
this service runs more than one container during a Render deploy and both tick
the same account. Without it a deploy at the wrong minute sends everything
twice. Where there is no shared backend the claim answers None and an
in-process set stands in — best effort, and a restart may repeat a message,
which is the right way to fail for a notification.
"""
import hashlib
import threading
import time

from apex import news, user_store

# How far ahead the heads-up goes out. Deliberately the guard's own window:
# the message says the bot is standing aside, and it must not say that before
# the bot actually does.
def lead_min() -> int:
    return news.window_min()


# Long enough that an event can never be re-claimed while it is still eligible
# (an event stays "recently released" for at most a couple of hours), short
# enough that keys expire on their own.
_CLAIM_TTL_S = 12 * 3600

# Clear fires once the release is this many minutes behind us. The guard stops
# blocking at exactly `window_min()`, so this is the first tick after it.
_CLEAR_AFTER_MIN = 1

_local = {"seen": {}}          # fallback when there is no shared backend
_lock = threading.Lock()


def enabled_for(user) -> bool:
    """Per-client toggle, defaulting ON.

    Separate from `news_filter`, which decides whether the bot STANDS ASIDE for
    releases. A client can reasonably want the pause without the messages, or
    the messages without the pause; one flag could not express either.
    """
    return bool((user or {}).get("news_alerts", True))


def event_id(ev) -> str:
    """Stable across restarts, redeploys and feed refreshes.

    Keyed on what identifies the release itself — currency, title, scheduled
    time — and never on its position in the feed, which moves as the week
    fills in.
    """
    raw = "|".join(str(ev.get(k) or "") for k in ("currency", "title", "time"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _claim(key) -> bool:
    """True exactly once per key, across every container. See module docstring."""
    got = user_store.claim(key, ttl_s=_CLAIM_TTL_S)
    if got is not None:
        return bool(got)
    now = time.time()
    with _lock:
        seen = _local["seen"]
        # Opportunistic prune so a long-lived process does not grow this
        # without bound.
        if len(seen) > 512:
            for k, exp in list(seen.items()):
                if exp <= now:
                    seen.pop(k, None)
        if seen.get(key, 0) > now:
            return False
        seen[key] = now + _CLAIM_TTL_S
        return True


def _mark_told(uid, eid):
    """Record that the heads-up went out, so the all-clear is allowed to."""
    user_store.set_blob(f"newstold:{uid}:{eid}", "1", ttl_s=_CLAIM_TTL_S)
    with _lock:
        _local["seen"][f"told:{uid}:{eid}"] = time.time() + _CLAIM_TTL_S


def _was_told(uid, eid) -> bool:
    try:
        if user_store.get_blob(f"newstold:{uid}:{eid}"):
            return True
    except Exception:
        pass
    with _lock:
        return _local["seen"].get(f"told:{uid}:{eid}", 0) > time.time()


def due(user_id, currencies, user=None, guard_on=True):
    """Alerts to send to this client right now. Claims them — call once a tick.

    Returns a list of {"action", "event", "currencies"} ready to hand to the
    alert function. Empty whenever the client opted out, the calendar is
    unreachable, or nothing is near — and never raises, because a notification
    path must not be able to break the trading loop that calls it.
    """
    try:
        if not enabled_for(user):
            return []
        curset = {str(c).upper() for c in (currencies or []) if c}
        if not curset:
            return []
        lead = lead_min()
        out = []
        # Only ever high impact: `min_rank=3`. The panel shows medium because a
        # panel is read on purpose; a push interrupts.
        for ev in news.feed(currencies=curset, back_hours=3, ahead_hours=2,
                            limit=40, min_rank=3):
            eid = event_id(ev)
            mins = ev.get("mins")
            if mins is None:
                continue
            if 0 < mins <= lead:
                if _claim(f"newsahead:{user_id}:{eid}"):
                    _mark_told(user_id, eid)
                    out.append({"action": "NEWS_AHEAD", "event": ev,
                                "guard": bool(guard_on)})
            elif mins <= -(lead + _CLEAR_AFTER_MIN):
                # The guard blocks while abs(mins) <= lead, so it has just
                # stopped. Only speak if we announced the pause in the first
                # place — "back to trading" for a pause nobody heard about
                # explains nothing.
                if _was_told(user_id, eid) and _claim(f"newsclear:{user_id}:{eid}"):
                    out.append({"action": "NEWS_CLEAR", "event": ev,
                                "guard": bool(guard_on)})
        return out
    except Exception as e:
        print(f"[NEWS] alert scan failed ({e}) — skipped, trading unaffected")
        return []
