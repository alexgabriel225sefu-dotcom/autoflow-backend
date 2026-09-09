"""API keys must never reach the log stream.

requests embeds the full request URL in the text of an HTTPError. The news
collector logged that text directly:

    print(f"[NEWS] feed unavailable ({ex}) — guard fail-open, ...")

so every failed fetch of a keyed feed published the key in plaintext. It was
not hypothetical: FMP retired /api/v3/economic_calendar on 2025-08-31 and
answers 403 to every key issued after that date, so the bot wrote its own FMP
key into Render's logs every 30 minutes, for days, in a line that looks like a
harmless connectivity warning.

The fix redacts at the point of logging rather than at one call site, so a
future feed keyed some other way cannot repeat it.

Run: python tests/test_news_redaction.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import news  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SECRET = "3RQ54sLwiXnwC9BM5W7fxcz8Hb5fD3l3"

print("\n── the exact line that was leaking in production ──")
real = ("403 Client Error: Forbidden for url: "
        "https://financialmodelingprep.com/api/v3/economic_calendar"
        f"?from=2026-08-13&to=2026-08-21&apikey={SECRET}")
out = news._redact(real)
check("the key is gone", SECRET not in out, out)
check("the parameter name survives so the line stays diagnosable",
      "apikey=***" in out, out)
check("the rest of the URL is intact",
      "from=2026-08-13" in out and "to=2026-08-21" in out, out)
check("the status code is still readable", out.startswith("403 Client Error"), out)

print("\n── other ways a feed might carry a credential ──")
for raw, secret in (
    ("GET https://x.io/v1?apiKey=abc123&q=1", "abc123"),
    ("timeout for url: https://x.io/?token=zzz999)", "zzz999"),
    ("https://x.io/?api_key=v3ry-s3cret then some prose", "v3ry-s3cret"),
    ("https://x.io/?secret=p4ss", "p4ss"),
    ("https://x.io/?password=hunter2&x=1", "hunter2"),
    ("https://x.io/?key=K1&apikey=K2", "K1"),
):
    r = news._redact(raw)
    check(f"{secret!r} redacted", secret not in r, r)

print("\n── redaction must not eat anything else ──")
clean = "403 Client Error: Forbidden for url: https://nfs.faireconomy.media/ff.json"
check("a key-less URL is passed through byte-for-byte",
      news._redact(clean) == clean, news._redact(clean))
check("plain prose is untouched",
      news._redact("connection reset by peer") == "connection reset by peer")
check("an exception object is accepted, not just a string",
      SECRET not in news._redact(RuntimeError(real)))
check("redacting twice changes nothing",
      news._redact(news._redact(real)) == news._redact(real))

print("\n── the free feed is the default when no key is set ──")
for var in ("NEWS_API_KEY", "NEWS_FEED_URL"):
    os.environ.pop(var, None)
check("falls back to Forex Factory", news._feed_url() == news._DEFAULT_FEED,
      news._feed_url())
check("no apikey parameter is appended", "apikey" not in news._feed_url(),
      news._feed_url())

print("\n── with a key set, the URL carries it but the LOG never does ──")
os.environ["NEWS_API_KEY"] = SECRET
url = news._feed_url()
check("the real request still gets the key", SECRET in url)
check("and FMP's live endpoint is used, not the retired v3 one",
      "/stable/economic-calendar" in url and "/api/v3/" not in url, url)
check("but logging that URL redacts it", SECRET not in news._redact(url),
      news._redact(url))
os.environ.pop("NEWS_API_KEY", None)


# ── silence is not success ──────────────────────────────────────────────
# Appended: the leak fix above was only half the story. Chasing why
# macro_risk never appeared turned up two bugs that make a feed which
# answers 200 with nothing in it indistinguishable from a healthy one.
print("\n── a 200 that parses to zero events must SAY so ──")

import io                          # noqa: E402
import contextlib                  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def fetch_with(payload):
    """Run one _do_fetch against a canned payload, return what it printed."""
    news._cache["events"] = []
    news._cache["ts"] = 0.0
    news._state.update({"fetching": False, "fails": 0, "next_retry": 0.0})
    real_get = news.requests.get
    news.requests.get = lambda *a, **k: FakeResp(payload)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            news._do_fetch()
    finally:
        news.requests.get = real_get
    return buf.getvalue()


out = fetch_with([])
check("an empty list is reported, not swallowed", "ZERO events" in out, out.strip())
check("and the shape is named so it can be diagnosed", "list[0]" in out, out.strip())

out = fetch_with({"message": "upgrade your plan"})
check("a dict payload is reported too", "ZERO events" in out, out.strip())
check("its keys are shown", "message" in out, out.strip())

good = [{"title": "Core CPI m/m", "country": "USD", "impact": "High",
         "date": "2026-08-12T08:30:00-04:00"},
        {"title": "Bank Lending", "country": "JPY", "impact": "Low",
         "date": "2026-08-09T19:50:00-04:00"}]
out = fetch_with(good)
check("a healthy fetch reports its counts", "2 events" in out, out.strip())
check("including how many are high-impact", "1 high-impact" in out, out.strip())
check("and does NOT cry zero", "ZERO" not in out, out.strip())

print("\n── an empty answer is still an answer (no refetch storm) ──")
# Before: fresh = bool(events) and ..., so an empty-but-successful fetch was
# never fresh, and the success path had reset next_retry to 0 — every _load()
# spawned another thread, one round-trip per tick per symbol, forever.
spawned = []
real_thread = news.threading.Thread


class CountingThread:
    def __init__(self, *a, **k):
        spawned.append(k.get("name"))

    def start(self):
        pass


news._cache["events"] = []
news._cache["ts"] = __import__("time").time()   # just fetched, came back empty
news._state.update({"fetching": False, "fails": 0, "next_retry": 0.0})
news.threading.Thread = CountingThread
try:
    for _ in range(25):
        news._load()
finally:
    news.threading.Thread = real_thread
check("25 loads after an empty fetch spawn no refetches", spawned == [],
      f"{len(spawned)} spawned")

# A stale cache must still refresh — the fix must not freeze the feed.
news._cache["ts"] = __import__("time").time() - (news._TTL + 1)
news.threading.Thread = CountingThread
try:
    news._load()
finally:
    news.threading.Thread = real_thread
check("but once the TTL expires it does refetch", len(spawned) == 1,
      f"{len(spawned)} spawned")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL NEWS CHECKS PASSED.")
