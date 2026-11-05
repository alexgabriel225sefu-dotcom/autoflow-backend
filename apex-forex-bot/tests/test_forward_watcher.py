"""Forward watcher records closed-bar decisions without an order path."""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="a4t-forward-watcher-"))

from apex import user_store
from apex.platform import broker_read, ruledoc, forward_watcher


def check(label, condition, detail=""):
    if not condition:
        raise AssertionError(f"{label}: {detail}")
    print(f"  ok   {label}")


uid = "forward-watcher-user"
now = 2_000_000_000.0
rule = ruledoc.blank(user_id=uid, account_id="demo", symbols=["EUR_USD"], timeframe="1h")
rule.update({"ruleDocId": "rule-forward", "state": "active", "sides": "BUY"})
rule["entry"] = {"combine": "AND", "conditions": [
    {"id": "weekday", "params": {"days": [0, 1, 2, 3, 4, 5, 6]}},
]}
rule["exit"] = {"combine": "OR", "conditions": [
    {"id": "rsi", "params": {"op": "above", "value": 100}},
]}
bars = [
    {"time": now - 7200, "open": 1.1000, "high": 1.1100,
     "low": 1.0900, "close": 1.1050},
    {"time": now - 3600, "open": 1.1050, "high": 1.1150,
     "low": 1.1000, "close": 1.1100},
]

old_dir, old_redis = user_store._DIR, user_store._USE_REDIS
user_store._DIR, user_store._USE_REDIS = tempfile.mkdtemp(prefix="a4t-forward-"), False
forward_watcher._seen.clear()
try:
    def active(_uid):
        return [rule]

    def candles(_uid, **_kwargs):
        return {"status": broker_read.OK, "candles": bars}

    def quote(_uid, **_kwargs):
        return {"status": broker_read.OK, "bid": 1.1098, "ask": 1.1102,
                "receivedAt": now + 10}

    first = forward_watcher.run_once(
        now=now, user_ids=[uid], platform_reader=lambda _uid: True,
        active_reader=active, candle_reader=candles, quote_reader=quote)
    rows = user_store.load(uid).get("forwardEvents") or []
    check("one closed bar is recorded", first["recorded"] == 1 and len(rows) == 1)
    check("signal decision and execution are separate", rows[0]["signal"] == "BUY"
          and rows[0]["decision"] == "BUY"
          and rows[0]["execution"]["status"] == "pending")

    second = forward_watcher.run_once(
        now=now + 30, user_ids=[uid], platform_reader=lambda _uid: True,
        active_reader=active, candle_reader=candles, quote_reader=quote)
    rows = user_store.load(uid).get("forwardEvents") or []
    check("the later quote resolves the hypothetical execution",
          second["resolved"] == 1 and rows[0]["execution"]["status"] == "priced")
    check("slippage uses the later executable ask",
          rows[0]["execution"]["price"] == 1.1102
          and abs(rows[0]["execution"]["slippage"] - 0.0002) < 1e-9)

    reads = []

    def counting_candles(_uid, **kwargs):
        reads.append(kwargs.get("symbol"))
        return {"status": broker_read.OK, "candles": bars}

    third = forward_watcher.run_once(
        now=now + 60, user_ids=[uid], platform_reader=lambda _uid: True,
        active_reader=active, candle_reader=counting_candles, quote_reader=quote)
    check("the same closed bar is not duplicated", third["recorded"] == 0
          and len(user_store.load(uid).get("forwardEvents") or []) == 1)
    check("no broker read while no new bar can have closed",
          reads == [] and third["reads"] == 0, str(reads))
    later_bars = bars + [{"time": now, "open": 1.1100, "high": 1.1200,
                          "low": 1.1050, "close": 1.1150}]

    def later_candles(_uid, **kwargs):
        reads.append(kwargs.get("symbol"))
        return {"status": broker_read.OK, "candles": later_bars}

    fourth = forward_watcher.run_once(
        now=now + 3605, user_ids=[uid], platform_reader=lambda _uid: True,
        active_reader=active, candle_reader=later_candles, quote_reader=quote)
    check("it reads again once the next bar has closed",
          fourth["reads"] == 1 and len(reads) == 1, str(fourth))
finally:
    user_store._DIR, user_store._USE_REDIS = old_dir, old_redis

print("ALL OK")
