"""Mini App read-only API: trade history, and the replay of one past trade.

READ ONLY. Nothing here opens, closes, amends or authorizes anything. It reads
the caller's own journal and asks the broker for candles. The trading core
stays the only thing that trades.

THE OWNERSHIP RULE, because it is the one that matters. Every function takes a
`chat_id` that the CALLER HAS ALREADY PROVEN — bot.py derives it from Telegram
initData whose HMAC it verified, never from a query parameter. Nothing here
accepts a user id from the client, and `find_trade` resolves ids only within
one user's own journal, so a crafted trade id cannot reach another account's
row: the id is looked up in a list that only ever contained this user's trades.

WHY THE REPLAY WINDOW IS ANCHORED TO THE TRADE. `get_candles(to_ts=...)` ends
the window at a chosen moment instead of at "now". Without that the replay
would draw today's market under a trade from three weeks ago — the chart would
render, the markers would land on unrelated candles, and nothing about it would
look broken.
"""
import hashlib
import time
from datetime import datetime, timezone

# The client may ask for these and nothing else. An unknown timeframe is an
# error, never a silent substitution — a chart secretly showing M5 when the
# caller asked for H1 is worse than a refusal.
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

# Context around the trade, in bars. Enough to see what the setup looked like
# and how it resolved, bounded so a replay never pulls an unbounded history.
BARS_BEFORE = 40
BARS_AFTER = 20
MAX_BARS = 300

HISTORY_PAGE_MAX = 50


class ReplayError(Exception):
    """Carries a code the UI maps to a sentence, never a stack trace."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _parse_ts(value):
    """Journal timestamps to unix seconds, or None.

    The journal writes local-format strings ("2026-08-14 20:06:11") and some
    rows carry epoch numbers. Both appear; neither is worth crashing over.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v      # tolerate milliseconds
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        return float(s)
    except ValueError:
        return None


def trade_id(row) -> str:
    """A stable identifier for one journal row.

    The broker's positionId when there is one — it is the real identity of the
    trade and survives the journal being re-read, re-sorted or trimmed.

    Otherwise a hash of the fields that together identify the close (time,
    symbol, entry, exit, pnl). Deterministic on purpose: the array index would
    have been easier and is exactly what must not be used, because it renames
    every trade the moment one is inserted or the list is reordered — a
    bookmarked replay would silently open a DIFFERENT trade.
    """
    r = row or {}
    pid = r.get("positionId")
    if pid not in (None, "", 0):
        return f"p{pid}"
    basis = "|".join(str(r.get(k, "")) for k in
                     ("time", "symbol", "entry", "exit", "netPnl", "openedAt"))
    return "h" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _num(value):
    """A float, or None. Never raises.

    Journals accumulate rows from several code paths across a long time, and
    one of them will eventually hold a string where a number belongs. Letting
    that raise here took the ENTIRE history screen down over a single bad row —
    found by the malformed-row test, which is the only reason it is not a
    production incident. One unreadable trade should cost you that trade.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_view(row):
    """One journal row as the UI needs it. Never invents a missing value."""
    r = row or {}
    net = _num(r.get("netPnl"))
    return {
        "id": trade_id(r),
        "symbol": r.get("symbol"),
        "side": r.get("side"),
        "entry": _num(r.get("entry")),
        "exit": _num(r.get("exit")),
        "netPnl": net,
        "win": (None if net is None else net >= 0),
        "time": r.get("time"),
        "openedAt": r.get("openedAt"),
        "mode": r.get("mode"),
        "strategyId": r.get("strategyId"),
    }


def history(chat_id, *, limit=25, offset=0):
    """This user's closed trades, newest first, bounded.

    Reads only `chat_id`'s journal — there is no query that spans users, so
    there is nothing to filter out client-side and nothing to leak by
    forgetting to.
    """
    from apex import user_store
    limit = max(1, min(int(limit or 25), HISTORY_PAGE_MAX))
    offset = max(0, int(offset or 0))
    try:
        rows = user_store.load_trades(str(chat_id)) or []
    except Exception as e:
        raise ReplayError("HISTORY_UNAVAILABLE", str(e)[:120])
    # The journal is appended chronologically; the client wants newest first.
    ordered = list(reversed(rows))
    page = ordered[offset:offset + limit]
    return {
        "trades": [_row_view(r) for r in page],
        "total": len(ordered),
        "offset": offset,
        "limit": limit,
        "hasMore": offset + len(page) < len(ordered),
    }


def find_trade(chat_id, tid):
    """One of THIS user's trades by id, or None.

    Ownership is structural rather than checked: the candidate rows are this
    user's journal and nothing else, so an id belonging to somebody else simply
    does not match anything here.
    """
    from apex import user_store
    if not tid:
        return None
    try:
        rows = user_store.load_trades(str(chat_id)) or []
    except Exception as e:
        raise ReplayError("HISTORY_UNAVAILABLE", str(e)[:120])
    want = str(tid)
    for r in rows:
        try:
            if trade_id(r) == want:
                return r
        except Exception:
            continue          # a malformed row is skipped, never fatal
    return None


def _window(entry_ts, exit_ts, tf):
    """(from_ts, to_ts, bars) covering the trade plus context."""
    step = _TF_SECONDS[tf]
    start = entry_ts - BARS_BEFORE * step
    end = exit_ts + BARS_AFTER * step
    bars = int((end - start) / step) + 2
    if bars > MAX_BARS:
        # Long trade on a fine timeframe. Keep the window anchored on the trade
        # and drop context rather than silently returning a partial window that
        # starts after the entry.
        bars = MAX_BARS
        start = max(entry_ts - BARS_BEFORE * step, end - MAX_BARS * step)
    return start, end, bars


def replay(chat_id, tid, timeframe="15m"):
    """Everything needed to draw one past trade. Raises ReplayError with a code.

    The candles come from the broker anchored to the trade's own timestamps.
    The markers come from the JOURNAL's stored entry/exit prices, never from a
    candle's open or close — the fill happened at a price, and reading it off a
    bar would quietly move the marker to wherever that bar happened to end.
    """
    from apex import user_loop, user_store

    tf = str(timeframe or "15m").lower()
    if tf not in TIMEFRAMES:
        raise ReplayError("INVALID_TIMEFRAME", tf)

    row = find_trade(chat_id, tid)
    if not row:
        raise ReplayError("TRADE_NOT_FOUND")

    symbol = row.get("symbol")
    entry_ts = _parse_ts(row.get("openedAt")) or _parse_ts(row.get("time"))
    exit_ts = _parse_ts(row.get("time")) or entry_ts
    if not symbol or not entry_ts:
        raise ReplayError("TRADE_INCOMPLETE")
    if exit_ts < entry_ts:
        exit_ts = entry_ts

    start, end, bars = _window(entry_ts, exit_ts, tf)

    try:
        user = user_store.load(str(chat_id)) or {}
    except Exception as e:
        raise ReplayError("ACCOUNT_UNAVAILABLE", str(e)[:120])
    if not user:
        raise ReplayError("ACCOUNT_UNAVAILABLE")

    try:
        broker, _cfg = user_loop._make_broker(user)
        candles = broker.get_candles(symbol, tf, bars, to_ts=int(end)) or []
    except Exception as e:
        raise ReplayError("MARKET_DATA_UNAVAILABLE", str(e)[:120])
    if not candles:
        raise ReplayError("MARKET_DATA_UNAVAILABLE", "no bars for that period")

    net = _num(row.get("netPnl"))
    return {
        "trade": _row_view(row),
        "timeframe": tf,
        "candles": candles,
        "window": {"from": int(start), "to": int(end), "bars": len(candles)},
        "markers": {
            "entry": {"time": int(entry_ts), "price": _num(row.get("entry"))},
            "exit": {"time": int(exit_ts), "price": _num(row.get("exit")),
                     "win": (None if net is None else net >= 0)},
        },
        # What APEX knew AT ENTRY — read back, never recomputed from today's
        # indicators. A value the journal does not hold stays null so the UI can
        # say "not recorded" instead of showing a number invented after the fact.
        "snapshot": {
            "strategyId": row.get("strategyId"),
            "strategyVersion": row.get("strategyVersion"),
            "confidence": row.get("confidence"),
            "probability": row.get("probability"),
            "regime": row.get("regime"),
            "spreadPips": row.get("spreadPips"),
            "atr": row.get("atr"),
            "slPips": row.get("slPips"),
            "tpPips": row.get("tpPips"),
            "evR": row.get("evR"),
        },
        "generatedAt": int(time.time()),
    }
