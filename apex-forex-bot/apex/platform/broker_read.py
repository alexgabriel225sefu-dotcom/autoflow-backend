"""Reading a client's cTrader account. Reads only — nothing here can trade.

WHAT THIS MODULE MAY DO IS BOUNDED BY WHAT IT CALLS

Four connector methods: get_all_positions, get_pending_orders, get_balance
and get_candles.
No place_order, no close_position, no amend_sltp. A test asserts that by
walking this file's AST, so the boundary is a property of the code rather
than a promise in a comment.

WHY EVERY ANSWER CARRIES A STATUS

An empty list of positions is a claim — "you have nothing open" — and a client
reads it as one. It is only true when we actually asked the broker and the
broker said so. When the token needs re-authorising, when cTrader times out,
or when nothing is connected at all, an empty list would be a lie told in the
most reassuring possible way. So the shape is always {connected, status, ...}
and the data key is ABSENT unless status is "ok".

    connected: false           nothing is linked
    reauth_required            linked, but the token is dead and the refresh
                               could not revive it — the client must reconnect
    unavailable                linked and authorised, but cTrader could not be
                               reached or answered with an error
    ok                         we asked, and this is the answer

TOKENS NEVER REACH A LOG OR A RESPONSE

The access token is passed to the connector and nowhere else. Broker errors
are scrubbed of it before they are returned or printed, because an exception
string is the one place a credential escapes without anyone deciding to put it
there.
"""

import copy
import threading
import time

from apex import forex
from apex.platform import ctrader_link as _link

# Bounded so a hung broker cannot hold an HTTP worker open indefinitely.
DEFAULT_TIMEOUT_S = 12.0

NOT_CONNECTED = "not_connected"
REAUTH_REQUIRED = "reauth_required"
UNAVAILABLE = "unavailable"
OK = "ok"

# Deal history is expensive: cTrader may walk as many as forty pages for one
# seven-day read, and the historical request budget is shared by every reader
# on a connection. A successful result is a read-only snapshot, so keeping it
# for one minute is honest and prevents dashboard polling from becoming a
# broker-history loop. Failures are never cached; the next request must be able
# to recover as soon as the broker does.
DEALS_CACHE_TTL_S = 60.0
DEALS_CACHE_MAX = 256
_deals_cache = {}
_deals_cache_lock = threading.Lock()
_deals_fetch_locks = {}


def _scrub(text, *secrets):
    """An error message with every known secret removed."""
    out = str(text)
    for s in secrets:
        if s and isinstance(s, str) and len(s) >= 8 and s in out:
            out = out.replace(s, "[redacted]")
    return out[:300]


def _disconnected(reason="no cTrader account is connected"):
    return {"connected": False, "status": NOT_CONNECTED, "reason": reason}


def _open(user_id, *, ctid=None, connection_fn=None, broker_fn=None):
    """(broker, connection) or a status dict that the caller returns as-is."""
    getter = connection_fn or _link.get_ctrader_connection
    try:
        conn = getter(user_id, ctid=ctid)
    except _link.LinkConfigError:
        # A failed token persistence step is an infrastructure failure, not
        # evidence that the client has no account. Let the API return 503.
        raise
    except _link.LinkError as e:
        if e.code in ("NO_SUCH_ACCOUNT", "LIVE_BLOCKED"):
            raise
        if e.code in ("REFRESH_UNAVAILABLE", "REFRESH_FAILED"):
            # The link exists; the credential behind it is dead. This is the
            # one case that must NOT read as "not connected", because the
            # remedy is different: reconnect, not connect.
            return None, {"connected": True, "status": REAUTH_REQUIRED,
                          "reason": "the cTrader authorisation has expired — "
                                    "reconnect the account"}
        return None, _disconnected(e.detail)
    if not conn:
        return None, _disconnected(
            "no cTrader account is connected, or none has been selected")

    # The account id is part of the security boundary, not merely a routing
    # hint.  A connector factory or test double that returns a connection for
    # a different account must never be allowed to service this request: all
    # subsequent reads would otherwise be honest responses about the wrong
    # broker account.  Refuse the mismatch before constructing a broker.
    if ctid is not None and str(conn.get("ctid")) != str(ctid):
        raise _link.LinkError(
            "ACCOUNT_BINDING_MISMATCH",
            "the broker connection did not match the requested account")

    if broker_fn is None:
        from apex import user_loop, user_store
        try:
            user = user_store.load(user_id) or {}
        except Exception as e:  # noqa: BLE001
            return None, {"connected": True, "status": UNAVAILABLE,
                          "reason": _scrub(e, conn.get("accessToken"))}
        broker_fn = lambda: user_loop._make_broker(
            user, user_id, ctid=ctid)[0]
    try:
        return broker_fn(), conn
    except Exception as e:  # noqa: BLE001
        return None, {"connected": True, "status": UNAVAILABLE,
                      "reason": _scrub(e, conn.get("accessToken"))}


def _read(user_id, key, call, *, ctid=None, connection_fn=None,
          broker_fn=None):
    broker, other = _open(user_id, ctid=ctid, connection_fn=connection_fn,
                          broker_fn=broker_fn)
    if broker is None:
        return other
    conn = other
    try:
        data = call(broker)
    except Exception as e:  # noqa: BLE001
        # Deliberately not an empty list. "We could not ask" and "there is
        # nothing" look identical to a dashboard and mean opposite things.
        return {"connected": True, "status": UNAVAILABLE,
                "accountId": conn.get("ctid"), "mode": conn.get("mode"),
                "reason": _scrub(e, conn.get("accessToken"))}
    return {"connected": True, "status": OK, "accountId": conn.get("ctid"),
            "mode": conn.get("mode"), key: data}


def _quote(broker, symbol):
    """Return bid, ask, received timestamp from a read-only broker quote."""
    getter = getattr(broker, "get_quote", None)
    if callable(getter):
        quote = getter(symbol)
        if isinstance(quote, dict):
            return (quote["bid"], quote["ask"],
                    quote.get("receivedAt", quote.get("timestamp", time.time())))
        if len(quote) == 3:
            return quote
        bid, ask = quote
        return bid, ask, time.time()
    bid, ask = broker.get_bid_ask(symbol)
    return bid, ask, time.time()


def _enrich_positions(broker):
    rows = broker.get_all_positions()
    out = []
    for original in rows:
        row = dict(original)
        symbol = row.get("symbol")
        bid, ask, received_at = _quote(broker, symbol)
        side = str(row.get("side") or "").upper()
        current = bid if side == "BUY" else ask if side == "SELL" else None
        age = max(0.0, time.time() - float(received_at))
        row["currentPrice"] = current
        row["quoteAgeSec"] = round(age, 1)
        row["quoteStale"] = age > 30.0

        stop = row.get("stopLoss")
        target = row.get("takeProfit")
        row["hasStop"] = stop is not None
        if stop is None:
            row["warning"] = "UNPROTECTED: no stop-loss is attached"
        row["stopDistancePips"] = (
            abs(forex.to_pips(current - stop, symbol, current))
            if current is not None and stop is not None else None)
        row["targetDistancePips"] = (
            abs(forex.to_pips(current - target, symbol, current))
            if current is not None and target is not None else None)

        entry = row.get("entryPrice")
        units = row.get("units")
        if (current is not None and not row["quoteStale"] and entry is not None
                and units is not None and side in ("BUY", "SELL")):
            direction = 1 if side == "BUY" else -1
            row["pnlPips"] = round(
                forex.to_pips((current - entry) * direction, symbol, current), 1)
            row["pnlAccount"] = round(
                forex.pnl_usd(side, entry, current, units, symbol), 2)
            row["pnlIsEstimate"] = not (
                original.get("pnlPips") is not None
                and original.get("pnlAccount") is not None)
        else:
            row["pnlPips"] = None
            row["pnlAccount"] = None
            row["pnlIsEstimate"] = True
        out.append(row)
    return out


def positions(user_id, **kw):
    return _read(user_id, "positions", _enrich_positions, **kw)


def _deal_rows(broker, days):
    if days is None:
        days = 7
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("days must be a whole number")
    if days < 1 or days > 30:
        raise ValueError("days must be between 1 and 30")
    end = int(time.time())
    history = broker.get_deal_history(end - days * 86400, end)
    if not isinstance(history, dict) or not history.get("ok"):
        reason = (history or {}).get("error", "the broker did not return deal history")
        raise RuntimeError(reason)
    raw = history.get("deals")
    if not isinstance(raw, dict):
        raise RuntimeError("the broker returned an invalid deal history")
    return [{
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "units": row.get("units"),
        "entry": row.get("entryPrice"),
        "exit": row.get("exitPrice"),
        "net": row.get("netPnl"),
        "closedAt": row.get("closedAt"),
        "positionId": row.get("positionId"),
    } for row in raw.values()]


def deals(user_id, *, days=7, **kw):
    broker, other = _open(user_id, ctid=kw.get("ctid"),
                          connection_fn=kw.get("connection_fn"),
                          broker_fn=kw.get("broker_fn"))
    if broker is None:
        return other
    conn = other
    try:
        parsed_days = int(days if days is not None else 7)
    except (TypeError, ValueError):
        # Keep the same honest validation/error envelope as the uncached path.
        return {"connected": True, "status": UNAVAILABLE,
                "accountId": conn.get("ctid"), "mode": conn.get("mode"),
                "reason": "days must be a whole number"}
    key = (str(user_id), str(conn.get("ctid")), parsed_days)
    with _deals_cache_lock:
        fetch_lock = _deals_fetch_locks.setdefault(key, threading.Lock())
    # Serialize misses for one account so concurrent dashboard requests do
    # not each walk forty pages of broker history after the TTL expires.
    with fetch_lock:
        now = time.monotonic()
        with _deals_cache_lock:
            cached = _deals_cache.get(key)
            if cached and now - cached[0] < DEALS_CACHE_TTL_S:
                return {"connected": True, "status": OK,
                        "accountId": conn.get("ctid"),
                        "mode": conn.get("mode"),
                        "deals": copy.deepcopy(cached[1])}
        try:
            rows = _deal_rows(broker, parsed_days)
        except Exception as e:  # noqa: BLE001
            return {"connected": True, "status": UNAVAILABLE,
                    "accountId": conn.get("ctid"), "mode": conn.get("mode"),
                    "reason": _scrub(e, conn.get("accessToken"))}
        stored_at = time.monotonic()
        with _deals_cache_lock:
            _deals_cache[key] = (stored_at, copy.deepcopy(rows))
            if len(_deals_cache) > DEALS_CACHE_MAX:
                oldest = sorted(_deals_cache,
                                key=lambda item: _deals_cache[item][0])
                for old_key in oldest[:len(_deals_cache) - DEALS_CACHE_MAX]:
                    _deals_cache.pop(old_key, None)
    return {"connected": True, "status": OK,
            "accountId": conn.get("ctid"), "mode": conn.get("mode"),
            "deals": rows}


def orders(user_id, **kw):
    return _read(user_id, "orders", lambda b: b.get_pending_orders(), **kw)


def account(user_id, **kw):
    """Balance and mode for the selected account."""
    return _read(user_id, "balance", lambda b: b.get_balance(), **kw)


# Bounded so one request cannot ask for a year of minute bars and hold a
# worker open while cTrader streams it. 1000 is well past anything the
# condition library needs: the longest default period is 200.
MAX_CANDLES = 1000
DEFAULT_CANDLES = 200


def validate_candle_query(symbol, timeframe, limit):
    """(symbol, timeframe, limit) or ValueError.

    Checked BEFORE a broker is opened. A mistyped timeframe is a mistake in
    the request, not a state of the connection, and answering it with
    "unavailable" would send whoever reads that after a broker problem that
    does not exist. It also means a bad request never spends a socket.
    """
    from apex import forex
    sym = str(symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    if not forex.is_tradeable(sym):
        raise ValueError(
            f"{sym} is not an instrument this platform trades — spot FX with "
            f"a USD leg, plus metals")
    tf = str(timeframe or "").strip().lower()
    if tf not in forex.TIMEFRAMES:
        raise ValueError(
            f"timeframe must be one of {', '.join(forex.TIMEFRAMES)}, "
            f"got {timeframe!r}")
    if limit is None or limit == "":
        n = DEFAULT_CANDLES
    else:
        try:
            n = int(limit)
        except (TypeError, ValueError):
            raise ValueError(f"limit must be a whole number, got {limit!r}")
    if n < 2 or n > MAX_CANDLES:
        raise ValueError(f"limit must be between 2 and {MAX_CANDLES}, got {n}")
    return sym, tf, n


def candles(user_id, *, symbol, timeframe, limit=None, **kw):
    """Trendbars for a preview. Read-only, and it places nothing.

    The bars come from the SAME connector the trading loop uses, through the
    same shared candle cache — not a second path to the broker. What makes
    this safe is not a promise: this module imports no gate, no ledger and no
    order function, and a test walks its AST to keep it that way.

    The answer carries the usual {connected, status} contract, so a broker
    that cannot be reached produces `unavailable` rather than an empty list
    that a preview would then evaluate as if it were the market.
    """
    sym, tf, n = validate_candle_query(symbol, timeframe, limit)
    out = _read(user_id, "candles",
                lambda b: _shape(b.get_candles(sym, tf, n)), **kw)
    if out.get("status") == OK:
        out["symbol"] = sym
        out["timeframe"] = tf
        # The count actually returned, which can be fewer than asked for on a
        # young instrument. Stated so a preview that then refuses for want of
        # history can point at the real reason.
        out["requested"] = n
        out["count"] = len(out.get("candles") or [])
    return out


def _shape(rows):
    """Only the five fields a snapshot needs, as plain numbers.

    Narrowed on purpose: whatever else the connector attaches to a bar is not
    part of this contract, and passing it through would make it one.
    """
    out = []
    for r in rows or []:
        try:
            bar = {k: float(r[k]) for k in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError):
            continue
        if r.get("time") is not None:
            bar["time"] = r["time"]
        out.append(bar)
    return out
