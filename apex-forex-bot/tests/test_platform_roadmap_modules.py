import contextlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="a4t-roadmap-"))
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"



class pytest:                                   # tests/run_all.py runs files as scripts
    @staticmethod
    @contextlib.contextmanager
    def raises(exc):
        try:
            yield
        except exc:
            return
        raise AssertionError(f"{exc.__name__} was not raised")


from apex.platform import backtest, broker_read, forward, health_score, incidents, multi_account, ruledoc
from apex.platform import overfit, replay, risk_guard, risk_map, rule_layer


def test_rule_layer_rejects_unknown_and_rounds_volume():
    spec = rule_layer.normalise_instrument("EURUSD", price=1.1)
    assert spec.symbol == "EURUSD"
    assert rule_layer.round_volume(1234, spec) == 1000
    with pytest.raises(ValueError):
        rule_layer.normalise_instrument("UNKNOWN")


def test_risk_guard_fails_closed_on_unknown_state():
    result = risk_guard.evaluate({"stopAll": False})
    assert result["allowed"] is False
    assert "weekly_loss" in {item["guard"] for item in result["blocks"]}


def test_risk_map_does_not_turn_missing_stops_into_zero():
    result = risk_map.build([{"symbol": "EURUSD", "side": "BUY", "units": 1000}])
    assert result["unreadablePositions"] == 1
    assert "unknown stop risk" in result["warnings"][0]


def test_risk_map_reports_currency_and_correlation_exposure():
    result = risk_map.build([
        {"symbol": "EUR_USD", "side": "BUY", "units": 1000, "riskToStop": 12},
        {"symbol": "GBP_USD", "side": "BUY", "units": 500, "riskToStop": 8},
    ], balance=1000)
    assert result["currencyExposure"]["USD"] == -1500
    assert result["lossIfEveryStopHit"] == 20
    assert result["correlatedPairs"]
    assert result["gapScenario"]["status"] == "unknown"


def test_incidents_persist_observed_fields_for_account_data_lifecycle():
    import apex.user_store as us
    old_dir, old_redis = us._DIR, us._USE_REDIS
    us._DIR, us._USE_REDIS = tempfile.mkdtemp(prefix="a4t-incidents-"), False
    try:
        out = incidents.record("incident-user", {"brokerStatus": "unavailable",
                                                  "affectedScope": "demo account",
                                                  "systemAction": "paused reads",
                                                  "traderActionRequired": True})
        row = out["incidents"][0]
        assert {"startedAt", "affectedScope", "systemAction", "traderActionRequired",
                "recoveredAt"} <= set(row)
        assert us.load("incident-user")["incidents"]
    finally:
        us._DIR, us._USE_REDIS = old_dir, old_redis


def test_multi_account_isolation_uses_user_store_adapter():
    import apex.user_store as us
    old_dir, old_redis = us._DIR, us._USE_REDIS
    us._DIR, us._USE_REDIS = tempfile.mkdtemp(prefix="a4t-accounts-"), False
    try:
        store = multi_account.UserStoreIsolation()
        store.put("alice", "a", {"balance": 1})
        store.put("alice", "b", {"balance": 2})
        store.put("bob", "a", {"balance": 99})
        store.set_kill("alice", "a", True, reason="one account")
        assert store.get("alice", "a")["balance"] == 1
        assert store.get("alice", "b")["balance"] == 2
        assert store.get("bob", "a")["balance"] == 99
        assert store.is_killed("alice", "a") is True
        assert store.is_killed("alice", "b") is False
        assert store.is_killed("bob", "a") is False
    finally:
        us._DIR, us._USE_REDIS = old_dir, old_redis


def test_health_and_incident_outputs_are_conservative():
    result = health_score.score({"brokerConnected": True})
    assert result["score"] < 100
    assert result["warnings"]
    assert incidents.derive({"brokerStatus": "unavailable"})["incidents"]
    disconnected = health_score.score({"brokerConnected": False,
                                       "ruleValid": True,
                                       "storeAvailable": True,
                                       "criticalIncidents": False})
    assert disconnected["status"] == "not_connected"
    assert disconnected["checks"]["data"] == "not_applicable"
    assert disconnected["checks"]["session"] == "not_applicable"
    assert any("Connect a cTrader account to check data and session." in w
               for w in disconnected["warnings"])
    assert not any("failed" in w for w in disconnected["warnings"])


def test_backtest_replay_forward_are_read_only():
    candles = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    result = backtest.run(candles, signal=lambda c: {"side": "BUY"}, initial_balance=100)
    assert result["hypothetical"] is True
    assert replay.timeline(candles)["readOnly"] is True
    assert forward.record([{"symbol": "EURUSD"}])["readOnly"] is True


def test_backtest_runs_the_shared_rule_evaluator():
    rule = ruledoc.blank(user_id="u", account_id="a", symbols=["EUR_USD"], timeframe="1h")
    rule["state"] = "active"
    rule["sides"] = "BUY"
    rule["entry"] = {"combine": "AND", "conditions": [
        {"id": "weekday", "params": {"days": [0, 1, 2, 3, 4, 5, 6]}}]}
    rule["exit"] = {"combine": "OR", "conditions": [
        {"id": "rsi", "params": {"op": "above", "value": 100}}]}
    candles = [{"time": 1758542400 + i * 3600, "open": 1.1,
                "high": 1.11, "low": 1.09, "close": 1.105}
               for i in range(20)]
    result = backtest.run(candles, rule=rule, symbol="EUR_USD", timeframe="1h")
    assert result["tradeCount"] > 0


def test_replay_reads_are_anchored_to_the_requested_past_window():
    calls = []

    class Broker:
        def get_candles(self, *args, **kwargs):
            calls.append((args, kwargs))
            return [{"open": 1, "high": 2, "low": 0.5, "close": 1.5}]

    result = broker_read.candles(
        "u", symbol="EUR_USD", timeframe="1h", limit=2,
        to_ts=1_700_000_000, connection_fn=lambda _uid, ctid=None: {
            "ctid": "a", "mode": "demo", "accessToken": "secret"},
        broker_fn=lambda: Broker())
    assert result["status"] == "ok"
    assert calls == [(("EUR_USD", "1h", 2), {"to_ts": 1_700_000_000.0})]


def test_overfit_and_multi_account_are_scoped():
    assert overfit.analyse({"conditionCount": 10})["warnings"]
    assert "unknown" in " ".join(overfit.analyse({})["warnings"])
    result = multi_account.isolate("u1", [{"ctid": 42, "mode": "demo"}])
    assert result["accounts"][0]["scope"] == "u1:42"


def test_backtest_converts_pips_and_refuses_when_nothing_to_run():
    candles = [{"open": 1.1000, "high": 1.1100, "low": 1.0900, "close": 1.1050}]
    with pytest.raises(ValueError):
        backtest.run(candles)                                   # no strategy
    with pytest.raises(ValueError):
        backtest.run(candles, signal=lambda c: {"side": "BUY"}, spread_pips=1.5)  # no symbol
    free = backtest.run(candles, signal=lambda c: {"side": "BUY"})
    costly = backtest.run(candles, signal=lambda c: {"side": "BUY"},
                          spread_pips=1.5, symbol="EURUSD")
    # 1.5 pips on EURUSD is 0.00015 in price, not 1.5.
    assert round(free["totalPnl"] - costly["totalPnl"], 8) == 0.00015
    assert "latency" in " ".join(costly["notModelled"])
    assert "partial fills" in costly["notModelled"]


def test_risk_guard_derives_real_trade_state_and_blocks_unreadable():
    measured = risk_guard.state_from_trades({
        "status": "ok", "trades": [
            {"closedAt": 1_800_000_000, "net": -20},
            {"closedAt": 1_800_000_100, "net": -10},
        ]}, {"balance": 1000}, now=1_800_000_200)
    assert measured["readable"] is True
    assert measured["consecutiveLosses"] == 2
    assert measured["tradesToday"] == 2
    assert risk_guard.evaluate(measured)["stopNewEntriesOnly"] is True
    unknown = risk_guard.state_from_trades({"status": "unavailable"}, {})
    assert risk_guard.evaluate(unknown)["allowed"] is False


def test_forward_persists_three_distinct_read_only_fields():
    import apex.user_store as us
    tmp_path = tempfile.mkdtemp(prefix="a4t-forward-")
    old_dir, old_redis = us._DIR, us._USE_REDIS
    us._DIR, us._USE_REDIS = str(tmp_path), False
    try:
        rule = ruledoc.blank(user_id="u", account_id="a", symbols=["EUR_USD"], timeframe="1h")
        rule["state"] = "active"
        rule["entry"] = {"combine": "AND", "conditions": [
            {"id": "weekday", "params": {"days": [0, 1, 2, 3, 4, 5, 6]}}]}
        result = forward.record_for_user("u", rule=rule,
                                         candles=[{"time": 1_800_000_000,
                                                   "open": 1.1, "high": 1.2,
                                                   "low": 1.0, "close": 1.15}],
                                         executable_price=1.151)
        event = result["events"][0]
        assert set(("signal", "decision", "execution")) <= set(event)
        assert event["execution"]["price"] == 1.151
        assert us.load("u")["forwardEvents"]
    finally:
        us._DIR, us._USE_REDIS = old_dir, old_redis


def test_overfit_counts_rule_history_without_typed_form_values():
    rule = {"symbols": ["EUR_USD", "GBP_USD"],
            "entry": {"conditions": [{"id": "a"}, {"id": "b"}]},
            "exit": {"conditions": [{"id": "c"}]}}
    result = overfit.analyse({"rule": rule, "versions": [],
                              "trades": [{"closedAt": 1_700_000_000, "net": 1}]})
    assert result["evidence"]["conditionCount"] == 3
    assert result["evidence"]["tradeCount"] == 1


def test_rule_layer_exposes_metadata_sources_and_unknown_stop_distance():
    out = rule_layer.risk_units(balance=1000, risk_fraction=.01,
                                stop_pips=10, symbol="EURUSD", price=1.1)
    meta = out["metadata"]
    assert meta["minLot"] == 1000
    assert meta["lotStep"] == 1000
    assert meta["contractSize"] == 100000
    assert meta["minimumStopDistancePips"] is None
    assert "minimumStopDistance" in meta["sources"]


def test_backtest_reports_risk_metrics_and_directional_breakdowns():
    candles = [{"time": 1_700_000_000 + i * 86400, "open": 1.1,
                "high": 1.2, "low": 1.0, "close": close}
               for i, close in enumerate((1.11, 1.09, 1.12))]
    signals = iter(({"side": "BUY", "entry": 1.10, "exit": 1.11},
                    {"side": "SELL", "entry": 1.10, "exit": 1.09},
                    {"side": "BUY", "entry": 1.10, "exit": 1.12}))
    result = backtest.run(candles, signal=lambda _c: next(signals), initial_balance=100)
    assert result["netProfit"] == result["totalPnl"]
    assert result["maxDrawdown"] is not None
    assert "profitFactor" in result
    assert len(result["equityCurve"]) == 3
    assert result["longVsShort"]["long"]["trades"] == 2
    assert result["longVsShort"]["short"]["trades"] == 1


def test_replay_explains_conditions_and_stop_without_lookahead():
    rule = ruledoc.blank(user_id="u", account_id="a", symbols=["EUR_USD"], timeframe="1h")
    rule["state"] = "active"
    rule["sides"] = "BUY"
    rule["entry"] = {"combine": "AND", "conditions": [
        {"id": "weekday", "params": {"days": [0, 1, 2, 3, 4, 5, 6]}}]}
    rule["stopLoss"] = {"mode": "pips", "pips": 10}
    candles = [{"time": 1_758_542_400 + i * 3600, "open": 1.1,
                "high": 1.11, "low": 1.09, "close": 1.105}
               for i in range(3)]
    out = replay.timeline(candles, rule=rule, symbol="EUR_USD", timeframe="1h")
    assert out["events"][0]["dataAvailableThrough"] == candles[0]["time"]
    assert out["events"][0]["entry"]["price"] == candles[0]["open"]
    assert out["events"][0]["stop"] == 1.099
    assert out["events"][0]["conditions"]["met"]


def test_incidents_do_not_reassure_about_what_was_not_checked():
    nothing = incidents.derive({})
    assert "not an all-clear" in nothing["message"]
    some = incidents.derive({"brokerStatus": "ok"})
    assert "Not checked" in some["message"] and "brokerStatus" in some["checked"]


if __name__ == "__main__":
    failed = []
    for name, fn in sorted((n, f) for n, f in globals().items()
                           if n.startswith("test_") and callable(f)):
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as e:                  # noqa: BLE001
            failed.append(name)
            print(f"  FAIL {name}: {e!r}")
    print("\nFAILED: " + ", ".join(failed) if failed else "\nALL OK")
    sys.exit(1 if failed else 0)
