"""Read every linked cTrader account. Nothing here can send an order.

The dashboard used to follow the one selected account. Selecting live hid
the demo figures, and selecting demo hid the live ones. This asks the
read-only broker path once per linked account and labels each answer with
the environment stored on the link. A failed read is unknown, never zero,
and it is not cached: the next request can recover as soon as the broker does.
"""
import math

from apex.platform import broker_read as _read
from apex.platform import ctrader_link as _link


def _number(value):
    """A finite number, or None. Booleans and missing values are not zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _equity(balance, positions):
    """Balance plus open P&L, or None when any leg is unknown.

    Substituting the balance alone would present an equity the broker did
    not confirm. An empty position list is a confirmed zero open P&L.
    """
    if balance is None:
        return None
    if not isinstance(positions, list):
        return None
    total = 0.0
    for row in positions:
        if not isinstance(row, dict):
            return None
        pnl = _number(row.get("pnlAccount"))
        if pnl is None:
            return None
        total += pnl
    return round(balance + total, 2)


def _count(result, key):
    if not isinstance(result, dict) or result.get("status") != _read.OK:
        return None
    rows = result.get(key)
    if not isinstance(rows, list):
        return None
    return len(rows)


def _view(result, *, count):
    if not isinstance(result, dict):
        return {"status": "unavailable", "count": None,
                "reason": "the broker read did not return a result",
                "errorCode": "BROKER_UNAVAILABLE", "correlationId": None}
    status = result.get("status")
    if status == _read.OK:
        return {"status": "ok", "count": count, "reason": None,
                "errorCode": None, "correlationId": result.get("correlationId")}
    return {
        "status": status or "unavailable",
        "count": None,
        "reason": result.get("reason"),
        "errorCode": result.get("errorCode"),
        "correlationId": result.get("correlationId"),
    }


def _one(user_id, ctid, mode, read_fn):
    expected = mode if mode in ("demo", "live") else None
    balance_read = read_fn(user_id, "balance", ctid, expected)
    positions_read = read_fn(user_id, "positions", ctid, expected)
    orders_read = read_fn(user_id, "orders", ctid, expected)
    balance = None
    if isinstance(balance_read, dict) and balance_read.get("status") == _read.OK:
        balance = _number(balance_read.get("balance"))
    positions = positions_read.get("positions") if isinstance(positions_read, dict) else None
    return {
        "ctid": ctid,
        "mode": mode if mode in ("demo", "live") else "unknown",
        "balance": balance,
        "equity": _equity(balance, positions if isinstance(positions, list) else None),
        "account": _view(balance_read, count=None),
        "positions": _view(positions_read, count=_count(positions_read, "positions")),
        "orders": _view(orders_read, count=_count(orders_read, "orders")),
    }


def _default_read(user_id, kind, ctid, mode):
    fn = {"balance": _read.account, "positions": _read.positions,
          "orders": _read.orders}[kind]
    return fn(user_id, ctid=ctid, expected_mode=mode)


def snapshot(user_id, *, status_fn=None, read_fn=None):
    """One labelled read per linked account. Does not change the selection."""
    status = (status_fn or _link.public_status)(user_id)
    if not isinstance(status, dict) or not status.get("connected"):
        return {"status": "ok", "connected": False, "accounts": [],
                "selected": None}
    reader = read_fn or _default_read
    rows = []
    for account in status.get("accounts") or []:
        if not isinstance(account, dict) or account.get("ctid") in (None, ""):
            continue
        try:
            rows.append(_one(user_id, account.get("ctid"), account.get("mode"), reader))
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "ctid": account.get("ctid"),
                "mode": account.get("mode") if account.get("mode") in ("demo", "live") else "unknown",
                "balance": None,
                "equity": None,
                "account": {"status": "unavailable", "count": None,
                            "reason": "the account could not be read",
                            "errorCode": type(exc).__name__, "correlationId": None},
                "positions": {"status": "unavailable", "count": None,
                              "reason": "the account could not be read",
                              "errorCode": type(exc).__name__, "correlationId": None},
                "orders": {"status": "unavailable", "count": None,
                           "reason": "the account could not be read",
                           "errorCode": type(exc).__name__, "correlationId": None},
            })
    return {"status": "ok", "connected": True, "accounts": rows,
            "selected": status.get("selected")}
