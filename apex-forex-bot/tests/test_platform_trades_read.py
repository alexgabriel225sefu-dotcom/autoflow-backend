"""The Trades read: one row per closed trade, and the curve they make.

WHY THIS EXISTS

The Positions page listed closed trades without their open time, stop or
target, only for seven days, and Performance had totals but no way to draw a
curve. A replay of "when was this trade placed" and a profit-and-loss overview
need those facts from the API.

WHAT THESE TESTS WILL NOT ACCEPT

* A start time, a stop or a target that was not known, filled in by guesswork:
  they are null, never estimated.
* A stop or target level that is not the entry moved by the engine's own
  recorded distance in the right direction for the side.
* An empty list of trades when the broker could not be read, or a data key on
  an unavailable answer.
* A trade placed on the wrong UTC day, or the same trade on a different day in
  Trades and in Performance.
* A trade from the other kind of account (demo or live) shown as this one's.
* A trade with an invalid net result counted in the curve.
* The read reaching an order, close or approval function, or a route that
  answers without a session.

Run: python3 tests/test_platform_trades_read.py
"""
import ast
import os
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-trades-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import broker_read as BR                  # noqa: E402
from apex.platform import performance_read as PR             # noqa: E402
from apex.platform import pnl_series as PS                   # noqa: E402
from apex.platform import ratelimit as RL                    # noqa: E402
from apex.platform import trades_read as TR                  # noqa: E402


def utc(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp()


NOW = utc(2026, 10, 22, 12)


def deal(pid, closed, net, *, opened=None, symbol="EURUSD", side="BUY",
         entry=1.1000, exit_=1.1010, **extra):
    row = {"positionId": str(pid), "symbol": symbol, "side": side, "units": 1000,
           "entry": entry, "exit": exit_, "net": net, "closedAt": closed,
           "openedAt": opened,
           "durationS": None if opened is None else max(0, closed - opened),
           "gross": net, "swap": 0.0, "commission": 0.0}
    row.update(extra)
    return row


def reader(deals, *, mode="demo", status="ok", reason=None, seen=None):
    def r(uid, **kw):
        if seen is not None:
            seen.append(kw)
        if status == "boom":
            raise RuntimeError("socket closed")
        out = {"connected": True, "status": status, "accountId": "501", "mode": mode}
        if status == "ok":
            out["deals"] = deals
        if reason:
            out["reason"] = reason
        return out
    return r


def jrow(pid, strategy="trend", sl=10, tp=20):
    return {"positionId": str(pid), "strategyId": strategy, "slPips": sl,
            "tpPips": tp, "time": "2026-10-21 09:00:00"}


def read(deals, journal=None, *, seen=None, **kw):
    return TR.read("u", deals_reader=reader(deals, seen=seen),
                   rows_reader=lambda uid: journal or [], now=NOW, **kw)


print("\n[1] the curve: UTC days, wins and losses, running total")
rows = [
    {"closedAt": utc(2026, 10, 20, 23, 59, 59), "netPnl": 10.0},
    {"closedAt": utc(2026, 10, 21, 0, 0, 0), "netPnl": -4.0},
    {"closedAt": utc(2026, 10, 21, 8), "netPnl": 0.0},
    {"closedAt": utc(2026, 10, 21, 9), "netPnl": 2.5},
]
s = PS.build(list(reversed(rows)))
check("a close one second before UTC midnight is the earlier day",
      s["daily"][0]["date"] == "2026-10-20" and s["daily"][0]["net"] == 10.0, str(s["daily"]))
check("the next second starts the next day",
      s["daily"][1]["date"] == "2026-10-21" and s["daily"][1]["trades"] == 3, str(s["daily"]))
check("a zero result is a trade, neither win nor loss",
      s["daily"][1]["wins"] == 1 and s["daily"][1]["losses"] == 1, str(s["daily"][1]))
check("equity is the running total, oldest first, whatever the input order",
      [e["equity"] for e in s["equity"]] == [10.0, 6.0, 6.0, 8.5], str(s["equity"]))
check("days are sorted oldest first", [d["date"] for d in s["daily"]] == sorted(d["date"] for d in s["daily"]))
bad = PS.build([{"closedAt": utc(2026, 10, 20), "netPnl": 5.0},
                {"closedAt": None, "netPnl": 9.0},
                {"closedAt": utc(2026, 10, 20, 1), "netPnl": float("nan")},
                {"closedAt": utc(2026, 10, 20, 2), "netPnl": float("inf")},
                {"closedAt": utc(2026, 10, 20, 3), "netPnl": True},
                {"closedAt": utc(2026, 10, 20, 4)}])
check("rows without a usable time or net are counted out, not bucketed",
      bad["excluded"] == 5 and len(bad["equity"]) == 1 and bad["daily"][0]["net"] == 5.0, str(bad))
check("an empty range is empty, not an error",
      PS.build([]) == {"daily": [], "equity": [], "excluded": 0})

print("\n[2] a trade carries what is known and null for what is not")
opened, closed = utc(2026, 10, 21, 8, 30), utc(2026, 10, 21, 11, 45)
r = read([deal(1, closed, 12.5, opened=opened, symbol="EURUSD", side="BUY",
               entry=1.1000)], [jrow(1, "trend", sl=10, tp=20)])
t = r["trades"][0]
check("the answer is ok and names the account", r["status"] == "ok" and r["accountId"] == "501")
check("open time and duration come from the broker",
      t["openedAt"] == opened and t["durationS"] == closed - opened, str(t))
check("a long's stop is below entry by the journal's distance, target above",
      abs(t["slPrice"] - 1.0990) < 1e-9 and abs(t["tpPrice"] - 1.1020) < 1e-9, str(t))
check("the distances are carried too", t["slPips"] == 10 and t["tpPips"] == 20)
check("the strategy comes from the journal, with a label",
      t["strategyId"] == "trend" and t["strategy"], str(t))
short = read([deal(2, closed, -3.0, opened=opened, side="SELL", entry=1.1000,
                   exit_=1.1010)], [jrow(2, sl=10, tp=20)])["trades"][0]
check("a short's stop is above entry, target below",
      abs(short["slPrice"] - 1.1010) < 1e-9 and abs(short["tpPrice"] - 1.0980) < 1e-9, str(short))
gold = read([deal(3, closed, 5.0, opened=opened, symbol="XAUUSD", side="BUY",
                  entry=4000.0, exit_=4010.0)], [jrow(3, sl=50, tp=100)])["trades"][0]
check("gold uses its own pip size (0.1)",
      abs(gold["slPrice"] - 3995.0) < 1e-6 and abs(gold["tpPrice"] - 4010.0) < 1e-6, str(gold))
nj = read([deal(4, closed, 1.0, opened=None)], [])["trades"][0]
check("no journal row: no strategy, no levels, and no invented open time",
      nj["strategyId"] is None and nj["strategy"] is None and nj["slPrice"] is None
      and nj["tpPrice"] is None and nj["openedAt"] is None and nj["durationS"] is None, str(nj))
nside = read([deal(5, closed, 1.0, side=None)], [jrow(5)])["trades"][0]
check("an unknown side gives no levels even with distances",
      nside["slPrice"] is None and nside["tpPrice"] is None and nside["slPips"] == 10, str(nside))
zero = read([deal(6, closed, 1.0)], [jrow(6, sl=0, tp=None)])["trades"][0]
check("a zero or missing distance gives no level", zero["slPrice"] is None and zero["tpPrice"] is None)
check("the amounts are said to have no known currency",
      r["currency"] is None and "currency" in r["note"].lower())

print("\n[3] range, padding and ordering")
seen = []
old_close = NOW - 40 * 86400
r = read([deal(10, NOW - 3600, 1.0, opened=NOW - 7200), deal(11, NOW - 86400, 2.0),
          deal(12, old_close, 9.0, opened=old_close - 100)], seen=seen, days=30)
check("the broker is asked for the range plus the padding",
      seen[0]["days"] == 30 + TR.PAD_DAYS, str(seen))
check("only trades closed inside the range are listed",
      [t["positionId"] for t in r["trades"]] == ["10", "11"], str([t["positionId"] for t in r["trades"]]))
check("newest first", r["trades"][0]["closedAt"] > r["trades"][1]["closedAt"])
check("the summary adds up what is listed",
      r["summary"] == {"trades": 2, "net": 3.0, "wins": 2, "losses": 0}, str(r["summary"]))
edge = read([deal(13, NOW - 30 * 86400 - 5, 1.0, opened=NOW - 30 * 86400 - 99999)], days=30)
check("a close just outside the range is not listed",
      edge["trades"] == [], str(edge["trades"]))
seen = []
read([], seen=seen, days=TR.MAX_DAYS)
check("the largest range is padded no further than the broker allows",
      seen[0]["days"] == TR.MAX_DAYS, str(seen))
seen = []
read([], seen=seen)
check("the days default to 30", seen[0]["days"] == 30 + TR.PAD_DAYS, str(seen))
undated = read([deal(14, None, 1.0), deal(15, NOW - 60, 1.0)])
check("a deal with no close time is counted, not listed",
      [t["positionId"] for t in undated["trades"]] == ["15"] and undated["excluded"]["undated"] == 1)

print("\n[4] the same trade is on the same day here and in Performance")
d1 = [deal(20, utc(2026, 10, 21, 23, 30), 7.0), deal(21, utc(2026, 10, 22, 0, 30), -2.0)]
tr = read(d1, days=5)
pr = PR.read("u", period="all", mode="demo",
             deals_reader=reader(d1), rows_reader=lambda u: [],
             now=datetime(2026, 10, 22, 12, 0, 0))
check("Performance carries the curve too", "daily" in pr and "equity" in pr, str(list(pr)))
check("daily series are identical in both reads", tr["daily"] == pr["daily"], f"{tr['daily']} vs {pr['daily']}")
check("equity is identical in both reads", tr["equity"] == pr["equity"])

print("\n[5] an unreadable broker is not 'no trades'")
for label, kw in (("unavailable", {"status": "unavailable", "reason": "cTrader timed out"}),
                  ("not connected", {"status": "not_connected"})):
    rd = reader([], **kw)
    r = TR.read("u", deals_reader=rd, rows_reader=lambda u: [jrow(1)], now=NOW)
    check(f"{label}: status is unavailable and there is no trades key",
          r["status"] == "unavailable" and "trades" not in r and "daily" not in r, str(r))
check("the broker's reason is passed on", "timed out" in TR.read(
    "u", deals_reader=reader([], status="unavailable", reason="cTrader timed out"),
    rows_reader=lambda u: [], now=NOW)["reason"])
boom = TR.read("u", deals_reader=reader([], status="boom"), rows_reader=lambda u: [], now=NOW)
check("a reader that raises is unavailable, without the exception text",
      boom["status"] == "unavailable" and "socket closed" not in str(boom), str(boom))

print("\n[6] demo and live are not blended")
live = reader([deal(30, NOW - 100, 5.0)], mode="live")
r = TR.read("u", mode="demo", deals_reader=live, rows_reader=lambda u: [], now=NOW)
check("a live account asked for as demo lists nothing and says so",
      r["trades"] == [] and r["excluded"]["otherMode"] == 1 and r["daily"] == [], str(r["excluded"]))
r = TR.read("u", mode="live", deals_reader=live, rows_reader=lambda u: [], now=NOW)
check("asked for as live it lists the trade", len(r["trades"]) == 1)
r = TR.read("u", mode="all", deals_reader=live, rows_reader=lambda u: [], now=NOW)
check("'all' lists it whatever the kind", len(r["trades"]) == 1)

print("\n[7] a journal that cannot be read does not hide the trades")


def jboom(uid):
    raise RuntimeError("redis down")


r = TR.read("u", deals_reader=reader([deal(40, NOW - 60, 1.0)]), rows_reader=jboom, now=NOW)
check("the trade is still listed, unlabelled, and the answer says why",
      len(r["trades"]) == 1 and r["trades"][0]["strategyId"] is None
      and r["source"]["journalReadable"] is False, str(r["source"]))

print("\n[8] bad input is refused before a broker is opened")
opened_broker = []
for kw in ({"days": 0}, {"days": TR.MAX_DAYS + 1}, {"days": "abc"}, {"days": True},
           {"days": "1.5"}, {"mode": "paper"}):
    try:
        TR.read("u", deals_reader=lambda *a, **k: opened_broker.append(1), **kw)
        check(f"{kw} is refused", False)
    except ValueError:
        check(f"{kw} is refused", True)
check("and no read was attempted", not opened_broker)

print("\n[9] the broker read hands the new fields through")


class Broker:
    def get_deal_history(self, a, b):
        return {"ok": True, "deals": {"7": {
            "symbol": "EURUSD", "side": "BUY", "units": 1000, "entryPrice": 1.1,
            "exitPrice": 1.101, "netPnl": 9.0, "closedAt": 200, "positionId": "7",
            "openedAt": 100, "durationS": 100, "grossPnl": 10.0, "swap": -0.5,
            "commissionUsd": 0.5}}}


row = BR._deal_rows(Broker(), 7)[0]
check("openedAt, durationS, gross, swap and commission are carried",
      (row["openedAt"], row["durationS"], row["gross"], row["swap"], row["commission"])
      == (100, 100, 10.0, -0.5, 0.5), str(row))
check("the older fields are unchanged",
      (row["entry"], row["exit"], row["net"], row["closedAt"]) == (1.1, 1.101, 9.0, 200))


class NoOpen(Broker):
    def get_deal_history(self, a, b):
        h = super().get_deal_history(a, b)
        for d in h["deals"].values():
            d.pop("openedAt"), d.pop("durationS")
        return h


row = BR._deal_rows(NoOpen(), 7)[0]
check("an opening deal outside the window leaves openedAt null",
      row["openedAt"] is None and row["durationS"] is None)

print("\n[10] it is a read, wired like one")
src = open(os.path.join(ROOT, "apex", "platform", "trades_read.py"), encoding="utf-8").read()
tree = ast.parse(src)
imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
         for a in n.names}
for banned in ("place_order", "close_position", "amend_sltp", "force_trade",
               "authorize_order", "bridge", "live_execution", "position_close",
               "approvals", "gates"):
    check(f"trades_read imports nothing named `{banned}`",
          banned not in names and not any(banned in (m or "") for m in imported))
check("`trades` shares the broker market-data budget",
      RL.classify("GET", "trades") == "candles", RL.classify("GET", "trades"))
api_src = open(os.path.join(ROOT, "apex", "platform", "api.py"), encoding="utf-8").read()
block = api_src[api_src.index('route == "trades"'):][:420]
check("the route authenticates before it reads", "_authenticate(headers)" in block, block)
check("and is GET only", 'method == "GET"' in block)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All trades read checks passed.")
