"""Performance on the web is built from what the BROKER says closed.

THE BUG THIS FILE EXISTS TO KEEP CLOSED

The first version read the engine's trade journal alone. The deployed page said
"No closed trades in this period" while the Positions page, two taps away,
listed closed trades from the broker's deal history: the journal only holds
what the loop recorded, so a trade closed by hand — or before the journal
labelled it — did not exist for the performance page. A screen asserting a fact
(none closed) that another screen of the same product contradicted.

WHAT THESE TESTS WILL NOT ACCEPT

* A zero-trade success when the broker's history was not read.
* Deals the broker lists being missing because the journal does not know them.
* A strategy label invented for a deal the journal never opened (it is
  "unlabelled").
* Demo, live and unknown-mode trades blended into one headline.
* `Infinity` in the response (a profit factor with no losing trade).
* A re-implementation of the maths: figures must equal `apex.performance`.
* Three lucky trades ranked as evidence.

Run: python3 tests/test_platform_performance.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-perf-")
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


from apex import performance as BASE                         # noqa: E402
from apex.platform import performance_read as PR            # noqa: E402

NOW = datetime(2026, 10, 22, 12, 0, 0)


def ts(day, hh=10):
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hh, 0, 0).timestamp()


def deal(day, net, *, pid, symbol="EURUSD", side="BUY"):
    return {"symbol": symbol, "side": side, "units": 1000, "entry": 1.1000,
            "exit": 1.1010, "net": net, "closedAt": ts(day), "positionId": pid}


def jrow(pid, strategy, *, day="2026-10-20", mode="demo", sl=10, net=0.0):
    return {"time": f"{day} 10:00:00", "symbol": "EURUSD", "side": "BUY",
            "entry": 1.1, "exit": 1.101, "slPips": sl, "netPnl": net,
            "strategyId": strategy, "mode": mode, "positionId": pid}


def broker(deals, *, mode="demo", status="ok", reason=None):
    def reader(uid, **kw):
        if status == "boom":
            raise RuntimeError("socket closed")
        out = {"connected": True, "status": status, "accountId": 501,
               "mode": mode}
        if status == "ok":
            out["deals"] = deals
        if reason:
            out["reason"] = reason
        return out
    return reader


def read(deals, journal=None, **kw):
    return PR.read("u", deals_reader=kw.pop("deals_reader", broker(deals)),
                   rows_reader=lambda uid: journal or [], now=NOW, **kw)


# ── 1. the authority is the broker ──────────────────────────────────────────
print("\n[1] trades the broker closed are counted even if the journal has never heard of them")
deals = [deal("2026-10-20", 10, pid=1), deal("2026-10-21", -4, pid=2)]
r = read(deals, journal=[])
check("both deals are counted with an EMPTY journal", r["summary"]["trades"] == 2, str(r["summary"]))
check("net is the broker's", r["summary"]["net"] == 6.0, str(r["summary"]["net"]))
check("they are 'unlabelled', not given a strategy", [s["id"] for s in r["byStrategy"]] == [BASE.UNLABELLED], str(r["byStrategy"]))
check("and the source says how many are unattributed",
      r["source"]["unattributed"] == 2 and r["source"]["attributed"] == 0, str(r["source"]))

print("\n[1b] the journal tells us which strategy opened a deal, joined by position id")
r = read(deals, journal=[jrow(1, "trend"), jrow(2, "breakout")])
check("strategies come from the journal join",
      {s["id"] for s in r["byStrategy"]} == {"trend", "breakout"}, str(r["byStrategy"]))
check("attributed count", r["source"]["attributed"] == 2, str(r["source"]))
check("a journal row can never change what the broker says closed",
      read(deals, journal=[jrow(1, "trend", net=9999)])["summary"]["net"] == 6.0)
r = read(deals, journal=[jrow(99, "ghost")])
check("a journal row with no matching deal does not add a trade inside the window",
      r["summary"]["trades"] == 2, str(r["summary"]))

# ── 2. broker failures are errors ───────────────────────────────────────────
print("\n[2] a broker that cannot be read is 'unavailable', never an empty success")
for name, rd in (("raises", broker([], status="boom")),
                 ("unavailable", broker([], status="unavailable", reason="cTrader did not answer")),
                 ("not connected", broker([], status="not_connected", reason="no account selected")),
                 ("reauth", broker([], status="reauth_required", reason="reconnect the account"))):
    r = PR.read("u", deals_reader=rd, rows_reader=lambda uid: [jrow(1, "trend")], now=NOW)
    check(f"{name}: unavailable, with a reason, and no figures",
          r["status"] == "unavailable" and r.get("reason") and "summary" not in r, str(r))
check("the reason carries the broker's own words",
      "cTrader did not answer" in PR.read("u", deals_reader=broker([], status="unavailable", reason="cTrader did not answer"),
                                          rows_reader=lambda u: [], now=NOW)["reason"])
check("the journal alone is never presented as the answer",
      "summary" not in PR.read("u", deals_reader=broker([], status="boom"),
                               rows_reader=lambda u: [jrow(1, "trend")] * 5, now=NOW))

print("\n[2b] an unreadable journal costs labels, not trades")


def _jboom(uid):
    raise RuntimeError("redis down")


r = PR.read("u", deals_reader=broker(deals), rows_reader=_jboom, now=NOW)
check("the broker's trades are still shown", r["summary"]["trades"] == 2, str(r.get("summary")))
check("and the loss of labels is said", r["source"]["journalReadable"] is False, str(r.get("source")))

# ── 3. mode ─────────────────────────────────────────────────────────────────
print("\n[3] demo is the default; another account type is never blended in")
r = read(deals, mode="demo", deals_reader=broker(deals, mode="live"))
check("a LIVE account's deals are not in a demo headline",
      r["summary"]["trades"] == 0 and r["excluded"]["otherMode"] == 2, str(r))
r = read(deals, mode="all", deals_reader=broker(deals, mode="live"))
check("'all' includes them", r["summary"]["trades"] == 2, str(r["summary"]))
r = read(deals, deals_reader=broker(deals, mode="mystery"))
check("a mode the broker did not confirm is counted and left out, not guessed",
      r["summary"]["trades"] == 0 and r["excluded"]["unknownMode"] == 2, str(r["excluded"]))

# ── 4. periods ──────────────────────────────────────────────────────────────
print("\n[4] periods are cut as the bot cut them")
dl = [deal("2026-10-22", 1, pid=1), deal("2026-10-16", 1, pid=2),
      deal("2026-10-15", 1, pid=3), deal("2026-09-23", 1, pid=4)]
check("today = 1", read(dl, period="today")["summary"]["trades"] == 1)
check("week = 2", read(dl, period="week")["summary"]["trades"] == 2)
check("month = 4", read(dl, period="month")["summary"]["trades"] == 4)
check("all = 4", read(dl, period="all")["summary"]["trades"] == 4)

print("\n[4b] 'all time' adds older trades only the journal remembers, once each")
old = jrow(50, "trend", day="2026-08-01", net=7.0)
r = read(dl, journal=[old, jrow(2, "trend", day="2026-10-16")], period="all")
check("the older journal trade is added", r["summary"]["trades"] == 5, str(r["summary"]))
check("a journal row that duplicates a deal is not counted twice",
      sum(1 for s in r["byStrategy"] for _ in range(s["trades"])) == 5)
check("but 30 days does not include it", read(dl, journal=[old], period="month")["summary"]["trades"] == 4)

# ── 5. valid JSON ───────────────────────────────────────────────────────────
print("\n[5] a profit factor with no losses is null, never Infinity")
wins = [deal("2026-10-20", 10, pid=1), deal("2026-10-21", 20, pid=2)]
r = read(wins)
check("the base module returns infinity here (so the guard is needed)",
      BASE.summarize([{"netPnl": 10}, {"netPnl": 20}])["profit_factor"] == float("inf"))
check("profit_factor is null with the reason", r["summary"]["profit_factor"] is None and r["summary"]["noLosses"] is True)
try:
    json.dumps(r, allow_nan=False)
    ok = True
except ValueError:
    ok = False
check("the whole response is strict JSON", ok)

# ── 6. one definition of the maths ──────────────────────────────────────────
print("\n[6] the figures equal apex.performance on the same rows")
mixed = [deal("2026-10-20", 10, pid=1), deal("2026-10-20", -4, pid=2), deal("2026-10-21", 6, pid=3)]
want = BASE.summarize([{"netPnl": 10}, {"netPnl": -4}, {"netPnl": 6}])
got = read(mixed)["summary"]
for k in ("trades", "wins", "losses", "win_rate", "net", "expectancy", "max_drawdown", "profit_factor"):
    check(f"{k} matches", got[k] == want[k], f"{got[k]} vs {want[k]}")

# ── 7. groups ───────────────────────────────────────────────────────────────
print("\n[7] strategy and instrument groups; thin ones are labelled and last")
dl = ([deal("2026-10-20", 5, pid=i) for i in range(1, 5)]
      + [deal("2026-10-20", 50, pid=i, symbol="XAUUSD") for i in range(10, 12)])
jr = ([jrow(i, "trend") for i in range(1, 5)] + [jrow(i, "breakout") for i in range(10, 12)])
r = read(dl, journal=jr)
by = {s["id"]: s for s in r["byStrategy"]}
check("trend has 4, breakout 2", by["trend"]["trades"] == 4 and by["breakout"]["trades"] == 2)
check("breakout is thin and listed after trend",
      by["breakout"]["thin"] is True and r["byStrategy"][0]["id"] == "trend", str(r["byStrategy"]))
sym = {s["id"]: s for s in r["bySymbol"]}
check("instruments are split", sym["EURUSD"]["trades"] == 4 and sym["XAUUSD"]["trades"] == 2)
check("labels: 'platform_rule' is 'My conditions'",
      PR._label("platform_rule") == "My conditions" and PR._label(BASE.UNLABELLED).startswith("Unlabelled"))

# ── 8. emptiness, input, routing ────────────────────────────────────────────
print("\n[8] a successful empty read is empty; bad input is refused; the route exists")
r = read([])
check("a broker that answered with nothing is 0 trades, honestly",
      r["status"] == "ok" and r["summary"]["trades"] == 0 and r["summary"]["noLosses"] is False)
for kw in ({"period": "decade"}, {"mode": "paper"}):
    try:
        read([], **kw)
        check(f"{kw} raises ValueError", False)
    except ValueError:
        check(f"{kw} raises ValueError", True)
src = open(os.path.join(ROOT, "apex", "platform", "api.py")).read()
check("GET /performance is routed with the selected account", 'route == "performance"' in src and "_perfread.read(" in src)
check("the note says where the numbers come from", "deal history" in read([])["note"])

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All platform-performance checks passed.")
