"""Performance for the web: the same figures the Telegram bot showed.

This is a thin READ over `apex.performance`, which already computes win rate,
profit factor, expectancy and drawdown (and the per-strategy split) from the
closed-trade journal. Nothing is recomputed here — a second expectancy formula
that drifts from the first is worse than none.

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

NOTE = ("Closed trades the engine recorded. A position you closed by hand at "
        "your broker may not appear until the engine next reconciles, and an "
        "open position is not a result yet.")


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


def read(user_id, *, period="all", mode="demo", rows_reader=None, now=None):
    """Closed-trade performance for one client. Raises ValueError on bad input;
    otherwise returns a dict and never lets one unreadable journal become a
    success with zeros."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")

    try:
        if rows_reader is None:
            from apex import user_store
            rows = user_store.load_trades(str(user_id))
        else:
            rows = rows_reader(str(user_id))
        rows = list(rows or [])
    except Exception as e:                                   # noqa: BLE001
        # An unreadable journal is NOT "no trades". Said as unreadable.
        print(f"[Performance] journal unreadable ({type(e).__name__})")
        return {"status": "unavailable",
                "reason": "the trade journal could not be read just now"}

    now = now or datetime.now()
    if period != "all":
        day = (now - timedelta(days=_DAYS_BACK[period])).strftime("%Y-%m-%d")
        in_period = _perf.since(rows, day)
    else:
        in_period = rows

    def _mode(r):
        v = r.get("mode")
        return v if v in ("demo", "live") else "unknown"

    unknown = [r for r in in_period if _mode(r) == "unknown"]
    wrong = [r for r in in_period if _mode(r) not in (mode, "unknown")] \
        if mode != "all" else []
    chosen = in_period if mode == "all" else [r for r in in_period if _mode(r) == mode]

    return {
        "status": "ok", "period": period, "mode": mode,
        "summary": _clean(_perf.summarize(chosen)),
        "byStrategy": _ranked(_perf.by_strategy(chosen), _label),
        "bySymbol": _ranked(_perf.by_symbol(chosen), lambda n: n),
        "minTrades": MIN_TRADES,
        "excluded": {"unknownMode": len(unknown) if mode != "all" else 0,
                     "otherMode": len(wrong)},
        "journalTrades": len(rows),
        "note": NOTE,
    }
