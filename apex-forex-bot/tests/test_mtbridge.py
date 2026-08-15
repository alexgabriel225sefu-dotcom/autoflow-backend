"""Unit tests for the MetaTrader bridge — protocol, auth, command queue.

Simulates the ApexBridge EA talking to the bot, no network needed.
Run: python tests/test_mtbridge.py
"""
import os
import sys
import time

os.environ["PAPER_TRADING"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import config as cfg  # noqa: E402
from apex.brokers import mtbridge  # noqa: E402

cfg.MT_BRIDGE_SECRET = "test-secret-123"
cfg.PAPER_TRADING = False


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def ea_sync(position="NONE", acks=(), n_candles=210, secret="test-secret-123"):
    """Build a sync body the way the EA does."""
    body = (f"SECRET={secret}\nSYMBOL=EURUSD\nBID=1.08500\nASK=1.08512\n"
            f"BALANCE=10000.00\nEQUITY=10005.20\nPOSITION={position}\n")
    for a in acks:
        body += f"ACK={a}\n"
    for i in range(n_candles):
        c = 1.08 + i * 0.0001
        body += f"CANDLE={1718000000 + i * 300}|{c:.5f}|{c + 0.0005:.5f}|{c - 0.0005:.5f}|{c + 0.0002:.5f}|150\n"
    return body


print("\n🧪 METATRADER BRIDGE TESTS\n")
print("1. Authentication")
status, resp = mtbridge.handle_sync(ea_sync(secret="wrong"))
check("wrong secret → 403", status == 403 and "ERR" in resp, (status, resp))
status, resp = mtbridge.handle_sync(ea_sync())
check("correct secret → 200 OK", status == 200 and resp.startswith("OK"), (status, resp))

print("\n2. State ingestion")
check("symbol converted EURUSD → EUR_USD", mtbridge.current_symbol() == "EUR_USD",
      mtbridge.current_symbol())
bid, ask = mtbridge.get_bid_ask()
check("bid/ask stored", bid == 1.085 and ask == 1.08512, (bid, ask))
check("mid price", abs(mtbridge.get_price() - 1.08506) < 1e-9, mtbridge.get_price())
check("balance stored", mtbridge.get_balance() == 10000.0, mtbridge.get_balance())
candles = mtbridge.get_candles(limit=200)
check("candles stored and trimmed to limit", len(candles) == 200, len(candles))
check("candle fields parsed", abs(candles[-1]["close"] - (1.08 + 209 * 0.0001 + 0.0002)) < 1e-9,
      candles[-1])
check("flat position reported", mtbridge.position_reported() is None)
check("bridge connected", mtbridge.is_connected())

print("\n3. Broker suffix symbols (EURUSD.a)")
mtbridge.handle_sync(ea_sync().replace("SYMBOL=EURUSD", "SYMBOL=EURUSD.a"))
check("suffix stripped", mtbridge.current_symbol() == "EUR_USD", mtbridge.current_symbol())

print("\n4. Command queue — open")
r = mtbridge.place_order("BUY", 13333, "EUR_USD", sl=1.0835, tp=1.0880)
check("order queued", r["status"] == "QUEUED", r)
status, resp = mtbridge.handle_sync(ea_sync())
check("command delivered to EA", "CMD=" in resp and "|OPEN|BUY|0.13|" in resp, resp)
check("SL/TP included", "1.08350" in resp and "1.08800" in resp, resp)
status, resp2 = mtbridge.handle_sync(ea_sync())
check("undelivered command repeats until acked", "OPEN|BUY" in resp2, resp2)

print("\n5. Ack clears the queue")
cmd_id = r["orderId"]
status, resp = mtbridge.handle_sync(ea_sync(position="BUY|0.13|1.08510",
                                            acks=[f"{cmd_id}|FILLED|1.08510"]))
check("acked command no longer sent", "CMD=" not in resp, resp)
pos = mtbridge.position_reported()
check("EA position reported", pos and pos["side"] == "BUY" and pos["lots"] == 0.13, pos)

print("\n6. Close command")
r = mtbridge.close_position("EUR_USD")
status, resp = mtbridge.handle_sync(ea_sync(position="BUY|0.13|1.08510"))
check("CLOSE delivered", f"CMD={r['orderId']}|CLOSE" in resp, resp)
mtbridge.handle_sync(ea_sync(position="NONE", acks=[f"{r['orderId']}|CLOSED|1.08620"]))
check("position flat after close", mtbridge.position_reported() is None)

print("\n7. Minimum lot")
r = mtbridge.place_order("SELL", 100, "EUR_USD", sl=1.09, tp=1.07)  # 100 units → 0.001 lots
status, resp = mtbridge.handle_sync(ea_sync())
check("tiny size floors at 0.01 lots", "|OPEN|SELL|0.01|" in resp, resp)
mtbridge.handle_sync(ea_sync(acks=[f"{r['orderId']}|FILLED|1.085"]))

print("\n8. Paper mode never reaches the EA")
cfg.PAPER_TRADING = True
r = mtbridge.place_order("BUY", 10000, "EUR_USD")
check("paper order filled locally", r["status"] == "FILLED" and str(r["orderId"]).startswith("PAPER"), r)
status, resp = mtbridge.handle_sync(ea_sync())
check("no command queued", "CMD=" not in resp, resp)
cfg.PAPER_TRADING = False

print("\n9. Stale bridge detection")
mtbridge._state["last_sync"] = time.time() - 120
try:
    mtbridge.get_price()
    check("stale bridge raises", False)
except RuntimeError as e:
    check("stale bridge raises", "offline" in str(e), e)
check("is_connected() false when stale", not mtbridge.is_connected())

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — MetaTrader bridge works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
