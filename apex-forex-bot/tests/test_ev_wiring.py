"""Integration test: does a closed trade actually reach the calibrator labelled?

The EV gate is only as good as the data behind it. This checks the whole
handoff — entry snapshot on the position → _log_trade → journal → calibrate —
because a break anywhere in that chain leaves the calibrator permanently
starved while everything still *looks* fine at runtime.

Run: python tests/test_ev_wiring.py
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

# Point the store at a scratch dir before importing anything that reads it.
_tmp = tempfile.mkdtemp(prefix="apex-ev-test-")
os.environ["DATA_DIR"] = _tmp
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


UID = "ev-wiring-test-user"
try:
    user_store.clear_trades(UID)
except Exception:
    pass

print("\n── entry snapshot survives into the journal ──")

# What the loop attaches to open_pos at entry.
position = {
    "side": "BUY", "entryPrice": 1.0850, "symbol": "EUR_USD", "units": 1000,
    "openedAt": "2026-08-11 09:00:00",
    "entrySpreadPips": 0.8,
    "entryConfidence": 84,
    "entryRegime": "trending",
    "entryAtr": 0.0009,
    "entrySlPips": 11.25,
    "entryTpPips": 19.13,
    "entrySide": "BUY",
    "entryProbability": 0.71,
    "entryEvR": 0.28,
}
# What the loop builds at close.
close_record = {
    "action": "CLOSE", "symbol": "EUR_USD", "price": 1.0869,
    "entryPrice": 1.0850, "grossPnl": 19.0, "costUsd": 0.8,
    "netPnl": 18.2, "balance": 1018.2,
    "reason": "TAKE_PROFIT", "openedAt": "2026-08-11 09:00:00",
    "time": "2026-08-11 10:00:00",
}

user_loop._log_trade(UID, close_record, position)
rows = user_store.load_trades(UID)
check("trade written", len(rows) == 1, f"got {len(rows)}")

row = rows[0]
check("confidence labelled", row.get("confidence") == 84, str(row.get("confidence")))
check("regime labelled", row.get("regime") == "trending", str(row.get("regime")))
check("spread labelled", row.get("spreadPips") == 0.8, str(row.get("spreadPips")))
check("sl/tp labelled", row.get("slPips") == 11.25 and row.get("tpPips") == 19.13)
check("probability labelled", row.get("probability") == 0.71)
check("ev labelled", row.get("evR") == 0.28)
check("accounting fields intact",
      row.get("netPnl") == 18.2 and row.get("exit") == 1.0869
      and row.get("entry") == 1.0850)

print("\n── record wins over position on overlapping keys ──")
user_store.clear_trades(UID)
user_loop._log_trade(UID, {**close_record, "netPnl": -5.0},
                     {**position, "netPnl": 999.0})
check("close record's P&L is authoritative",
      user_store.load_trades(UID)[0]["netPnl"] == -5.0)

print("\n── unlabelled rows still persist (accounting must not break) ──")
user_store.clear_trades(UID)
user_loop._log_trade(UID, close_record)          # no position passed
row = user_store.load_trades(UID)[0]
check("row written without a position", row.get("netPnl") == 18.2)
check("decision fields are None, not crashes", row.get("confidence") is None)

print("\n── journal → calibrate round-trip ──")
user_store.clear_trades(UID)


def _synth(i, conf, win):
    """One distinct closed trade. Each needs its own positionId and entry —
    the close deduper (correctly) collapses identical closes on the same pair,
    so a fixture of N byte-identical rows would write exactly one."""
    return (
        {**close_record,
         "netPnl": 20.0 if win else -12.0,
         "entryPrice": round(1.0850 + i * 0.0001, 5),
         "time": f"2026-08-11 {9 + i // 60:02d}:{i % 60:02d}:00"},
        {**position,
         "entryConfidence": conf,
         "positionId": 900000 + i,
         "entryPrice": round(1.0850 + i * 0.0001, 5)},
    )


for i in range(60):
    user_loop._log_trade(UID, *_synth(i, 84, i % 5 != 0))      # 80% hit rate
for i in range(60, 100):
    user_loop._log_trade(UID, *_synth(i, 55, i % 4 == 0))      # 25% hit rate

journal = user_store.load_trades(UID)
check("journal holds all trades", len(journal) == 100, f"got {len(journal)}")

cal = ev.calibrate(journal)
check("calibration builds from real journal rows", cal is not None)
if cal:
    p_hi = ev.calibrated_probability(84, cal)
    p_lo = ev.calibrated_probability(55, cal)
    check("high-confidence bucket has the higher measured probability",
          p_hi > p_lo, f"{p_hi} vs {p_lo}")
    check("probabilities are plausible, not the raw confidence",
          0.3 < p_hi < 0.9 and p_hi != 0.84, f"got {p_hi}")

    # The whole point: the gate now runs on measured data.
    verdict = ev.evaluate(confidence=84, calibration=cal, atr_pips=9.0,
                          spread_pips=0.8, regime="trending", equity=1000.0)
    check("gate reaches a verdict from journal-derived data",
          verdict["probability"] == p_hi and verdict["reason"] in
          ("APPROVED", "NEGATIVE_EV", "LOW_PROBABILITY"), verdict["reason"])

    weak = ev.evaluate(confidence=55, calibration=cal, atr_pips=9.0,
                       spread_pips=0.8, regime="trending", equity=1000.0)
    check("weak bucket is filtered out", not weak["approved"], weak["reason"])

print("\n── calibration refuses to guess before there is data ──")
user_store.clear_trades(UID)
for i in range(10):
    user_loop._log_trade(UID, *_synth(i, 84, i % 3 != 0))
check("ten distinct trades really were written",
      len(user_store.load_trades(UID)) == 10,
      str(len(user_store.load_trades(UID))))
check("too little history → no calibration",
      ev.calibrate(user_store.load_trades(UID)) is None)
check("and the gate stands aside rather than inventing a probability",
      ev.evaluate(confidence=84, calibration=None, atr_pips=9.0,
                  spread_pips=0.8, regime="trending",
                  equity=1000.0)["reason"] == "NO_PROBABILITY")

try:
    user_store.clear_trades(UID)
except Exception:
    pass

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL EV WIRING CHECKS PASSED.")
