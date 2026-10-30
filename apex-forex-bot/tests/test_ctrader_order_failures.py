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


class _SequenceConn:
    def __init__(self, *responses):
        self.responses = list(responses)

    def _request(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def test_close_does_not_report_acceptance_as_filled():
    broker = _broker(_Conn(event=ctrader.ProtoOAExecutionEvent(
        executionType=ctrader.ProtoOAExecutionType.ORDER_ACCEPTED,
    )))
    broker.get_open_position = lambda instrument: {
        "positionId": 456, "units": 23_063, "side": "SELL"
    }
    broker.get_bid_ask = lambda instrument: (0.812, 0.813)
    try:
        broker.close_position("USDCHF")
    except RuntimeError as error:
        assert "terminal execution" in str(error)
    else:
        raise AssertionError("close acceptance was reported as FILLED")


def test_close_execution_error_is_logged_and_propagated():
    output = io.StringIO()
    broker = _broker(_Conn(event=ctrader.ProtoOAExecutionEvent(
        executionType=ctrader.ProtoOAExecutionType.ORDER_REJECTED,
        errorCode="TRADING_BAD_VOLUME",
    )))
    broker.get_open_position = lambda instrument: {
        "positionId": 456, "units": 23_063, "side": "SELL"
    }
    with contextlib.redirect_stdout(output):
        try:
            broker.close_position("USDCHF")
        except RuntimeError:
            pass
        else:
            raise AssertionError("close error was reported as FILLED")
    assert "TRADING_BAD_VOLUME" in output.getvalue()


def test_stop_verification_failure_fails_closed():
    filled = ctrader.ProtoOAExecutionEvent(
        executionType=ctrader.ProtoOAExecutionType.ORDER_FILLED,
    )
    amend_failure = RuntimeError("amend failed")
    broker = _broker(_SequenceConn(filled, amend_failure))
    position_reads = iter([{"positionId": 456}, amend_failure])
    broker.get_open_position = lambda instrument: next(position_reads)
    broker.close_position = lambda instrument: (_ for _ in ()).throw(
        RuntimeError("close failed")
    )
    result = broker.place_order("SELL", 23_063, "USDCHF", sl=0.812953)
    assert result["status"] == "UNPROTECTED"


if __name__ == "__main__":
    test_execution_error_code_is_rejected_and_logged()
    test_execution_timeout_is_logged_and_propagated()
    test_unknown_execution_uses_existing_position_for_protection()
    test_unknown_execution_without_position_is_logged_and_rejected()
    test_close_does_not_report_acceptance_as_filled()
    test_close_execution_error_is_logged_and_propagated()
    test_stop_verification_failure_fails_closed()
    print("order failure tests passed")
