"""Shape cTrader read replies into the audit document.

Pure apart from `read_*`, which only call the guarded session. Lots follow
the engine's own conversion. Times are Europe/Amsterdam. A deal is the
platform's when the order that created it carries the engine marker on its
label, comment or client order id; the opening order's stop and target are
reported separately, because a closing fill is not the order that set them.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from apex.brokers import ctrader as _ct
from apex.ctrader_proto.OpenApiMessages_pb2 import (
    ProtoOADealListReq,
    ProtoOADealListRes,
    ProtoOAOrderDetailsReq,
    ProtoOAOrderDetailsRes,
    ProtoOAOrderListReq,
    ProtoOAOrderListRes,
    ProtoOAReconcileReq,
    ProtoOAReconcileRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
)
from apex.ctrader_proto.OpenApiModelMessages_pb2 import (
    ProtoOAOrderStatus,
    ProtoOATradeSide,
)
from apex.platform import ctrader_readonly as _ro

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
MAX_PAGES = 20
MAX_ORDER_DETAILS = 100
DEAL_PAGE_ROWS = 500


def _opt(msg, name):
    return _ro._opt(msg, name)


def _enum_name(enum_cls, msg, name):
    value = _opt(msg, name)
    if value is None:
        return None
    try:
        return enum_cls.Name(int(value))
    except Exception:                                        # noqa: BLE001
        return None


def _side(msg):
    name = _enum_name(ProtoOATradeSide, msg, "tradeSide")
    return name if name in ("BUY", "SELL") else None


def _opposite(side):
    return {"BUY": "SELL", "SELL": "BUY"}.get(side)


def placed_by_platform(label, comment, client_order_id):
    """True only when one of the three fields is exactly the engine marker.

    The engine writes that marker as the order label. The other two are
    checked because a fill can echo it there. Blank is not a match: a
    position with no label was not opened by the platform.
    """
    mark = _ct.ENGINE_ORDER_LABEL
    return any(value is not None and str(value) == mark
               for value in (label, comment, client_order_id))


def lots_from_volume(volume, symbol):
    """Hundredths-of-a-unit volume as lots, using the engine's lot size."""
    try:
        units = float(volume) / 100.0
    except (TypeError, ValueError):
        return None
    from apex import forex
    norm = forex._norm(symbol or "")
    if forex._is_fx(norm) or norm.endswith("JPY"):
        return round(units / 100_000.0, 8)
    return round(units, 8)


def iso_amsterdam(stamp, *, millis=True):
    if stamp is None or stamp == "":
        return None
    try:
        n = float(stamp)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if millis and n > 10_000_000_000:
        n = n / 1000.0
    return datetime.fromtimestamp(n, tz=AMSTERDAM).isoformat(timespec="seconds")


def _symbol_name(symbols, symbol_id):
    try:
        sid = int(symbol_id)
    except (TypeError, ValueError):
        return None
    name = (symbols or {}).get(sid)
    if not name:
        return str(sid)
    return str(name).replace("/", "").replace("_", "").upper()


def symbols_from(res):
    out = {}
    for row in getattr(res, "symbol", ()) or ():
        if getattr(row, "symbolId", None) is None or not getattr(row, "symbolName", None):
            continue
        out[int(row.symbolId)] = str(row.symbolName)
    return out


def _order_mark(order):
    if order is None:
        return None
    trade = getattr(order, "tradeData", None)
    return placed_by_platform(
        _opt(trade, "label"), _opt(trade, "comment"), _opt(order, "clientOrderId"))


def _protection(order):
    """Absolute prices plus whether a stop or target was set at all.

    A relative distance counts as set even when the absolute price is absent.
    Unknown (no order) is a null flag, which is not the same as false.
    """
    if order is None:
        return None, None, None, None
    stop, take = _opt(order, "stopLoss"), _opt(order, "takeProfit")
    try:
        sl_set = stop is not None or int(_opt(order, "relativeStopLoss") or 0) > 0
        tp_set = take is not None or int(_opt(order, "relativeTakeProfit") or 0) > 0
    except (TypeError, ValueError):
        sl_set, tp_set = stop is not None, take is not None
    return stop, take, bool(sl_set), bool(tp_set)


def _position_row(position, symbols):
    trade = position.tradeData
    symbol = _symbol_name(symbols, trade.symbolId)
    return {
        "positionId": int(position.positionId),
        "symbol": symbol,
        "side": _side(trade),
        "lots": lots_from_volume(trade.volume, symbol),
        "entryPrice": _opt(position, "price"),
        "stopLoss": _opt(position, "stopLoss"),
        "takeProfit": _opt(position, "takeProfit"),
        "openTime": iso_amsterdam(_opt(trade, "openTimestamp")),
        "label": _opt(trade, "label"),
        "comment": _opt(trade, "comment"),
        "placedByPlatform": placed_by_platform(
            _opt(trade, "label"), _opt(trade, "comment"), None),
    }


def _pending_row(order, symbols):
    trade = order.tradeData
    symbol = _symbol_name(symbols, trade.symbolId)
    entry = _opt(order, "limitPrice")
    if entry is None:
        entry = _opt(order, "stopPrice")
    return {
        "orderId": int(order.orderId),
        "positionId": _opt(order, "positionId"),
        "symbol": symbol,
        "side": _side(trade),
        "lots": lots_from_volume(trade.volume, symbol),
        "entryPrice": entry,
        "stopLoss": _opt(order, "stopLoss"),
        "takeProfit": _opt(order, "takeProfit"),
        "openTime": iso_amsterdam(_opt(trade, "openTimestamp")),
        "label": _opt(trade, "label"),
        "comment": _opt(trade, "comment"),
        "clientOrderId": _opt(order, "clientOrderId"),
        "placedByPlatform": _order_mark(order),
    }


def open_view(reconcile, symbols):
    return {
        "positions": [_position_row(p, symbols) for p in reconcile.position],
        "pendingOrders": [_pending_row(o, symbols) for o in reconcile.order],
    }


def _close_view(deal):
    if not deal.HasField("closePositionDetail"):
        return None
    cpd = deal.closePositionDetail
    digits = int(getattr(cpd, "moneyDigits", 0) or 0) or int(
        getattr(deal, "moneyDigits", 0) or 0) or 2
    gross = _ro._money(cpd.grossProfit, digits)
    swap = _ro._money(cpd.swap, digits)
    commission = _ro._money(cpd.commission, digits)
    # Same net the journal stores. Commission is a cost either sign.
    net = round((gross or 0.0) + (swap or 0.0) - abs(commission or 0.0),
                digits if digits else 2)
    return {"grossProfit": gross, "commission": commission, "swap": swap, "net": net}


def _deal_volume(deal):
    if deal.HasField("closePositionDetail"):
        closed = _opt(deal.closePositionDetail, "closedVolume")
        if closed:
            return closed
    return _opt(deal, "filledVolume") or getattr(deal, "volume", None)


def deals_view(deal_msgs, orders_by_id, symbols):
    """Entry protection comes from the earliest opening deal's order.

    `placedByPlatform` is that deal's own order. Null means the order was
    not read, not that a person placed it by hand.
    """
    opening, opening_side = {}, {}
    for deal in deal_msgs:
        if deal.HasField("closePositionDetail"):
            continue
        pid = int(deal.positionId)
        ts = int(getattr(deal, "executionTimestamp", 0) or 0)
        prev = opening.get(pid)
        if prev is None or (ts and ts < prev[0]):
            opening[pid] = (ts, int(deal.orderId))
        opening_side.setdefault(pid, _side(deal))
    rows = []
    for deal in deal_msgs:
        pid = int(deal.positionId)
        symbol = _symbol_name(symbols, deal.symbolId)
        own = (orders_by_id or {}).get(int(deal.orderId))
        open_id = (opening.get(pid) or (None, None))[1]
        opener = (orders_by_id or {}).get(open_id) if open_id is not None else None
        deal_side = _side(deal)
        if pid in opening_side:
            side = opening_side[pid]
        elif deal.HasField("closePositionDetail"):
            side = _opposite(deal_side)
        else:
            side = deal_side
        stop, take, sl_set, tp_set = _protection(opener)
        trade = getattr(own, "tradeData", None) if own is not None else None
        rows.append({
            "dealId": int(deal.dealId),
            "orderId": int(deal.orderId),
            "positionId": pid,
            "symbol": symbol,
            "side": side,
            "lots": lots_from_volume(_deal_volume(deal), symbol),
            "executionPrice": _opt(deal, "executionPrice"),
            "time": iso_amsterdam(getattr(deal, "executionTimestamp", None)),
            "close": _close_view(deal),
            "entryStopLoss": stop,
            "entryTakeProfit": take,
            "entry_sl_set": sl_set,
            "entry_tp_set": tp_set,
            "label": _opt(trade, "label") if trade is not None else None,
            "comment": _opt(trade, "comment") if trade is not None else None,
            "clientOrderId": _opt(own, "clientOrderId") if own is not None else None,
            "placedByPlatform": None if own is None else _order_mark(own),
        })
    return rows


def orders_view(order_msgs, symbols):
    rows = []
    for order in order_msgs:
        trade = order.tradeData
        symbol = _symbol_name(symbols, trade.symbolId)
        price = _opt(order, "executionPrice")
        if price is None:
            price = _opt(order, "limitPrice")
        if price is None:
            price = _opt(order, "stopPrice")
        opened = _opt(trade, "openTimestamp") or _opt(order, "utcLastUpdateTimestamp")
        rows.append({
            "orderId": int(order.orderId),
            "positionId": _opt(order, "positionId"),
            "symbol": symbol,
            "side": _side(trade),
            "lots": lots_from_volume(trade.volume, symbol),
            "price": price,
            "time": iso_amsterdam(opened),
            "stopLoss": _opt(order, "stopLoss"),
            "takeProfit": _opt(order, "takeProfit"),
            "label": _opt(trade, "label"),
            "comment": _opt(trade, "comment"),
            "clientOrderId": _opt(order, "clientOrderId"),
            "orderStatus": _enum_name(ProtoOAOrderStatus, order, "orderStatus"),
            "placedByPlatform": _order_mark(order),
        })
    return rows


def _page(session, make_req, res_cls, field, start_ms, end_ms):
    items, cur, end_ms = [], int(start_ms), int(end_ms)
    for _ in range(MAX_PAGES):
        if cur >= end_ms:
            return items, False
        res = session.request(make_req(cur, end_ms), res_cls, timeout=20)
        batch = list(getattr(res, field) or [])
        items.extend(batch)
        if not getattr(res, "hasMore", False):
            return items, False
        newest = cur
        for item in batch:
            for attr in ("executionTimestamp", "utcLastUpdateTimestamp"):
                try:
                    newest = max(newest, int(getattr(item, attr) or 0))
                except (TypeError, ValueError):
                    pass
            trade = getattr(item, "tradeData", None)
            if trade is not None:
                try:
                    newest = max(newest, int(_opt(trade, "openTimestamp") or 0))
                except (TypeError, ValueError):
                    pass
        if newest <= cur:
            return items, True
        cur = newest + 1
    return items, True


def _symbols(session, ctid):
    if session._symbols is None:
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = int(ctid)
        session._symbols = symbols_from(
            session.request(req, ProtoOASymbolsListRes, timeout=20))
    return session._symbols


def read_open(session, ctid):
    req = ProtoOAReconcileReq()
    req.ctidTraderAccountId = int(ctid)
    reconcile = session.request(req, ProtoOAReconcileRes, timeout=15)
    return open_view(reconcile, _symbols(session, ctid))


def _order_details(session, ctid, order_id):
    req = ProtoOAOrderDetailsReq()
    req.ctidTraderAccountId = int(ctid)
    req.orderId = int(order_id)
    try:
        res = session.request(req, ProtoOAOrderDetailsRes, timeout=15)
    except RuntimeError:
        return None
    return res.order


def read_deals(session, ctid, start_s, end_s):
    symbols = _symbols(session, ctid)

    def make_req(cur, end):
        req = ProtoOADealListReq()
        req.ctidTraderAccountId = int(ctid)
        req.fromTimestamp = int(cur)
        req.toTimestamp = int(end)
        req.maxRows = DEAL_PAGE_ROWS
        return req

    deals, truncated = _page(
        session, make_req, ProtoOADealListRes, "deal",
        int(start_s * 1000), int(end_s * 1000))
    wanted, seen = [], set()
    ordered = [d for d in deals if not d.HasField("closePositionDetail")] + list(deals)
    for deal in ordered:
        oid = int(deal.orderId)
        if oid not in seen:
            seen.add(oid)
            wanted.append(oid)
    orders = {oid: _order_details(session, ctid, oid)
              for oid in wanted[:MAX_ORDER_DETAILS]}
    return {
        "deals": deals_view(deals, orders, symbols),
        "truncated": bool(truncated or len(wanted) > MAX_ORDER_DETAILS),
        "timezone": "Europe/Amsterdam",
    }


def read_orders(session, ctid, start_s, end_s):
    symbols = _symbols(session, ctid)

    def make_req(cur, end):
        req = ProtoOAOrderListReq()
        req.ctidTraderAccountId = int(ctid)
        req.fromTimestamp = int(cur)
        req.toTimestamp = int(end)
        return req

    orders, truncated = _page(
        session, make_req, ProtoOAOrderListRes, "order",
        int(start_s * 1000), int(end_s * 1000))
    return {
        "orders": orders_view(orders, symbols),
        "truncated": bool(truncated),
        "timezone": "Europe/Amsterdam",
    }


def _with_session(env, token, ctid, fn):
    with _ro.open_account_session(env, token, ctid) as session:
        return fn(session, ctid)


def describe_open(env, token, ctid):
    return _with_session(env, token, ctid, read_open)


def describe_deals(env, token, ctid, start_s, end_s):
    def run(session, account):
        return read_deals(session, account, start_s, end_s)
    return _with_session(env, token, ctid, run)


def describe_orders(env, token, ctid, start_s, end_s):
    def run(session, account):
        return read_orders(session, account, start_s, end_s)
    return _with_session(env, token, ctid, run)
