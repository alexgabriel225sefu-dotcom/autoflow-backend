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

    # A position id is a whole number. Checked BEFORE the gate takes its claim:
    # `abc` used to take the claim, fail at the broker, come back as "result
    # unknown" and then lock out a retry of the right id for minutes. "0123" is
    # normalised so it cannot take a second claim on the same position.
    raw_id = str(position_id).strip()
    if not raw_id.isdigit():
        raise CloseRefused("BAD_POSITION_ID",
                           "the position id must be a whole number", status=400)
    position_id = str(int(raw_id))

    # The default gate keys its claim on the account AND the position, so a close
    # sent under the wrong account cannot use up the right account's claim.
    gate = gate_fn or (lambda uid, **kw: _gates.authorize_platform_demo_close(
        uid, account=ctid, **kw))
    decision, rid = gate(str(user_id), position_id=position_id,
                         origin="platform")
    if not decision:
        raise CloseRefused("CLOSE_REFUSED", decision.detail or decision.reason)

    # Everything up to `submit(...)` happens BEFORE anything reaches cTrader, so
    # a failure here proves nothing was closed: the claim is released and the
    # refusal is specific. Only an exception from the submit itself can leave
    # the outcome unknown.
    try:
        broker, other = _read._open(
            str(user_id), ctid=ctid, connection_fn=connection_fn,
            broker_fn=broker_fn)
    except Exception as e:  # noqa: BLE001
        _ledger.release(rid)
        if isinstance(e, _link.LinkError):
            raise
        raise CloseRefused(
            "BROKER_UNAVAILABLE",
            "the cTrader connection could not be prepared — nothing was sent",
            status=503,
        ) from None
    if broker is None:
        _ledger.release(rid)
        if (other or {}).get("status") == _read.REAUTH_REQUIRED:
            raise CloseRefused(
                "REAUTH_REQUIRED",
                "the cTrader authorisation has expired — reconnect the account",
                status=401,
            )
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
    try:
        result = submit(position_id)
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
