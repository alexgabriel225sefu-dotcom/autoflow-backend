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
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

_DEFAULT_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_TTL = 1800  # re-fetch the calendar at most every 30 min
# (connect, read) timeouts — kept short so a slow/hung feed lingers briefly.
# The fetch runs on a background thread and never blocks the trading loop;
# these bounds just cap how long that background thread waits.
_TIMEOUT = (3.05, 6)

_cache = {"ts": 0.0, "events": []}
# Refresh coordination: `fetching` prevents overlapping fetches; `fails` /
# `next_retry` implement exponential back-off so a persistently down feed is
# retried ever more slowly instead of on every tick.
_state = {"fetching": False, "fails": 0, "next_retry": 0.0}
_lock = threading.Lock()


def enabled() -> bool:
    return (os.getenv("NEWS_GUARD", "true") or "true").strip().lower() not in ("false", "0", "no", "off")


def window_min() -> int:
    try:
        return int(os.getenv("NEWS_WINDOW_MIN") or 30)
    except ValueError:
        return 30


# FMP's economic calendar. The old /api/v3/economic_calendar was retired on
# 2025-08-31 and now answers 403 "Legacy Endpoint" to every key issued after
# that date — a valid key looks exactly like a broken one. /stable/ is the
# live replacement, but it is a PAID endpoint: a free key gets 402 "Restricted
# Endpoint". So NEWS_API_KEY only buys anything on a paid FMP plan; without one
# leave it unset and the free Forex Factory feed below is used instead (it is
# reachable from datacenter IPs and carries the same high-impact releases).
_FMP = "https://financialmodelingprep.com/stable/economic-calendar"

# Country code → currency, so a US/EU/GB event matches USD/EUR/GBP filters.
_CCY = {"US": "USD", "USA": "USD", "EU": "EUR", "EMU": "EUR", "DE": "EUR",
        "FR": "EUR", "IT": "EUR", "ES": "EUR", "GB": "GBP", "UK": "GBP",
        "JP": "JPY", "CH": "CHF", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CN": "CNY"}


def _norm_ccy(c) -> str:
    c = (c or "").upper()
    return _CCY.get(c, c)


def _feed_url() -> str:
    # Explicit feed wins. Else, if a key is set, use Financial Modeling Prep's
    # economic calendar (reachable from datacenters, unlike Forex Factory).
    url = os.getenv("NEWS_FEED_URL")
    key = os.getenv("NEWS_API_KEY")
    if url:
        if key and "apikey=" not in url:
            url += ("&" if "?" in url else "?") + "apikey=" + key
        return url
    if key:
        today = datetime.now(timezone.utc).date()
        frm = today.isoformat()
        to = (today + timedelta(days=8)).isoformat()
        return f"{_FMP}?from={frm}&to={to}&apikey={key}"
    return _DEFAULT_FEED  # Forex Factory — often blocked on datacenter IPs


_SECRET_PARAMS = ("apikey", "api_key", "token", "key", "secret", "password")


def _redact(text) -> str:
    """Strip secret query-string values out of anything bound for the logs.

    requests puts the full request URL into the text of an HTTPError, so
    `print(f"...({ex})")` on a failing keyed feed publishes the API key in
    plaintext to the log stream — which is exactly what happened here: a 403
    from the calendar provider wrote the FMP key into Render's logs every 30
    minutes for days. Redacting at the point of logging means no future feed,
    keyed however it likes, can repeat it.
    """
    s = str(text)
    for p in _SECRET_PARAMS:
        # Match `p=<value>` case-insensitively, keeping the delimiter that ends
        # the value (& or whitespace or the closing paren requests adds).
        s = re.sub(rf"({re.escape(p)}=)[^&\s)\"']+", r"\1***", s, flags=re.I)
    return s


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


# Ordered severity, so the news PANEL can show medium-impact releases while the
# trading GUARD keeps standing aside for high impact only. Those are different
# questions and were previously answered by the same test: because only "High"
# ever qualified, and a normal week carries ~8 of those against ~90 low/medium
# ones, the panel was empty on most days by design rather than by fault.
_RANK = {"low": 1, "1": 1, "yellow": 1,
         "medium": 2, "2": 2, "orange": 2, "moderate": 2,
         "high": 3, "3": 3, "red": 3}


def _impact_rank(val) -> int:
    s = str(val).strip().lower()
    if s in _RANK:
        return _RANK[s]
    for word, rank in (("high", 3), ("medium", 2), ("moderate", 2), ("low", 1)):
        if word in s:
            return rank
    return 0  # unknown/holiday markers — never surfaced, never guarded against


def _clean(v):
    """Feed values are strings and blanks are '' rather than absent."""
    s = str(v).strip() if v is not None else ""
    return s or None


def _do_fetch():
    """Fetch + parse the calendar. Runs on a background thread so it can NEVER
    block the trading loop. Updates the shared cache on success; applies
    exponential back-off on failure so a down feed isn't hammered every tick."""
    try:
        r = requests.get(_feed_url(), headers={"User-Agent": "ApexBot/1.0"}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else (data.get("events") or data.get("result") or [])
        events = []
        for e in rows:
            if not isinstance(e, dict):
                continue
            events.append({
                "title": e.get("title") or e.get("event") or "Economic event",
                "currency": _norm_ccy(e.get("country") or e.get("currency") or ""),
                "impact": e.get("impact") or e.get("importance"),
                "time": e.get("date") or e.get("time") or e.get("datetime"),
                # Carried through for the Mini App's news panel. The guard has
                # no use for them, but throwing them away here meant the panel
                # could only ever say THAT a release was due, never what the
                # market expected of it.
                "forecast": _clean(e.get("forecast") or e.get("estimate")),
                "previous": _clean(e.get("previous")),
                "actual": _clean(e.get("actual")),
            })
        with _lock:
            _cache["events"] = events
            _cache["ts"] = time.time()
            _state["fails"] = 0
            _state["next_retry"] = 0.0
        # Silence is not success. A 200 that parses to nothing looks exactly
        # like a healthy feed from the outside — no exception, no log line, and
        # every downstream consumer just sees "no events". Say what happened
        # either way, so a feed that answers but carries nothing is visible.
        host = _feed_url().split("/")[2] if "//" in _feed_url() else "?"
        if events:
            highs = sum(1 for e in events if _impact_high(e.get("impact")))
            print(f"[NEWS] calendar ok — {len(events)} events "
                  f"({highs} high-impact) from {host}")
        else:
            shape = (f"list[{len(data)}]" if isinstance(data, list)
                     else f"{type(data).__name__}"
                     + (f" keys={sorted(data)[:6]}" if isinstance(data, dict) else ""))
            print(f"[NEWS] calendar answered 200 but parsed to ZERO events "
                  f"from {host} — payload was {_redact(shape)}. Macro risk "
                  f"stays unknown; the guard fail-opens.")
    except Exception as ex:
        with _lock:
            _state["fails"] += 1
            backoff = min(_TTL, 60 * (2 ** (_state["fails"] - 1)))
            _state["next_retry"] = time.time() + backoff
        # Fail-open: keep any stale cache; if empty it stays empty → the guard
        # reports "no event" and trading continues normally.
        print(f"[NEWS] feed unavailable ({_redact(ex)}) — guard fail-open, "
              f"retry in ~{int(backoff)}s")
    finally:
        with _lock:
            _state["fetching"] = False


def _load():
    """Return the cached events immediately — NEVER blocks on the network.

    When the cache is stale (and no fetch is in flight and we're past the
    back-off window), kick off a background refresh and return whatever we have
    right now. The very first call, before any successful fetch, returns [] →
    the news guard fail-opens and trading proceeds; fresh data lands on a later
    tick once the background fetch completes."""
    now = time.time()
    with _lock:
        # Freshness is about WHEN we last asked, not whether the answer had
        # anything in it. Keying it on `bool(events)` meant an empty-but-
        # successful fetch was never fresh: the success path resets next_retry
        # to 0, so every single call spawned another fetch thread, forever, at
        # one network round-trip per tick per symbol. An empty answer is still
        # an answer and holds for the TTL like any other.
        fresh = _cache["ts"] > 0 and now - _cache["ts"] < _TTL
        should_fetch = not fresh and not _state["fetching"] and now >= _state["next_retry"]
        if should_fetch:
            _state["fetching"] = True
        events = list(_cache["events"])
    if should_fetch:
        threading.Thread(target=_do_fetch, name="news-refresh", daemon=True).start()
    return events


def has_data():
    """True when the calendar actually holds events right now.

    high_impact_window() returns None both for "no event is near" and for "the
    feed is dead and we know nothing", which is the right fail-open answer for
    a trading guard — absent data must not block a trade. It is the wrong
    answer for anything that wants to RECORD the absence of macro risk as an
    observation: a 403 from the calendar provider would otherwise be published
    as the confident fact that no releases are due.

    Callers that need to tell the two apart check this first.
    """
    try:
        return bool(enabled() and _load())
    except Exception:
        return False


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


def today(currencies=None, limit=12):
    """High-impact events for TODAY (UTC) — both already-released and still
    upcoming, in chronological order. `mins` is negative for a released event
    (minutes ago) and positive for one still to come (for the Mini App's
    'today's news' view — a same-day recap, not just what's coming up).
    Fail-open like every other lookup here."""
    try:
        now = datetime.now(timezone.utc)
        today_str = now.date().isoformat()
        curset = {str(c).upper() for c in currencies} if currencies else None
        out = []
        for e in _load():
            if not _impact_high(e.get("impact")):
                continue
            if curset and e.get("currency") not in curset:
                continue
            t = _parse_time(e.get("time"))
            # .date() on a tz-aware datetime is the date in ITS OWN offset. The
            # calendar publishes New York time (-04:00), so an event at 21:30
            # on the 19th is 01:30 UTC on the 20th — genuinely today — and was
            # dropped because "2026-08-19" != "2026-08-20". Everything between
            # 20:00 and midnight New York was misfiled by a day, every day.
            if not t or t.astimezone(timezone.utc).date().isoformat() != today_str:
                continue
            mins = int((t - now).total_seconds() / 60.0)
            out.append({"title": e["title"], "currency": e["currency"],
                        "mins": mins, "released": mins <= 0, "time": e["time"]})
        out.sort(key=lambda x: x["mins"])
        return out[:limit]
    except Exception:
        return []


def feed(currencies=None, back_hours=12, ahead_hours=36, limit=14, min_rank=2):
    """Economic events for the Mini App's news panel.

    Deliberately different from `upcoming()` and `today()`, which serve the
    trading guard and answer "is a high-impact release near?". A panel answers
    "what is going on?", so this one:

      * spans a ROLLING window (last `back_hours` → next `ahead_hours`) instead
        of a calendar day, so it still has something to show at 06:00 UTC when
        the day's releases are all still ahead and yesterday's are all behind;
      * includes MEDIUM impact by default, not high alone — a normal week holds
        roughly 8 high-impact events against 90 low/medium ones, so a
        high-only panel is empty on most days;
      * carries forecast/previous/actual, so a release reads as a number the
        market expected rather than just a name.

    `mins` is negative for a released event and positive for one still to come.
    `guarded` marks the ones the bot actually stands aside for, so the panel
    never implies the bot reacts to every line on it. Fail-open like the rest
    of this module: any error yields an empty list, never an exception.
    """
    try:
        now = datetime.now(timezone.utc)
        curset = {str(c).upper() for c in currencies} if currencies else None
        win = window_min()
        out = []
        for e in _load():
            rank = _impact_rank(e.get("impact"))
            if rank < min_rank:
                continue
            if curset and e.get("currency") not in curset:
                continue
            t = _parse_time(e.get("time"))
            if not t:
                continue
            mins = int((t - now).total_seconds() / 60.0)
            if not (-abs(back_hours) * 60 <= mins <= abs(ahead_hours) * 60):
                continue
            out.append({
                "title": e.get("title"),
                "currency": e.get("currency"),
                "impact": "high" if rank >= 3 else "medium",
                "mins": mins,
                "released": mins <= 0,
                "time": e.get("time"),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
                "actual": e.get("actual"),
                # True only where the guard would genuinely hold the bot back.
                "guarded": bool(enabled() and rank >= 3 and abs(mins) <= win),
            })
        out.sort(key=lambda x: x["mins"])
        return out[:limit]
    except Exception:
        return []
