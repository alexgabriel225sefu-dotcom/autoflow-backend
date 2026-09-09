"""Polling faster must not make the terminal slower.

Every cTrader read in this process rides ONE pooled socket per account, behind a
lock held across the round-trip. Concurrent reads therefore queue rather than
parallelise. A 1-second tick asking for bid/ask, the position list, a price per
position and the balance was seven serialised round-trips per second on that one
socket — and /api/app/data, which needs the same socket for candles, queued
behind all of it and timed out.

The symptom was the opposite of the cause: the Mini App said "Reconnecting…
market data unavailable" while the bot was perfectly healthy and the log showed
`[cTrader] balance` firing every 2-3 seconds. The terminal was starving itself.

Run: python tests/test_miniapp_cache.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-mcache-")

from apex import miniapp_cache as mc  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n🧪 MINI APP CACHE — a faster poll must cost nothing\n")

print("1. A miss is distinguishable from a real empty answer")
mc.invalidate("u1")
check("no entry reads as None, meaning 'ask the broker'",
      mc.get_positions("u1") is None)
mc.put_positions("u1", [])
check("an empty LIST is a real answer — the account is flat",
      mc.get_positions("u1") == [],
      "returning None here would re-ask the broker forever while flat")

print("\n2. Within the TTL the broker is not asked again")
mc.invalidate("u2")
mc.put_tick("u2", {"price": 1.36})
check("a tick built a moment ago is reused", mc.get_tick("u2") == {"price": 1.36})
mc.put_balance("u2", 3214.0)
check("so is the balance", mc.get_balance("u2") == 3214.0)
mc.put_positions("u2", [{"symbol": "GBPUSD"}])
check("so is the position list", len(mc.get_positions("u2")) == 1)

print("\n3. The TTLs match how fast each thing actually changes")
check("price is the freshest — it moves tick to tick", mc.TICK_TTL_S <= 2.0,
      str(mc.TICK_TTL_S))
check("the position LIST outlives it — it changes on a trade, not a poll",
      mc.POSITIONS_TTL_S > mc.TICK_TTL_S, f"{mc.POSITIONS_TTL_S}s")
check("balance outlives both — it only moves when a position CLOSES",
      mc.BALANCE_TTL_S > mc.POSITIONS_TTL_S, f"{mc.BALANCE_TTL_S}s")
check("...but none is long enough to show a stale price as live",
      mc.TICK_TTL_S < 3.0)

print("\n4. Expiry actually expires")
mc._put(mc._tick, "u3", {"old": True})
mc._tick["u3"] = ({"old": True}, time.time() - (mc.TICK_TTL_S + 0.5))
check("an expired tick is a miss, not a stale hit", mc.get_tick("u3") is None)
mc._balance["u3"] = (1.0, time.time() - (mc.BALANCE_TTL_S + 1))
check("an expired balance is a miss too", mc.get_balance("u3") is None)

print("\n5. A trade opening or closing drops the cache immediately")
mc.put_tick("u4", {"price": 1.0})
mc.put_positions("u4", [{"symbol": "GBPUSD"}])
mc.put_balance("u4", 100.0)
mc.invalidate("u4")
check("the tick is gone", mc.get_tick("u4") is None)
check("the positions are gone", mc.get_positions("u4") is None,
      "otherwise a closed trade stays on screen for the rest of the TTL")
check("the balance is gone", mc.get_balance("u4") is None)

LOOP = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "user_loop.py"), encoding="utf-8").read()
check("every open and close invalidates it",
      "miniapp_cache.invalidate(user_id)" in LOOP)
check("...from the one function they ALL pass through",
      LOOP.index("miniapp_cache.invalidate(user_id)")
      > LOOP.index("def _persist_open_position"),
      "loop, manual /buy//close and the MCP tools all call this")

print("\n6. One user's cache is not another's")
mc.invalidate("a"); mc.invalidate("b")
mc.put_tick("a", {"who": "a"})
check("b does not see a's tick", mc.get_tick("b") is None)
check("a still does", mc.get_tick("a") == {"who": "a"})

print("\n7. The route reads through it")
BOT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "bot.py"), encoding="utf-8").read()
_tick_block = BOT[BOT.index('/api/app/tick'):BOT.index("# ── Mini App: history")]
check("a cache hit returns before any broker object is built",
      _tick_block.index("_mc.get_tick(chat_id)") < _tick_block.index("_make_broker"))
check("the balance read goes through the cache", "_mc.get_balance(chat_id)" in _tick_block)
check("the position list goes through the cache", "_mc.get_positions(chat_id)" in _tick_block)
check("a fresh payload is stored for the next poll", "cache=_mc.put_tick" in _tick_block)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the terminal no longer starves itself.")
