"""A closed trade must say which strategy, at which version, opened it.

Blueprint §14. Without both, comparing strategies on real results is
guesswork: the journal knows the outcome but not what produced it, and a
strategy whose logic changed last week is indistinguishable in the record
from the one that actually traded.

The plumbing has three hops, and a break in any one of them loses the label
silently — the trade still journals, just unlabelled, exactly like the
confidence/regime snapshot did before it was fixed:

    signal  --stamped-->  position (entry* keys)  --survives-->  journal row
                              ^                                      ^
                     must outlive a broker re-read        the row ev.calibrate
                     on every tick, hours later           and the tax export read

This exercises those hops for real rather than grepping the source.

Run: python tests/test_strategy_provenance.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-prov-")

from apex import strategy_api, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n── the registry is populated when the loop is imported ──")
avail = strategy_api.available()
check("strategies are registered", len(avail) >= 10, str(avail))
check("the live default is among them", "mean_reversion" in avail, str(avail))
check("importing user_loop was enough (no manual load_builtins needed)",
      strategy_api.get("mean_reversion") is not None)

print("\n── every registered strategy carries a version ──")
for row in strategy_api.describe():
    ok = bool(row["strategy_id"].strip()) and bool(row["strategy_version"].strip())
    check(f"{row['strategy_id']} is versioned", ok, str(row))

print("\n── a module stamps its verdict with its own identity ──")
mod = strategy_api.get("mean_reversion")
prov = mod.provenance()
check("provenance names the strategy", prov["strategy_id"] == "mean_reversion", str(prov))
check("and its version", prov["strategy_version"] == "1.0.0", str(prov))
stamped = mod.stamp({"action": "BUY", "confidence": 73})
check("stamping preserves the verdict",
      stamped["action"] == "BUY" and stamped["confidence"] == 73, str(stamped))
check("and adds both provenance keys",
      stamped["strategy_id"] == "mean_reversion"
      and stamped["strategy_version"] == "1.0.0", str(stamped))

print("\n── provenance survives the broker re-read that happens every tick ──")
# The loop throws the position dict away each tick and replaces it with a
# fresh broker read, which never carries entry* keys. This is the mechanism
# that keeps the snapshot alive across that.
pos = {"symbol": "EURUSD", "side": "BUY", "entryPrice": 1.1,
       "entryConfidence": 73, "entryStrategyId": "mean_reversion",
       "entryStrategyVersion": "1.0.0"}
meta = user_loop._entry_meta(pos)
check("the strategy id is part of the snapshot",
      meta.get("entryStrategyId") == "mean_reversion", str(meta))
check("so is the version", meta.get("entryStrategyVersion") == "1.0.0", str(meta))

fresh_from_broker = {"symbol": "EURUSD", "side": "BUY", "entryPrice": 1.1}
rejoined = user_loop._reattach_entry_meta(fresh_from_broker, meta)
check("a bare broker read gets the strategy back",
      rejoined.get("entryStrategyId") == "mean_reversion", str(rejoined))
check("including the version",
      rejoined.get("entryStrategyVersion") == "1.0.0", str(rejoined))

print("\n── and reaches the journal row the calibrator reads ──")
uid = "prov-test-1"
user_store.clear_trades(uid)
user_loop._log_trade(uid, {
    "time": "2026-08-14 09:00:00", "symbol": "EURUSD", "entryPrice": 1.1,
    "price": 1.105, "grossPnl": 50.0, "costUsd": 1.0, "netPnl": 49.0,
    "balance": 3000.0,
}, pos=rejoined)
rows = user_store.load_trades(uid)
check("the trade was journalled", len(rows) == 1, str(len(rows)))
row = rows[0] if rows else {}
check("the row names the strategy", row.get("strategyId") == "mean_reversion", str(row))
check("and its version", row.get("strategyVersion") == "1.0.0", str(row))
check("without losing the existing decision snapshot",
      row.get("confidence") == 73, str(row))

print("\n── a trade closed with no position still journals, just unlabelled ──")
user_store.clear_trades(uid)
user_loop._log_trade(uid, {
    "time": "2026-08-14 10:00:00", "symbol": "GBPUSD", "entryPrice": 1.35,
    "price": 1.351, "grossPnl": 10.0, "costUsd": 1.0, "netPnl": 9.0,
    "balance": 3009.0,
}, pos=None)
rows = user_store.load_trades(uid)
check("broker-side reconciliation still records the trade", len(rows) == 1)
check("with the strategy simply absent, not invented",
      rows and rows[0].get("strategyId") is None, str(rows[:1]))

print("\n── a mismatched position must not mislabel a trade ──")
user_store.clear_trades(uid)
wrong = dict(rejoined)
wrong["symbol"] = "USDJPY"          # position disagrees with the record
user_loop._log_trade(uid, {
    "time": "2026-08-14 11:00:00", "symbol": "EURUSD", "entryPrice": 1.1,
    "price": 1.102, "grossPnl": 20.0, "costUsd": 1.0, "netPnl": 19.0,
    "balance": 3028.0,
}, pos=wrong)
rows = user_store.load_trades(uid)
check("the row is still written", len(rows) == 1)
check("but carries NO strategy rather than the wrong one",
      rows and rows[0].get("strategyId") is None, str(rows[:1]))

print("\n── the advisory cannot become an override ──")
class Greedy(strategy_api.Strategy):
    strategy_id = "_greedy_probe"
    strategy_version = "0.0.1"

    def advise_risk(self, market):
        return {"multiplier": 99, "override_risk_engine": True,
                "bypass_daily_loss": True}


g = Greedy()
advice = g.risk(object())
check("an absurd multiplier is clamped to the band",
      advice["multiplier"] == strategy_api.ADVISORY_MAX, str(advice))
check("override keys are stripped", "override_risk_engine" not in advice, str(advice))
check("bypass keys too", "bypass_daily_loss" not in advice, str(advice))
check("and it is marked advisory", advice.get("advisory") is True, str(advice))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL STRATEGY-PROVENANCE CHECKS PASSED.")
