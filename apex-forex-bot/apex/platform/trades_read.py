"""Closed trades for the web: one row per trade, and the curve they make.

THE BROKER SAYS WHAT CLOSED; THE JOURNAL SAYS WHY IT WAS OPENED

Same split as `performance_read`, for the same reason. Every trade here comes
from the broker's deal history (`broker_read.deals`), joined by position id to
the engine's trade journal ONLY to learn the strategy and the stop and target
distances the engine chose at entry. A deal with no journal row is real and is
listed, with those fields null.

WHAT A FIELD MEANS, AND WHEN IT IS NULL

  openedAt, durationS   The time of the opening deal. Known only when that deal
                        is inside the window the broker was asked about, so the
                        read asks for `PAD_DAYS` more than the range and then
                        keeps only trades CLOSED inside the range. A position
                        that opened before even that has no recoverable start,
                        and the answer is null rather than an estimate.
  slPrice, tpPrice      The levels the engine set at ENTRY: the entry price moved
                        by the journal's `slPips` / `tpPips` in the direction
                        that protects or targets. They are where the stop and
                        target started, not where a trailing stop ended, and
                        they are null unless the side, the entry and the
                        distance are all known.
  strategyId, strategy  Null for a trade the engine did not record.
  gross, swap, commission  As the broker reported them; null when it did not.

AMOUNTS HAVE NO CURRENCY HERE. They are in the account's deposit currency, and
this platform does not read which currency that is. `currency` is therefore
null, said in the note, and never filled with a guess such as USD.

If the broker cannot be read the answer is `unavailable` with the reason. It is
never an empty list of trades built from the journal alone.
"""
import math
import time

from apex import forex
from apex.platform import performance_read as _pr
from apex.platform import pnl_series

MAX_DAYS = 3650                  # the bound broker_read.deals enforces
DEFAULT_DAYS = 30
# Extra history requested so a trade closed near the start of the range still
# finds the deal that opened it. Positions held longer than this show no open
# time.
PAD_DAYS = 2

NOTE = ("Closed trades from your broker's deal history. Amounts are in the "
        "account's deposit currency, which is not read here. Stop and target "
        "are the levels set at entry, from the engine's own record, and are "
        "empty for trades the engine did not open. An open position is not a "
        "result yet.")


def _num(v):
    return v if (isinstance(v, (int, float)) and not isinstance(v, bool)
                 and math.isfinite(v)) else None


def _levels(side, entry, sl_pips, tp_pips, symbol):
    """(stop price, target price) at entry, each None unless fully known."""
    entry, side = _num(entry), str(side or "").upper()
    if entry is None or side not in ("BUY", "SELL"):
        return None, None
    sign = 1 if side == "BUY" else -1

    def price(pips, toward):
        pips = _num(pips)
        if pips is None or pips <= 0:
            return None
        return round(entry + toward * sign * forex.from_pips(pips, symbol, entry), 6)

    return price(sl_pips, -1), price(tp_pips, +1)


def _trade(deal, journal_by_pos):
    pid = str(deal["positionId"]) if deal.get("positionId") is not None else None
    j = journal_by_pos.get(pid) if pid else None
    j = j or {}
    sid = j.get("strategyId") or None
    sl_pips, tp_pips = _num(j.get("slPips")), _num(j.get("tpPips"))
    sl, tp = _levels(deal.get("side"), deal.get("entry"), sl_pips, tp_pips,
                     deal.get("symbol"))
    return {
        "positionId": pid,
        "symbol": deal.get("symbol"),
        "side": deal.get("side"),
        "units": deal.get("units"),
        "openedAt": deal.get("openedAt"),
        "closedAt": deal.get("closedAt"),
        "durationS": deal.get("durationS"),
        "entry": deal.get("entry"),
        "exit": deal.get("exit"),
        "net": deal.get("net"),
        "gross": deal.get("gross"),
        "swap": deal.get("swap"),
        "commission": deal.get("commission"),
        "strategyId": sid,
        "strategy": _pr._label(sid) if sid else None,
        "slPips": sl_pips, "tpPips": tp_pips,
        "slPrice": sl, "tpPrice": tp,
    }


def _days(value):
    if isinstance(value, bool):
        raise ValueError("days must be a whole number")
    try:
        n = int(value if value is not None else DEFAULT_DAYS)
    except (TypeError, ValueError):
        raise ValueError("days must be a whole number")
    if n < 1 or n > MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")
    return n


def read(user_id, *, days=DEFAULT_DAYS, mode="demo", ctid=None,
         deals_reader=None, rows_reader=None, now=None):
    """Closed trades in the last `days` days, newest first, plus the curve.

    Raises ValueError on bad input. A broker that cannot be read is
    `unavailable`, never an empty success.
    """
    days = _days(days)
    if mode not in _pr.MODES:
        raise ValueError(f"mode must be one of {', '.join(_pr.MODES)}")
    now_ts = time.time() if now is None else float(now)

    try:
        if deals_reader is None:
            from apex.platform import broker_read
            deals_reader = lambda uid, **kw: broker_read.deals(uid, **kw)  # noqa: E731
        got = deals_reader(str(user_id), days=min(days + PAD_DAYS, MAX_DAYS),
                           ctid=ctid)
    except Exception as e:                                   # noqa: BLE001
        print(f"[Trades] broker deals unreadable ({type(e).__name__})")
        return {"status": "unavailable",
                "reason": "the broker's closed-trade history could not be read just now"}
    if not isinstance(got, dict) or got.get("status") != "ok":
        reason = ((got or {}).get("reason") if isinstance(got, dict) else None) \
            or "the broker's closed-trade history is not available"
        return {"status": "unavailable", "reason": str(reason)[:200],
                "brokerStatus": got.get("status") if isinstance(got, dict) else None}
    acct_mode = got.get("mode") if got.get("mode") in ("demo", "live") else "unknown"

    cutoff = now_ts - days * 86400
    in_range, undated = [], 0
    for d in got.get("deals") or []:
        if not isinstance(d, dict):
            continue
        closed = _num(d.get("closedAt"))
        if closed is None:
            undated += 1
        elif closed >= cutoff:
            in_range.append(d)

    journal_ok = True
    try:
        if rows_reader is None:
            from apex import user_store
            journal = list(user_store.load_trades(str(user_id)) or [])
        else:
            journal = list(rows_reader(str(user_id)) or [])
    except Exception as e:                                   # noqa: BLE001
        print(f"[Trades] journal unreadable ({type(e).__name__})")
        journal, journal_ok = [], False
    by_pos = {str(r.get("positionId")): r for r in journal
              if isinstance(r, dict) and r.get("positionId") is not None}

    other_mode = 0
    if mode != "all" and acct_mode != mode:
        # The account on file is not the kind asked for. Its trades are
        # counted, not shown, and not guessed into the other kind.
        other_mode, in_range = len(in_range), []

    trades = [_trade(d, by_pos) for d in in_range]
    trades.sort(key=lambda t: t["closedAt"], reverse=True)
    series = pnl_series.build([{"closedAt": t["closedAt"], "netPnl": t["net"]}
                               for t in trades])
    nets = [t["net"] for t in trades if _num(t["net"]) is not None]
    return {
        "status": "ok", "mode": mode, "accountMode": acct_mode,
        "accountId": got.get("accountId"), "days": days, "currency": None,
        "trades": trades,
        "summary": {"trades": len(trades), "net": round(sum(nets), 2),
                    "wins": sum(1 for n in nets if n > 0),
                    "losses": sum(1 for n in nets if n < 0)},
        "daily": series["daily"], "equity": series["equity"],
        "excluded": {"otherMode": other_mode, "undated": undated,
                     "unusableForCurve": series["excluded"]},
        "source": {"closedTrades": "broker deal history",
                   "journalReadable": journal_ok,
                   "labelled": sum(1 for t in trades if t["strategyId"])},
        "note": NOTE,
    }
