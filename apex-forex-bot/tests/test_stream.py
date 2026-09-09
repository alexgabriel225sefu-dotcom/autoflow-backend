"""A live feed must not cost one broker connection per viewer.

cTrader's documented limit is the whole design constraint:

    "5 requests per second for any historical data requests. These limits are
     per connection, no matter how many users are authorized through it."

`apex/candle_cache.py` exists because of it — it lifted a ~187-concurrent-user
ceiling by collapsing per-user candle fetches. A stream that polls the broker
per connected client reinstates that ceiling on the screen everyone opens
first, and worse: the broker socket is pooled behind a lock, so a streaming
loop holding it starves /api/app/data. That regression has already happened
here once.

So the property measured below is not "the stream works". It is that N
connected clients cost the same upstream work as one.

The second half is honesty about the connection. A socket that is open but
silent looks identical to a working one, and a frozen feed that keeps drawing
its last frame is a lie about the market.

Run: python tests/test_stream.py
"""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


if not shutil.which("redis-server"):
    print("\n  SKIP  redis-server not on PATH — these checks CANNOT run here.")
    sys.exit(0)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
_redis = subprocess.Popen(
    ["redis-server", "--port", str(PORT), "--save", "", "--appendonly", "no"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
os.environ["REDIS_URL"] = f"redis://127.0.0.1:{PORT}/0"
os.environ["APP_ENV"] = "production"
os.environ["PRODUCT"] = "forex"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-signing-secret")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-str-"))
os.environ.setdefault("TOKEN_ENCRYPTION_KEY",
                      base64.urlsafe_b64encode(os.urandom(32)).decode())

from apex import stream, markets, user_loop  # noqa: E402

SRC = open(os.path.join(ROOT, "apex", "stream.py"), encoding="utf-8").read()
BODY = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("#"))
BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()
ROUTE = BOT[BOT.index('if self.path.startswith("/api/app/stream")'):]
ROUTE = ROUTE[:ROUTE.index('if self.path.startswith("/api/app/automation") and self.command == "GET"')]
CODE = "\n".join(l for l in ROUTE.splitlines() if not l.strip().startswith("#"))

print("\n1. The stream adds no broker calls of its own")
for forbidden in ("get_candles", "get_bid_ask", "get_price", "get_balance",
                  "get_open_position", "get_all_positions", "place_order"):
    check(f"{forbidden} is never called from the stream",
          f"{forbidden}(" not in BODY,
          "a per-client broker call reinstates the ~187-user ceiling")
check("account state is read from the loop's in-memory dash",
      "user_loop.get_dash(chat_id)" in BODY)
check("market prices come from the shared snapshot",
      "markets.snapshot(broker)" in BODY)

print("\n2. N clients cost one shared snapshot, not N")
calls = {"n": 0}
real_snapshot = markets.snapshot


def counting_snapshot(broker, **kw):
    calls["n"] += 1
    return {"rows": [], "asOf": int(time.time()), "cached": True}


class FakeBroker:
    pass


markets.snapshot = counting_snapshot
_orig_make = user_loop._make_broker
user_loop._make_broker = lambda user: (FakeBroker(), None)
stream.reset()
try:
    ids = []
    for i in range(25):
        cid, q = stream.register(f"chat{i}")
        ids.append(cid)
    check(f"25 clients registered ({stream.client_count()})",
          stream.client_count() == 25)
    calls["n"] = 0
    # Two producer ticks' worth of wall clock.
    time.sleep(stream._TICK_S * 2 + 0.6)
    check(f"the shared snapshot was fetched a handful of times, not 25 per tick "
          f"({calls['n']})",
          calls["n"] <= 4,
          "one shared read per tick, however many clients are connected")
finally:
    for cid in ids:
        stream.unregister(cid)
    markets.snapshot = real_snapshot
    user_loop._make_broker = _orig_make
    stream.reset()

print("\n3. The client set is bounded")
check(f"a cap exists ({stream._MAX_CLIENTS})", stream._MAX_CLIENTS > 0)
stream.reset()
kept = []
for i in range(stream._MAX_CLIENTS + 5):
    cid, q = stream.register("chatX")
    if cid is not None:
        kept.append(cid)
check(f"registration stops at the cap ({len(kept)})",
      len(kept) == stream._MAX_CLIENTS)
cid, q = stream.register("chatY")
check("an extra client is refused, not queued", cid is None and q is None)
check("the route tells a refused client to keep polling",
      "STREAM_BUSY" in CODE and "keep refreshing" in CODE)
stream.reset()
check("reset clears the registry", stream.client_count() == 0)

print("\n4. One slow client cannot stall the feed")
check(f"each queue is bounded ({stream._MAX_QUEUE})", stream._MAX_QUEUE > 0)
stream.reset()
cid, q = stream.register("slow")
for i in range(stream._MAX_QUEUE + 30):
    stream._publish({"type": "account.updated", "ts": time.time(), "i": i},
                    chat_id="slow")
check("the queue never grows past its cap", q.qsize() <= stream._MAX_QUEUE,
      str(q.qsize()))
drained = []
while not q.empty():
    drained.append(json.loads(q.get_nowait()))
check("the client is told it lost events",
      any(d.get("type") == "connection.status" and d.get("status") == "lagging"
          for d in drained),
      "silently dropping updates leaves a stale screen looking live")
stream.reset()

print("\n5. Account events never cross accounts")
# Asserted on CONTENT, not on queue length. The producer runs on its own
# cadence and publishes to every registered chat, so any check on an exact
# count races it — an earlier version of this section passed once by luck and
# failed on the next two runs.
stream.reset()
a_id, a_q = stream.register("aaa")
b_id, b_q = stream.register("bbb")


def _drain(q):
    out = []
    while not q.empty():
        try:
            out.append(json.loads(q.get_nowait()))
        except Exception:
            break
    return out


_drain(a_q)
_drain(b_q)
MARK = "A-only-secret-value"
stream._publish({"type": "account.updated", "ts": time.time(), "secret": MARK},
                chat_id="aaa")
a_seen, b_seen = _drain(a_q), _drain(b_q)
check("the addressed client receives it",
      any(e.get("secret") == MARK for e in a_seen), str(a_seen)[:120])
check("the other client never receives it",
      not any(e.get("secret") == MARK for e in b_seen),
      "account and position events are per-chat, not broadcast")
BEACON = "market-beacon"
stream._publish({"type": "market.tick", "ts": time.time(), "rows": [], "beacon": BEACON})
a_seen, b_seen = _drain(a_q), _drain(b_q)
check("market events do reach everyone",
      any(e.get("beacon") == BEACON for e in a_seen)
      and any(e.get("beacon") == BEACON for e in b_seen))
stream.reset()

print("\n6. The route is authenticated before the stream opens")
check("identity is checked before registering",
      CODE.index("_telegram_identity") < CODE.index("_v_st.register"))
check("a denied caller is refused", "_telegram_denied" in CODE)
check("the chat id comes from the signature", '_v_chat = str(_v_user["id"])' in CODE)
check("no identifier is read from the query string",
      "parse_qs" not in CODE and '"chat_id"' not in CODE)
check("the client is always unregistered", "finally:" in CODE
      and "_v_st.unregister(_v_cid)" in CODE,
      "a leaking registry is the memory leak the cap was meant to prevent")
check("a dropped connection is a normal exit, not an error",
      "BrokenPipeError" in CODE and "ConnectionResetError" in CODE)
RX = re.compile(r'^\s+([a-z][\w]*) = (?!=)', re.M)
check("every route local is prefixed",
      not {m.group(1) for m in RX.finditer(CODE)})

print("\n7. SSE headers a proxy will not swallow")
check("the content type is text/event-stream", "text/event-stream" in CODE)
check("the response is not cached", "no-store" in CODE)
check("proxy buffering is disabled", "X-Accel-Buffering" in CODE,
      "Render buffers the stream otherwise and nothing arrives until it closes")
check("a keepalive frame is sent while idle", "keepalive" in CODE)

print("\n8. The credential does not travel in a URL")
check("the client opens the stream with fetch, not EventSource's URL",
      "fetch('/api/app/stream'" in HTML)
check("...carrying initData in a header",
      "'Authorization':'Telegram '+initData" in HTML)
check("initData is never appended to the stream URL",
      not re.search(r"/api/app/stream\?[^'\"]*initData", HTML),
      "a URL reaches proxy logs; a credential must not")

print("\n9. Polling survives the stream")
check("the 1.5s tick still runs", "setInterval(tick, 1500)" in HTML)
check("the 6s refresh still runs", "setInterval(refresh, 6000)" in HTML)
check("the stream is described as an accelerator, not a replacement",
      "never a replacement" in HTML)
check("a lost feed retries", "setTimeout(openStream, 5000)" in HTML)
check("a browser with no EventSource still works",
      "if(!window.EventSource) return" in HTML)

print("\n10. A silent connection is not shown as live")
check("staleness is detected independently of the socket",
      "Date.now()-streamAt > 30000" in HTML,
      "an open but silent socket looks identical to a working one")
check("...and reported as delayed", "setConn('delayed'" in HTML)
check("the connection state is rendered as a word, not only a colour",
      "DELAYED" in HTML and "content:' \\u00b7 LIVE'" in HTML
      or "' · LIVE'" in HTML)
check("a stale market snapshot says so",
      "last one the broker answered" in HTML)

stream.reset()
print("\n" + "=" * 50)
_redis.terminate()
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL STREAM CHECKS PASSED - many viewers, one upstream, and no silent freeze.")
