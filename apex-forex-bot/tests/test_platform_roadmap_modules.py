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
    result = backtest.run(candles, signal=lambda c: {"side": "BUY"}, initial_balance=100)
    assert result["hypothetical"] is True
    assert replay.timeline(candles)["readOnly"] is True
    assert forward.record([{"symbol": "EURUSD"}])["readOnly"] is True


def test_overfit_and_multi_account_are_scoped():
    assert overfit.analyse({"conditionCount": 10})["warnings"]
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
