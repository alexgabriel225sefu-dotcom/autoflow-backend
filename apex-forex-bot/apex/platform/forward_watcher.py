"""Read-only forward-test watcher for platform accounts.

The watcher observes active RuleDocs at closed-bar boundaries. It never starts
or controls automation and never imports an order or close path. A bar-close
event is persisted once per user/rule/symbol; a later quote resolves its
hypothetical execution price and directional slippage when that quote can be
read.
"""

import threading
import time
from typing import Any, Callable

from apex import user_store
from apex.platform import broker_read, forward, rule_strategy, store

POLL_INTERVAL_S = 30.0
MAX_SYMBOLS_PER_RULE = 8
_lock = threading.Lock()
_stop = threading.Event()
_thread = None


def start() -> bool:
    """Start one daemon watcher; return False when it was already running."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_run, name="forward-watcher",
                                    daemon=True)
        _thread.start()
        return True


def stop(timeout: float = 2.0) -> None:
    """Stop the watcher during a graceful server shutdown."""
    _stop.set()
    thread = _thread
    if thread is not None:
        thread.join(timeout=max(0.0, float(timeout)))


def run_once(*, now: float | None = None,
             user_ids: list[str] | None = None,
             platform_reader: Callable[[str], bool] | None = None,
             active_reader: Callable[[str], list[dict[str, Any]]] | None = None,
             candle_reader: Callable[..., dict[str, Any]] | None = None,
             quote_reader: Callable[..., dict[str, Any]] | None = None) -> dict[str, int]:
    """Process one bounded read cycle; injectable readers make this testable."""
    now = time.time() if now is None else float(now)
    platform_reader = platform_reader or _is_platform_account
    active_reader = active_reader or (lambda uid: store.active_docs(uid))
    candle_reader = candle_reader or _read_candles
    quote_reader = quote_reader or _read_quote
    users = user_ids if user_ids is not None else list(user_store.all_active() or [])
    summary = {"users": 0, "rules": 0, "reads": 0, "recorded": 0, "resolved": 0}
    for raw_user_id in users:
        user_id = str(raw_user_id)
        try:
            if not platform_reader(user_id):
                continue
            rules = active_reader(user_id) or []
        except Exception as exc:  # noqa: BLE001
            print(f"[ForwardWatcher:{user_id}] account read failed: {type(exc).__name__}")
            continue
        if not rules:
            continue
        summary["users"] += 1
        # Rule activation is exclusive in the UI. If damaged storage contains
        # more than one active record, follow the same newest-first choice as
        # the API and do not duplicate signals for several rules.
        rule = rules[0]
        summary["rules"] += 1
        pending = forward.pending_symbols(user_id)
        for symbol in (rule.get("symbols") or [])[:MAX_SYMBOLS_PER_RULE]:
            timeframe = str(rule.get("timeframe") or "")
            if not isinstance(symbol, str) or not symbol.strip() or not timeframe:
                continue
            try:
                read = candle_reader(user_id, symbol=symbol, timeframe=timeframe,
                                     limit=200)
                summary["reads"] += 1
                if not isinstance(read, dict) or read.get("status") != broker_read.OK:
                    continue
                candles = read.get("candles") or []
                seconds = rule_strategy._sentinel.timeframe_seconds(timeframe, default=0)
                if not seconds:
                    continue
                closed = rule_strategy._closed_candles(candles, seconds, now)
                if not closed or closed[-1].get("time") is None:
                    continue
                bar_close_time = float(closed[-1]["time"]) + float(seconds)
                quote = None
                if _norm(symbol) in pending:
                    candidate = quote_reader(user_id, symbol=symbol)
                    if isinstance(candidate, dict) and candidate.get("status") == broker_read.OK:
                        quote = candidate
                result = forward.record_bar_close(
                    user_id, rule=rule, symbol=symbol, timeframe=timeframe,
                    candles=closed, bar_close_time=bar_close_time,
                    later_quote=quote)
                changed = result.get("events") or []
                summary["recorded"] += sum(1 for row in changed
                                           if row.get("barCloseTime") == bar_close_time)
                summary["resolved"] += sum(1 for row in changed
                                            if row.get("execution", {}).get("status") == "priced")
            except Exception as exc:  # noqa: BLE001
                # One unreadable symbol must not stop other users or symbols.
                print(f"[ForwardWatcher:{user_id}:{symbol}] read failed: {type(exc).__name__}")
    return summary


def _run() -> None:
    while not _stop.wait(POLL_INTERVAL_S):
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001
            print(f"[ForwardWatcher] cycle failed: {type(exc).__name__}")


def _is_platform_account(user_id: str) -> bool:
    from apex.platform import ctrader_link
    return bool(ctrader_link.is_platform_account(user_id))


def _read_candles(user_id: str, *, symbol: str, timeframe: str, limit: int):
    return broker_read.candles(user_id, symbol=symbol, timeframe=timeframe,
                               limit=limit)


def _read_quote(user_id: str, *, symbol: str):
    return broker_read.quote(user_id, symbol=symbol)


def _norm(symbol: Any) -> str:
    return str(symbol or "").replace("/", "").replace("_", "").upper()
