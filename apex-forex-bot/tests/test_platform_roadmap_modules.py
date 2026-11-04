import pytest

from apex.platform import backtest, forward, health_score, incidents, multi_account
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


def test_health_and_incident_outputs_are_conservative():
    result = health_score.score({"brokerConnected": True})
    assert result["score"] < 100
    assert result["warnings"]
    assert incidents.derive({"brokerStatus": "unavailable"})["incidents"]


def test_backtest_replay_forward_are_read_only():
    candles = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    result = backtest.run(candles, initial_balance=100)
    assert result["hypothetical"] is True
    assert replay.timeline(candles)["readOnly"] is True
    assert forward.record([{"symbol": "EURUSD"}])["readOnly"] is True


def test_overfit_and_multi_account_are_scoped():
    assert overfit.analyse({"conditionCount": 10})["warnings"]
    result = multi_account.isolate("u1", [{"ctid": 42, "mode": "demo"}])
    assert result["accounts"][0]["scope"] == "u1:42"
