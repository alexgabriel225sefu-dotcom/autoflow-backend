"""Regression test: the entry decision snapshot must survive the broker read.

In LIVE mode the loop replaces its tracked position with
`broker.get_open_position(symbol)` on every single tick. That dict is the
broker's truth — price, size, current stop — and it carries none of the
entry* fields the bot recorded when it decided to enter.

So the snapshot written at entry lived for exactly one tick. By the time the
trade closed it was gone, `_log_trade` wrote `confidence: None`, and
`ev.labelled_count()` skipped the row. Live symptom: evCalibration stuck at
1/30 while trades kept closing, meaning the probability model could never be
built and every EV decision ran on the fallback.

The same loss booked the spread half of realised cost at $0 on every live
close, because entrySpreadPips is in the same set of fields.

Run: python tests/test_entry_meta_survives.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-entrymeta-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import ev, user_store, user_loop  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


UID = "entry-meta-test"
user_store.clear_trades(UID)

# What the loop builds at entry (mirrors the snapshot block in _loop).
AT_ENTRY = {
    "symbol": "EURUSD", "side": "BUY", "entryPrice": 1.0842,
    "units": 20000, "stopLoss": 1.0830, "takeProfit": 1.0862,
    "entrySpreadPips": 0.9, "openedAt": "2026-08-12 09:14:02",
    "entryConfidence": 79, "entryRegime": "trending", "entryAtr": 0.00061,
    "entrySlPips": 12.0, "entryTpPips": 20.4, "entrySide": "BUY",
    "entryProbability": 0.61, "entryEvR": 0.18,
}

# What cTrader hands back on the next tick — no idea why we entered.
FROM_BROKER = {
    "symbol": "EURUSD", "side": "BUY", "entryPrice": 1.0842,
    "units": 20000, "quantity": 20000,
    "stopLoss": 1.0836, "takeProfit": 1.0862,   # stop has already trailed
}

print("\n── the snapshot is extracted out-of-band ──")
meta = user_loop._entry_meta(AT_ENTRY)
check("confidence captured", meta.get("entryConfidence") == 79)
check("spread captured", meta.get("entrySpreadPips") == 0.9)
check("EV probability captured", meta.get("entryProbability") == 0.61)
check("only entry* / openedAt keys, no market state",
      set(meta) <= set(user_loop._ENTRY_META_KEYS), str(sorted(meta)))
check("price and size are NOT copied (broker owns those)",
      "entryPrice" not in meta and "units" not in meta)

print("\n── the broker read alone loses everything ──")
naked = dict(FROM_BROKER)
check("broker dict has no confidence", naked.get("entryConfidence") is None)
check("broker dict has no spread", naked.get("entrySpreadPips") is None)

print("\n── reattaching restores it without overwriting broker truth ──")
restored = user_loop._reattach_entry_meta(dict(FROM_BROKER), meta)
check("confidence restored", restored.get("entryConfidence") == 79)
check("spread restored", restored.get("entrySpreadPips") == 0.9)
check("regime restored", restored.get("entryRegime") == "trending")
check("openedAt restored", restored.get("openedAt") == "2026-08-12 09:14:02")
check("the TRAILED stop is kept — broker wins on what it knows",
      restored.get("stopLoss") == 1.0836, str(restored.get("stopLoss")))

print("\n── a value already on the position is never clobbered ──")
partial = user_loop._reattach_entry_meta(
    {**FROM_BROKER, "entryConfidence": 91}, meta)
check("existing entryConfidence survives", partial.get("entryConfidence") == 91)

print("\n── missing / empty inputs are handled ──")
check("no meta → position returned untouched",
      user_loop._reattach_entry_meta(dict(FROM_BROKER), None) == FROM_BROKER)
check("flat (None position) → None",
      user_loop._reattach_entry_meta(None, meta) is None)
check("empty position dict extracts an empty snapshot",
      user_loop._entry_meta({}) == {} and user_loop._entry_meta(None) == {})

print("\n── end to end: close journalled off the broker-read position ──")
CLOSE = {"action": "CLOSE", "symbol": "EURUSD", "price": 1.0862,
         "entryPrice": 1.0842, "grossPnl": 40.0, "costUsd": 1.8,
         "netPnl": 38.2, "balance": 3028.0, "time": "2026-08-12 10:41:00"}

user_store.clear_trades(UID)
user_loop._log_trade(UID, CLOSE, dict(FROM_BROKER))   # the old behaviour
check("BEFORE the fix this row is unlabelled",
      ev.labelled_count(user_store.load_trades(UID)) == 0)

user_store.clear_trades(UID)
user_loop._log_trade(UID, CLOSE, user_loop._reattach_entry_meta(
    dict(FROM_BROKER), meta))
row = user_store.load_trades(UID)[0]
check("AFTER the fix the row carries the confidence", row.get("confidence") == 79)
check("and the entry spread", row.get("spreadPips") == 0.9)
check("and the EV probability", row.get("probability") == 0.61)
check("it counts toward calibration",
      ev.labelled_count(user_store.load_trades(UID)) == 1)

print("\n── 30 such closes actually build a calibration table ──")
user_store.clear_trades(UID)
for i in range(30):
    pos = user_loop._reattach_entry_meta(
        dict(FROM_BROKER), {**meta, "entryConfidence": 60 + (i % 25)})
    won = i % 3 != 0          # 20 wins / 10 losses
    user_loop._log_trade(UID, {
        **CLOSE,
        "entryPrice": round(1.0842 + i * 1e-4, 6),
        "netPnl": 38.2 if won else -22.5,
        "time": f"2026-07-{(i % 28) + 1:02d} 10:41:00",
    }, pos)

journal = user_store.load_trades(UID)
check("all 30 closes were journalled (no false dedupe)",
      len(journal) == 30, f"got {len(journal)}")
check("all 30 are labelled", ev.labelled_count(journal) == 30,
      str(ev.labelled_count(journal)))
cal = ev.calibrate(journal, min_total=30)
check("calibrate() now returns a table", cal is not None)
if cal:
    check("it measured the real 2/3 hit rate", abs(cal["overall"] - 2 / 3) < 0.02,
          str(cal["overall"]))
    check("a probability comes back from the table",
          ev.calibrated_probability(79, cal) is not None)

user_store.clear_trades(UID)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL ENTRY-SNAPSHOT SURVIVAL CHECKS PASSED.")
