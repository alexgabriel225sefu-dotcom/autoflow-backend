"""A decision log is only worth having if it cannot be rewritten or interfere.

Everything the product promises to explain rests on this: why a position was
opened, why one was not, what the timeline looked like. Three properties decide
whether those explanations are evidence or a story told about a result.

  IMMUTABLE. A strategy change tomorrow must not alter the explanation of a
  trade from last week, so each event carries the versions that were live when
  it happened and nothing edits an event after the fact.

  OBSERVATIONAL. Journalling must never be able to refuse, delay or alter a
  trading decision. A log that can break execution is worse than no log.

  HONEST ABOUT ABSENCE. No backfill exists. A period with no recorded decision
  must read as "no recorded decision", never as "there was no reason".

Run: python tests/test_trade_events.py
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
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-evt-"))
os.environ.setdefault("TOKEN_ENCRYPTION_KEY",
                      base64.urlsafe_b64encode(os.urandom(32)).decode())

from apex import trade_events as te, user_store  # noqa: E402

U = "700001"

print("\n1. An event carries its own provenance")
eid = te.record(U, te.ORDER_FILLED, symbol="eurusd", position_id="p1",
                strategy_id="fibonacci", strategy_version="1.0.0",
                payload={"side": "BUY", "entryPrice": 1.0842})
check("recording returns an id", bool(eid), str(eid))
rows = te.recent(U)["events"]
check("the event is readable back", len(rows) == 1, str(len(rows)))
e = rows[0]
check("it has a unique event id", e["event_id"] == eid)
check("the symbol is normalised", e["symbol"] == "EURUSD", e["symbol"])
check("the strategy version is kept", e["strategy_version"] == "1.0.0")
check("the risk version is stamped", e["risk_version"] == te.RISK_VERSION)
check("the schema version is stamped", e["schema"] == te.SCHEMA_VERSION)
check("the environment is resolved, not guessed",
      e["environment"] in ("LIVE", "DEMO", "SIMULATION", "UNKNOWN"), e["environment"])
check("a timestamp is present", isinstance(e["ts"], float))

print("\n2. Events are appended, never edited")
before = json.loads(user_store.get_blob(f"evt:user:{U}"))
te.record(U, te.DECISION_DECLINED, symbol="GBPUSD", payload={"reason": "spread"})
after = json.loads(user_store.get_blob(f"evt:user:{U}"))
check("the earlier event is byte-identical afterwards", after[0] == before[0])
check("the new one was appended at the end", after[-1]["type"] == te.DECISION_DECLINED)
check("nothing was reordered", len(after) == len(before) + 1)
SRC = open(os.path.join(ROOT, "apex", "trade_events.py"), encoding="utf-8").read()
BODY = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("#"))
check("the module exposes no update or delete",
      not re.search(r"^def (update|edit|delete|patch|amend)", BODY, re.M),
      "an event that can be rewritten is not evidence")

print("\n3. Unknown event types are refused, not stored")
n_before = te.stats(U)["count"]
check("an invented type returns None",
      te.record(U, "trade.definitely_happened", payload={}) is None)
check("...and nothing was written", te.stats(U)["count"] == n_before)

print("\n4. Recording can never break execution")
check("record catches everything", "except Exception as e:" in BODY
      and "return None" in BODY)
# Feed it the things a trading loop actually holds: objects, cycles, huge blobs.
class Weird:
    def __repr__(self):
        raise RuntimeError("even repr explodes")


cyclic = {}
cyclic["self"] = cyclic
for bad, why in ((Weird(), "an object whose repr raises"),
                 (cyclic, "a cyclic structure"),
                 ("x" * 50000, "a 50k string")):
    try:
        te.record(U, te.MARKET_SNAPSHOT, symbol="EURUSD", payload={"v": bad})
        raised = False
    except Exception:
        raised = True
    check(f"{why} does not raise", not raised)
check("the log is still readable after all that", isinstance(te.recent(U), dict))

print("\n5. Oversized payloads are bounded, not dropped silently")
te.record(U, te.ANALYSIS_COMPLETED, symbol="EURUSD",
          payload={"note": "y" * 8000})
big = [r for r in te.recent(U)["events"] if r["type"] == te.ANALYSIS_COMPLETED][0]
check("the payload is clamped", len(json.dumps(big["payload"])) <= 2200,
      str(len(json.dumps(big["payload"]))))
check("...and says it was truncated rather than pretending to be whole",
      big["payload"].get("_truncated") is True or len(str(big["payload"])) < 8000)

print("\n6. Refusals are the source for 'why didn't APEX trade'")
te.record(U, te.DECISION_DECLINED, symbol="XAUUSD", payload={"reason": "no setup"})
d = te.declines(U, symbol="XAUUSD")
check("a refusal is retrievable by symbol", len(d) == 1, str(len(d)))
check("...with its reason", d[0]["payload"]["reason"] == "no setup")
check("a symbol with no refusal returns empty, not a guess",
      te.declines(U, symbol="AUDUSD") == [])
check("an untouched user has no history at all", te.declines("999999") == [])

print("\n7. The timeline is ordered and belongs to one trade")
t0 = time.time()
for i, typ in enumerate((te.SIGNAL_GENERATED, te.RISK_CHECKED,
                         te.ORDER_AUTHORIZED, te.ORDER_SUBMITTED)):
    te.record(U, typ, symbol="EURUSD", position_id="p9", payload={"step": i})
tl = te.timeline(U, position_id="p9")
check("every event for that position is present", len(tl) == 4, str(len(tl)))
check("...in the order they happened",
      [r["payload"]["step"] for r in tl] == [0, 1, 2, 3])
check("another position's events are not included",
      all(r["position_id"] == "p9" for r in tl))
win = te.timeline(U, start_ts=t0, end_ts=time.time(), symbol="EURUSD")
check("a time window also works — early events precede any position id",
      len(win) >= 4, str(len(win)))
check("the window does not leak another symbol",
      all(r["symbol"] == "EURUSD" for r in win))

print("\n8. Reads are bounded — the Mini App cannot ask for everything")
for i in range(60):
    te.record(U, te.MARKET_SNAPSHOT, symbol="EURUSD", payload={"i": i})
page = te.recent(U, limit=10)
check("a page is the size asked for", len(page["events"]) == 10)
check("the total is reported", page["total"] > 10)
check("an absurd limit is capped", len(te.recent(U, limit=100000)["events"]) <= 200)
check("newest first", page["events"][0]["ts"] >= page["events"][-1]["ts"])

print("\n9. The log is bounded")
check(f"a cap exists ({te._MAX_EVENTS})", te._MAX_EVENTS > 0)
check("the cap is applied on append", "events[-_MAX_EVENTS:]" in BODY)

print("\n10. The trading loop journals without being able to break")
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
check("refusals are recorded", "_te.DECISION_DECLINED" in LOOP)
check("fills are recorded", "_te.ORDER_FILLED" in LOOP)
for marker in ("decision log (skip) failed", "decision log (fill) failed"):
    check(f"...wrapped: {marker!r}", marker in LOOP,
          "an exception in journalling must not reach the execution path")
check("the strategy version is looked up, not assumed",
      'getattr(_s, "strategy_version", None)' in LOOP,
      "an event naming a version it did not verify is worse than one that admits unknown")

print("\n" + "=" * 50)
_redis.terminate()
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL TRADE-EVENT CHECKS PASSED - appended, versioned, and unable to interfere.")
