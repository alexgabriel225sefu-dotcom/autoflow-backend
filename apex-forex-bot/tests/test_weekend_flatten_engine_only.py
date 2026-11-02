"""The weekend flatten closes the ENGINE's positions, not the client's manual ones.

It used to close every broker position on the account. A client who opened a
trade by hand and meant to hold it over the weekend had it closed by a bot
that never opened it.

Ownership, in order of evidence:
  * the position carries the engine's order label -> engine;
  * it carries some OTHER label -> not the engine's;
  * no label (opened before labels existed): engine only if the engine holds
    its entry record (entry meta for the symbol) or it is the tracked
    position. Anything else is left open and named in the alert.

Run: python tests/test_weekend_flatten_engine_only.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["PAPER_TRADING"] = "true"

from apex import user_loop  # noqa: E402
from apex.brokers import ctrader  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


L = ctrader.ENGINE_ORDER_LABEL
rows = [
    {"symbol": "EURUSD", "positionId": 1, "label": L},
    {"symbol": "GBPUSD", "positionId": 2, "label": "my-manual"},
    {"symbol": "XAUUSD", "positionId": 3},                 # legacy, engine meta
    {"symbol": "USDJPY", "positionId": 4},                 # legacy, unknown
    {"symbol": "AUDUSD", "positionId": 5},                 # tracked position
]
meta = {"XAUUSD": {"entryConfidence": 80}}
owned, left = user_loop._engine_positions(rows, meta, tracked_ids={"5"})
ids = {r["positionId"] for r in owned}
check("labelled engine position is closed", 1 in ids)
check("a position with another label is left", 2 not in ids)
check("legacy position with engine entry meta is closed", 3 in ids)
check("legacy position nobody recorded is left", 4 not in ids)
check("the tracked position is closed", 5 in ids)
check("the left-open ones are reported", sorted(left) == ["GBPUSD", "USDJPY"],
      str(left))
check("symbol spelling is normalised (EUR_USD meta matches EURUSD)",
      user_loop._engine_positions([{"symbol": "EURUSD", "positionId": 9}],
                                  {"EUR_USD": {"x": 1}}, set())[0] != [])

print("\n2. The broker reports the label it was given")
with open(os.path.join(ROOT, "apex", "brokers", "ctrader.py"), encoding="utf-8") as fh:
    CT = fh.read()
i = CT.find("def get_all_positions")
check("get_all_positions exposes tradeData.label",
      'row["label"] = td.label' in CT[i:i + 3000])

print("\n3. The weekend flatten uses it")
with open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8") as fh:
    SRC = fh.read()
i = SRC.find("_wk_targets = list(broker.get_all_positions() or [])")
check("broker positions are filtered to the engine's",
      "_engine_positions(" in SRC[i:i + 900], SRC[i:i + 900])
check("the alert names what was left", '"leftManual"' in SRC)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - the weekend flatten leaves manual trades alone.")
