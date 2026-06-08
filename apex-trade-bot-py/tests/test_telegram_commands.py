"""Simulate a real Telegram chat: feed commands, capture bot replies.

Mocks out the network (send_to / deleteMessage / requests) so we can verify
the command-handling logic without hitting api.telegram.org.
Run: python tests/test_telegram_commands.py
"""
import os
import sys
import tempfile

# Configure a fake bot identity BEFORE importing the bot modules
os.environ["TELEGRAM_BOT_TOKEN"] = "TEST:TOKEN"
os.environ["TELEGRAM_CHAT_ID"] = "999"
os.environ["PAPER_TRADING"] = "true"
os.environ["BYPASS_LICENSE"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import telegram as tg  # noqa: E402

# Point runtime.json at a throwaway temp file so we don't touch the real one
tg._RUNTIME = os.path.join(tempfile.gettempdir(), "apex_test_runtime.json")
if os.path.exists(tg._RUNTIME):
    os.remove(tg._RUNTIME)

# ─── Capture outgoing messages instead of sending them ───
replies = []
deleted = []
tg.send_to = lambda chat_id, text, extra=None: replies.append(text)
tg.send = lambda text, extra=None: replies.append(text)
tg._delete_message = lambda chat_id, mid: deleted.append(mid)

# Fake bot control callbacks (pause flag + exchange reload)
_state = {"paused": True, "reloads": 0}
tg._bot_control = {
    "set_paused": lambda p: _state.update(paused=p),
    "get_paused": lambda: _state["paused"],
    "reload_exchange": lambda: _state.update(reloads=_state["reloads"] + 1),
}

# Fake dashboard so /status has something to render
tg._get_dash = lambda: {
    "exchange": "BINANCE", "mode": "PAPER", "balance": 1000.0, "startBalance": 1000.0,
    "currentSymbol": "SOLUSDT", "currentPrice": 142.50, "openPosition": None,
    "trades": [], "lastTick": "2026-06-08 12:00:00",
}
tg._exchange = None  # skip the candle fetch in /status


# ─── Helper: push one message through the dispatcher ─────
_uid = [1]


def send_command(text):
    """Mimic what _poll_loop does for a single incoming message."""
    replies.clear()
    deleted.clear()
    chat_id = 999
    msg_id = _uid[0]
    _uid[0] += 1

    # Wizard-step continuation (non-slash reply during an active wizard)
    if tg._wizard.get("step") and not text.startswith("/"):
        tg._handle_wizard_reply(chat_id, text, msg_id)
        return replies[:]

    cmd, _, args = text.partition(" ")
    cmd = cmd.lower()
    if cmd in ("/status", "/s"):
        tg._handle_status(chat_id)
    elif cmd == "/help":
        tg.send_to(chat_id, tg._HELP)
    elif cmd == "/setup":
        tg._handle_setup(chat_id)
    elif cmd == "/config":
        tg._handle_config(chat_id)
    elif cmd == "/setkeys":
        tg._handle_setkeys(chat_id, args, msg_id)
    elif cmd == "/exchange":
        tg._handle_exchange(chat_id, args)
    elif cmd == "/paper":
        tg._handle_paper(chat_id, args)
    elif cmd == "/risk":
        tg._handle_risk(chat_id, args)
    elif cmd == "/symbol":
        tg._handle_symbol(chat_id, args)
    elif cmd == "/start":
        tg._handle_start(chat_id)
    elif cmd == "/stop":
        tg._handle_stop(chat_id)
    return replies[:]


def check(label, condition, last_reply=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {last_reply[:120]}")
        check.failed += 1


check.failed = 0


# ─── Test scenarios ───────────────────────────────────────
print("\n🧪 SIMULATING A REAL TELEGRAM CHAT\n")

print("1. /help")
r = send_command("/help")
check("returns command list", r and "APEX BOT COMMANDS" in r[-1], r[-1] if r else "")

print("\n2. /status")
r = send_command("/status")
check("shows balance + paused tag", r and "$1000.00" in r[-1] and "PAUSED" in r[-1], r[-1] if r else "")

print("\n3. /config")
r = send_command("/config")
check("shows exchange + symbol", r and "BINANCE" in r[-1] and "SOLUSDT" in r[-1], r[-1] if r else "")

print("\n4. /risk 25")
r = send_command("/risk 25")
check("confirms 25%", r and "25%" in r[-1], r[-1] if r else "")
from apex import config as cfg  # noqa: E402
check("cfg.RISK_PER_TRADE == 0.25", abs(cfg.RISK_PER_TRADE - 0.25) < 1e-9)

print("\n5. /risk 999 (invalid)")
r = send_command("/risk 999")
check("rejects out-of-range", r and "1–50" in r[-1], r[-1] if r else "")

print("\n6. /symbol BTCUSDT")
r = send_command("/symbol BTCUSDT")
check("confirms BTCUSDT", r and "BTCUSDT" in r[-1], r[-1] if r else "")
check("cfg.SYMBOL updated", cfg.SYMBOL == "BTCUSDT")

print("\n7. /exchange okx")
r = send_command("/exchange okx")
check("confirms OKX", r and "OKX" in r[-1], r[-1] if r else "")
check("triggered exchange reload", _state["reloads"] == 1)

print("\n8. /exchange notreal (invalid)")
r = send_command("/exchange notreal")
check("rejects unknown exchange", r and "Supported exchanges" in r[-1], r[-1] if r else "")

print("\n9. /paper off")
r = send_command("/paper off")
check("confirms live mode", r and "OFF" in r[-1], r[-1] if r else "")
check("cfg.PAPER_TRADING == False", cfg.PAPER_TRADING is False)

print("\n10. /setkeys (secret deletion)")
r = send_command("/setkeys BINANCE_API_KEY=abcd1234 BINANCE_API_SECRET=secret9999")
check("confirms 2 keys", r and "2 credential" in r[-1], r[-1] if r else "")
check("masks the key value", r and "abcd***" in r[-1] and "abcd1234" not in r[-1], r[-1] if r else "")
check("DELETED the message (security)", len(deleted) == 1)
check("cfg got the real key", getattr(cfg, "BINANCE_API_KEY", "") == "abcd1234")

print("\n11. /start then /stop")
r = send_command("/start")
check("start unpauses", _state["paused"] is False and "started" in r[-1].lower(), r[-1] if r else "")
r = send_command("/stop")
check("stop pauses", _state["paused"] is True and "paused" in r[-1].lower(), r[-1] if r else "")

print("\n12. Full /setup wizard")
send_command("/setup")
r = send_command("bybit")          # step 1: exchange
check("wizard accepts exchange", r and "paper" in r[-1].lower(), r[-1] if r else "")
r = send_command("yes")            # step 2: paper on
check("wizard accepts paper=yes", r and "pair" in r[-1].lower(), r[-1] if r else "")
r = send_command("ETHUSDT")        # step 3: symbol (paper skips keys)
check("wizard completes setup", r and "Setup complete" in r[-1], r[-1] if r else "")
check("wizard set exchange=bybit", cfg.EXCHANGE == "bybit")
check("wizard set symbol=ETHUSDT", cfg.SYMBOL == "ETHUSDT")

print("\n13. runtime.json persisted")
import json  # noqa: E402
with open(tg._RUNTIME) as f:
    saved = json.load(f)
check("EXCHANGE saved", saved.get("EXCHANGE") == "bybit")
check("TRADE_SYMBOL saved", saved.get("TRADE_SYMBOL") == "ETHUSDT")
check("API key saved to disk", saved.get("BINANCE_API_KEY") == "abcd1234")

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — Telegram command layer works.")
    sys.exit(0)
else:
    print(f"❌ {check.failed} CHECK(S) FAILED.")
    sys.exit(1)
