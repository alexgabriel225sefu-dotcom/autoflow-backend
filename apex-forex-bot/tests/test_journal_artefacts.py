"""Rows that are not this account's trades must not reach the account's totals.

WHAT WENT WRONG

A backfill wrote five rows into user 7585109158's journal that did not come
from this account. Four carry balance 470,586.42 on an account that held
3,002.96 that day, one of them on US400 — an index this platform cannot trade
at all. The fifth is XAUUSD -779.74 against a balance of 3,002.96, 26% of the
account in one trade, when the sizing cap makes 2.5% the maximum.

Together they are -27,365. The real 71 trades are +264.16. So /report showed
the client "NET P&L: -$27,052" — a false statement about their own money, and
every win rate, profit factor and drawdown built on the journal was wrong the
same way.

THE SHAPE OF THE FIX

Marked, never deleted. The journal is the one record a client cannot
reconstruct, and a row that is wrong is still evidence of what happened. Each
gets an `artefact` field naming the reason, and reads exclude them by default.

FILTERING AT THE SOURCE, AND THE TRAP IN IT

Sixteen call sites read this journal. Filtering at each one means the next
reader added forgets, so load_trades() excludes by default and callers that
genuinely need every row pass include_artefacts=True.

That default is a data-loss trap for one caller: append_trade re-reads the
journal, appends, and writes the whole list back. With a filtering read it
would silently drop the marked rows on the next closed trade — deleting the
evidence by accident, which is the one thing this fix promised not to do. It
reads raw. So does backup, for the same reason.

Run: python tests/test_journal_artefacts.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-artefact-")

from apex import user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


UID = "7585109158"
REAL = [
    {"time": "2026-08-18 06:07", "symbol": "NZDUSD", "netPnl": -2.10,
     "balance": 2938.71, "confidence": 71},
    {"time": "2026-09-01 09:42", "symbol": "NZDUSD", "netPnl": 71.54,
     "balance": 3312.03, "confidence": 80},
]
# The five real ones, verbatim from the live journal.
ARTEFACTS = [
    {"time": "2026-08-19 12:41", "symbol": "XAUUSD", "netPnl": -779.74,
     "balance": 3002.96, "artefact": "impossible_size"},
    {"time": "2026-08-19 15:48", "symbol": "XAUUSD", "netPnl": -32440.0,
     "balance": 470586.42, "artefact": "foreign_account"},
    {"time": "2026-08-19 15:48", "symbol": "US400", "netPnl": -1296.0,
     "balance": 470586.42, "artefact": "foreign_account"},
    {"time": "2026-08-19 15:48", "symbol": "EURUSD", "netPnl": 930.0,
     "balance": 470586.42, "artefact": "foreign_account"},
    {"time": "2026-08-19 15:48", "symbol": "AUDUSD", "netPnl": 6220.0,
     "balance": 470586.42, "artefact": "foreign_account"},
]
ALL = [REAL[0]] + ARTEFACTS + [REAL[1]]
user_store.save_trades(UID, ALL)

print("\n1. Reads exclude artefacts by DEFAULT")
got = user_store.load_trades(UID)
check("only the real trades come back", len(got) == 2, f"got {len(got)}")
check("the totals are the account's own",
      round(sum(t["netPnl"] for t in got), 2) == 69.44,
      f"got {sum(t['netPnl'] for t in got)}")
check("no marked row survives the filter",
      not any(t.get("artefact") for t in got))

print("\n2. The rows are marked, not deleted")
raw = user_store.load_trades(UID, include_artefacts=True)
check("every row is still stored", len(raw) == 7, f"got {len(raw)}")
check("the five artefacts are all there",
      sum(1 for t in raw if t.get("artefact")) == 5)
check("each one says WHY",
      all(isinstance(t["artefact"], str) and t["artefact"]
          for t in raw if t.get("artefact")))
check("order is preserved", [t["symbol"] for t in raw][:2] == ["NZDUSD", "XAUUSD"])

print("\n3. append_trade must NOT delete them (the trap in a filtering default)")
user_store.append_trade(UID, {"time": "2026-09-03 10:00", "symbol": "GBPUSD",
                              "netPnl": 12.0, "balance": 3360.97})
after = user_store.load_trades(UID, include_artefacts=True)
check("the artefacts survived a new trade",
      sum(1 for t in after if t.get("artefact")) == 5,
      "a filtering read + full rewrite would have silently dropped them")
check("the new trade was appended", len(after) == 8)
check("and it is visible to normal reads", len(user_store.load_trades(UID)) == 3)

print("\n4. Backup captures the whole record, artefacts included")
from apex import backup  # noqa: E402
import inspect  # noqa: E402
src = inspect.getsource(backup)
check("backup reads with include_artefacts=True",
      "include_artefacts=True" in src,
      "a backup that quietly drops rows is not a backup")

print("\n5. A journal with no artefacts behaves exactly as before")
user_store.save_trades("clean", REAL)
check("nothing is filtered", len(user_store.load_trades("clean")) == 2)
check("raw and filtered agree",
      user_store.load_trades("clean") ==
      user_store.load_trades("clean", include_artefacts=True))

print("\n6. Malformed marks do not break the read")
user_store.save_trades("odd", [
    {"time": "t", "symbol": "EURUSD", "netPnl": 1.0, "artefact": None},
    {"time": "t", "symbol": "EURUSD", "netPnl": 2.0, "artefact": ""},
    {"time": "t", "symbol": "EURUSD", "netPnl": 3.0},
])
check("an empty or null mark is not an artefact",
      len(user_store.load_trades("odd")) == 3,
      "only a non-empty reason marks a row; a blank field is not a verdict")

# ── The classifier, against the real journal it was written for ──────────
# Section 7 runs the migration's rules over the actual 76 rows from user
# 7585109158 (time, symbol, netPnl, balance — the fields the rules read). If a
# rule ever widens enough to catch a genuine trade, this fails.
import importlib.util  # noqa: E402
import statistics  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "mark_artefacts", os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "scripts", "mark_journal_artefacts.py"))
_mark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mark)

# (symbol, netPnl, balance) for all 76 live rows.
LIVE = [
    ("GBPUSD", 29.87, 3348.97), ("EURUSD", -50.60, 3319.10),
    ("XAUUSD", -28.32, 3319.10), ("AUDUSD", 46.53, 3398.02),
    ("XAUUSD", -9.64, 3351.49), ("USDJPY", 17.20, 3368.58),
    ("USDCAD", 26.85, 3351.38), ("GBPUSD", 47.35, 3324.53),
    ("EURUSD", -34.85, 3277.18), ("NZDUSD", 71.54, 3312.03),
    ("EURUSD", 64.26, 3176.23), ("GBPUSD", 23.09, 3153.14),
    ("USDCHF", -89.40, 3242.54), ("EURUSD", 8.20, 3242.54),
    ("XAUUSD", 8.34, 3226.00), ("USDCHF", -31.16, 3257.16),
    ("NZDUSD", 20.16, 3237.00), ("XAUUSD", 1.74, 3237.00),
    ("USDCHF", 22.15, 3213.11), ("GBPUSD", -14.21, 3227.32),
    ("USDJPY", 0.26, 3227.32), ("AUDUSD", -16.45, 3243.51),
    ("XAUUSD", 21.69, 3243.51), ("NZDUSD", -0.56, 3221.82),
    ("EURUSD", -1.98, 3222.54), ("GBPUSD", -13.50, 3238.20),
    ("EURUSD", -6.96, 3238.20), ("XAUUSD", 21.12, 3224.04),
    ("GBPUSD", 10.30, 3224.04), ("AUDUSD", -0.26, 3214.00),
    ("XAUUSD", -32440.0, 470586.42), ("US400", -1296.0, 470586.42),
    ("EURUSD", 930.0, 470586.42), ("AUDUSD", 6220.0, 470586.42),
    ("XAUUSD", -779.74, 3002.96), ("USDCHF", -6.78, 3002.96),
    ("XAUUSD", 100.60, 2909.14), ("AUDUSD", -0.95, 2935.69),
    ("XAUUSD", -3.31, 2935.69), ("NZDUSD", -2.10, 2938.71),
    ("GBPUSD", -71.88, 3012.69), ("EURUSD", -1.20, 3012.69),
    ("XAUUSD", -19.21, 3014.24), ("EURUSD", -1.00, 3033.45),
    ("EURUSD", -4.50, 3034.57), ("XAUUSD", -25.08, 3039.27),
    ("XAUUSD", -21.60, 3085.95), ("EURUSD", 55.00, 3085.95),
    ("AUDUSD", 54.00, 2976.95), ("XAUUSD", -22.50, 2976.95),
    ("USDCAD", 8.40, 2991.05), ("EURUSD", 2.89, 2991.05),
    ("USDCAD", 0.00, 2988.84), ("USDCHF", -18.98, 2988.84),
    ("USDCAD", -2.51, 3008.05), ("EURUSD", -26.29, 3011.25),
    ("USDCHF", -2.14, 3037.98), ("AUDUSD", 24.99, 3040.30),
    ("XAUUSD", 26.01, 3015.31), ("AUDUSD", -1.04, 2988.85),
    ("AUDUSD", 3.78, 2990.67), ("EURUSD", 1.68, 2988.15),
    ("GBPUSD", -10.80, 2986.47), ("GBPUSD", -10.80, 2986.47),
    ("GBPUSD", -5.21, 2997.27), ("GBPUSD", -5.21, 2997.27),
    ("AUDUSD", -39.60, 3002.48), ("NZDUSD", -6.00, 3043.40),
    ("USDJPY", 48.80, 3050.30), ("AUDUSD", -133.95, 3001.50),
    ("USDCAD", 50.29, 3137.14), ("AUDUSD", 50.06, 3086.85),
    ("AUDUSD", -16.25, 3036.79), ("AUDUSD", 40.04, 3053.79),
    ("AUDUSD", 51.04, 3013.75), ("EURUSD", 62.71, 2962.71),
]
_rows = [{"symbol": s, "netPnl": p, "balance": b} for s, p, b in LIVE]
_median = statistics.median([r["balance"] for r in _rows])
_verdicts = [(r, _mark.classify(r, _median)) for r in _rows]
_flagged = [(r, v) for r, v in _verdicts if v]

print("\n7. The migration's rules, run over the real 76-row journal")
check("all 76 rows are accounted for", len(_verdicts) == 76)
check("exactly five are flagged", len(_flagged) == 5,
      f"flagged {len(_flagged)}: {[(r['symbol'], v) for r, v in _flagged]}")
check("the four foreign-account rows are caught",
      sum(1 for _, v in _flagged if v == "foreign_account") == 4)
check("the impossible-size row is caught",
      any(v == "impossible_size" and r["netPnl"] == -779.74
          for r, v in _flagged))
check("US400 would be caught on instrument alone",
      _mark.classify({"symbol": "US400", "netPnl": -1.0, "balance": 3000.0},
                     _median) == "foreign_instrument")
_removed = sum(r["netPnl"] for r, _ in _flagged)
_kept = [r for r, v in _verdicts if not v]
check("removing them turns -27,101 into +264",
      round(_removed, 2) == -27365.74
      and round(sum(r["netPnl"] for r in _kept), 2) == 264.16,
      f"removed {_removed:,.2f}, kept {sum(r['netPnl'] for r in _kept):,.2f}")

print("\n8. The rules have margin against the worst REAL row")
_worst = max((abs(r["netPnl"]) / r["balance"] for r in _kept), default=0)
check(f"worst genuine row is {_worst*100:.2f}% of its balance, rule fires at 20%",
      _worst < _mark.IMPOSSIBLE_PNL_FRACTION / 4,
      "less than a 4x margin means the rule is too close to real trading")
_maxbal = max(r["balance"] for r in _kept)
check("highest genuine balance is far below the foreign threshold",
      _maxbal < _median * _mark.FOREIGN_BALANCE_MULTIPLE / 2)

print("\n" + "=" * 66)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL ARTEFACT CHECKS PASSED - marked, excluded from totals,\n"
      "never deleted, and the classifier is verified against the real journal.")
