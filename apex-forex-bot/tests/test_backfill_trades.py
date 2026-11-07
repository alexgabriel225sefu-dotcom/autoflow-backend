"""The backfill fills gaps. It does not rewrite history, and it does not guess.

A tool that edits a client's trade journal has exactly one way to be useful and
several ways to be worse than doing nothing. The rows below are real ones, read
from the live demo account through the control plane before any of this was
fixed — thirteen of fifteen with no exit price, nine with no position id, six
with no direction at all, and every balance recorded from before that trade's
own P&L.

What must hold:

  1. an existing value is never replaced, even when the broker disagrees;
  2. a row the broker has nothing for is left exactly as it was;
  3. a row that could be two different deals is refused, not assigned;
  4. the direction is derived from arithmetic that cannot invert;
  5. running it twice changes nothing the second time.

Run: python tests/test_backfill_trades.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


import backfill_trades as bf

# ── Real journal rows (live account 47765456, before the fix) ────────────
ROWS = [
    # Has netPnl and time; no exit, no side, no positionId.
    {"time": "2026-08-28 14:04:58", "symbol": "USDCHF", "entry": 0.8045,
     "exit": None, "grossPnl": -89.48, "costUsd": 2.28, "netPnl": -89.4,
     "balance": 3242.54, "openedAt": None, "positionId": None, "side": None},
    # Has a position id, and a side already recorded.
    {"time": "2026-08-27 18:25:21", "symbol": "EURUSD", "entry": 1.165,
     "exit": None, "grossPnl": 10.66, "costUsd": 2.46, "netPnl": 8.2,
     "balance": 3242.54, "openedAt": None, "positionId": 55438200,
     "side": "SELL"},
    # Fully recorded — the tool must not touch it at all.
    {"time": "2026-08-21 20:02:57", "symbol": "NZDUSD", "entry": 0.59812,
     "exit": 0.59801, "grossPnl": -0.44, "costUsd": 0.12, "netPnl": -0.56,
     "balance": 3221.82, "openedAt": "2026-08-21 19:10:00",
     "positionId": 54932716, "side": "SELL"},
]

DEALS = {
    "55438200": {"positionId": "55438200", "symbol": "EURUSD", "netPnl": 8.2,
                 "grossPnl": 10.66, "commissionUsd": 2.46, "entryPrice": 1.165,
                 "exitPrice": 1.16407, "side": "SELL", "balance": 3250.74,
                 "closedAt": 1787855121, "openedAt": 1787851521},
    "55401111": {"positionId": "55401111", "symbol": "USDCHF", "netPnl": -89.4,
                 "grossPnl": -89.48, "commissionUsd": 2.28, "entryPrice": 0.8045,
                 "exitPrice": 0.80912, "side": "SELL", "balance": 3153.14,
                 "closedAt": 1787929498},
    # A decoy: same instrument and P&L, but months away.
    "50000001": {"positionId": "50000001", "symbol": "USDCHF", "netPnl": -89.4,
                 "grossPnl": -89.48, "commissionUsd": 2.28, "entryPrice": 0.8045,
                 "exitPrice": 0.80912, "side": "SELL", "balance": 1.0,
                 "closedAt": 1777929498},
    "54932716": {"positionId": "54932716", "symbol": "NZDUSD", "netPnl": -0.56,
                 "grossPnl": -0.44, "commissionUsd": 0.12, "entryPrice": 0.59812,
                 "exitPrice": 0.59801, "side": "SELL", "balance": 3221.26,
                 "closedAt": 1787342577},
}

print("\n1. A position id is an exact key")
d, why = bf.match(ROWS[1], DEALS)
check("the row with an id finds its deal",
      d is not None and d["positionId"] == "55438200")
check("...and says how", why == "position id", why)

print("\n2. Without an id, the match must be unambiguous")
d, why = bf.match(ROWS[0], DEALS)
check("symbol + net P&L + time identifies it",
      d is not None and d["positionId"] == "55401111", why)
check("...and the decoy months away is not chosen",
      d is not None and d["positionId"] != "50000001")
_near = dict(DEALS["50000001"], closedAt=DEALS["55401111"]["closedAt"] + 60)
d, why = bf.match(ROWS[0], {**DEALS, "50000001": _near})
check("two equally good candidates are REFUSED, not picked",
      d is None and "ambiguous" in why, why)

print("\n3. A row the broker has nothing for is left alone")
d, why = bf.match({"time": "2026-01-01 00:00:00", "symbol": "GBPUSD",
                   "netPnl": 123.45, "positionId": None}, DEALS)
check("no match is reported as no match",
      d is None and why == "no deal matches", why)
d, why = bf.match({"time": None, "symbol": "GBPUSD", "netPnl": None,
                   "positionId": None}, DEALS)
check("a row with nothing to match on is refused",
      d is None and "no net P&L or time" in why, why)
d, why = bf.match({"symbol": "GBPUSD", "positionId": 99999999}, DEALS)
check("an id the broker's window does not cover is refused",
      d is None and "not in the broker's window" in why, why)

print("\n4. Only gaps are filled — never an existing value")
patch = bf.plan_row(ROWS[1], DEALS["55438200"])
check("the missing exit is filled", patch.get("exit") == 1.16407, str(patch))
check("the recorded side is NOT replaced", "side" not in patch, str(patch))
check("the recorded netPnl is NOT replaced", "netPnl" not in patch, str(patch))
check("the recorded balance is NOT replaced", "balance" not in patch,
      "3242.54 is wrong — it is the pre-trade balance — but overwriting it "
      "would make it impossible to tell which rows the tool touched")
check("the recorded entry is NOT replaced", "entry" not in patch, str(patch))
check("a recoverable open time IS filled",
      patch.get("openedAt") == "2026-08-27 17:25:21", str(patch.get("openedAt")))

patch0 = bf.plan_row(ROWS[0], DEALS["55401111"])
check("a missing side IS filled", patch0.get("side") == "SELL", str(patch0))
check("a missing position id IS filled", patch0.get("positionId") == "55401111")
check("an open time the broker's window did not cover stays absent",
      "openedAt" not in patch0,
      "the opening leg was outside the range; an absent duration is honest")

print("\n5. A complete row produces no change at all")
check("nothing to patch", bf.plan_row(ROWS[2], DEALS["54932716"]) == {},
      str(bf.plan_row(ROWS[2], DEALS["54932716"])))

print("\n6. It is idempotent")
row = dict(ROWS[0])
row.update(bf.plan_row(row, DEALS["55401111"]))
check("the second pass finds nothing left",
      bf.plan_row(row, DEALS["55401111"]) == {},
      str(bf.plan_row(row, DEALS["55401111"])))

print("\n7. Direction is derived from arithmetic that cannot invert")
# A long is closed by a SELL deal, so the deal's own tradeSide is the opposite
# of the position's. Reading it naively would flip every historical trade. The
# broker method derives it from price and profit instead: a position was long
# exactly when the exit moved the same way as the profit.
CT = open(os.path.join(ROOT, "apex", "brokers", "ctrader.py"),
          encoding="utf-8").read()


def side_of(entry, exit_, gross):
    """The same expression get_deal_history uses, exercised directly."""
    if entry and exit_ and gross and exit_ != entry:
        return "BUY" if ((exit_ - entry) > 0) == (gross > 0) else "SELL"
    return None


check("price up, profit up  -> BUY", side_of(1.1000, 1.1050, 50.0) == "BUY")
check("price down, loss     -> BUY", side_of(1.1000, 1.0950, -50.0) == "BUY")
check("price down, profit   -> SELL", side_of(1.1000, 1.0950, 50.0) == "SELL")
check("price up, loss       -> SELL", side_of(1.1000, 1.1050, -50.0) == "SELL")
check("a flat exit is unknown, not a guess", side_of(1.1, 1.1, 5.0) is None)
check("a zero P&L is unknown, not a guess", side_of(1.1, 1.2, 0.0) is None)
check("a missing exit is unknown", side_of(1.1, None, 5.0) is None)
check("the real losing USDCHF row derives as SELL",
      side_of(0.8045, 0.80912, -89.48) == "SELL",
      "the journal recorded no side, and the screen drew it as LONG")
check("this is the expression the broker actually uses",
      '"BUY" if ((exit_ - entry) > 0) == (gross > 0) else "SELL"' in CT)
# The docstring names the field in order to warn about it, so this looks for
# the field being READ, not merely mentioned.
check("the deal's own tradeSide is never read for direction",
      ".tradeSide" not in CT.split("def get_deal_history")[1].split("\n    def ")[0],
      "a closing deal's side is the OPPOSITE of the position's")

print("\n8. The deal reader separates 'no trades' from 'could not ask'")
_GDH = CT.split("def get_deal_history")[1].split("\n    def ")[0]
check("it reports ok", '"ok": ok' in _GDH)
check("...set only after a page actually came back", "ok = True" in _GDH)
check("paging is bounded", "for _ in range(max_pages)" in _GDH)
check("...and cannot spin without progress", "if newest <= cur:" in _GDH)
check("the opening leg is kept for the open time", "opened[_pid]" in _GDH)
check("...the earliest one, since a position can be built from several fills",
      "_t < opened[_pid]" in _GDH)
check("money is scaled by the deal's own digits", "gross = cpd.grossProfit / scale" in _GDH)

print("\n9. The tool cannot write by accident")
SRC = open(os.path.join(ROOT, "scripts", "backfill_trades.py"),
           encoding="utf-8").read()
check("apply is opt-in", 'action="store_true"' in SRC and '"--apply"' in SRC)
check("a dry run returns before any write",
      SRC.index("if not apply:") < SRC.index("user_store.save_trades"))
check("a backup is taken before the write",
      SRC.index("json.dump(user_store.load_trades")
      < SRC.index("user_store.save_trades"))
check("a failed backup aborts instead of writing",
      "could not write the backup" in SRC
      and SRC.index("could not write the backup")
      < SRC.index("user_store.save_trades"))
check("an unreadable deal history aborts",
      'if not res.get("ok"):' in SRC and "Nothing was changed." in SRC)
check("a paper account is skipped", 'user.get("paper", True)' in SRC)
check("it never places or closes anything",
      not any(x in SRC for x in ("place_order", "force_close", "close_position",
                                 "amend_sltp")))

print("\n10. The store's rewrite is bounded and refuses bad input")
US = open(os.path.join(ROOT, "apex", "user_store.py"), encoding="utf-8").read()
_SAVE = US.split("def save_trades")[1].split("\ndef ")[0]
check("save_trades exists", "def save_trades(" in US)
check("...it rejects a non-list", "raise TypeError" in _SAVE)
check("...and keeps the NEWEST 500", "trades[-500:]" in _SAVE,
      "slicing from the front would silently drop the most recent trades")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL BACKFILL CHECKS PASSED - gaps filled, history untouched, guesses refused.")
