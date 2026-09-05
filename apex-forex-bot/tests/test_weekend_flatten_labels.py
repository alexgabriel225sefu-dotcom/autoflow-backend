"""A trade closed by the weekend flatten is still a labelled observation.

THE DEFECT

_log_trade's own docstring says what the `pos` argument is for: "Its `entry*`
keys are the DECISION snapshot, and they are what turns a closed trade into a
labelled training example rather than just an accounting row ... ev.calibrate()
has nothing to learn from" without them.

The broker-close path passes the persisted snapshot:

    _meta = entry_meta_by_sym.get(cs)
    _log_trade(user_id, rec, {**_meta, "symbol": ...} if _meta else None)

The weekend flatten passed the raw position instead:

    _log_trade(user_id, result, open_pos)

For anything read back from broker.get_all_positions() that dict holds symbol,
side, entryPrice, stopLoss and units — and no entryConfidence, entryRegime or
entryStrategyId, because a broker does not record why a trade was taken. So
every position the Friday flatten closed was journalled unlabelled.

Measured on the live account, 2026-09-05: the journal went from 82 rows to 84
while `labelled` stayed at 42. Both new rows were opened by the bot, with full
metadata at entry, and both came back with confidence: null.

The flatten runs every Friday, so this quietly excluded a whole day of the
week from ev.calibrate() — the calibrator the EV gate reads.

Run: python tests/test_weekend_flatten_labels.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-wkend-lab-")

from apex import ev, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


UID = "wk1"
# What broker.get_all_positions() returns: no entry* keys at all.
FROM_BROKER = {"symbol": "EURUSD", "side": "BUY", "entryPrice": 1.16177,
               "stopLoss": 1.15927, "units": 36619}
# What the loop persisted at entry, keyed by symbol.
PERSISTED = {"symbol": "EURUSD", "entryConfidence": 73, "entryRegime": "ranging",
             "entrySlPips": 25.0, "entryTpPips": 50.0, "entrySide": "BUY",
             "entryStrategyId": "fibonacci", "entryStrategyVersion": "1.0.0",
             "entrySpreadPips": 0.1, "entryProbability": 0.46, "entryEvR": 0.36}
ROW = {"action": "CLOSE", "symbol": "EURUSD", "price": 1.16144,
       "entryPrice": 1.16177, "side": "BUY", "grossPnl": -11.88,
       "costUsd": 1.08, "netPnl": -12.96, "balance": 3057.06,
       "time": "2026-09-04 20:01:34"}

print("\n1. The raw broker position cannot label a row — that is the defect")
user_store.save_trades(UID, [])
user_loop._log_trade(UID, ROW, FROM_BROKER)
rows = user_store.load_trades(UID)
check("the row is written for accounting", len(rows) == 1)
check("but it carries no confidence", rows[0].get("confidence") is None)
check("so the calibrator cannot see it", ev.labelled_count(rows) == 0)

print("\n2. The persisted snapshot labels it")
user_store.save_trades(UID, [])
user_loop._log_trade(UID, ROW, PERSISTED)
rows = user_store.load_trades(UID)
check("confidence survives", rows[0].get("confidence") == 73)
check("regime survives", rows[0].get("regime") == "ranging")
check("strategy survives", rows[0].get("strategyId") == "fibonacci")
check("the calibrator counts it", ev.labelled_count(rows) == 1)

print("\n3. The flatten passes the snapshot, not the broker dict")
SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
_blk = SRC[SRC.index("Closed before the weekend"):]
_blk = _blk[:_blk.index("strategies.record_trade")]
_code = "\n".join(l.split("#")[0] for l in _blk.splitlines())
check("it reaches for the persisted entry metadata",
      "entry_meta_by_sym" in _code,
      "passing the broker's position dict labels nothing")
check("_log_trade is still the single journalling call",
      _code.count("_log_trade(") == 1)

print("\n3b. The news flatten has the same shape and the same fix")
# It was written from the weekend flatten and inherited the defect: `_np` is a
# row from broker.get_all_positions(), so it labels nothing either.
_nb = SRC[SRC.index('origin="news_exit"'):]
_nb = _nb[:_nb.index("NEWS_FLATTEN")]
_ncode = "\n".join(l.split("#")[0] for l in _nb.splitlines())
check("it also reaches for the persisted entry metadata",
      "entry_meta_by_sym" in _ncode,
      "the news exit journalled unlabelled rows for the same reason")
check("it does not pass the broker's position dict",
      "_log_trade(user_id, result, _np)" not in _ncode)

print("\n4. A position with no snapshot is still journalled, just unlabelled")
# Never lose an accounting row to a missing label — the tax export reads this.
user_store.save_trades(UID, [])
user_loop._log_trade(UID, ROW, None)
check("the row is still written", len(user_store.load_trades(UID)) == 1)

print("\n5. The mismatch guard still protects the row")
user_store.save_trades(UID, [])
user_loop._log_trade(UID, ROW, {**PERSISTED, "symbol": "GBPUSD"})
rows = user_store.load_trades(UID)
check("another instrument's entry data is refused",
      rows[0].get("confidence") is None,
      "a snapshot filed under the wrong symbol must not label this row")

print("\n" + "=" * 62)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED — Friday's trades reach the calibrator.")
