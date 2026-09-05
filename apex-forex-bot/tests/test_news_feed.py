"""The Mini App's news panel was empty every single day. Two reasons.

1. `today()` compared a New-York-local date against a UTC one. The calendar
   publishes times like 2026-08-19T21:30:00-04:00, and `.date()` on a
   tz-aware datetime is the date in ITS OWN offset — so an event at 01:30 UTC
   on the 20th read as "2026-08-19" and was dropped from the 20th. Everything
   between 20:00 and midnight New York was misfiled by a day, every day.

2. Only HIGH impact was ever eligible. A normal week carries ~8 high-impact
   releases against ~90 low/medium ones, and plenty of days have zero. That is
   the right rule for the trading GUARD, which stands the bot aside for events
   that blow spreads out — and the wrong one for a PANEL, whose job is to say
   what is going on.

The guard's own behaviour must not move: this file pins that `upcoming()` and
`high_impact_window()` still see high impact only, so widening the panel can
never widen what the bot refuses to trade through.

Run: python tests/test_news_feed.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-news-")

from apex import news  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def at(minutes_from_now, offset_hours=-4):
    """An event time expressed in the feed's own offset, like the real one."""
    tz = timezone(timedelta(hours=offset_hours))
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).astimezone(tz).isoformat()


def seed(events):
    """Plant a calendar directly in the cache, fresh, so nothing is fetched."""
    import time as _t
    news._cache["events"] = events
    news._cache["ts"] = _t.time()
    news._state["fails"] = 0
    news._state["next_retry"] = 0.0


print("\n🧪 NEWS PANEL — it must actually have something to show\n")

print("1. The timezone bug that hid events from their own day")
# An early-UTC time today, written as the PREVIOUS day in the feed's -04:00
# offset — that mismatch is the bug this guards.
#
# The hour is derived from the clock rather than pinned at 01:30, because the
# assertion below also requires the event to have HAPPENED. A fixed 01:30 is
# still in the future whenever this runs between midnight and 01:30 UTC, so
# the check failed for ninety minutes a day and said the code was broken when
# it was the fixture that was. Pick the latest instant that is both today and
# already past, capped inside the early-UTC window so the -04:00 rendering
# still lands on the previous day.
now = datetime.now(timezone.utc)
_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
utc_early = min(max(_midnight, now - timedelta(minutes=5)),
                _midnight + timedelta(hours=3, minutes=59))
seed([{"title": "Employment Change", "currency": "AUD", "impact": "High",
       "time": utc_early.astimezone(timezone(timedelta(hours=-4))).isoformat(),
       "forecast": "11.7K", "previous": "76.3K", "actual": None}])
got = news.today()
check("an early-UTC event counts as today, not yesterday",
      len(got) == 1 and got[0]["title"] == "Employment Change",
      f"got {got} — the feed wrote it as {utc_early.astimezone(timezone(timedelta(hours=-4)))}")
check("and it is marked released, not upcoming",
      bool(got) and got[0]["released"] is True)

print("\n2. The panel includes medium impact; the guard still does not")
seed([
    {"title": "Unemployment Claims", "currency": "USD", "impact": "Medium",
     "time": at(90), "forecast": "210K", "previous": "209K", "actual": None},
    {"title": "Services Index", "currency": "NZD", "impact": "Low",
     "time": at(60), "forecast": None, "previous": "50.6", "actual": None},
    {"title": "CPI y/y", "currency": "GBP", "impact": "High",
     "time": at(300), "forecast": "2.1%", "previous": "2.4%", "actual": None},
])
feed = news.feed()
titles = [e["title"] for e in feed]
check("medium-impact release is shown", "Unemployment Claims" in titles, titles)
check("high-impact release is shown", "CPI y/y" in titles, titles)
check("low-impact noise is left out", "Services Index" not in titles, titles)
check("each row carries its impact", {e["impact"] for e in feed} == {"medium", "high"},
      [e["impact"] for e in feed])
check("forecast and previous survive the fetch",
      any(e["forecast"] == "210K" and e["previous"] == "209K" for e in feed))

# The guard is the whole reason impact matters. It must not have widened.
check("upcoming() still sees high impact only",
      [e["title"] for e in news.upcoming(hours=24)] == ["CPI y/y"],
      news.upcoming(hours=24))
check("the medium release does not halt trading",
      news.high_impact_window(["USD"], window=180) is None,
      "a medium-impact event must never stand the bot aside")
check("the high one still does",
      (news.high_impact_window(["GBP"], window=400) or {}).get("title") == "CPI y/y")

print("\n3. A rolling window, so a quiet morning is not a blank screen")
seed([
    {"title": "Released hours ago", "currency": "USD", "impact": "High",
     "time": at(-240), "forecast": None, "previous": None, "actual": "3.1%"},
    {"title": "Later today", "currency": "EUR", "impact": "Medium",
     "time": at(600), "forecast": None, "previous": None, "actual": None},
    {"title": "Next week", "currency": "USD", "impact": "High",
     "time": at(60 * 24 * 5), "forecast": None, "previous": None, "actual": None},
])
feed = news.feed()
titles = [e["title"] for e in feed]
check("a release from four hours ago is still listed", "Released hours ago" in titles, titles)
check("something later today is listed", "Later today" in titles, titles)
check("next week is not", "Next week" not in titles, titles)
check("released events sort before upcoming ones",
      [e["mins"] for e in feed] == sorted(e["mins"] for e in feed))
check("an actual figure is carried once published",
      any(e["actual"] == "3.1%" for e in feed))

print("\n4. 'The bot stands aside' is claimed only where it is true")
seed([
    {"title": "Near high", "currency": "USD", "impact": "High",
     "time": at(10), "forecast": None, "previous": None, "actual": None},
    {"title": "Far high", "currency": "USD", "impact": "High",
     "time": at(600), "forecast": None, "previous": None, "actual": None},
    {"title": "Near medium", "currency": "USD", "impact": "Medium",
     "time": at(10), "forecast": None, "previous": None, "actual": None},
])
by = {e["title"]: e for e in news.feed()}
check("a high-impact release inside the window is guarded",
      by.get("Near high", {}).get("guarded") is True)
check("a high-impact release hours away is not",
      by.get("Far high", {}).get("guarded") is False)
check("a nearby medium-impact release is not",
      by.get("Near medium", {}).get("guarded") is False,
      "the panel would otherwise promise behaviour the bot does not have")

print("\n5. Nothing here can throw at the caller")
news._cache["events"] = [{"impact": "High", "time": "not-a-date"}, "garbage", None]
check("a malformed calendar yields an empty panel, not an exception",
      news.feed() == [] and news.today() == [] and news.upcoming() == [])

print("\n6. The panel is actually wired end to end")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()
check("the API sends the feed", '"newsFeed": news_feed' in BOT)
check("built from news.feed(), not the guard's view", "news_mod.feed()" in BOT)
check("the page reads it", "d.newsFeed" in HTML)
check("a page cached from before still renders",
      '"newsToday": news_today' in BOT and "d.newsToday" in HTML)
check("impact is shown to the reader", "'HIGH'" in HTML and "'MED'" in HTML)
check("expected/previous figures are shown", "'exp '" in HTML and "'prev '" in HTML)
check("the stand-aside note is conditional on e.guarded", "e.guarded?" in HTML)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the news panel has something to say.")
