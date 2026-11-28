"""A LIVE account takes no NEW entry while the economic calendar is unavailable.

The news guard is fail-open by design: a dead feed answers "no event" and
trading carries on. Failing closed "around the high-impact windows" is not
possible without the data that says where those windows are, so on a live
account the rule is simpler: no calendar (never fetched, empty, or stale) ->
no new live entry. Demo behaviour is unchanged.

Run: python tests/test_news_live_stale.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ["PAPER_TRADING"] = "true"

from apex import news  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


EV = [{"title": "CPI", "currency": "USD", "impact": "High",
       "time": "2026-10-29T12:30:00+00:00"}]
_saved = (dict(news._cache), dict(news._state), os.environ.get("NEWS_GUARD"))
# Never touch the network from this test: a pending "fetch" blocks refreshes.
news._state["fetching"] = True
try:
    os.environ["NEWS_GUARD"] = "true"
    now = time.time()

    print("\n1. calendar_status")
    news._cache.update(ts=0.0, events=[])
    st, _ = news.calendar_status(now=now)
    check("never fetched -> unavailable", st == "unavailable", st)

    news._cache.update(ts=now - 60, events=[])
    st, _ = news.calendar_status(now=now)
    check("fetched but parsed to nothing -> empty", st == "empty", st)

    news._cache.update(ts=now - 60, events=list(EV))
    st, age = news.calendar_status(now=now)
    check("fresh with events -> ok", st == "ok", st)
    check("...with its age", age is not None and 55 <= age <= 65, str(age))

    news._cache.update(ts=now - news.STALE_S - 5, events=list(EV))
    st, _ = news.calendar_status(now=now)
    check("older than STALE_S -> stale", st == "stale", st)
    check("STALE_S is bounded (<= 12h)", 0 < news.STALE_S <= 12 * 3600)

    os.environ["NEWS_GUARD"] = "false"
    st, _ = news.calendar_status(now=now)
    check("operator-disabled guard -> disabled", st == "disabled", st)
    os.environ["NEWS_GUARD"] = "true"

    print("\n2. live_entry_block")
    news._cache.update(ts=0.0, events=[])
    why = news.live_entry_block(live=True)
    check("live + no calendar -> blocked, with a reason",
          bool(why) and "calendar" in why.lower(), str(why))
    check("demo + no calendar -> not blocked (unchanged fail-open)",
          news.live_entry_block(live=False) is None)
    news._cache.update(ts=time.time() - 60, events=list(EV))
    check("live + fresh calendar -> not blocked",
          news.live_entry_block(live=True) is None)
    news._cache.update(ts=time.time() - news.STALE_S - 5, events=list(EV))
    check("live + stale calendar -> blocked",
          news.live_entry_block(live=True) is not None)
    os.environ["NEWS_GUARD"] = "false"
    check("operator-disabled guard does not block (an explicit operator choice)",
          news.live_entry_block(live=True) is None)
    os.environ["NEWS_GUARD"] = "true"

    print("\n3. The loop asks it for live entries, inside the news guard")
    with open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8") as fh:
        SRC = fh.read()
    i_guard = SRC.find("ev = news.high_impact_window(_currency_legs(symbol))")
    i_live = SRC.find("news.live_entry_block(live=_is_live_cfg(cfg))")
    check("the loop calls live_entry_block", i_live > 0)
    check("...next to the news guard", i_guard > 0 and abs(i_live - i_guard) < 2500,
          f"{i_guard} vs {i_live}")
    check("...and refuses the entry", "entry_ok = False" in SRC[i_live:i_live + 400])
finally:
    news._cache.clear(); news._cache.update(_saved[0])
    news._state.clear(); news._state.update(_saved[1])
    if _saved[2] is None:
        os.environ.pop("NEWS_GUARD", None)
    else:
        os.environ["NEWS_GUARD"] = _saved[2]

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - no live entry is taken blind to the calendar.")
