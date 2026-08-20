"""The calendar has to reach out, not wait to be opened.

NEWS_WARN already existed, but it only fires when a setup was actually
refused — so on a day the bot finds no trade at all, a release the client
cares about passes in total silence. These two messages fire on the release
itself: a heads-up while it is still ahead, and the all-clear once it passes.

The thing to protect here is volume, which is the whole reason alert_policy
exists. A normal week carries ~8 high-impact releases against ~90 low/medium
ones, and a client who is pushed all 98 stops reading the two that mattered.
So the push is high-impact only — deliberately NARROWER than the Mini App's
panel, which shows medium too because a panel is read on purpose and a push
interrupts — and scoped to the currencies this client actually trades.

The other risk is repetition. Render runs two containers during a deploy and
both tick the same account, so dedupe has to be a cross-process claim, not
in-process state.

Run: python tests/test_news_alerts.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-newsalert-")

from apex import news, news_alerts, alert_policy  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def at(minutes_from_now):
    """An event time in the feed's own -04:00 offset, like the real calendar."""
    tz = timezone(timedelta(hours=-4))
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).astimezone(tz).isoformat()


def seed(events):
    import time as _t
    news._cache["events"] = events
    news._cache["ts"] = _t.time()
    news._state["fails"] = 0
    news._state["next_retry"] = 0.0


def ev(title, ccy, mins, impact="High", forecast=None, previous=None):
    return {"title": title, "currency": ccy, "impact": impact, "time": at(mins),
            "forecast": forecast, "previous": previous, "actual": None}


LEAD = news.window_min()
ON = {"news_alerts": True}

print("\n🧪 NEWS PUSH — the calendar reaches out, exactly twice per release\n")

print("1. A heads-up goes out while the release is still ahead")
seed([ev("FOMC Statement", "USD", LEAD - 5, forecast="4.25%", previous="4.50%")])
got = news_alerts.due("u1", ["USD", "EUR"], user=ON)
check("one message", len(got) == 1, got)
check("it is the heads-up", bool(got) and got[0]["action"] == "NEWS_AHEAD", got)
check("it carries the event", bool(got) and got[0]["event"]["title"] == "FOMC Statement")
check("with the figures the market expects",
      bool(got) and got[0]["event"]["forecast"] == "4.25%")

print("\n2. It is said once, however many times the loop ticks")
again = news_alerts.due("u1", ["USD", "EUR"], user=ON)
check("the second tick is silent", again == [], again)
check("and the third", news_alerts.due("u1", ["USD", "EUR"], user=ON) == [], "dedupe leaked")
check("a DIFFERENT client still gets their own copy",
      len(news_alerts.due("u2", ["USD"], user=ON)) == 1,
      "the claim must be per client, not global")

print("\n3. Scope: only what this client trades, only what moves the market")
seed([
    ev("CPI y/y", "GBP", LEAD - 5),
    ev("Unemployment Claims", "USD", LEAD - 5, impact="Medium"),
    ev("Services Index", "NZD", LEAD - 5, impact="Low"),
])
got = news_alerts.due("u3", ["GBP", "USD", "NZD"], user=ON)
titles = [m["event"]["title"] for m in got]
check("high impact is pushed", "CPI y/y" in titles, titles)
check("medium impact is NOT pushed", "Unemployment Claims" not in titles,
      "the panel shows medium; a push must not")
check("low impact is NOT pushed", "Services Index" not in titles, titles)
seed([ev("CPI y/y", "GBP", LEAD - 5)])
check("a currency this client does not trade is skipped",
      news_alerts.due("u4", ["USD", "JPY"], user=ON) == [])

print("\n4. Timing: not too early, not after the fact")
seed([ev("NFP", "USD", LEAD + 120)])
check("hours out is too early to interrupt", news_alerts.due("u5", ["USD"], user=ON) == [])
seed([ev("NFP", "USD", LEAD - 1)])
check("inside the guard window it fires",
      len(news_alerts.due("u6", ["USD"], user=ON)) == 1)
check("the lead matches the guard's own window, so the message is true",
      news_alerts.lead_min() == news.window_min())

print("\n5. The all-clear only follows a heads-up that was actually sent")
# The clock has to advance across a release for this, and the release keeps
# its scheduled time while `mins` counts down — which is exactly what makes
# the event id stable. Driving `news.feed` directly is the only way to walk a
# single event through its whole life inside one test run; re-seeding with a
# new time would silently be a DIFFERENT event, which is what an earlier
# version of this test did, and it passed for the wrong reason.
_real_feed = news.feed
FIXED_TIME = "2026-08-20T14:00:00-04:00"


def clock(mins, ccy="EUR", title="Rate Decision"):
    """Pin one release, at one scheduled time, `mins` away from now."""
    news.feed = lambda currencies=None, **kw: (
        [{"title": title, "currency": ccy, "impact": "high", "mins": mins,
          "released": mins <= 0, "time": FIXED_TIME, "forecast": None,
          "previous": None, "actual": None, "guarded": abs(mins) <= LEAD}]
        if (currencies is None or ccy in currencies) else [])


try:
    clock(LEAD - 5)
    first = news_alerts.due("u7", ["EUR"], user=ON)
    check("heads-up sent", len(first) == 1 and first[0]["action"] == "NEWS_AHEAD", first)

    clock(-(LEAD - 5))          # released, but the guard is still holding
    check("no all-clear while the bot is still standing aside",
          news_alerts.due("u7", ["EUR"], user=ON) == [])

    clock(-(LEAD + 10))         # the guard has let go
    after = news_alerts.due("u7", ["EUR"], user=ON)
    check("the all-clear follows once the window passes",
          len(after) == 1 and after[0]["action"] == "NEWS_CLEAR", after)
    check("it names the same release",
          bool(after) and after[0]["event"]["title"] == "Rate Decision")
    check("and it is said only once",
          news_alerts.due("u7", ["EUR"], user=ON) == [])

    # A client who never heard about the pause must not hear that it ended.
    check("a release we never announced stays silent",
          news_alerts.due("u8", ["EUR"], user=ON) == [],
          "'back to trading' for a pause nobody was told about explains nothing")

    print("\n6. The whole life of one release is two messages, never three")
    sent = []
    for m in (LEAD + 30, LEAD + 5, LEAD - 1, 5, 0, -5, -LEAD, -(LEAD + 5), -120):
        clock(m, ccy="CHF", title="CPI y/y")
        sent += [x["action"] for x in news_alerts.due("u9", ["CHF"], user=ON)]
    check("exactly one heads-up and one all-clear, in that order",
          sent == ["NEWS_AHEAD", "NEWS_CLEAR"], sent)
finally:
    news.feed = _real_feed

print("\n7. The client can switch it off")
seed([ev("FOMC Statement", "USD", LEAD - 5)])
check("opted out means silence",
      news_alerts.due("u10", ["USD"], user={"news_alerts": False}) == [])
check("the default is on", news_alerts.enabled_for({}) is True)
check("the guard's own setting is a different switch",
      news_alerts.enabled_for({"news_filter": False}) is True,
      "news_filter decides whether the bot pauses, not whether it speaks")

print("\n8. A notification path must never break the trading loop")
news._cache["events"] = [{"impact": "High", "time": "not-a-date"}, "garbage", None]
check("a malformed calendar is silent, not fatal",
      news_alerts.due("u11", ["USD"], user=ON) == [])
check("no currencies is silent", news_alerts.due("u12", [], user=ON) == [])
check("a missing user record is silent, not a crash",
      isinstance(news_alerts.due("u13", ["USD"], user=None), list))

print("\n9. Message identity is stable across restarts and feed refreshes")
a = news_alerts.event_id({"currency": "USD", "title": "NFP", "time": "2026-08-20T12:30:00-04:00"})
b = news_alerts.event_id({"currency": "USD", "title": "NFP", "time": "2026-08-20T12:30:00-04:00"})
c = news_alerts.event_id({"currency": "USD", "title": "CPI", "time": "2026-08-20T12:30:00-04:00"})
check("the same release hashes the same", a == b)
check("a different release does not", a != c)

print("\n10. Wired end to end")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
CA = open(os.path.join(ROOT, "apex", "control_actions.py"), encoding="utf-8").read()
check("the trading loop scans the calendar", "news_alerts.due(" in LOOP)
check("and imports it", "news_alerts" in LOOP.split("while True:")[0])
check("Telegram renders both messages", 'action in ("NEWS_AHEAD", "NEWS_CLEAR")' in TG)
check("both are classified, so neither is silently swallowed",
      alert_policy.tier("NEWS_AHEAD") == "useful"
      and alert_policy.tier("NEWS_CLEAR") == "useful")
check("a normal client receives them",
      alert_policy.allowed("NEWS_AHEAD", {}) and alert_policy.allowed("NEWS_CLEAR", {}))
check("/news on|off is routed with its argument", "_handle_news(chat_id, args)" in TG)
check("the toggle is remotely settable", '"news_alerts",' in CA)
check("and typed as a bool, so \"false\" does not read as True",
      '"news_alerts"' in CA.split("_BOOL_KEYS")[1].split("}")[0])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the calendar speaks, twice, and no more.")
