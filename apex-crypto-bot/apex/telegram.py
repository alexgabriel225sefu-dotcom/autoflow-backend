"""Telegram multi-tenant handler — crypto edition.

One bot token serves all paying clients. Keyless instant activation: the
purchase email / thank-you page hands out a t.me deep link, so anyone who
reaches the bot is a paying customer → granted on contact. Owner is set via
ADMIN_CHAT_ID. Polling runs in a background daemon thread.
"""
import json
import time
import threading
import requests
from apex import config as cfg
from apex import access, user_store, user_loop, binance

TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
_API = f"https://api.telegram.org/bot{TOKEN}"
_update_id = 0
_wizard = {}   # chat_id → step (e.g. "KEYS") for the real-account setup flow

SYMBOLS = [
    [("₿ BTC", "BTCUSDT"), ("⟠ ETH", "ETHUSDT")],
    [("◎ SOL", "SOLUSDT"), ("✕ XRP", "XRPUSDT")],
    [("Ð DOGE", "DOGEUSDT"), ("△ ADA", "ADAUSDT")],
    [("⬡ BNB", "BNBUSDT"), ("☀ AVAX", "AVAXUSDT")],
]
METHODS = ["auto", "turtle", "livermore", "soros", "ptj", "druckenmiller"]


def refresh_from_config():
    global TOKEN, _API
    TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
    _API = f"https://api.telegram.org/bot{TOKEN}"


# ─── API helpers ──────────────────────────────────────────
def send_to(chat_id, text, extra=None):
    if not TOKEN:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True, **(extra or {})}, timeout=8)
    except Exception as e:
        print(f"[TG] send error: {e}")


def _broadcast_owner(text):
    for cid in access.list_admins():
        send_to(cid, text)


def _answer_cb(cb_id):
    try:
        requests.post(f"{_API}/answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=5)
    except Exception:
        pass


def _delete_message(chat_id, message_id):
    try:
        requests.post(f"{_API}/deleteMessage",
                      json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
    except Exception:
        pass


# ─── Keyboards ────────────────────────────────────────────
def _kb_menu(paused, symbol="BTCUSDT"):
    chart_url = f"{cfg.SITE_URL}/chart?s={symbol}"
    rows = [
        [{"text": "📊 Status", "callback_data": "c:status"}, {"text": "📋 Trades", "callback_data": "c:trades"}],
        [{"text": "💎 Symbol", "callback_data": "c:symbol"}, {"text": "⚙️ Config", "callback_data": "c:config"}],
        [{"text": "🎯 Method", "callback_data": "c:method"}, {"text": "❓ Help", "callback_data": "c:help"}],
        [{"text": "📈 Live Chart", "web_app": {"url": chart_url}}],
        [{"text": "▶️ Start Trading" if paused else "⏸ Pause Bot",
          "callback_data": "c:resume" if paused else "c:pause"}],
    ]
    return {"reply_markup": json.dumps({"inline_keyboard": rows})}


def _kb_start():
    """First-run choice: paper (training) or real Binance account."""
    return {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "📝 Paper Trading (no risk)", "callback_data": "setup:paper"}],
        [{"text": "🔴 Real Binance Account", "callback_data": "setup:live"}],
    ]})}


_BINANCE_KEYS_URL = "https://www.binance.com/en/my/settings/api-management"


def _kb_binance():
    return {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "🔑 Open Binance API page", "url": _BINANCE_KEYS_URL}],
    ]})}


def _kb_symbols():
    rows = [[{"text": label, "callback_data": f"sym:{sym}"} for label, sym in row] for row in SYMBOLS]
    return {"reply_markup": json.dumps({"inline_keyboard": rows})}


def _kb_methods():
    rows = [[{"text": m.capitalize(), "callback_data": f"m:{m}"}] for m in METHODS]
    return {"reply_markup": json.dumps({"inline_keyboard": rows})}


# ─── Views ────────────────────────────────────────────────
def _settings(user_id):
    return user_loop._ensure_user(user_id)["settings"]


def _build_status(user_id):
    u = user_loop._ensure_user(user_id)
    s, st = u["settings"], u["state"]
    sb = st.get("startBalance", cfg.PAPER_BALANCE)
    bal = st.get("paperBalance", sb)
    pnl_pct = (bal - sb) / sb * 100 if sb else 0
    trades = st.get("trades", [])
    wins = sum(1 for t in trades if t.get("win"))
    total = len(trades)
    wr = f"{wins / total * 100:.0f}%" if total else "—"
    pos = st.get("openPosition")
    if pos:
        d = "🟢 LONG" if pos["side"] == "BUY" else "🔴 SHORT"
        p = pos.get("currentPnl", 0)
        pos_line = (f"{d} <b>{pos['symbol']}</b>\n  Entry: ${pos['entryPrice']:.4f}  "
                    f"PnL: <b>{'+' if p >= 0 else ''}${p:.4f}</b>")
    else:
        pos_line = "📭 No open position"
    sig = st.get("lastSignal")
    sig_line = (f"🤖 Signal: <b>{sig['action']}</b> ({sig['confidence']:.0f}%)" if sig else "🤖 Signal: scanning…")
    return (f"⚡ <b>APEX TRADE BOT</b>  {'PAPER' if u.get('paper', True) else 'LIVE'}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: <b>${bal:.2f}</b>  ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)\n\n"
            f"{pos_line}\n\n{sig_line}\n"
            f"📈 {total} trades · {wins}W/{total - wins}L · WR: {wr}\n"
            f"🎯 Symbol: <b>{s['SYMBOL']}</b>  ⏱️ {st.get('lastTick', 'starting…')}")


def _build_config(user_id):
    s = _settings(user_id)
    return (f"⚙️ <b>CONFIGURATION</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 Symbol: <b>{s['SYMBOL']}</b>\n"
            f"🎯 Method: <b>{s['STRATEGY_MODE']}</b>\n"
            f"💸 Risk/trade: <b>{s['RISK_PER_TRADE'] * 100:.1f}%</b>\n"
            f"🛡 SL: <b>{s['STOP_LOSS_PCT'] * 100:.1f}%</b>  🎯 TP: <b>{s['TAKE_PROFIT_PCT'] * 100:.1f}%</b>\n"
            f"🧠 Min confidence: <b>{s['MIN_CONFIDENCE']}%</b>  Criteria: <b>{s['MIN_CRITERIA']}/5</b>\n\n"
            f"<i>Change: /symbol /risk /sl /tp /confidence /method</i>")


def _build_trades(user_id):
    st = user_loop._ensure_user(user_id)["state"]
    lst = st.get("trades", [])[:10]
    if not lst:
        return "📭 No trades yet — the bot trades automatically when a setup appears."
    rows = [f"{'✅' if t['win'] else '❌'} {t['side']} <b>{t['symbol']}</b>  "
            f"${t['entry']}→${t['exit']}  <b>{'+' if t['pnl'] >= 0 else ''}${t['pnl']}</b>" for t in lst]
    return f"📋 <b>LAST {len(lst)} TRADES</b>\n━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(rows)


_HELP = ("📋 <b>APEX TRADE BOT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
         "Your AI bot trades crypto automatically. Just set it and watch.\n\n"
         "<b>Controls:</b>\n/menu · /status · /config · /trades\n\n"
         "<b>Settings:</b>\n/symbol BTCUSDT\n/method auto|turtle|livermore|soros|ptj|druckenmiller\n"
         "/risk 5 — % per trade\n/sl 1.6 — stop loss %\n/tp 3.2 — take profit %\n/confidence 70 — min AI confidence\n\n"
         "<b>Run:</b>\n/pause · /resume\n\n"
         "<b>Free AI key:</b>\n/groq gsk_YOUR_KEY (get one at console.groq.com)")


# ─── Alerts (per-user callback) ───────────────────────────
def make_alert(chat_id):
    def alert(kind, data):
        if kind == "open":
            d = "🟢 LONG" if data["side"] == "BUY" else "🔴 SHORT"
            mult = f"\n📐 Druckenmiller: ×{data['druckMult']:.2f}" if data.get("druckMult", 1) != 1 else ""
            send_to(chat_id, f"{d} <b>OPENED — {data['symbol']}</b>\n"
                             f"💰 Entry: ${data['price']:.4f}  Qty: {data['qty']}\n"
                             f"🛡 SL: ${data['stopLoss']:.4f}  🎯 TP: ${data['takeProfit']:.4f}{mult}")
        elif kind == "close":
            icons = {"TAKE_PROFIT": "🎯 TAKE PROFIT", "STOP_LOSS": "🛑 STOP LOSS", "AI_CLOSE": "🤖 AI CLOSE"}
            send_to(chat_id, f"{'✅' if data['pnl'] > 0 else '❌'} <b>{icons.get(data['reason'], data['reason'])} — {data['symbol']}</b>\n"
                             f"${data['entryPrice']:.4f} → ${data['exitPrice']:.4f}\n"
                             f"PnL: <b>{'+' if data['pnl'] >= 0 else ''}${data['pnl']:.4f}</b>  💼 ${data['balance']:.2f}")
        elif kind == "heartbeat":
            p = data["openPosition"]
            line = (f"{'🟢' if p['side'] == 'BUY' else '🔴'} {p['symbol']} @ ${p['entryPrice']:.4f}  "
                    f"PnL: {'+' if p.get('currentPnl', 0) >= 0 else ''}${p.get('currentPnl', 0):.4f}")
            send_to(chat_id, f"💓 Tick #{data['tickCount']}  💼 ${data['balance']:.2f}\n{line}")
        elif kind == "risk_pause":
            send_to(chat_id, "🛡️ <b>Risk pause</b> — protecting your capital.\n"
                             + "\n".join(f"• {r}" for r in data["reasons"])
                             + f"\n\n<i>Auto-resumes in {cfg.RISK_PAUSE_MIN} min, or tap ▶️ Start Trading to resume now.</i>")
        elif kind == "risk_resume":
            send_to(chat_id, "▶️ <b>Trading resumed</b> — risk pause over, scanning the market again. 🚀")
        elif kind == "groq_error":
            send_to(chat_id, "⚠️ <b>Your Groq key is invalid or hit its limit.</b>\n"
                             "Get a new free key at console.groq.com → API Keys, then send /groq gsk_NEW_KEY")
    return alert


def _ensure_running(chat_id):
    if not user_loop.is_running(chat_id):
        user_loop.start(chat_id, make_alert(chat_id))


# ─── Command handling ─────────────────────────────────────
def _upd(chat_id, key, value):
    u = user_loop._ensure_user(chat_id)
    u["settings"][key] = value
    user_store.save(chat_id, u)


def _handle_command(chat_id, text):
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:]
    is_adm = access.is_admin(str(chat_id))
    s = _settings(chat_id)

    if cmd in ("/start", "/menu", "/m"):
        u = user_loop._ensure_user(chat_id)
        # First run (or never chose a mode): ask paper vs real before trading.
        if cmd == "/start" and not u.get("setup_done"):
            return send_to(chat_id,
                           "✅ <b>Welcome to APEX TRADE BOT!</b>\n\n"
                           "Choose how you want to trade:\n\n"
                           "📝 <b>Paper</b> — $100 virtual, real market prices, zero risk.\n"
                           "🔴 <b>Real Binance</b> — trade your own account.\n\n"
                           "<i>You can switch any time from the menu.</i>",
                           _kb_start())
        _ensure_running(chat_id)
        return send_to(chat_id, "⚡ <b>APEX TRADE BOT — Control Panel</b>\n"
                                "Your AI bot is active and trading automatically. 🚀",
                       _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if cmd in ("/status", "/s"):
        return send_to(chat_id, _build_status(chat_id), _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if cmd in ("/config", "/c"):
        return send_to(chat_id, _build_config(chat_id))
    if cmd in ("/trades", "/t"):
        return send_to(chat_id, _build_trades(chat_id))
    if cmd == "/help":
        return send_to(chat_id, _HELP)
    if cmd == "/symbol":
        if not args:
            return send_to(chat_id, f"💎 <b>Choose trading pair:</b>\nCurrent: <b>{s['SYMBOL']}</b>", _kb_symbols())
        sym = args[0].upper()
        if not binance.valid_symbol(sym):
            return send_to(chat_id, f"❌ <b>{sym}</b> is not a valid Binance pair. Example: <code>/symbol BTCUSDT</code>")
        _upd(chat_id, "SYMBOL", sym)
        user_loop.reset_risk(chat_id)
        return send_to(chat_id, f"💎 Symbol → <b>{sym}</b>", _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if cmd == "/method":
        if not args or args[0].lower() not in METHODS:
            return send_to(chat_id, f"🎯 Method (current: <b>{s['STRATEGY_MODE']}</b>)\nChoose:", _kb_methods())
        _upd(chat_id, "STRATEGY_MODE", args[0].lower())
        return send_to(chat_id, f"🎯 Method → <b>{args[0].lower()}</b>")
    if cmd == "/risk":
        try:
            pct = float(args[0])
            assert 0.5 <= pct <= 20
        except (IndexError, ValueError, AssertionError):
            return send_to(chat_id, "❌ Usage: <code>/risk 5</code>  (0.5–20%)")
        _upd(chat_id, "RISK_PER_TRADE", pct / 100)
        return send_to(chat_id, f"💸 Risk/trade → <b>{pct:g}%</b>")
    if cmd == "/sl":
        try:
            pct = float(args[0])
            assert 0.3 <= pct <= 20
        except (IndexError, ValueError, AssertionError):
            return send_to(chat_id, "❌ Usage: <code>/sl 1.6</code>  (0.3–20%)")
        _upd(chat_id, "STOP_LOSS_PCT", pct / 100)
        return send_to(chat_id, f"🛡 Stop loss → <b>{pct:g}%</b>")
    if cmd == "/tp":
        try:
            pct = float(args[0])
            assert 0.3 <= pct <= 50
        except (IndexError, ValueError, AssertionError):
            return send_to(chat_id, "❌ Usage: <code>/tp 3.2</code>  (0.3–50%)")
        _upd(chat_id, "TAKE_PROFIT_PCT", pct / 100)
        return send_to(chat_id, f"🎯 Take profit → <b>{pct:g}%</b>")
    if cmd == "/confidence":
        try:
            v = int(args[0])
            assert 40 <= v <= 95
        except (IndexError, ValueError, AssertionError):
            return send_to(chat_id, "❌ Usage: <code>/confidence 70</code>  (40–95)")
        _upd(chat_id, "MIN_CONFIDENCE", v)
        return send_to(chat_id, f"🧠 Min confidence → <b>{v}%</b>")
    if cmd == "/groq":
        if not args or not args[0].startswith("gsk_"):
            return send_to(chat_id, "❌ Usage: <code>/groq gsk_YOUR_KEY</code>\nGet a free key at console.groq.com")
        user_store.update(chat_id, {"groq_key": args[0]})
        return send_to(chat_id, "✅ <b>Groq key saved!</b> Your AI signals now use your personal key.")
    if cmd == "/pause":
        _upd(chat_id, "PAUSED", True)
        return send_to(chat_id, "⏸️ <b>Bot paused.</b>", _kb_menu(True))
    if cmd == "/resume":
        _upd(chat_id, "PAUSED", False)
        user_loop.reset_risk(chat_id)
        _ensure_running(chat_id)
        return send_to(chat_id, "▶️ <b>Bot ACTIVE</b> — trading every minute! 🚀", _kb_menu(False))

    # ── Admin ──
    if cmd == "/grant" and is_adm and args:
        if access.grant(args[0]):
            send_to(chat_id, f"✅ Access granted to <code>{args[0]}</code>.")
            send_to(args[0], "✅ <b>Welcome to Apex Trade Bot!</b> Send /start to begin.")
        else:
            send_to(chat_id, f"ℹ️ <code>{args[0]}</code> already has access.")
        return
    if cmd == "/revoke" and is_adm and args:
        ok = access.revoke(args[0])
        return send_to(chat_id, f"{'✅ Revoked' if ok else 'ℹ️ Not found'} <code>{args[0]}</code>.")
    if cmd == "/users" and is_adm:
        clients = access.list_clients()
        lines = "\n".join(f"✅ {c}" for c in clients) or "— none yet —"
        return send_to(chat_id, f"👥 <b>CLIENTS ({len(clients)})</b>\n{lines}")

    if not is_adm:
        return  # clients: ignore unknown commands silently
    send_to(chat_id, _HELP)


def _handle_callback(chat_id, data):
    s = _settings(chat_id)
    if data == "setup:paper":
        return _start_paper(chat_id)
    if data == "setup:live":
        return _start_live_setup(chat_id)
    if data.startswith("sym:"):
        sym = data[4:]
        _upd(chat_id, "SYMBOL", sym)
        user_loop.reset_risk(chat_id)
        return send_to(chat_id, f"💎 Symbol → <b>{sym}</b>", _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if data.startswith("m:"):
        _upd(chat_id, "STRATEGY_MODE", data[2:])
        return send_to(chat_id, f"🎯 Method → <b>{data[2:]}</b>")
    if data == "c:status":
        return send_to(chat_id, _build_status(chat_id), _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if data == "c:config":
        return send_to(chat_id, _build_config(chat_id))
    if data == "c:trades":
        return send_to(chat_id, _build_trades(chat_id))
    if data == "c:symbol":
        return send_to(chat_id, f"💎 Choose trading pair:\nCurrent: <b>{s['SYMBOL']}</b>", _kb_symbols())
    if data == "c:method":
        return send_to(chat_id, f"🎯 Method (current: <b>{s['STRATEGY_MODE']}</b>):", _kb_methods())
    if data == "c:help":
        return send_to(chat_id, _HELP)
    if data == "c:pause":
        _upd(chat_id, "PAUSED", True)
        return send_to(chat_id, "⏸️ <b>Bot paused.</b>", _kb_menu(True))
    if data == "c:resume":
        _upd(chat_id, "PAUSED", False)
        user_loop.reset_risk(chat_id)
        _ensure_running(chat_id)
        return send_to(chat_id, "▶️ <b>Bot ACTIVE</b> — trading every minute! 🚀", _kb_menu(False))


# ─── Poll loop ────────────────────────────────────────────
def _activate(chat_id):
    """Keyless instant activation — grant + welcome + ask paper vs real."""
    access.grant(str(chat_id))
    send_to(chat_id,
            "✅ <b>Welcome to APEX TRADE BOT!</b>\n\n"
            "Your AI crypto bot is ready. First, choose how you want to trade:\n\n"
            "📝 <b>Paper</b> — practice with $100 virtual, real market prices, zero risk.\n"
            "🔴 <b>Real Binance</b> — trade your own Binance account.\n\n"
            "<i>You can switch any time from the menu.</i>",
            _kb_start())
    _broadcast_owner(f"🆕 <b>New client activated!</b>\nID: <code>{chat_id}</code>")


def _start_paper(chat_id):
    u = user_loop._ensure_user(chat_id)
    u["paper"] = True
    u["setup_done"] = True
    u["settings"]["PAUSED"] = False
    user_store.save(chat_id, u)
    _ensure_running(chat_id)
    send_to(chat_id,
            "✅ <b>Paper account ready!</b>\n💰 $100 virtual · real market data · zero risk.\n\n"
            "Your bot is now trading automatically. 🚀\nWatch it work — tap 📈 Live Chart or 📊 Status.",
            _kb_menu(False, u["settings"]["SYMBOL"]))


def _start_live_setup(chat_id):
    _wizard[str(chat_id)] = "KEYS"
    send_to(chat_id,
            "🔴 <b>Connect your real Binance account</b>\n\n"
            "1. Tap <b>Open Binance API page</b> below\n"
            "2. Create an API key — enable <b>Spot &amp; Margin Trading</b>\n"
            "3. Send the key + secret here in ONE message:\n"
            "<code>API_KEY=your_key API_SECRET=your_secret</code>\n\n"
            "🔒 <i>Your message is deleted instantly after I read it.</i>",
            _kb_binance())


def _finish_live_setup(chat_id, text, msg_id):
    _delete_message(chat_id, msg_id)
    pairs = {}
    for part in text.replace("\n", " ").split():
        if "=" in part:
            k, _, v = part.partition("=")
            pairs[k.strip().upper()] = v.strip()
    if "API_KEY" not in pairs or "API_SECRET" not in pairs:
        return send_to(chat_id, "❌ Send both in one message:\n<code>API_KEY=xxx API_SECRET=yyy</code>")
    u = user_loop._ensure_user(chat_id)
    u["paper"] = False
    u["setup_done"] = True
    u["api_key"] = pairs["API_KEY"]
    u["api_secret"] = pairs["API_SECRET"]
    u["settings"]["PAUSED"] = False
    user_store.save(chat_id, u)
    _wizard.pop(str(chat_id), None)
    _ensure_running(chat_id)
    safety = "🧪 Testnet (safe)" if cfg.BINANCE_TESTNET else "🔴 LIVE — real funds"
    send_to(chat_id,
            f"✅ <b>Binance connected!</b>\nMode: <b>{safety}</b>\n\n"
            "Your bot is now trading your account automatically. Watch it on 📊 Status / 📈 Live Chart.",
            _kb_menu(False, u["settings"]["SYMBOL"]))


def _poll_loop():
    global _update_id
    try:
        requests.post(f"{_API}/deleteWebhook", json={"drop_pending_updates": False}, timeout=5)
    except Exception:
        pass
    user_loop.start_all(None)  # restore previously active users (alert wired per-user below)
    for uid in user_store.all_active():
        user_loop.start(uid, make_alert(uid))
    print(f"[TG] Poll loop started. TOKEN={bool(TOKEN)}")
    while True:
        try:
            r = requests.get(f"{_API}/getUpdates",
                             params={"offset": _update_id, "timeout": 25,
                                     "allowed_updates": json.dumps(["message", "callback_query"])},
                             timeout=30)
            data = r.json()
            if not data.get("ok"):
                print(f"[TG] API error: {data.get('description')} (code {data.get('error_code')})")
                time.sleep(5)
                continue
            for u in data.get("result", []):
                _update_id = u["update_id"] + 1
                if "callback_query" in u:
                    cb = u["callback_query"]
                    chat_id = cb["message"]["chat"]["id"]
                    _answer_cb(cb["id"])
                    if not access.is_allowed(str(chat_id)):
                        _activate(chat_id)
                        continue
                    try:
                        _handle_callback(chat_id, cb.get("data", ""))
                    except Exception as e:
                        print(f"[TG] callback error: {e}")
                    continue
                msg = u.get("message", {})
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                msg_id = msg.get("message_id")
                if not text or chat_id is None:
                    continue
                if not access.is_allowed(str(chat_id)):
                    _activate(chat_id)  # deep-link /start TOKEN lands here too
                    continue
                # Real-account setup: capture the API key message (not a command)
                if _wizard.get(str(chat_id)) == "KEYS" and not text.startswith("/"):
                    try:
                        _finish_live_setup(chat_id, text, msg_id)
                    except Exception as e:
                        print(f"[TG] keys error: {e}")
                    continue
                try:
                    _handle_command(chat_id, text)
                except Exception as e:
                    print(f"[TG] command error: {e}")
        except Exception as e:
            print(f"[TG] poll error: {e}")
            time.sleep(3)


def start_polling():
    if not TOKEN:
        print("[TG] Missing TELEGRAM_BOT_TOKEN — polling disabled")
        return
    threading.Thread(target=_poll_loop, daemon=True).start()
    print("[TG] Polling started")
