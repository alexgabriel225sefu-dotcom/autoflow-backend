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

from apex.platform import ctrader_link as _link

# Bounded so a hung broker cannot hold an HTTP worker open indefinitely.
DEFAULT_TIMEOUT_S = 12.0

NOT_CONNECTED = "not_connected"
REAUTH_REQUIRED = "reauth_required"
UNAVAILABLE = "unavailable"
OK = "ok"


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

    if broker_fn is None:
        from apex import user_loop, user_store
        try:
            user = user_store.load(user_id) or {}
        except Exception as e:  # noqa: BLE001
            return None, {"connected": True, "status": UNAVAILABLE,
                          "reason": _scrub(e, conn.get("accessToken"))}
        broker_fn = lambda: user_loop._make_broker(user, user_id)[0]
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


def positions(user_id, **kw):
    return _read(user_id, "positions", lambda b: b.get_all_positions(), **kw)


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
