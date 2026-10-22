"""Performance on the web says what the journal says, and nothing it cannot.

WHAT THESE TESTS WILL NOT ACCEPT

* Demo, live and unlabelled trades blended into one headline.
* Unlabelled trades guessed into demo (they are counted and excluded).
* `Infinity` in the response: a profit factor with no losing trade is what a
  screen must handle gracefully, and `json.dumps` would print it as invalid
  JSON that a browser rejects — the page would break on the best result.
* An unreadable journal presented as "0 trades".
* A re-implementation of the maths: the figures must equal
  `apex.performance.summarize` on the same rows.
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


def row(day, net, *, mode="demo", strategy="trend", symbol="EURUSD"):
    return {"time": f"{day} 10:00:00", "symbol": symbol, "side": "BUY",
            "entry": 1.1000, "exit": 1.1010, "slPips": 10, "netPnl": net,
            "strategyId": strategy, "mode": mode}


def read(rows, **kw):
    return PR.read("u", rows_reader=lambda uid: rows, now=NOW, **kw)


# ── 1. mode ─────────────────────────────────────────────────────────────────
print("\n[1] demo is the default and live/unknown are never blended in")
rows = [row("2026-10-20", 10), row("2026-10-20", -5),
        row("2026-10-20", 99, mode="live"),
        {**row("2026-10-20", 77), "mode": None}]
r = read(rows)
check("the headline is demo only", r["summary"]["trades"] == 2
      and r["summary"]["net"] == 5.0, str(r["summary"]))
check("the live trade is counted as excluded, not hidden",
      r["excluded"]["otherMode"] == 1, str(r["excluded"]))
check("the unlabelled-mode trade is counted, and NOT guessed into demo",
      r["excluded"]["unknownMode"] == 1, str(r["excluded"]))
r = read(rows, mode="all")
check("'all' includes everything", r["summary"]["trades"] == 4, str(r["summary"]))

# ── 2. period ───────────────────────────────────────────────────────────────
print("\n[2] periods are cut as the bot cut them")
rows = [row("2026-10-22", 1), row("2026-10-16", 1), row("2026-10-15", 1),
        row("2026-09-23", 1), row("2026-09-22", 1)]
check("today = 1", read(rows, period="today")["summary"]["trades"] == 1)
check("week (today and 6 days back) = 2", read(rows, period="week")["summary"]["trades"] == 2)
check("month (29 days back) = 4", read(rows, period="month")["summary"]["trades"] == 4)
check("all = 5", read(rows, period="all")["summary"]["trades"] == 5)

# ── 3. no losing trade must still be valid JSON ─────────────────────────────
print("\n[3] a profit factor with no losses is null, never Infinity")
wins = [row("2026-10-20", 10), row("2026-10-21", 20)]
r = read(wins)
check("the base module really does return infinity here (so this guard is needed)",
      BASE.summarize(wins)["profit_factor"] == float("inf"))
check("profit_factor is null", r["summary"]["profit_factor"] is None, str(r["summary"]))
check("and the reason is said", r["summary"]["noLosses"] is True)
try:
    json.dumps(r, allow_nan=False)
    ok = True
except ValueError:
    ok = False
check("the whole response serialises as strict JSON", ok)
for s in r["byStrategy"] + r["bySymbol"]:
    check(f"group {s['id']} has no non-finite number",
          all(not isinstance(v, float) or v == v and abs(v) != float("inf")
              for v in s.values()), str(s))

# ── 4. figures come from the one definition ────────────────────────────────
print("\n[4] the numbers equal apex.performance on the same rows")
mixed = [row("2026-10-20", 10), row("2026-10-20", -4), row("2026-10-21", 6)]
want = BASE.summarize(mixed)
got = read(mixed)["summary"]
for k in ("trades", "wins", "losses", "win_rate", "net", "expectancy",
          "max_drawdown", "profit_factor", "avg_win", "avg_loss"):
    check(f"{k} matches", got[k] == want[k], f"{got[k]} vs {want[k]}")

# ── 5. strategy split, thin groups, labels ──────────────────────────────────
print("\n[5] strategies are split, labelled, and thin ones are not ranked")
rows = ([row("2026-10-20", 5, strategy="trend")] * 4
        + [row("2026-10-20", 50, strategy="breakout")] * 2
        + [row("2026-10-20", -3, strategy="platform_rule")] * 3
        + [{**row("2026-10-20", 1), "strategyId": None}] * 3)
r = read(rows)
by = {s["id"]: s for s in r["byStrategy"]}
check("each strategy has its own count",
      by["trend"]["trades"] == 4 and by["breakout"]["trades"] == 2, str({k: v["trades"] for k, v in by.items()}))
check("a group under 3 trades is flagged thin", by["breakout"]["thin"] is True)
check("and is listed after the non-thin ones",
      [s["thin"] for s in r["byStrategy"]] == sorted(s["thin"] for s in r["byStrategy"]),
      str([(s["id"], s["thin"]) for s in r["byStrategy"]]))
check("the rule-built strategy is called 'My conditions'",
      by["platform_rule"]["label"] == "My conditions", by["platform_rule"]["label"])
check("older trades are 'Unlabelled', not dropped",
      by[BASE.UNLABELLED]["label"].startswith("Unlabelled") and by[BASE.UNLABELLED]["trades"] == 3)
check("a thin group with a huge win does not outrank a real one",
      r["byStrategy"][0]["thin"] is False, str(r["byStrategy"][0]["id"]))

# ── 6. honesty about emptiness and unreadability ────────────────────────────
print("\n[6] empty is empty; unreadable is not empty")
r = read([])
check("no trades is 0 trades with no 'noLosses' claim",
      r["summary"]["trades"] == 0 and r["summary"]["noLosses"] is False, str(r["summary"]))


def _boom(uid):
    raise RuntimeError("redis down")


r = PR.read("u", rows_reader=_boom, now=NOW)
check("an unreadable journal is 'unavailable', not zeros",
      r["status"] == "unavailable" and "summary" not in r, str(r))
check("the note says what the numbers are and are not",
      "engine recorded" in read([])["note"])

# ── 7. input is validated ───────────────────────────────────────────────────
print("\n[7] bad input is refused")
for kw in ({"period": "decade"}, {"mode": "paper"}):
    try:
        read([], **kw)
        check(f"{kw} raises ValueError", False)
    except ValueError:
        check(f"{kw} raises ValueError", True)

# ── 8. routed ───────────────────────────────────────────────────────────────
print("\n[8] GET /performance is routed")
src = open(os.path.join(ROOT, "apex", "platform", "api.py")).read()
check("api routes it to performance_read", 'route == "performance"' in src and "_perfread.read(" in src)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All platform-performance checks passed.")
