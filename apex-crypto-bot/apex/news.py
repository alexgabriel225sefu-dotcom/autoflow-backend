"""Economic-news guard — avoid trading into high-impact announcements.

This is the safe, deterministic core of "AI news analysis": rather than guessing
direction from headlines, the bot simply stands aside in the minutes around a
high-impact release (FOMC, CPI, NFP, rate decisions…), when spreads blow out and
price gaps unpredictably. The AI assistant can also cite this when asked.

Source is configurable and the guard is ALWAYS fail-open: if the feed is
unreachable, empty, or in an unexpected shape, it reports "no event" and trading
proceeds normally — a down feed must never silently halt the bot.

Config (env):
    NEWS_GUARD=true|false        default true
    NEWS_FEED_URL=<json url>      default: Forex Factory weekly JSON
    NEWS_API_KEY=<optional>       sent as ?apikey= if your feed needs one
    NEWS_WINDOW_MIN=<int>        minutes around an event to stay flat (default 30)
"""
import os
import time
from datetime import datetime, timezone

import requests

_DEFAULT_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_TTL = 1800  # re-fetch the calendar at most every 30 min
_cache = {"ts": 0.0, "events": []}


def enabled() -> bool:
    return (os.getenv("NEWS_GUARD", "true") or "true").strip().lower() not in ("false", "0", "no", "off")


def window_min() -> int:
    try:
        return int(os.getenv("NEWS_WINDOW_MIN") or 30)
    except ValueError:
        return 30


def _feed_url() -> str:
    url = os.getenv("NEWS_FEED_URL") or _DEFAULT_FEED
    key = os.getenv("NEWS_API_KEY")
    if key and "apikey=" not in url:
        url += ("&" if "?" in url else "?") + "apikey=" + key
    return url


def _parse_time(raw):
    if not raw:
        return None
    try:
        # ISO 8601, usually with a timezone offset (e.g. 2024-01-10T08:30:00-05:00)
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _impact_high(val) -> bool:
    s = str(val).strip().lower()
    return s in ("high", "3", "red") or "high" in s


def _load():
    now = time.time()
    if _cache["events"] and now - _cache["ts"] < _TTL:
        return _cache["events"]
    try:
        r = requests.get(_feed_url(), headers={"User-Agent": "ApexBot/1.0"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else (data.get("events") or data.get("result") or [])
        events = []
        for e in rows:
            if not isinstance(e, dict):
                continue
            events.append({
                "title": e.get("title") or e.get("event") or "Economic event",
                "currency": (e.get("country") or e.get("currency") or "").upper(),
                "impact": e.get("impact") or e.get("importance"),
                "time": e.get("date") or e.get("time") or e.get("datetime"),
            })
        _cache["events"] = events
        _cache["ts"] = now
    except Exception as ex:
        print(f"[NEWS] feed unavailable ({ex}) — guard is fail-open, trading continues")
        # keep any stale cache; if empty stays empty → guard reports no event
    return _cache["events"]


def high_impact_window(currencies, window=None):
    """Nearest high-impact event within ±window minutes for any of `currencies`,
    as {title, currency, mins, time}, else None. Fail-open on any error."""
    try:
        if not enabled():
            return None
        win = window if window is not None else window_min()
        curset = {str(c).upper() for c in currencies}
        now = datetime.now(timezone.utc)
        best = None
        for e in _load():
            if not _impact_high(e.get("impact")):
                continue
            if e.get("currency") not in curset:
                continue
            t = _parse_time(e.get("time"))
            if not t:
                continue
            mins = abs((t - now).total_seconds()) / 60.0
            if mins <= win and (best is None or mins < best["mins"]):
                best = {"title": e["title"], "currency": e["currency"],
                        "mins": int(mins), "time": e["time"]}
        return best
    except Exception:
        return None


def upcoming(currencies=None, hours=24, limit=8):
    """List upcoming high-impact events in the next `hours` (for /news). Fail-open."""
    try:
        now = datetime.now(timezone.utc)
        curset = {str(c).upper() for c in currencies} if currencies else None
        out = []
        for e in _load():
            if not _impact_high(e.get("impact")):
                continue
            if curset and e.get("currency") not in curset:
                continue
            t = _parse_time(e.get("time"))
            if not t:
                continue
            mins = (t - now).total_seconds() / 60.0
            if 0 <= mins <= hours * 60:
                out.append({"title": e["title"], "currency": e["currency"],
                            "in_min": int(mins), "time": e["time"]})
        out.sort(key=lambda x: x["in_min"])
        return out[:limit]
    except Exception:
        return []
