"""The Mini App may only ever show you your own account, and your own past.

Three properties, each with a concrete way of going wrong:

  IDENTITY   the chat id comes from Telegram's signed initData. If it could
             come from a query parameter, every account is one edited URL away.

  OWNERSHIP  a trade id is resolved inside ONE user's journal. If ids were
             looked up globally, changing a digit would open somebody else's
             trade — the classic IDOR, and the spec calls it out by name.

  HONESTY    the replay must draw the market AROUND THE TRADE. Anchored to
             "now" instead, the chart still renders and the markers still land
             on candles — they are just the wrong ones, and nothing looks
             broken. That is the failure worth a test.

Run: python tests/test_miniapp.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-miniapp-")

from apex import account_mode, miniapp_api as api, user_store, webapp  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


BOT_TOKEN = "123456:TESTTOKEN"


def signed_init(user_id):
    """A genuine Telegram initData string for `user_id`."""
    pairs = {"auth_date": str(int(time.time())),
             "query_id": "AAA",
             "user": json.dumps({"id": user_id, "first_name": "T"})}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


print("\n🧪 APEX MINI APP — identity, ownership, honesty\n")

print("1. Identity comes from a signature, not from a parameter")
ok = webapp.validate(signed_init(555), BOT_TOKEN)
check("valid initData resolves the user", (ok or {}).get("id") == 555, str(ok))
tampered = signed_init(555).replace("%22id%22%3A+555", "%22id%22%3A+999")
check("tampering with the user id invalidates it",
      webapp.validate(tampered, BOT_TOKEN) is None)
check("a wrong bot token invalidates it",
      webapp.validate(signed_init(555), "other:token") is None)
check("missing initData is refused", webapp.validate("", BOT_TOKEN) is None)
check("garbage initData is refused", webapp.validate("not-a-query", BOT_TOKEN) is None)
check("initData with no hash is refused",
      webapp.validate("user=%7B%22id%22%3A1%7D", BOT_TOKEN) is None)

print("\n2. Trade ids are stable — never the array index")
A = {"positionId": 987654, "time": "2026-08-12 10:41:00", "symbol": "EURUSD",
     "entry": 1.08420, "exit": 1.08620, "netPnl": 38.20,
     "openedAt": "2026-08-12 09:14:02", "side": "BUY", "mode": "demo",
     "confidence": 79, "probability": 0.61, "regime": "trending",
     "spreadPips": 0.9, "strategyId": "mean_reversion"}
B = {"time": "2026-08-11 12:00:00", "symbol": "GBPUSD", "entry": 1.29120,
     "exit": 1.29310, "netPnl": -21.40, "openedAt": "2026-08-11 11:00:00",
     "side": "SELL", "mode": "demo"}
check("the broker's positionId is the identity when present",
      api.trade_id(A) == "p987654")
check("a row without one still gets a deterministic id",
      api.trade_id(B) == api.trade_id(dict(B)))
check("...and it is not the index", api.trade_id(B) not in ("0", "1", 0, 1))
check("two different trades get different ids", api.trade_id(A) != api.trade_id(B))
_re = api.trade_id(B)
check("the id survives the list being reordered",
      api.trade_id([B, A][0]) == _re)

print("\n3. History is scoped to one user's own journal")
ME, OTHER = "700001", "700002"
user_store.save(ME, {"paper": True, "active": True})
user_store.save(OTHER, {"paper": True, "active": True})
user_store.clear_trades(ME); user_store.clear_trades(OTHER)
for r in (B, A):
    user_store.append_trade(ME, r)
SECRET = {"positionId": 111222, "time": "2026-08-10 09:00:00", "symbol": "XAUUSD",
          "entry": 2418.20, "exit": 2426.70, "netPnl": 84.10,
          "openedAt": "2026-08-10 08:00:00", "side": "BUY", "mode": "live"}
user_store.append_trade(OTHER, SECRET)

h = api.history(ME)
check("I see my own trades", h["total"] == 2, h["total"])
check("newest first", h["trades"][0]["id"] == api.trade_id(A), h["trades"][0]["id"])
check("I do NOT see the other user's trade",
      all(t["id"] != api.trade_id(SECRET) for t in h["trades"]))
check("the page is bounded", api.history(ME, limit=999)["limit"] <= api.HISTORY_PAGE_MAX)
check("pagination reports more", api.history(ME, limit=1)["hasMore"] is True)
check("an empty journal is not an error", api.history("700999")["total"] == 0)

print("\n4. IDOR — another user's trade id resolves to nothing")
check("I cannot fetch it by id",
      api.find_trade(ME, api.trade_id(SECRET)) is None,
      "this is the whole ownership property")
check("the owner still can",
      (api.find_trade(OTHER, api.trade_id(SECRET)) or {}).get("positionId") == 111222)
check("a forged id resolves to nothing", api.find_trade(ME, "p999999999") is None)
check("an empty id resolves to nothing", api.find_trade(ME, "") is None)


class FakeBroker:
    """Records what the replay asked the broker for."""

    def __init__(self, bars=120):
        self.calls = []
        self._bars = bars

    def get_candles(self, symbol=None, interval=None, limit=None, to_ts=None):
        self.calls.append({"symbol": symbol, "interval": interval,
                           "limit": limit, "to_ts": to_ts})
        step = api._TF_SECONDS[interval]
        end = to_ts or int(time.time())
        return [{"time": end - (self._bars - i) * step, "open": 1.08, "high": 1.09,
                 "low": 1.07, "close": 1.085} for i in range(self._bars)]


import apex.user_loop as _ul  # noqa: E402
_orig_make = _ul._make_broker
fake = FakeBroker()
_ul._make_broker = lambda user: (fake, object())

print("\n5. The replay window is anchored to the TRADE, not to today")
rep = api.replay(ME, api.trade_id(A), "15m")
call = fake.calls[-1]
exit_ts = api._parse_ts(A["time"])
check("the broker was asked for the right symbol", call["symbol"] == "EURUSD")
check("...on the requested timeframe", call["interval"] == "15m")
check("...ending near the trade's EXIT, not now",
      abs(call["to_ts"] - exit_ts) <= api.BARS_AFTER * 900 + 60,
      f"to_ts={call['to_ts']} exit={exit_ts} now={int(time.time())}")
check("...which is far from now (the bug this catches)",
      abs(call["to_ts"] - time.time()) > 86400,
      "a window anchored to now still renders — with the wrong candles")
check("the window is bounded", call["limit"] <= api.MAX_BARS, call["limit"])

print("\n6. Markers come from the stored fill prices, not from candles")
check("entry price is the journal's entry",
      rep["markers"]["entry"]["price"] == A["entry"])
check("exit price is the journal's exit",
      rep["markers"]["exit"]["price"] == A["exit"])
check("entry time is the OPEN time, not the close",
      rep["markers"]["entry"]["time"] == int(api._parse_ts(A["openedAt"])))
check("a winning exit is marked as won", rep["markers"]["exit"]["win"] is True)

print("\n7. The snapshot is read back, never recomputed")
s = rep["snapshot"]
check("confidence as recorded at entry", s["confidence"] == 79)
check("probability as recorded", s["probability"] == 0.61)
check("regime as recorded", s["regime"] == "trending")
check("spread as recorded", s["spreadPips"] == 0.9)
check("strategy as recorded", s["strategyId"] == "mean_reversion")
_b = api.replay(ME, api.trade_id(B), "15m")
check("a trade with no snapshot reports null, not a guess",
      _b["snapshot"]["confidence"] is None and _b["snapshot"]["regime"] is None)

print("\n8. Failures are codes, never stack traces")
for tid, code in ((api.trade_id(SECRET), "TRADE_NOT_FOUND"),
                  ("p000", "TRADE_NOT_FOUND")):
    try:
        api.replay(ME, tid, "15m"); check(f"{code} raised", False, "no error")
    except api.ReplayError as e:
        check(f"another/unknown trade → {code}", e.code == code, e.code)
try:
    api.replay(ME, api.trade_id(A), "7s"); check("invalid tf raised", False)
except api.ReplayError as e:
    check("an unknown timeframe is refused, not substituted",
          e.code == "INVALID_TIMEFRAME", e.code)


def _boom(user):
    raise RuntimeError("cTrader unavailable")


_ul._make_broker = _boom
try:
    api.replay(ME, api.trade_id(A), "15m"); check("broker outage raised", False)
except api.ReplayError as e:
    check("a broker outage is a clean code",
          e.code == "MARKET_DATA_UNAVAILABLE", e.code)
_ul._make_broker = lambda user: (FakeBroker(bars=0), object())
try:
    api.replay(ME, api.trade_id(A), "15m"); check("no bars raised", False)
except api.ReplayError as e:
    check("no bars for that period is a clean code",
          e.code == "MARKET_DATA_UNAVAILABLE", e.code)
_ul._make_broker = _orig_make

MALFORMED = {"symbol": None, "time": None, "netPnl": "x"}
user_store.append_trade(ME, MALFORMED)
check("a malformed row does not break history",
      api.history(ME)["total"] == 3)
try:
    api.replay(ME, api.trade_id(MALFORMED), "15m")
    check("a malformed row is refused", False, "no error")
except api.ReplayError as e:
    check("a malformed row is refused with a code",
          e.code in ("TRADE_INCOMPLETE", "TRADE_NOT_FOUND"), e.code)

print("\n9. DEMO is never shown as LIVE")
check("paper account → SIMULATION",
      account_mode.resolve({"paper": True})[0] == account_mode.SIMULATION)
check("broker-executed on a DEMO cTrader account is NOT live",
      account_mode.resolve({"paper": False, "ctrader_env": "demo",
                            "ctrader_account_id": 1, "ctrader_access_token": "t"},
                           allow_broker=False)[0] == account_mode.DEMO,
      "paper=false used to mean 'live' regardless of the account")
check("a live account is live",
      account_mode.resolve({"paper": False, "ctrader_env": "live",
                            "ctrader_account_id": 1, "ctrader_access_token": "t"},
                           allow_broker=False)[0] == account_mode.LIVE)
check("no linked account → UNVERIFIED",
      account_mode.resolve({"paper": False})[0] == account_mode.UNVERIFIED)
check("UNVERIFIED is not badged as demo OR live",
      account_mode.badge(account_mode.UNVERIFIED) not in
      (account_mode.badge(account_mode.DEMO), account_mode.badge(account_mode.LIVE)))
check("...and is not treated as real money",
      account_mode.is_real_money(account_mode.UNVERIFIED) is False)
check("only a verified LIVE is real money",
      account_mode.is_real_money(account_mode.LIVE) is True
      and account_mode.is_real_money(account_mode.DEMO) is False)

print("\n10. The Mini App cannot trade")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "miniapp_api.py"), encoding="utf-8").read()
for forbidden in ("place_order", "close_position", "authorize_order",
                  "force_trade", "force_close", "amend_sltp"):
    check(f"it never calls {forbidden}", forbidden not in SRC)

print("\n11. The terminal itself shows only real, escaped, backend-supplied data")
HTML = webapp.terminal_html()
BOT_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "apex", "bot.py"), encoding="utf-8").read()
check("it renders the backend's badge verdict", 'id="modeBadge"' in HTML)
check("...and has a distinct class for unverified",
      "unver" in HTML, "an unknown account must not borrow the demo styling")
check("timeframes are selectable", all(f'data-tf="{t}"' in HTML
                                       for t in ("1m", "5m", "15m", "1h", "4h", "1d")))
check("history is a tab", 'data-p="hist"' in HTML)
check("the replay screen exists", 'id="replay"' in HTML and 'id="rPlay"' in HTML)
check("it calls the user-scoped endpoints",
      "/api/app/history" in HTML and "/api/app/replay?trade=" in HTML)
# Every call must still be authenticated — but initData is the credential, so
# it must not be in the URL. This previously asserted the query-string form,
# which is the leak itself written down as a requirement.
check("every call carries initData",
      "'Authorization': 'Telegram ' + initData" in HTML, "the api() helper is unauthenticated")
check("and never in the query string",
      "init='+encodeURIComponent" not in HTML and "'init='" not in HTML,
      "initData is still being appended to a URL")
# Position direction must come from the POSITION, never from whether it is
# winning. The status line originally used a red/green emoji as a PROFIT
# indicator; when those were replaced with "Long"/"Short" for the platform
# rewrite, one of the two code paths kept keying off the P&L sign — so a
# profitable short rendered as "Long SELL". On a trading screen that is the
# kind of error someone acts on.
check("direction is never derived from profit or loss",
      "up?'Long" not in HTML and 'up?"Long' not in HTML,
      "a winning short would display as Long")
check("both status paths read the side from the position",
      HTML.count("side==='BUY'?'Long ':'Short '") >= 2,
      "one of the refresh paths is not using the position's own side")
check("and the P&L wording is separate from the direction",
      "up?'up $':'down $'" in HTML or "fl>=0?'up $':'down $'" in HTML)

check("it never invents market data", "Math.random" not in HTML)
for fake in ("10,142", "12,482", "1.08452"):
    check(f"no hardcoded {fake}", fake not in HTML)
check("untrusted trade text is escaped", "&lt;" in HTML and "esc(" in HTML)
check("the client cannot ask for another account",
      "user_id=" not in HTML and "telegram_id=" not in HTML)
check("a stale feed is visibly stale", "stale" in HTML and "freshness" in HTML)
check("errors are sentences, not stack traces",
      "could not be found" in HTML and "temporarily unavailable" in HTML)

print("\n12. It moves like a terminal, at the broker's own precision")
# The screenshot that prompted this: a GBPUSD entry of 1.36078 rendered as
# "1.36". Lightweight Charts formats to 2 decimals unless told otherwise, so
# the three digits that carry the meaning were being dropped.
check("price precision comes from the broker, not a default",
      "applyPrecision" in HTML and "priceFormat" in HTML)
check("...and the payload carries it", '"digits"' in BOT_SRC and '"pipSize"' in BOT_SRC)
check("prices render at that precision", "toFixed(DIGITS)" in HTML)
check("there is a fast tick endpoint", "/api/app/tick" in HTML and "/api/app/tick" in BOT_SRC)
# The three client-data routes each used to call webapp.validate on a query
# parameter. They now share one helper that reads the header, so the count is
# of routes reaching the gate rather than of copies of the same three lines.
check("the tick is authenticated like every other route",
      BOT_SRC.count("self._telegram_identity()") >= 3,
      "a client-data route is not going through the identity gate")
check("and the verification itself still happens exactly once, in one place",
      BOT_SRC.count("webapp.validate(") == 1)
check("the candle GROWS instead of the series being redrawn",
      "series.update(lastBar)" in HTML and "growBar" in HTML)
check("a stale tick never rewrites a closed bar",
      "never rewrites history" in HTML)
check("the entry line carries the running P&L, cTrader style",
      "entryTitle" in HTML and "refreshEntryLine" in HTML)
check("money settles rather than snapping", "function glide" in HTML)
check("a position closed between refreshes clears immediately",
      "The position closed between full refreshes" in HTML)
check("EVERY open position is returned, not just the focused symbol",
      '"positions": positions_out' in BOT_SRC and "get_all_positions()" in BOT_SRC,
      "the account holds up to maxpos at once")
check("...and the terminal renders all of them", "renderPositions" in HTML)
check("pricing the extra symbols is bounded", "PRICE_BUDGET" in BOT_SRC,
      "this runs once a second; unbounded pricing is a broker call per position")
check("floating sums across positions, not just the focused one",
      "sum(p[\"pnlUsd\"] or 0 for p in positions_out)" in BOT_SRC)
check("only the focused symbol's levels go on the chart",
      "worse than no line at all" in HTML,
      "a GBPUSD stop on a XAUUSD scale is worse than no line")
check("precision is applied even when it equals the default",
      "_precisionSet" in HTML,
      "d===DIGITS short-circuited, and DIGITS defaults to 5 — so 5-digit pairs "
      "never got the format and the axis kept showing 1.36")
check("a single failed poll does not cry outage",
      "failStreak>=3" in HTML and "everLoaded" in HTML)
check("...but a bad login says so straight away",
      "TELEGRAM_AUTH_FAILED" in HTML)
check("the tick is lighter than the full payload",
      "candles" not in BOT_SRC[BOT_SRC.index("/api/app/tick"):BOT_SRC.index("# ── Mini App: history")],
      "the whole point is that it does not ship candles")

print("\n🕒  initData must be FRESH, not merely signed")
# Telegram signs initData once per app open and the page replays that same
# string on every poll, so a captured one authenticated forever — and it
# travels in a URL query string (/api/app/data?init=...), which is exactly
# where strings leak: proxy logs, access logs, browser history, a screenshot
# of a shared link. The holder could read that client's balance, open
# positions and full journal indefinitely.
import time as _time                                        # noqa: E402


def _signed(auth_date=None, omit_date=False):
    pairs = {"user": json.dumps({"id": 7585109158, "first_name": "A"}),
             "query_id": "AAH"}
    if not omit_date:
        pairs["auth_date"] = str(auth_date if auth_date is not None
                                 else int(_time.time()))
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    sec = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(sec, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


_now = int(_time.time())
check("a fresh signature is accepted",
      (webapp.validate(_signed(), BOT_TOKEN) or {}).get("id") == 7585109158)
# The window was 24 hours, and this asserted that a day-old signature still
# worked — "a session open all day must not be logged out". initData IS the
# credential: whoever holds a fresh one can read this client's balance, open
# positions and full trade journal as them, so a day-long window turned a
# single capture into a day of impersonation. It is one hour now, bounded and
# clamped in apex/webapp.py, and the checks follow the real window rather than
# a fixed number so they keep meaning something if it is tuned again.
_WINDOW = webapp._MAX_AGE_S
check("the production window is an hour, not a day",
      _WINDOW <= 3600, f"window is {_WINDOW}s")
check("a signature from inside the window still works",
      (webapp.validate(_signed(_now - int(_WINDOW * 0.5)), BOT_TOKEN) or {}).get("id")
      == 7585109158, "a live terminal session must not be logged out mid-use")
check("one just inside the edge works",
      (webapp.validate(_signed(_now - (_WINDOW - 60)), BOT_TOKEN) or {}).get("id")
      == 7585109158)
check("a stale one is refused",
      webapp.validate(_signed(_now - (_WINDOW + 60)), BOT_TOKEN) is None)
check("a day-old signature is now refused",
      webapp.validate(_signed(_now - 24 * 3600), BOT_TOKEN) is None,
      "the whole point of shortening the window")
check("the window cannot be configured away",
      webapp._resolve_max_age.__doc__ is not None
      and webapp._MAX_ALLOWED_AGE_S <= 6 * 3600)
check("a month-old capture is refused",
      webapp.validate(_signed(_now - 30 * 86400), BOT_TOKEN) is None,
      "this is the replay the check exists for")
check("a future timestamp is refused",
      webapp.validate(_signed(_now + 3600), BOT_TOKEN) is None,
      "no clock we should trust produces it")
check("a MISSING auth_date is refused, not skipped",
      webapp.validate(_signed(omit_date=True), BOT_TOKEN) is None,
      "otherwise the check is opt-out by omitting the field")
check("an unparseable auth_date is refused",
      webapp.validate(_signed("not-a-number"), BOT_TOKEN) is None)
check("a bad signature is still refused first",
      webapp.validate(_signed()[:-4] + "0000", BOT_TOKEN) is None)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — your account, your trades, the right candles.")
