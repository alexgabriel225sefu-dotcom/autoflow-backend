"""Performance for the web: the same figures the Telegram bot showed.

This is a thin READ over `apex.performance`, which already computes win rate,
profit factor, expectancy and drawdown (and the per-strategy split). Nothing is
recomputed here — a second expectancy formula that drifts from the first is
worse than none.

THE CLOSED TRADES COME FROM THE BROKER'S DEAL HISTORY — the same source the
Positions page lists — joined by position id to the engine's trade journal ONLY
to learn which strategy opened each one. The first version read the journal
alone and told a client "no closed trades" over trades the Positions page was
showing: the journal only holds what the loop recorded, and a trade closed by
hand, or before the journal labelled it, was invisible to it. The broker is the
authority on what closed; the journal is the authority on why it was opened.
A deal with no journal row is real and is counted, as "unlabelled".

If the broker cannot be read, the answer is `unavailable` with the reason. It
is never a zero-trade success built from the journal alone.

WHAT THIS ADDS, AND WHY EACH THING IS HERE

* A MODE FILTER, demo by default. The journal mixes demo, live and older rows
  with no mode; a report that blends them is useless exactly when it matters.
  Rows with no recorded mode are COUNTED and reported (`excluded.unknownMode`)
  but never guessed into demo.
* A PERIOD (today / week / month / all), cut the way the bot cut it.
* JSON THAT IS JSON. `apex.performance` returns `float("inf")` for a profit
  factor with no losing trade; `json.dumps` renders that as `Infinity`, which
  a browser's JSON.parse rejects — the whole page would fail on the best
  possible result. It becomes `null` with `noLosses: true`.
* THIN GROUPS LABELLED. Three trades is not evidence; groups under three are
  returned last and flagged `thin` so a screen cannot rank on luck.
* WHAT THE NUMBERS ARE NOT. They are closed trades the ENGINE recorded.
  A position closed by hand at the broker, or by the Close button, may not be
  in the journal until the loop reconciles it; the response says so in
  `note`, and an empty journal is `trades: 0`, not "no losses".
"""
import math
from datetime import datetime, timedelta

from apex import performance as _perf

PERIODS = ("today", "week", "month", "all")
MODES = ("demo", "live", "all")
_DAYS_BACK = {"today": 0, "week": 6, "month": 29}
MIN_TRADES = 3
# The broker keeps this much deal history reachable through `broker_read.deals`.
BROKER_WINDOW_DAYS = 30

NOTE = ("Closed trades from your broker's deal history for the last 30 days "
        "(\"All time\" adds older trades the engine recorded). Each deal is "
        "counted once, so a position closed in two parts counts as two. Trades "
        "the engine did not open show as unlabelled, and an open position is "
        "not a result yet.")


def _finite(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v) else None


def _clean(summary):
    """A summary safe to serialise: no inf/NaN, and the reason said out loud."""
    out = dict(summary)
    out["noLosses"] = bool(out.get("wins")) and not out.get("losses")
    for k in ("profit_factor", "expectancy", "net", "win_rate", "max_drawdown",
              "avg_win", "avg_loss", "best", "worst"):
        if k in out:
            out[k] = _finite(out[k])
    if isinstance(out.get("r"), dict):
        out["r"] = {k: (_finite(v) if isinstance(v, (int, float)) else v)
                    for k, v in out["r"].items()}
    return out


def _label(strategy_id):
    if strategy_id == _perf.UNLABELLED:
        return "Unlabelled (older trades)"
    if strategy_id == "platform_rule":
        return "My conditions"
    try:
        from apex.platform import strategy_catalog
        d = strategy_catalog.get(strategy_id)
        if d and d.get("label"):
            return str(d["label"])
    except Exception:                                        # noqa: BLE001
        pass
    return str(strategy_id)


def _ranked(groups, label_fn):
    out = []
    for name, s in _perf.ranked(groups, min_trades=MIN_TRADES):
        row = _clean(s)
        row["id"] = name
        row["label"] = label_fn(name)
        out.append(row)
    return out


def _stamp(ts):
    """'YYYY-MM-DD HH:MM:SS' (server-local, as the journal writes it), or ''."""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _mode_of(row):
    v = row.get("mode")
    return v if v in ("demo", "live") else "unknown"


def _deal_to_row(deal, journal_by_pos, acct_mode):
    """A broker deal as the row shape `apex.performance` reads.

    The deal supplies everything about the CLOSE (instrument, side, prices, net,
    time). The journal row with the same position id, if any, supplies only the
    strategy and the stop distance (for R). No journal row: unlabelled.
    """
    pid = str(deal.get("positionId")) if deal.get("positionId") is not None else None
    j = journal_by_pos.get(pid) if pid else None
    return {
        "time": _stamp(deal.get("closedAt")),
        "symbol": deal.get("symbol"), "side": deal.get("side"),
        "entry": deal.get("entry"), "exit": deal.get("exit"),
        "netPnl": deal.get("net"),
        "positionId": pid,
        "strategyId": (j or {}).get("strategyId"),
        "slPips": (j or {}).get("slPips"),
        "mode": acct_mode,
        "_attributed": bool(j and j.get("strategyId")),
    }


def read(user_id, *, period="all", mode="demo", ctid=None, deals_reader=None,
         rows_reader=None, now=None):
    """Closed-trade performance for one client. Raises ValueError on bad input;
    otherwise returns a dict. A broker that cannot be read is `unavailable`."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")

    # ── the authority: what the broker says closed ──────────────────────────
    try:
        if deals_reader is None:
            from apex.platform import broker_read
            deals_reader = lambda uid, **kw: broker_read.deals(uid, **kw)  # noqa: E731
        got = deals_reader(str(user_id), days=BROKER_WINDOW_DAYS, ctid=ctid)
    except Exception as e:                                   # noqa: BLE001
        print(f"[Performance] broker deals unreadable ({type(e).__name__})")
        return {"status": "unavailable",
                "reason": "the broker's closed-trade history could not be read just now"}
    if not isinstance(got, dict) or got.get("status") != "ok":
        reason = ((got or {}).get("reason") if isinstance(got, dict) else None) \
            or "the broker's closed-trade history is not available"
        return {"status": "unavailable", "reason": str(reason)[:200],
                "brokerStatus": (got or {}).get("status") if isinstance(got, dict) else None}
    acct_mode = got.get("mode") if got.get("mode") in ("demo", "live") else "unknown"
    deals = [d for d in (got.get("deals") or []) if isinstance(d, dict)]

    # ── the journal, only to say which strategy opened each one ─────────────
    journal_ok = True
    try:
        if rows_reader is None:
            from apex import user_store
            journal = list(user_store.load_trades(str(user_id)) or [])
        else:
            journal = list(rows_reader(str(user_id)) or [])
    except Exception as e:                                   # noqa: BLE001
        print(f"[Performance] journal unreadable ({type(e).__name__})")
        journal, journal_ok = [], False
    by_pos = {str(r.get("positionId")): r for r in journal
              if r.get("positionId") is not None}

    rows = [_deal_to_row(d, by_pos, acct_mode) for d in deals]
    deal_ids = {r["positionId"] for r in rows if r["positionId"]}

    # "All time" is the broker's window plus anything older that only the
    # journal remembers (deduplicated by position id). Journal-only rows keep
    # their own recorded mode; one with no recorded mode is counted and left out.
    if period == "all":
        oldest = min((r["time"] for r in rows if r["time"]), default=None)
        for j in journal:
            pid = str(j.get("positionId")) if j.get("positionId") is not None else None
            if pid and pid in deal_ids:
                continue
            if oldest is not None and str(j.get("time", "")) >= oldest:
                continue        # inside the broker's window, and not there: not ours
            rows.append(dict(j, _attributed=bool(j.get("strategyId"))))

    now = now or datetime.now()
    if period != "all":
        day = (now - timedelta(days=_DAYS_BACK[period])).strftime("%Y-%m-%d")
        in_period = _perf.since(rows, day)
    else:
        in_period = rows

    unknown = [r for r in in_period if _mode_of(r) == "unknown"]
    wrong = [r for r in in_period if _mode_of(r) not in (mode, "unknown")] \
        if mode != "all" else []
    chosen = in_period if mode == "all" else [r for r in in_period if _mode_of(r) == mode]
    attributed = sum(1 for r in chosen if r.get("_attributed"))

    return {
        "status": "ok", "period": period, "mode": mode,
        "summary": _clean(_perf.summarize(chosen)),
        "byStrategy": _ranked(_perf.by_strategy(chosen), _label),
        "bySymbol": _ranked(_perf.by_symbol(chosen), lambda n: n),
        "minTrades": MIN_TRADES,
        "excluded": {"unknownMode": len(unknown) if mode != "all" else 0,
                     "otherMode": len(wrong)},
        "source": {"closedTrades": "broker deal history",
                   "windowDays": BROKER_WINDOW_DAYS,
                   "journalReadable": journal_ok,
                   "attributed": attributed,
                   "unattributed": len(chosen) - attributed},
        "journalTrades": len(journal),
        "note": NOTE,
    }
