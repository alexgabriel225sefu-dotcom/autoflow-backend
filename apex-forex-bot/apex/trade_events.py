"""The append-only record of what the platform decided, and when.

Everything the product promises to explain — why a position was opened, why one
was not, what the timeline of a trade looked like — has to come from somewhere
that cannot be rewritten afterwards. Without that, an explanation is a story
told about a result, and the result is the only evidence for it.

What existed before this module:

  * closed trades carried a flat snapshot (confidence, regime, atr, strategyId,
    strategyVersion) — real recorded data, but one row per trade with no
    sequence, and nothing about the decisions that did NOT become trades;
  * refusals lived in dash["skips"], in memory, last thirty, `{time, reason}` —
    no symbol, no strategy version, no persistence. A restart erased the
    answer to "why didn't it trade this morning".

So this is the missing half. It is deliberately NOT a replacement for the trade
journal: that stays where it is and stays authoritative for money. This records
the DECISION history beside it.

Three properties matter more than any feature here:

  IMMUTABLE. Events are appended, never edited. A strategy change tomorrow must
  not alter the explanation of a trade from last week, so each event carries the
  strategy and risk versions that were live when it happened.

  OBSERVATIONAL. Nothing in this module can refuse, delay or alter a trading
  decision. Every call site wraps it and swallows failures. A journal that can
  break execution is worse than no journal.

  HONEST ABOUT ABSENCE. There is no backfill. Events begin when this ships, and
  a period with no recorded decision reads as "no recorded decision", never as
  "no decision was made".
"""

import json
import os
import time
import uuid

from apex import user_store

# Bumped when the meaning of a recorded field changes, so a reader can tell an
# old event from a new one rather than guessing from its shape.
SCHEMA_VERSION = "1.0.0"

# The version of the risk logic that evaluated an event. Trades keep the value
# that was current when they were decided; changing this constant must never
# rewrite what an old event says.
RISK_VERSION = os.getenv("RISK_VERSION") or "1.0.0"

# Event types. Named for what happened, not for what the UI does with it.
MARKET_SNAPSHOT = "market.snapshot"
SIGNAL_GENERATED = "signal.generated"
ANALYSIS_COMPLETED = "analysis.completed"
RISK_CHECKED = "risk.checked"
DECISION_DECLINED = "decision.declined"      # the "why didn't APEX trade" record
ORDER_AUTHORIZED = "order.authorized"
ORDER_SUBMITTED = "order.submitted"
ORDER_FILLED = "order.filled"
ORDER_REJECTED = "order.rejected"
POSITION_UPDATED = "position.updated"
STOP_UPDATED = "stop.updated"
TAKE_PROFIT_UPDATED = "take_profit.updated"
POSITION_CLOSED = "position.closed"

_TYPES = {
    MARKET_SNAPSHOT, SIGNAL_GENERATED, ANALYSIS_COMPLETED, RISK_CHECKED,
    DECISION_DECLINED, ORDER_AUTHORIZED, ORDER_SUBMITTED, ORDER_FILLED,
    ORDER_REJECTED, POSITION_UPDATED, STOP_UPDATED, TAKE_PROFIT_UPDATED,
    POSITION_CLOSED,
}

# Bounded, because this is a per-user list in Redis and an unbounded one is a
# memory leak with a slow fuse. Two thousand events is roughly a fortnight of
# an active account; the trade journal keeps the money record for longer.
_MAX_EVENTS = 2000

# A payload is context for a human reading a timeline, not a place to park
# whatever a call site happened to have. Clamped so one oversized event cannot
# push out the history around it.
_MAX_PAYLOAD_CHARS = 2000


def _key(user_id):
    return f"evt:user:{user_id}"


def _environment(user_id, user=None):
    """LIVE / DEMO / UNKNOWN, resolved the same way every other surface does.

    Never guessed here: an event that mislabels its environment is worse than
    one that admits it does not know, because it will be read later as proof.
    """
    try:
        from apex import account_mode
        u = user if user is not None else user_store.load(str(user_id))
        mode, _src = account_mode.resolve(u)
        return str(mode)
    except Exception:
        return "UNKNOWN"


def _clean(payload):
    """Bound the payload and drop anything that will not survive JSON.

    Values that cannot be serialised are replaced by their repr rather than
    dropped silently — a timeline with a gap in it is a timeline that lies by
    omission.
    """
    out = {}
    for k, v in (payload or {}).items():
        key = str(k)[:48]
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v[:400] if isinstance(v, str) else v
        elif isinstance(v, (list, tuple)):
            out[key] = [str(x)[:120] for x in list(v)[:20]]
        elif isinstance(v, dict):
            out[key] = {str(a)[:40]: str(b)[:120] for a, b in list(v.items())[:20]}
        else:
            out[key] = repr(v)[:200]
    blob = json.dumps(out, default=str)
    if len(blob) > _MAX_PAYLOAD_CHARS:
        return {"_truncated": True, "_size": len(blob),
                "summary": blob[:_MAX_PAYLOAD_CHARS - 60]}
    return out


def record(user_id, event_type, *, symbol=None, payload=None, trade_id=None,
           position_id=None, strategy_id=None, strategy_version=None, user=None):
    """Append one decision event. Returns the event id, or None if nothing was
    written.

    NEVER raises. This is called from the trading loop, and an exception here
    would turn a journalling problem into an execution problem. Every failure
    is printed and swallowed — the caller has money to move and this does not.
    """
    try:
        if event_type not in _TYPES:
            print(f"[Events] refused unknown event type {event_type!r}")
            return None
        uid = str(user_id)
        ev = {
            "event_id": uuid.uuid4().hex,
            "schema": SCHEMA_VERSION,
            "ts": time.time(),
            "type": event_type,
            "user_id": uid,
            "symbol": (str(symbol).upper() if symbol else None),
            "environment": _environment(uid, user),
            "strategy_id": (str(strategy_id)[:40] if strategy_id else None),
            "strategy_version": (str(strategy_version)[:20] if strategy_version else None),
            "risk_version": RISK_VERSION,
            "trade_id": (str(trade_id)[:64] if trade_id else None),
            "position_id": (str(position_id)[:64] if position_id else None),
            "payload": _clean(payload),
        }
        key = _key(uid)
        raw = user_store.get_blob(key)
        events = []
        if raw:
            try:
                events = json.loads(raw) or []
            except Exception as e:
                # A corrupt log is not a reason to lose the next event, but it
                # is a reason to say so loudly rather than start a fresh one
                # that looks like a complete history.
                print(f"[Events] log for {uid} unreadable ({e}) — starting a new one")
                events = []
        events.append(ev)
        if len(events) > _MAX_EVENTS:
            events = events[-_MAX_EVENTS:]
        user_store.set_blob(key, json.dumps(events))
        return ev["event_id"]
    except Exception as e:
        print(f"[Events] record failed for {user_id}/{event_type}: {e}")
        return None


def _all(user_id):
    try:
        raw = user_store.get_blob(_key(str(user_id)))
        return json.loads(raw) if raw else []
    except Exception as e:
        print(f"[Events] read failed for {user_id}: {e}")
        return []


def recent(user_id, *, limit=50, offset=0, event_type=None, symbol=None,
           since_ts=None):
    """Newest first. Bounded — the Mini App must never ask for everything."""
    rows = _all(user_id)
    if event_type:
        rows = [r for r in rows if r.get("type") == event_type]
    if symbol:
        want = str(symbol).upper()
        rows = [r for r in rows if (r.get("symbol") or "") == want]
    if since_ts:
        rows = [r for r in rows if (r.get("ts") or 0) >= float(since_ts)]
    rows = list(reversed(rows))
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    return {"events": rows[off:off + lim], "total": len(rows),
            "offset": off, "limit": lim}


def timeline(user_id, *, trade_id=None, position_id=None,
             start_ts=None, end_ts=None, symbol=None):
    """The events belonging to one trade, oldest first — the replay timeline.

    Matched by trade or position id when the caller has one. A time window is
    accepted as well, because the earliest events of a trade happen BEFORE it
    has an id: a signal and a risk check precede the order that creates one.
    """
    rows = _all(user_id)
    out = []
    for r in rows:
        if trade_id and r.get("trade_id") == str(trade_id):
            out.append(r); continue
        if position_id and r.get("position_id") == str(position_id):
            out.append(r); continue
        if start_ts is not None and end_ts is not None:
            ts = r.get("ts") or 0
            if float(start_ts) <= ts <= float(end_ts):
                if symbol and (r.get("symbol") or "") != str(symbol).upper():
                    continue
                out.append(r)
    seen, uniq = set(), []
    for r in out:
        if r["event_id"] in seen:
            continue
        seen.add(r["event_id"])
        uniq.append(r)
    uniq.sort(key=lambda r: r.get("ts") or 0)
    return uniq


def declines(user_id, *, symbol=None, limit=30):
    """Recorded refusals — the source for "why didn't APEX trade".

    Returns [] when nothing was recorded. The caller must render that as "no
    recorded decision for this period", never as "there was no reason".
    """
    return recent(user_id, limit=limit, event_type=DECISION_DECLINED,
                  symbol=symbol)["events"]


def stats(user_id):
    rows = _all(user_id)
    by = {}
    for r in rows:
        by[r.get("type")] = by.get(r.get("type"), 0) + 1
    return {"count": len(rows), "byType": by,
            "oldest": (rows[0].get("ts") if rows else None),
            "newest": (rows[-1].get("ts") if rows else None),
            "schema": SCHEMA_VERSION, "riskVersion": RISK_VERSION}
