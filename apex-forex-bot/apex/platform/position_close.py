"""Demo-only position close orchestration for the web platform.

This module owns the browser close contract. It verifies the account mode from
the cTrader link record, passes the request through the shared close gate, and
then invokes the broker by position id. It never resolves a symbol and never
turns a partial or already-flat response into a full realized P&L.
"""

from apex import gates as _gates
from apex import ledger as _ledger
from apex.platform import broker_read as _read
from apex.platform import ctrader_link as _link


class CloseRefused(RuntimeError):
    def __init__(self, code, detail, *, status=409):
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(f"{code}: {detail}")


class CloseUnknown(RuntimeError):
    """The broker call may have reached cTrader; the claim must remain held."""


def _account_mode(user_id, ctid):
    rec = _link._read_conn(str(user_id))
    match = next((a for a in rec.get("accounts") or []
                  if str(a.get("ctid")) == str(ctid)), None)
    if not match:
        raise _link.LinkError("NO_SUCH_ACCOUNT",
                              "that account is not one of the connected ones")
    return str(match.get("mode") or "").lower()


def close_demo(user_id, *, ctid, position_id, connection_fn=None,
               broker_fn=None, gate_fn=None):
    """Close one DEMO position and return the broker's result shape."""
    mode = _account_mode(user_id, ctid)
    if mode != "demo":
        raise CloseRefused(
            "DEMO_ONLY",
            "position close is available only for cTrader demo accounts",
            status=403,
        )

    gate = gate_fn or _gates.authorize_platform_demo_close
    decision, rid = gate(str(user_id), position_id=position_id,
                         origin="platform")
    if not decision:
        raise CloseRefused("CLOSE_REFUSED", decision.detail or decision.reason)

    try:
        broker, other = _read._open(
            str(user_id), ctid=ctid, connection_fn=connection_fn,
            broker_fn=broker_fn)
        if broker is None:
            if (other or {}).get("status") == _read.REAUTH_REQUIRED:
                _ledger.release(rid)
                raise CloseRefused(
                    "REAUTH_REQUIRED",
                    "the cTrader authorisation has expired — reconnect the account",
                    status=401,
                )
            _ledger.release(rid)
            raise CloseRefused(
                "BROKER_UNAVAILABLE",
                (other or {}).get("reason") or "the cTrader account is unavailable",
                status=503,
            )
        submit = getattr(broker, "close_position_by_id", None)
        if not callable(submit):
            _ledger.release(rid)
            raise CloseRefused(
                "UNSUPPORTED",
                "this cTrader connector cannot close positions by position id",
                status=501,
            )
        result = submit(position_id)
    except _link.LinkError as e:
        # Refresh failures happen before the close request leaves this
        # process, so the user must be able to retry after reconnecting.
        if e.code in ("REFRESH_UNAVAILABLE", "REFRESH_FAILED"):
            _ledger.release(rid)
        raise
    except CloseRefused:
        raise
    except Exception as e:  # noqa: BLE001
        # A socket timeout or connection drop does not prove the broker did
        # nothing. Keep the claim so a retry cannot close a position that was
        # filled just before the response disappeared.
        raise CloseUnknown(
            "the broker close result is unknown; check the position before retrying"
        ) from e

    if not isinstance(result, dict):
        raise CloseUnknown("the broker returned no close result")
    status = str(result.get("status") or "").upper()
    if status == "REJECTED":
        _ledger.release(rid)
        raise CloseRefused(
            "CLOSE_REJECTED",
            result.get("sentence") or "The broker rejected the close request.",
            status=409,
        )
    if status == "PARTIAL":
        # The requested full close no longer describes the remaining position,
        # so a subsequent click must be allowed to claim the remainder.
        _ledger.release(rid)
        return result
    if status in ("ALREADY_CLOSED", "FILLED"):
        _ledger.record(rid, result)
        return result
    raise CloseUnknown("the broker returned an unrecognised close result")
