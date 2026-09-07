import contextlib
import io
from types import SimpleNamespace

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


def test_missing_execution_type_is_not_reported_as_filled():
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
    test_missing_execution_type_is_not_reported_as_filled()
    print("order failure tests passed")
