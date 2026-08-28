"""Live updates for the Mini App, without adding a single broker call.

## Why Server-Sent Events rather than WebSockets

The feed is one-directional: the client asks nothing, it only receives. SSE is
plain HTTP over the ThreadingHTTPServer that already runs here — no protocol
upgrade to hand-roll, no dependency, no second server, and the browser's own
EventSource reconnects by itself. A WebSocket would buy bidirectionality this
feature does not use, and cost a framing implementation on a socket that also
serves the dashboard.

## The constraint that shapes everything else

cTrader's documented limit:

    "5 requests per second for any historical data requests. These limits are
     per connection, no matter how many users are authorized through it."

Non-historical: 50/second, same per-connection rule. `apex/candle_cache.py`
exists because of it — it collapsed per-user candle fetches and lifted a
~187-concurrent-user ceiling.

A stream that polled the broker per connected client would reintroduce that
ceiling immediately, and worse: the broker socket is pooled behind a lock, so a
streaming loop holding it starves `/api/app/data`. That regression has already
happened once in this repository.

So this module **makes no broker calls at all.** It publishes what already
exists in memory:

  * account and position state from `user_loop.get_dash(chat)` — an in-memory
    dict the trading loop maintains;
  * market prices from `markets.snapshot()` — one shared, TTL-cached read that
    every client is already served from.

N connected clients therefore cost N dictionary reads and ONE shared snapshot,
not N broker round-trips. That is the property the test measures.

## What a client receives

Market events are shared. Account, position and risk events are not: each
client is fed only from the chat its Telegram signature proved. There is no
subscription message and no client-supplied identifier anywhere in the
protocol, so there is nothing to tamper with.

Every event carries `ts`. The client shows a degraded state when the last one
is old, because a frozen stream that keeps drawing its last frame is a lie
about the market.
"""

import json
import queue
import threading
import time

# One producer, however many clients. Started lazily on the first connection
# and left running: a stream nobody is watching costs one sleeping thread.
_TICK_S = 2.0

# Bounded, because a set of hung connections is a memory leak and a
# denial-of-service surface. Refused politely rather than dropped silently.
_MAX_CLIENTS = 200

# Bounded per client too. A phone that stops reading must not grow a queue
# until the process dies; it loses the middle of the stream and is told so.
_MAX_QUEUE = 64

# Event types. Named for what happened.
MARKET_TICK = "market.tick"
ACCOUNT_UPDATE = "account.updated"
POSITION_UPDATE = "position.updated"
RISK_UPDATE = "risk.updated"
CONNECTION_STATUS = "connection.status"

_lock = threading.Lock()
_clients = {}          # id -> {"chat": str, "q": Queue, "since": float}
_next_id = [0]
_producer = None
_stop = threading.Event()

# Per-chat memory of what was last published, so only CHANGES go out. A stream
# that re-sends an unchanged balance twice a second is a poll wearing a
# different hat.
_last = {}


def _now():
    return time.time()


def register(chat_id):
    """Add a client. Returns (client_id, Queue) or (None, None) when full."""
    with _lock:
        if len(_clients) >= _MAX_CLIENTS:
            return None, None
        _next_id[0] += 1
        cid = _next_id[0]
        q = queue.Queue(maxsize=_MAX_QUEUE)
        _clients[cid] = {"chat": str(chat_id), "q": q, "since": _now()}
    _ensure_producer()
    return cid, q


def unregister(client_id):
    with _lock:
        _clients.pop(client_id, None)


def client_count():
    with _lock:
        return len(_clients)


def _publish(event, *, chat_id=None):
    """Queue an event for one chat, or for everyone when chat_id is None.

    A client whose queue is full loses this event and is told, rather than
    blocking the producer. One slow phone must not stall the feed for
    everybody else.
    """
    payload = json.dumps(event, default=str)
    with _lock:
        targets = [(cid, c) for cid, c in _clients.items()
                   if chat_id is None or c["chat"] == str(chat_id)]
    for cid, c in targets:
        try:
            c["q"].put_nowait(payload)
        except queue.Full:
            try:
                c["q"].get_nowait()          # drop the oldest
                c["q"].put_nowait(json.dumps({
                    "type": CONNECTION_STATUS, "ts": _now(),
                    "status": "lagging",
                    "detail": "Some updates were skipped; the screen will "
                              "refresh from the server."}))
            except Exception:
                pass


def _account_event(chat_id):
    """Account and position state, read from the loop's in-memory dash.

    No broker call. `get_dash` returns the dict the trading loop maintains, so
    this costs a dictionary lookup however many clients are watching.
    """
    from apex import user_loop
    dash = user_loop.get_dash(chat_id) or {}
    if not dash:
        return None
    positions = [
        {"symbol": p.get("symbol"), "side": p.get("side"),
         "entryPrice": p.get("entryPrice"), "stopLoss": p.get("stopLoss"),
         "takeProfit": p.get("takeProfit"), "pnlUsd": p.get("pnlUsd"),
         "pnlPips": p.get("pnlPips")}
        for p in (dash.get("positions") or []) if p.get("symbol")
    ]
    return {
        "type": ACCOUNT_UPDATE,
        "ts": _now(),
        "balance": dash.get("balance"),
        "equity": dash.get("equityLive"),
        "floatingPnl": dash.get("floatingPnl"),
        "symbol": dash.get("symbol"),
        "price": dash.get("currentPrice"),
        "brokerHealth": dash.get("brokerHealth"),
        # The loop's own reading of when it last heard from the broker. The
        # client needs it to tell "quiet market" from "we lost the feed".
        "lastTickTs": dash.get("lastTickTs"),
        "positions": positions,
        "openCount": dash.get("openCount"),
    }


def _risk_event(chat_id):
    from apex import ui_state, user_loop
    state, reasons = ui_state.risk_state(chat_id)
    guard = (user_loop.get_dash(chat_id) or {}).get("riskGuard") or {}
    return {"type": RISK_UPDATE, "ts": _now(), "engine": state,
            "halted": bool(guard.get("halted")),
            "reasons": reasons or list(guard.get("reasons") or [])}


def _market_event():
    """One shared snapshot for every client.

    `markets.snapshot` is TTL-cached and shared, and it is the same call the
    Markets screen already makes. Broker load does not grow with the number of
    connected clients — which is the whole point.
    """
    from apex import markets, user_loop, user_store
    with _lock:
        chats = {c["chat"] for c in _clients.values()}
    if not chats:
        return None
    # Any connected client's broker will do: the snapshot is shared, and the
    # instruments are the platform's, not the account's.
    for chat in list(chats)[:3]:
        try:
            user = user_store.load(chat) or {}
            broker, _cfg = user_loop._make_broker(user)
            snap = markets.snapshot(broker)
            return {"type": MARKET_TICK, "ts": _now(),
                    "asOf": snap.get("asOf"), "stale": bool(snap.get("stale")),
                    "rows": snap.get("rows") or []}
        except Exception:
            continue
    return None


def _loop():
    while not _stop.is_set():
        try:
            with _lock:
                chats = {c["chat"] for c in _clients.values()}
            for chat in chats:
                for build in (_account_event, _risk_event):
                    try:
                        ev = build(chat)
                    except Exception as e:
                        print(f"[Stream] {build.__name__} failed for {chat}: {e}")
                        continue
                    if not ev:
                        continue
                    # Only changes go out. `ts` is excluded from the comparison
                    # or every event would look new.
                    key = (chat, ev["type"])
                    fingerprint = json.dumps(
                        {k: v for k, v in ev.items() if k != "ts"},
                        sort_keys=True, default=str)
                    if _last.get(key) == fingerprint:
                        continue
                    _last[key] = fingerprint
                    _publish(ev, chat_id=chat)
            if chats:
                try:
                    mk = _market_event()
                    if mk:
                        fp = json.dumps({k: v for k, v in mk.items() if k != "ts"},
                                        sort_keys=True, default=str)
                        if _last.get(("*", MARKET_TICK)) != fp:
                            _last[("*", MARKET_TICK)] = fp
                            _publish(mk)
                except Exception as e:
                    print(f"[Stream] market event failed: {e}")
        except Exception as e:
            print(f"[Stream] producer tick failed: {e}")
        _stop.wait(_TICK_S)


def _ensure_producer():
    global _producer
    with _lock:
        if _producer is not None and _producer.is_alive():
            return
        _stop.clear()
        _producer = threading.Thread(target=_loop, name="apex-stream",
                                     daemon=True)
        _producer.start()


def stop():
    """For tests and shutdown. Daemon thread, so this is politeness."""
    _stop.set()
    with _lock:
        _clients.clear()
        _last.clear()


def reset():
    stop()
    _stop.clear()


def stats():
    with _lock:
        return {"clients": len(_clients), "tick": _TICK_S,
                "maxClients": _MAX_CLIENTS, "maxQueue": _MAX_QUEUE,
                "producerAlive": bool(_producer and _producer.is_alive())}
