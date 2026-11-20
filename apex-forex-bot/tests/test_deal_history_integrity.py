"""The broker's deal history is added up, and says when it is not complete.

FOUND BY AN INDEPENDENT REVIEW (two MEDIUM findings, both reproduced):

1. Closing deals were stored by position id and OVERWRITTEN, so a position
   closed in two parts kept only its last part: two closes of +50 and +70 became
   one row of +70, with half the volume. P&L, win rate and expectancy were wrong
   for any partially closed position.
2. If a later page of deals failed, the connector returned ok:true with the
   pages it had and an `error` beside them, and the platform read only `ok` —
   serving (and caching for a minute) a partial history as the whole account.
   Running out of pages did the same, silently.

WHAT THESE TESTS WILL NOT ACCEPT

* A position's parts not adding up, or the volume-weighted exit being wrong.
* A history that broke off, or was cut at the page budget, served as complete.
* A complete history being refused.

Run: python3 tests/test_deal_history_integrity.py
"""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-deals-")
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


from apex.brokers import ctrader as ct                       # noqa: E402
from apex.platform import broker_read as BR                  # noqa: E402

cls = [c for n, c in vars(ct).items() if isinstance(c, type) and hasattr(c, "get_deal_history")][0]


def broker():
    b = cls.__new__(cls)
    b._c = types.SimpleNamespace(PAPER_TRADING=False, CTRADER_ENV="demo")
    b._sym_id = {"EURUSD": 1}
    b._ctid = lambda: 1
    return b


class CPD:
    def __init__(s, gross, vol, swap=0, comm=0):
        s.grossProfit, s.swap, s.commission = gross, swap, comm
        s.moneyDigits, s.entryPrice, s.closedVolume = 2, 1.1, vol

    def HasField(s, f):
        return False


class Deal:
    def __init__(s, pid, ts, gross, vol, px, swap=0, comm=0):
        s.positionId, s.executionTimestamp, s.symbolId = pid, ts, 1
        s.executionPrice, s.moneyDigits, s.volume = px, 2, vol
        s.closePositionDetail = CPD(gross, vol, swap, comm)

    def HasField(self, f):
        return f == "closePositionDetail"


def page(deals, more=False):
    return types.SimpleNamespace(deal=deals, hasMore=more)


# ── 1. parts of one position add up ─────────────────────────────────────────
print("\n[1] a position closed in two parts is ONE row, with the parts added up")
b = broker()
pages = [page([Deal(42, 1_000_000, 5000, 50000, 1.11), Deal(42, 2_000_000, 7000, 50000, 1.12)])]
b._rpc = lambda req, c: pages.pop(0)
h = b.get_deal_history(0, 10_000)
row = h["deals"]["42"]
check("one row for the position", list(h["deals"]) == ["42"], str(list(h["deals"])))
check("net is the sum (50 + 70), not the last part", row["netPnl"] == 120.0, str(row["netPnl"]))
check("units are the sum", row["units"] == 1000.0, str(row["units"]))
check("exit price is the volume-weighted average", abs(row["exitPrice"] - 1.115) < 1e-9, str(row["exitPrice"]))
check("closed time is the latest part's", row["closedAt"] == 2000, str(row["closedAt"]))
check("a complete history carries no truncation flag", "truncated" not in h and "error" not in h)

print("\n[1b] swap and commission add up too; other positions are untouched")
b = broker()
pages = [page([Deal(1, 1_000_000, 1000, 10000, 1.1, swap=10, comm=-20),
               Deal(1, 2_000_000, 2000, 10000, 1.1, swap=30, comm=-40),
               Deal(2, 3_000_000, 500, 10000, 1.1)])]
b._rpc = lambda req, c: pages.pop(0)
d = b.get_deal_history(0, 10_000)["deals"]
check("position 1 swap summed (0.10 + 0.30)", d["1"]["swap"] == 0.4, str(d["1"]["swap"]))
check("position 1 commission summed (0.20 + 0.40)", d["1"]["commissionUsd"] == 0.6, str(d["1"]["commissionUsd"]))
check("position 2 is its own row, unchanged", d["2"]["netPnl"] == 5.0 and d["2"]["units"] == 100.0, str(d["2"]))

# ── 2. a history that broke off is not served as complete ───────────────────
print("\n[2] a failure on a later page is an error, not a partial success")
b = broker()
calls = {"n": 0}


def rpc(req, c):
    calls["n"] += 1
    if calls["n"] == 1:
        return page([Deal(42, 1_000_000, 5000, 50000, 1.11)], more=True)
    raise TimeoutError("cTrader: no response")


b._rpc = rpc
h = b.get_deal_history(0, 10_000)
check("the connector reports the error beside what it has", h.get("error") and len(h["deals"]) == 1, str(h))
try:
    BR._deal_rows(types.SimpleNamespace(get_deal_history=lambda a, z: h), 7)
    check("the platform read refuses it", False, "returned rows")
except RuntimeError as e:
    check("the platform read refuses it, naming the cause", "cut short" in str(e) and "no response" in str(e), str(e))

print("\n[2b] running out of pages is reported, not silent")
b = broker()
b._rpc = lambda req, c: page([Deal(next_id := (calls.__setitem__("n", calls["n"] + 1) or calls["n"]), 1_000_000 + calls["n"] * 1000, 100, 10000, 1.1)], more=True)
h = b.get_deal_history(0, 10_000_000, max_pages=3)
check("truncated is flagged", h.get("truncated") is True, str(h.keys()))
try:
    BR._deal_rows(types.SimpleNamespace(get_deal_history=lambda a, z: h), 7)
    check("the platform read refuses a truncated history", False)
except RuntimeError as e:
    check("the platform read refuses a truncated history", "longer than could be read" in str(e), str(e))

print("\n[2c] a complete history is accepted")
good = {"ok": True, "deals": {"42": {"symbol": "EURUSD", "side": "BUY", "units": 1.0, "entryPrice": 1.1,
                                     "exitPrice": 1.2, "netPnl": 5.0, "closedAt": 1, "positionId": "42"}}}
rows = BR._deal_rows(types.SimpleNamespace(get_deal_history=lambda a, z: good), 7)
check("one row comes back", len(rows) == 1 and rows[0]["net"] == 5.0, str(rows))

print("\n[3] the number of days is range-checked before it becomes a lock key")
calls_made = []
fb = types.SimpleNamespace(get_deal_history=lambda a, z: calls_made.append(1) or good)
conn = lambda *a, **k: {"ctid": "501", "mode": "demo"}              # noqa: E731
BR._deals_fetch_locks.clear()
for bad_days in (0, -1, 3651, 10**9):
    r = BR.deals("u", days=bad_days, ctid="501", connection_fn=conn, broker_fn=lambda: fb)
    check(f"days={bad_days}: unavailable with the reason", r["status"] == "unavailable" and "between 1 and 3650" in r["reason"], str(r))
check("and no lock entry was created for any of them", len(BR._deals_fetch_locks) == 0, str(len(BR._deals_fetch_locks)))
check("the broker was never asked", calls_made == [])
r = BR.deals("u", days=3650, ctid="501", connection_fn=conn, broker_fn=lambda: fb)
check("the top of the range is accepted (it is what 'All time' may need)", r["status"] == "ok", str(r))
r = BR.deals("u", days=7, ctid="501", connection_fn=conn, broker_fn=lambda: fb)
check("a valid range still works", r["status"] == "ok", str(r))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All deal-history checks passed.")
