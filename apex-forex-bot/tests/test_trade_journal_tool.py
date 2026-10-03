"""The journal tool reports what is measurable, not just what happened.

WHY IT EXISTS

`dash["trades"]` is capped at 50 AND rebuilt in memory, so after a restart it
holds only what has closed since. An analysis of "what actually works" could
therefore only ever see the last few days — which is how a 131-trade history
got read as 16 trades.

THE DISTINCTION THIS TOOL HAS TO PRESERVE

Total is not sample size. A row without a confidence carries no regime, no
strategy version and no entry snapshot; it says a trade happened and what it
paid, and it cannot say why. Reading 131 rows as 131 observations is how a
system gets tuned on rows nobody can explain.

So `total` and `labelled` are returned as separate fields, and `labelled` is
computed by ev.labelled_count — the platform's own definition — rather than by
a second rule that could drift from it.

Run: python tests/test_trade_journal_tool.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import control_actions, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


# Five labelled rows and five orphans — the real shape of this account's
# journal, where a restart lost the entry snapshot for the broker-closed ones.
LABELLED = [{"time": f"2026-08-{d:02d} 10:00:00", "symbol": "EURUSD",
             "side": "SELL", "netPnl": 10.0, "confidence": 80,
             "regime": "ranging", "strategyId": "fibonacci",
             "strategyVersion": "1.0.0",
             "entryProbability": 0.5, "somethingElse": "must not appear"}
            for d in range(1, 6)]
ORPHANS = [{"time": f"2026-08-{d:02d} 11:00:00", "symbol": "USDCHF",
            "side": None, "netPnl": -5.0, "confidence": None}
           for d in range(6, 11)]

_real_load = user_store.load_trades
user_store.load_trades = lambda uid: (LABELLED + ORPHANS) if uid != "empty" else []
H = control_actions.build()
journal = H["trade_journal"]

print("\n1. The tool is registered")
check("trade_journal is in the handler table", "trade_journal" in H)

print("\n2. Total and labelled are separate numbers")
r = journal({"user_id": "u1"})
check("total counts every row", r["total"] == 10, str(r["total"]))
check("labelled counts only measurable rows", r["labelled"] == 5, str(r["labelled"]))
check("they are distinct fields", r["total"] != r["labelled"],
      "a caller reading total as sample size would measure rows it cannot explain")
from apex import ev  # noqa: E402
check("labelled uses the platform's own definition",
      r["labelled"] == ev.labelled_count(LABELLED + ORPHANS),
      "a second rule here could drift from the calibrator's")

print("\n3. labelled_only returns only what can be analysed")
r2 = journal({"user_id": "u1", "labelled_only": True})
check("it filters", r2["returned"] == 5, str(r2["returned"]))
check("every row has a confidence",
      all(t.get("confidence") is not None for t in r2["trades"]))
check("...and total still reports the whole journal", r2["total"] == 10,
      "filtering the view must not misreport the account's history")

print("\n4. Only declared fields leave the process")
check("an undeclared field is dropped",
      not any("somethingElse" in t for t in r["trades"]),
      "an allowlist, so a new journal field cannot leak by default")
check("a labelled row carries what analysis needs",
      {"time", "symbol", "netPnl", "confidence", "regime", "strategyVersion"}
      <= set(r2["trades"][0]))
check("an unlabelled row carries only what it has",
      "regime" not in r["trades"][0] and "netPnl" in r["trades"][0],
      "the allowlist filters per row, so an orphan is not padded with nulls")

print("\n5. The answer is bounded")
check("a huge limit is clamped", journal({"user_id": "u1", "limit": 9999})["returned"] <= 500)
check("zero does not return nothing", journal({"user_id": "u1", "limit": 0})["returned"] >= 1)
check("None does not raise", journal({"user_id": "u1", "limit": None})["returned"] >= 1)

print("\n6. Newest first")
check("the most recent row leads",
      r["trades"][0]["time"].startswith("2026-08-10"), r["trades"][0]["time"])

print("\n7. An empty journal is empty, not an error")
e = journal({"user_id": "empty"})
check("it returns zeros", e["total"] == 0 and e["labelled"] == 0 and e["trades"] == [])

print("\n8. It reads and nothing else")
_src = ast.parse(open(os.path.join(ROOT, "apex", "control_actions.py"),
                      encoding="utf-8").read())
_fn = next((n for n in ast.walk(_src)
            if isinstance(n, ast.FunctionDef) and n.name == "h_trade_journal"), None)
check("the handler exists", _fn is not None)
_calls = {n.func.attr for n in ast.walk(_fn)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check(f"it calls nothing that writes or trades ({sorted(_calls)})",
      not (_calls & {"place_order", "force_close", "close_position", "update",
                     "save", "save_trades", "amend_sltp", "get_open_position"}))

print("\n9. The MCP surface exposes it, and the security note knows")
MCP = open(os.path.join(os.path.dirname(ROOT), "ruflo-mcp", "server.py"),
           encoding="utf-8").read()
check("the tool is declared", "def trade_journal(" in MCP)
check("...and routed to the handler", '_call(product, "trade_journal"' in MCP)
check("the unguessable-path note lists it",
      "user_detail, trade_journal, audit_log" in MCP,
      "it exposes client records, same as the tools already named there")

user_store.load_trades = _real_load

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL JOURNAL-TOOL CHECKS PASSED - total is not sample size.")
