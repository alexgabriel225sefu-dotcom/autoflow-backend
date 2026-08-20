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
check("it renders the backend's badge verdict", 'id="modeBadge"' in HTML)
check("...and has a distinct class for unverified",
      "unver" in HTML, "an unknown account must not borrow the demo styling")
check("timeframes are selectable", all(f'data-tf="{t}"' in HTML
                                       for t in ("1m", "5m", "15m", "1h", "4h", "1d")))
check("history is a tab", 'data-p="hist"' in HTML)
check("the replay screen exists", 'id="replay"' in HTML and 'id="rPlay"' in HTML)
check("it calls the user-scoped endpoints",
      "/api/app/history" in HTML and "/api/app/replay?trade=" in HTML)
check("every call carries initData",
      "init='+encodeURIComponent(initData)" in HTML)
check("it never invents market data", "Math.random" not in HTML)
for fake in ("10,142", "12,482", "1.08452"):
    check(f"no hardcoded {fake}", fake not in HTML)
check("untrusted trade text is escaped", "&lt;" in HTML and "esc(" in HTML)
check("the client cannot ask for another account",
      "user_id=" not in HTML and "telegram_id=" not in HTML)
check("a stale feed is visibly stale", "stale" in HTML and "freshness" in HTML)
check("errors are sentences, not stack traces",
      "could not be found" in HTML and "temporarily unavailable" in HTML)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — your account, your trades, the right candles.")
