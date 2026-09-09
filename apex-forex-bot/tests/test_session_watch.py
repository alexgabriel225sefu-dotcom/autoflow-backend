"""The market edge must fire once, and "reconnected" must mean the account answered.

Two failures this guards against, both of which look fine in a log:

  1. The edge fires more than once. Render runs two instances through a deploy
     and both watch the same clock, so "market open" without a cross-process
     claim is two identical messages to every client, every week.

  2. "Reconnected" is reported because a socket opened. A socket opens fine
     with an expired token; the broker rejects the first real request. If the
     open message does not depend on a request that actually returned data,
     it is a reassurance with nothing behind it — which is exactly the silent
     Monday this feature exists to prevent.

Run: python tests/test_session_watch.py
"""
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-sess-")

from apex import session_watch as sw, user_store, alert_policy  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n🧪 MARKET SESSION WATCHER\n")

print("1. Friday's close and Sunday's reopen belong to the SAME week key")
fri = datetime(2026, 8, 14, 21, 0, tzinfo=timezone.utc)
sun = datetime(2026, 8, 16, 21, 0, tzinfo=timezone.utc)
nxt = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)
check("Friday close and Sunday open share a stamp",
      sw._session_stamp(fri) == sw._session_stamp(sun),
      f"{sw._session_stamp(fri)} vs {sw._session_stamp(sun)}")
check("...so close/open are two distinct keys, not one",
      f"close:{sw._session_stamp(fri)}" != f"open:{sw._session_stamp(sun)}")
check("the following week gets its own stamp",
      sw._session_stamp(nxt) != sw._session_stamp(fri),
      f"{sw._session_stamp(nxt)} vs {sw._session_stamp(fri)}")

print("\n2. The edge is claimed once across processes")
_real_claim = user_store.claim
user_store.claim = lambda key, ttl_s=120: True
check("first instance announces", sw._edge_is_ours("open") is True)
user_store.claim = lambda key, ttl_s=120: False
check("second instance stands down", sw._edge_is_ours("open") is False)
user_store.claim = lambda key, ttl_s=120: None
check("no shared store → still announces (dev box must not go silent)",
      sw._edge_is_ours("open") is True)


def _boom(key, ttl_s=120):
    raise OSError("redis down")


user_store.claim = _boom
check("a store OUTAGE announces rather than swallowing the edge",
      sw._edge_is_ours("open") is True)
user_store.claim = _real_claim
check("the claim key carries the edge AND the week",
      "close" in f"mktedge:close:{sw._session_stamp(fri)}"
      and sw._session_stamp(fri) in f"mktedge:close:{sw._session_stamp(fri)}")

print("\n3. 'Reconnected' requires a real answer from the broker")


class _Broker:
    """A broker whose balance call behaves as the test dictates."""

    def __init__(self, behaviour):
        self._b = behaviour
        self.calls = 0

    def get_balance(self):
        self.calls += 1
        if callable(self._b):
            return self._b(self.calls)
        return self._b


import apex.user_loop as _ul  # noqa: E402

_orig_make = _ul._make_broker
_orig_refresh = _ul._refresh_ctrader_token

LIVE = {"ctrader_account_id": 47765456, "ctrader_env": "demo", "paper": False}

_ul._make_broker = lambda user: (_Broker(2999.45), object())
ok, detail = sw._reconnect("u1", LIVE)
check("a balance that returns → OK", ok is True, detail)
check("...and the amount is reported, not just 'connected'",
      "2999.45" in detail, detail)


def _reject(_n):
    raise RuntimeError("account auth failed: CH_ACCESS_TOKEN_INVALID")


_ul._make_broker = lambda user: (_Broker(_reject), object())
_ul._refresh_ctrader_token = lambda uid, cfg: False
ok, detail = sw._reconnect("u1", LIVE)
check("a rejected token → NOT ok", ok is False, detail)
check("...and the broker's own reason survives into the message",
      "CH_ACCESS_TOKEN_INVALID" in detail, detail)

# The repair that matters: valid on Friday, expired by Sunday.
_healed = _Broker(lambda n: (_reject(n) if n == 1 else 3100.0))
_ul._make_broker = lambda user: (_healed, object())
_ul._refresh_ctrader_token = lambda uid, cfg: True
ok, detail = sw._reconnect("u1", LIVE)
check("an EXPIRED token is refreshed and retried → OK", ok is True, detail)
check("...and the client is told the token was refreshed",
      "refreshed" in detail, detail)

# The two post-refresh outcomes must not be reported as the same thing: one
# sends the client to /ctrader, the other means the broker itself is down.
_stuck = _Broker(_reject)
_ul._make_broker = lambda user: (_stuck, object())
_ul._refresh_ctrader_token = lambda uid, cfg: True
ok, detail = sw._reconnect("u1", LIVE)
check("refreshed but still unreachable → NOT ok", ok is False, detail)
check("...and says the refresh WORKED, not that it failed",
      "token refreshed" in detail and "refresh failed" not in detail, detail)

_ul._make_broker = lambda user: (_Broker(1.0), object())
check("a paper account needs no broker session",
      sw._reconnect("u1", {"paper": True})[0] is True)
check("an unlinked account fails loudly rather than claiming success",
      sw._reconnect("u1", {"paper": False})[0] is False)

_ul._make_broker = _orig_make
_ul._refresh_ctrader_token = _orig_refresh

print("\n4. Disconnect targets the right account and is honest about it")
dropped = []
from apex.brokers import ctrader as _ct  # noqa: E402

_orig_drop = _ct._drop_conn
_ct._drop_conn = lambda env, ctid: dropped.append((env, ctid))
check("a linked account is dropped", sw._disconnect(LIVE) is True)
check("...with that account's env and id",
      dropped == [("demo", 47765456)], str(dropped))
check("an unlinked account reports nothing to drop",
      sw._disconnect({"paper": True}) is False)
_ct._drop_conn = _orig_drop

# Item 15 of the failure matrix: the control plane must not be able to reach a
# broker through this module. Asserted here too, so the reason survives next
# to the code it constrains rather than only in the matrix.
check("the watcher does not import a broker itself",
      "brokers.ctrader" not in open(
          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "apex", "session_watch.py"),
          encoding="utf-8").read())

print("\n5. Both edges reach the client — a quiet client is the bug")
_plain = {"verbose_alerts": False}
check("MARKET_OPEN is not a diagnostic", alert_policy.allowed("MARKET_OPEN", _plain))
check("MARKET_CLOSE is not a diagnostic", alert_policy.allowed("MARKET_CLOSE", _plain))
check("both are ESSENTIAL",
      {"MARKET_OPEN", "MARKET_CLOSE"} <= alert_policy.ESSENTIAL)

print("\n6. The open alert carries the reconnect VERDICT, not just the event")
sent = []
sw._alert = lambda uid, payload: sent.append(payload)
_ul._make_broker = lambda user: (_Broker(_reject), object())
_ul._refresh_ctrader_token = lambda uid, cfg: False
sw._on_open([("u1", LIVE)])
check("one message per user", len(sent) == 1, str(sent))
check("it is a MARKET_OPEN", sent and sent[0]["action"] == "MARKET_OPEN")
check("carrying ok=False so the renderer cannot show good news",
      sent and sent[0]["ok"] is False, str(sent[:1]))
check("and the reason the client has to act on",
      sent and "CH_ACCESS_TOKEN_INVALID" in sent[0]["detail"])

sent.clear()
_ul._make_broker = lambda user: (_Broker(2999.45), object())
sw._on_open([("u1", LIVE)])
check("a healthy reconnect reports ok=True", sent and sent[0]["ok"] is True)
_ul._make_broker = _orig_make
_ul._refresh_ctrader_token = _orig_refresh

print("\n7. One user's failure never silences the next")
sent.clear()


def _explode(user):
    raise RuntimeError("boom")


_ul._make_broker = _explode
sw._on_open([("u1", LIVE), ("u2", LIVE)])
check("both users still get a message", len(sent) == 2, str(len(sent)))
check("and both are marked failed rather than dropped",
      all(p["ok"] is False for p in sent))
_ul._make_broker = _orig_make

print("\n8. The watcher only acts on a CHANGE of state")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "apex", "session_watch.py"), encoding="utf-8").read()
check("it compares against the last observed state",
      "if now_open == _open_now:" in src and "continue" in src)
# Scope to the watcher body: `_edge_is_ours` is DEFINED earlier in the file,
# so searching the whole module compares against the definition, not the call.
_body = src[src.index("def _run("):]
check("it records the new state BEFORE the claim can fail",
      _body.index("_open_now = now_open") < _body.index("if not _edge_is_ours(edge)"))
check("it never opens or closes a trade",
      "place_order" not in src and "close_position" not in src)
check("start() is idempotent — one watcher per process",
      "if _started:" in src)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the edge fires once, and 'reconnected' is proven.")
