import contextlib
import io
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex.brokers import ctrader


class _Conn:
    def __init__(self, event=None, error=None):
        self.event = event
        self.error = error

    def _request(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.event


def _broker(conn):
    broker = ctrader.CtraderBroker(SimpleNamespace(
        PAPER_TRADING=False,
        SYMBOL="USDCHF",
        CTRADER_ACCOUNT_ID=123,
    ))
    broker._conn = lambda: conn
    broker._ctid = lambda: 123
    broker._symbol_id = lambda instrument: 7
    broker._vol_rules = lambda sid: (100_000, 100_000)
    return broker


def test_execution_error_code_is_rejected_and_logged():
    event = ctrader.ProtoOAExecutionEvent(
        executionType=ctrader.ProtoOAExecutionType.ORDER_ACCEPTED,
        errorCode="TRADING_BAD_VOLUME",
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            _broker(_Conn(event=event)).place_order("SELL", 23_063, "USDCHF")
        except RuntimeError:
            pass
        else:
            raise AssertionError("execution error was reported as a successful order")
    assert "TRADING_BAD_VOLUME" in output.getvalue()


def test_execution_timeout_is_logged_and_propagated():
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            _broker(_Conn(error=TimeoutError("no terminal execution event"))).place_order(
                "SELL", 23_063, "USDCHF"
            )
        except TimeoutError:
            pass
        else:
            raise AssertionError("execution timeout was swallowed")
    assert "no terminal execution event" in output.getvalue()


def test_unknown_execution_uses_existing_position_for_protection():
    broker = _broker(_Conn(event=ctrader.ProtoOAExecutionEvent()))
    broker.get_open_position = lambda instrument: {"positionId": 456}
    broker._conn = lambda: _Conn(event=ctrader.ProtoOAExecutionEvent(
        executionType=ctrader.ProtoOAExecutionType.ORDER_FILLED,
    ))
    result = broker.place_order("SELL", 23_063, "USDCHF", sl=0.812953, tp=0.804095)
    assert result["status"] == "FILLED"


def test_unknown_execution_without_position_is_logged_and_rejected():
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            _broker(_Conn(event=ctrader.ProtoOAExecutionEvent())).place_order(
                "SELL", 23_063, "USDCHF"
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("unconfirmed execution was reported as filled")
    assert "no terminal execution confirmation" in output.getvalue()


if __name__ == "__main__":
    test_execution_error_code_is_rejected_and_logged()
    test_execution_timeout_is_logged_and_propagated()
    test_unknown_execution_uses_existing_position_for_protection()
    test_unknown_execution_without_position_is_logged_and_rejected()
    print("order failure tests passed")
