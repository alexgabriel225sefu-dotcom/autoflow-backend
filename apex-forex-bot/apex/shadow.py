"""Track the trades the bot refused, and report whether refusing was right.

A filter that blocks entries is invisible. You see the trades taken, never the
ones avoided, so a filter that is saving money looks exactly like one that is
quietly removing the profitable setups. "The AI blocked 14 trades today" means
nothing without knowing what those 14 would have done.

So every blocked entry is recorded as a phantom position, with the stop and
target it would have been given, and followed on the same prices as a real one.
When it resolves the verdict is a fact rather than an opinion: refusing saved
21 pips, or it cost 30.

Phantoms are pure bookkeeping — no order is ever placed. They persist on the
user record so a redeploy does not lose the answer half way through.
"""
import time
from datetime import datetime

from apex import forex, user_store

_KEY = "shadow_trades"
_MAX_TRACKED = 12          # the newest few; this is a signal, not an archive
_MAX_AGE_H = 12            # a setup unresolved after half a day is stale
_MAX_HISTORY = 60          # resolved verdicts kept for the scoreboard


def _now():
    return int(time.time())


def _nrm(s):
    return (s or "").upper().replace("_", "").replace("/", "").replace("-", "")


def _load(user_id):
    rec = user_store.load(user_id) or {}
    d = rec.get(_KEY) or {}
    return {"open": d.get("open") or [], "done": d.get("done") or []}


def _save(user_id, state):
    state["open"] = state["open"][-_MAX_TRACKED:]
    state["done"] = state["done"][-_MAX_HISTORY:]
    try:
        user_store.update(user_id, {_KEY: state})
    except Exception as e:
        print(f"[Shadow:{user_id}] persist failed: {e}")


def open_shadow(user_id, symbol, side, price, sl, tp, blocked_by,
                reasoning="", confidence=None):
    """Record a refused entry. Returns the phantom, or None if a duplicate.

    One phantom per symbol at a time. The scanner re-evaluates the same setup
    every tick and a filter that blocked it will block it again next tick;
    unchecked, that is one phantom per tick for a single idea.
    """
    if not (price and sl and tp):
        return None
    if side not in ("BUY", "SELL"):
        return None
    state = _load(user_id)
    if any(_nrm(s.get("symbol")) == _nrm(symbol) for s in state["open"]):
        return None
    ph = {
        "id": f"{_nrm(symbol)}-{_now()}",
        "symbol": symbol,
        "side": side,
        "entry": round(float(price), 6),
        "sl": round(float(sl), 6),
        "tp": round(float(tp), 6),
        "opened": _now(),
        "openedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "blockedBy": blocked_by,
        "reasoning": (reasoning or "")[:300],
        "confidence": confidence,
        "peakR": 0.0,       # best it ever got, in R
        "troughR": 0.0,     # worst it ever got, in R
        "milestone": 0,     # which ±0.5R step has already been reported
    }
    state["open"].append(ph)
    _save(user_id, state)
    return ph


def _r_of(ph, price):
    """Where price sits, in R, relative to the phantom's entry and stop."""
    risk = abs(ph["entry"] - ph["sl"])
    if risk <= 0:
        return 0.0
    move = (price - ph["entry"]) if ph["side"] == "BUY" else (ph["entry"] - price)
    return move / risk


def _resolve(ph, outcome, price):
    move_pips = forex.to_pips(
        (price - ph["entry"]) if ph["side"] == "BUY" else (ph["entry"] - price),
        ph["symbol"], price)
    return {
        **ph,
        "outcome": outcome,
        "exit": round(float(price), 6),
        "closedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "r": round(_r_of(ph, price), 2),
        "pips": round(move_pips, 1),
    }


def update(user_id, symbol, high, low, price):
    """Advance every phantom on `symbol` against this bar. Returns events.

    Each event is {kind, phantom, ...}: `milestone` on crossing a fresh half-R
    either way, `resolved` on target or stop, `expired` when it has gone
    nowhere for too long. This module never sends anything itself — the caller
    decides what to do with the events.
    """
    state = _load(user_id)
    if not state["open"]:
        return []
    events, still_open, touched = [], [], False

    for ph in state["open"]:
        if _nrm(ph.get("symbol")) != _nrm(symbol):
            still_open.append(ph)
            continue
        touched = True
        hi = float(high if high is not None else price)
        lo = float(low if low is not None else price)

        # Stop before target when one bar spans both. We cannot know the order
        # within a bar, and assuming the good fill is how a phantom flatters
        # itself — the pessimistic read is the honest one.
        hit_sl = lo <= ph["sl"] if ph["side"] == "BUY" else hi >= ph["sl"]
        hit_tp = hi >= ph["tp"] if ph["side"] == "BUY" else lo <= ph["tp"]

        ph["peakR"] = round(max(ph.get("peakR", 0.0),
                                _r_of(ph, hi if ph["side"] == "BUY" else lo)), 2)
        ph["troughR"] = round(min(ph.get("troughR", 0.0),
                                  _r_of(ph, lo if ph["side"] == "BUY" else hi)), 2)

        if hit_sl:
            events.append({"kind": "resolved",
                           "phantom": _resolve(ph, "STOP_LOSS", ph["sl"])})
            continue
        if hit_tp:
            events.append({"kind": "resolved",
                           "phantom": _resolve(ph, "TAKE_PROFIT", ph["tp"])})
            continue
        if _now() - ph["opened"] > _MAX_AGE_H * 3600:
            events.append({"kind": "expired",
                           "phantom": _resolve(ph, "EXPIRED", price)})
            continue

        # Report each fresh half-R step once, so a price drifting around one
        # level does not send the same update every tick.
        step = int(_r_of(ph, price) / 0.5)
        if step and step != ph.get("milestone", 0):
            ph["milestone"] = step
            events.append({"kind": "milestone", "phantom": dict(ph),
                           "r": round(_r_of(ph, price), 2)})
        still_open.append(ph)

    if touched:
        state["open"] = still_open
        for e in events:
            if e["kind"] in ("resolved", "expired"):
                state["done"].append(e["phantom"])
        _save(user_id, state)
    return events


def scoreboard(user_id):
    """Over the recorded history, was blocking these trades the right call?"""
    done = _load(user_id)["done"]
    if not done:
        return {"n": 0}
    wins = [d for d in done if d.get("outcome") == "TAKE_PROFIT"]
    losses = [d for d in done if d.get("outcome") == "STOP_LOSS"]
    total_r = round(sum(d.get("r", 0.0) for d in done), 2)
    return {
        "n": len(done),
        "wouldHaveWon": len(wins),
        "wouldHaveLost": len(losses),
        "expired": len(done) - len(wins) - len(losses),
        # Positive means the refused trades were net profitable — the filter is
        # costing money. Negative means it is doing its job.
        "filterCostR": total_r,
        "verdict": ("the filter is costing money — refused setups were net winners"
                    if total_r > 0.5 else
                    "the filter is earning its keep — refused setups were net losers"
                    if total_r < -0.5 else
                    "too close to call so far"),
    }


def clear(user_id):
    _save(user_id, {"open": [], "done": []})
