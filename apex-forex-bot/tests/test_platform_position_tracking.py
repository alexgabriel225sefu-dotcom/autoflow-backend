"""Position and closed-trade reads keep broker uncertainty visible."""
import os
import sys
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")

from apex.platform import broker_read  # noqa: E402
from apex.brokers import ctrader  # noqa: E402
from apex.ctrader_proto.OpenApiModelMessages_pb2 import (  # noqa: E402
    ProtoOAPosition, ProtoOATradeSide,
)


class _Conn(dict):
    def __init__(self):
        super().__init__(ctid=501, mode="demo", accessToken="token")


class _Broker:
    def __init__(self, positions, *, quote=(1.101, 1.102), quote_ts=None,
                 quote_error=None, history=None):
        self._positions = positions
        self._quote = quote
        self._quote_ts = quote_ts if quote_ts is not None else time.time()
        self._quote_error = quote_error
        self._history = history if history is not None else {"ok": True, "deals": {}}
        self.history_calls = 0

    def get_all_positions(self):
        return self._positions

    def get_quote(self, symbol):
        if self._quote_error:
            raise RuntimeError(self._quote_error)
        bid, ask = self._quote
        return bid, ask, self._quote_ts

    def get_deal_history(self, start, end):
        self.history_calls += 1
        return self._history


def read_positions(broker):
    return broker_read.positions(
        "user-1", ctid=501, connection_fn=lambda *_args, **_kw: _Conn(),
        broker_fn=lambda: broker,
    )


def read_deals(broker):
    return broker_read.deals(
        "user-1", ctid=501, connection_fn=lambda *_args, **_kw: _Conn(),
        broker_fn=lambda: broker,
    )


def test_no_stop_is_explicitly_unprotected():
    result = read_positions(_Broker([{
        "symbol": "EURUSD", "side": "BUY", "units": 1000,
        "entryPrice": 1.1000, "stopLoss": None, "takeProfit": 1.1050,
        "positionId": 7,
    }]))
    row = result["positions"][0]
    assert row["hasStop"] is False
    assert row["warning"]


def test_failed_quote_never_prices_from_an_old_value():
    result = read_positions(_Broker([{
        "symbol": "EURUSD", "side": "BUY", "units": 1000,
        "entryPrice": 1.1000, "stopLoss": 1.0950, "takeProfit": None,
        "positionId": 7,
    }], quote_error="quote unavailable"))
    assert result["status"] == "unavailable"
    assert "positions" not in result


def test_stale_quote_is_marked_and_pnl_is_withheld():
    result = read_positions(_Broker([{
        "symbol": "EURUSD", "side": "BUY", "units": 1000,
        "entryPrice": 1.1000, "stopLoss": 1.0950, "takeProfit": None,
        "positionId": 7,
    }], quote_ts=time.time() - 31))
    row = result["positions"][0]
    assert row["quoteStale"] is True
    assert row["pnlPips"] is None and row["pnlAccount"] is None


def test_pnl_sign_is_correct_for_buy_and_sell():
    positions = [
        {"symbol": "EURUSD", "side": "BUY", "units": 1000,
         "entryPrice": 1.1000, "stopLoss": 1.0950, "takeProfit": None,
         "positionId": 1},
        {"symbol": "EURUSD", "side": "SELL", "units": 1000,
         "entryPrice": 1.1000, "stopLoss": 1.1050, "takeProfit": None,
         "positionId": 2},
    ]
    result = read_positions(_Broker(positions, quote=(1.101, 1.102)))
    rows = {p["positionId"]: p for p in result["positions"]}
    assert rows[1]["pnlPips"] > 0 and rows[1]["pnlAccount"] > 0
    assert rows[2]["pnlPips"] < 0 and rows[2]["pnlAccount"] < 0


def test_failed_deal_list_is_an_error_not_empty_success():
    result = read_deals(_Broker([], history={"ok": False, "deals": {}, "error": "broker timeout"}))
    assert result["status"] == "unavailable"
    assert "deals" not in result


def test_closed_deals_are_cached_for_sixty_seconds():
    broker = _Broker([], history={"ok": True, "deals": {}})
    first = read_deals(broker)
    second = read_deals(broker)
    assert first["status"] == second["status"] == "ok"
    assert broker.history_calls == 1


def test_ctrader_position_reads_only_schema_fields():
    p = ProtoOAPosition()
    p.positionId = 7
    p.tradeData.symbolId = 1
    p.tradeData.volume = 100_000
    p.tradeData.tradeSide = ProtoOATradeSide.BUY
    p.tradeData.openTimestamp = 1_700_000_000
    p.price = 1.1
    p.swap = -125
    p.commission = 35
    p.usedMargin = 4567
    p.moneyDigits = 2
    p.utcLastUpdateTimestamp = 1_700_000_010
    reply = ctrader.ProtoOAReconcileRes()
    reply.position.append(p)
    broker = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False, CTRADER_ACCOUNT_ID=501, SYMBOL="EURUSD"))
    broker._sym_id = {"EURUSD": 1}
    broker._rpc = lambda _req, _res: reply
    rows = broker.get_all_positions()
    assert rows[0]["openTime"] == 1_700_000_000
    assert rows[0]["swap"] == -1.25
    assert rows[0]["commission"] == 0.35
    assert rows[0]["usedMargin"] == 45.67
    assert rows[0]["lastUpdateTime"] == 1_700_000_010


if __name__ == "__main__":
    for _test in (
        test_no_stop_is_explicitly_unprotected,
        test_failed_quote_never_prices_from_an_old_value,
        test_stale_quote_is_marked_and_pnl_is_withheld,
        test_pnl_sign_is_correct_for_buy_and_sell,
        test_failed_deal_list_is_an_error_not_empty_success,
        test_closed_deals_are_cached_for_sixty_seconds,
        test_ctrader_position_reads_only_schema_fields,
    ):
        _test()
    print("OK: position tracking tests")
