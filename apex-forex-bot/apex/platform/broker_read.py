"""Reading a client's cTrader account. Reads only — nothing here can trade.

WHAT THIS MODULE MAY DO IS BOUNDED BY WHAT IT CALLS

Five connector methods: get_all_positions, get_pending_orders, get_balance,
get_candles and list_symbols (the broker's own symbol list).
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
# The most deal history one request may ask for.
MAX_DEAL_DAYS = 3650
DEALS_CACHE_TTL_S = 60.0
DEALS_CACHE_MAX = 256
_deals_cache = {}
_deals_cache_lock = threading.Lock()
_deals_fetch_locks = {}


def _human_broker_fault(exc, *secrets):
    """A sentence a client can read. A raw int(None) is not one.

    The TypeError text was shown in full on Orders and the market panel.
    The id was missing; saying so is the whole message.
    """
    raw = _scrub(exc, *secrets)
    if "NoneType" in raw or raw.startswith("int() argument"):
        return ("the account id was missing, so this was not sent to the "
                "broker. Choose the account again.")
    return raw


def _scrub(text, *secrets):
    """An error message with every known secret removed."""
    # Only the access token was known here, so a refresh token, the app secret
    # or a bearer header in the same message went out in the clear. The shared
    # redactor masks the secrets this process holds, the SHAPE of the usual
    # ones, and anything else that merely looks like a credential.
    from apex import redact as _redact
    from apex.platform import safe_errors as _safe
    masked = _redact.scrub_for_client(text, *secrets, limit=300)
    # Then the SHAPES a connector message carries that are not credentials: a
    # host, an IP, a URL, a path. Naming the provider's endpoint to a client
    # helps nobody and tells a stranger where to look.
    return _safe.message(masked, fallback="the broker did not answer", limit=300)


def _disconnected(reason="no cTrader account is connected"):
    return {"connected": False, "status": NOT_CONNECTED, "reason": reason}


def _bound_account(broker):
    """The account id this broker object will talk to, or None if it has none
    to report."""
    getter = getattr(broker, "_ctid", None)
    if not callable(getter):
        return None
    try:
        return str(getter())
    except Exception:                                        # noqa: BLE001
        return None


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
        # Built for the connection's own account when none was asked about, so a
        # selection that changes between the two reads is neither served nor
        # refused as a mismatch: the broker is for the account that was read.
        if ctid is None:
            ctid = conn.get("ctid")
        broker_fn = lambda: user_loop._make_broker(
            user, user_id, ctid=ctid)[0]
    try:
        broker = broker_fn()
    except Exception as e:  # noqa: BLE001
        # The account is known — the connection was read before the broker
        # was built. Omitting it here made the orders page say "No account
        # selected" beside a status strip that showed the demo account.
        return None, {"connected": True, "status": UNAVAILABLE,
                      "accountId": conn.get("ctid"), "mode": conn.get("mode"),
                      "reason": _human_broker_fault(e, conn.get("accessToken"))}
    # The check above is about the CONNECTION. The broker is built separately,
    # and `user_loop._make_broker` prefers a token and account id stored on the
    # legacy user record over the platform connection it was handed. Nothing on
    # the platform writes those fields today, so this cannot fire now; it is
    # here so that the day something does, a read or a close is refused rather
    # than served - or sent - for a different account than the one asked about.
    # With no account asked about (the default positions and orders reads), the
    # connection's own account is what the broker must match. A broker with no
    # account to report (a test double) is not judged.
    bound = _bound_account(broker)
    expected = str(ctid if ctid is not None else conn.get("ctid"))
    if bound is not None and conn.get("ctid") is not None and bound != expected:
        raise _link.LinkError(
            "ACCOUNT_BINDING_MISMATCH",
            "the broker was built for a different account than the one "
            "requested")
    return broker, conn


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
                "reason": _human_broker_fault(e, conn.get("accessToken"))}
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
        # Some cTrader spot frames carry a price but no receive timestamp.
        # That is an unknown-age quote, not a reason to fail the whole read
        # (the previous float(None) made dashboard/positions unusable).
        age = (max(0.0, time.time() - float(received_at))
               if received_at is not None else None)
        row["currentPrice"] = current
        row["quoteAgeSec"] = round(age, 1) if age is not None else None
        row["quoteStale"] = age is None or age > 30.0

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
    if days < 1 or days > MAX_DEAL_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DEAL_DAYS}")
    end = int(time.time())
    history = broker.get_deal_history(end - days * 86400, end)
    if not isinstance(history, dict) or not history.get("ok"):
        reason = (history or {}).get("error", "the broker did not return deal history")
        raise RuntimeError(reason)
    # A history that broke off part-way, or stopped when the page budget ran
    # out, is NOT the account's history. The connector reports both (an `error`
    # beside ok:true, or `truncated`); serving the partial set — and caching it —
    # showed a confident total over trades it had not read.
    if history.get("error"):
        raise RuntimeError(
            f"the broker's deal history was cut short: {history['error']}")
    if history.get("truncated"):
        raise RuntimeError(
            "the broker's deal history is longer than could be read here; "
            "try a shorter period")
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
        "strategyId": row.get("strategyId"),
        "positionId": row.get("positionId"),
        # When the opening deal was inside the window the connector read. Absent
        # (None) otherwise: a start time is never estimated.
        "openedAt": row.get("openedAt"),
        "durationS": row.get("durationS"),
        "gross": row.get("grossPnl"),
        "swap": row.get("swap"),
        "commission": row.get("commissionUsd"),
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
    # Range-checked BEFORE the per-request lock key is built (same bounds as
    # `_deal_rows`). The key includes `days`, the locks are never pruned, and an
    # unchecked value made every distinct number a new entry for ever.
    if parsed_days < 1 or parsed_days > MAX_DEAL_DAYS:
        return {"connected": True, "status": UNAVAILABLE,
                "accountId": conn.get("ctid"), "mode": conn.get("mode"),
                "reason": f"days must be between 1 and {MAX_DEAL_DAYS}"}
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


def symbols(user_id, **kw):
    """Every instrument the selected account's broker lists, each classified
    by whether the engine can trade it today and, if not, why.

    A read: the connector is asked for its symbol list and nothing is sent.
    The data key is absent unless the broker answered, like every read here.
    """
    from apex.platform import instruments as _instruments
    return _read(user_id, "symbols",
                 lambda b: _instruments.describe(b.list_symbols()), **kw)


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


# The multiple of ATR the engine puts its stop at when it places ATR stops
# (user_loop). The estimate below uses the same number, which is why it says
# "typical" and "estimate": a rule that sets its own stop in pips, or a
# strategy with structural stops, will differ.
ATR_STOP_MULTIPLE = 2.5


def estimate_min_lot(*, balance, risk_fraction, symbol, price, atr, broker_min=None):
    """What a typical entry on `symbol` would risk once the broker's minimum
    order size is applied, against what the client chose to risk.

    Pure: numbers in, numbers out, nothing asked of a broker. The client picks
    1% on a $3,800 account; gold's broker minimum is 1 oz; a stop of 2.5 x ATR
    on the hourly chart is close to $100, so the smallest allowed trade risks
    about 2.6%, not 1%. Nothing on the Trade page said so before the first
    trade, and the account had lost 4.9% in a day by the second.

    None when the inputs cannot support an estimate.
    """
    try:
        balance = float(balance)
        risk_fraction = float(risk_fraction)
        price = float(price)
        atr = float(atr)
    except (TypeError, ValueError):
        return None
    if not (balance > 0 and risk_fraction > 0 and price > 0 and atr > 0):
        return None
    pip = forex.pip_size(symbol, price)
    # The same floor the engine applies: never inside spread-and-noise.
    distance = max(ATR_STOP_MULTIPLE * atr, 20.0 * pip)
    stop_pips = forex.to_pips(distance, symbol, price)
    floor = max(forex.min_units(symbol), float(broker_min or 0))
    wanted = forex.calc_units(balance, risk_fraction, stop_pips, symbol, price)
    units = forex.round_units(max(wanted, floor), symbol)
    risk_usd = forex.floor_risk_at(units, symbol, price, stop_pips)
    target_usd = balance * risk_fraction
    return {
        "minUnits": floor,
        "unitLabel": forex.unit_label(symbol),
        "units": units,
        "stopDistance": round(distance, 5),
        "targetUsd": round(target_usd, 2),
        "targetPct": round(risk_fraction * 100, 2),
        "riskUsd": round(risk_usd, 2),
        "riskPct": round(risk_usd / balance * 100, 2),
        # Over the target by more than a lot-step's rounding.
        "exceeds": risk_usd > target_usd * 1.10,
    }


def min_lot(user_id, *, symbol, timeframe, risk_percent, **kw):
    """Would the broker's minimum order size risk more than the client chose?

    Read-only, like the rest of this module: balance, candles and the symbol's
    minimum size are asked for, and nothing is sent. Answers {connected,
    status} like the others, with `minLot` present only when status is ok.
    """
    sym, tf, _n = validate_candle_query(symbol, timeframe, 60)
    try:
        risk = float(risk_percent)
    except (TypeError, ValueError):
        raise ValueError(f"riskPercent must be a number, got {risk_percent!r}")
    if not (0 < risk <= 100):
        raise ValueError(f"riskPercent must be between 0 and 100, got {risk:g}")

    def _call(b):
        bars = _shape(b.get_candles(sym, tf, 60))
        if len(bars) < 16:
            raise RuntimeError("not enough bars to estimate a stop")
        from apex import indicators as _ind
        series = _ind.atr(bars, 14)
        # A series with None until there are enough bars; the latest value is
        # the one that describes the market now.
        atr = next((v for v in reversed(series or []) if v), None)
        mn = None
        try:
            mn = b.min_units(sym)
        except Exception:  # noqa: BLE001 - unknown minimum falls back to the class guess
            mn = None
        out = estimate_min_lot(
            balance=b.get_balance(), risk_fraction=risk / 100.0, symbol=sym,
            price=bars[-1]["close"], atr=atr, broker_min=mn)
        if out is None:
            raise RuntimeError("could not estimate the minimum-size risk")
        out.update(symbol=sym, timeframe=tf,
                   basis=f"{ATR_STOP_MULTIPLE:g} x ATR(14) on the last bars")
        return out

    return _read(user_id, "minLot", _call, **kw)


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
