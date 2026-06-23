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
from apex import access, user_store, user_loop, binance, ai, assistant

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
METHOD_DESC = {
    "auto":          "🤖 <b>Auto</b> — AI blends all strategies. Best for hands-off trading.",
    "turtle":        "🐢 <b>Turtle</b> — buys breakouts of recent highs. Trend-following.",
    "livermore":     "📐 <b>Livermore</b> — follows market structure &amp; strong trends.",
    "soros":         "💡 <b>Soros</b> — rides momentum, enters on strong directional moves.",
    "ptj":           "🛡 <b>PTJ</b> — defensive; only high-confidence setups (fewer trades).",
    "druckenmiller": "📈 <b>Druckenmiller</b> — scales position size up on the best setups.",
}


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


def _send_typing(chat_id):
    try:
        requests.post(f"{_API}/sendChatAction",
                      json={"chat_id": chat_id, "action": "typing"}, timeout=3)
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
    # Both Start and Pause always visible — active one gets a checkmark.
    return {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "📊 Status", "callback_data": "c:status"}, {"text": "📋 Trades", "callback_data": "c:trades"}],
        [{"text": "💎 Symbol", "callback_data": "c:symbol"}, {"text": "⚙️ Config", "callback_data": "c:config"}],
        [{"text": "🎯 Method", "callback_data": "c:method"}, {"text": "❓ Help", "callback_data": "c:help"}],
        [{"text": "📈 Live Chart", "callback_data": "c:chart"}],
        [
            {"text": "▶️ Start" + (" ✅" if not paused else ""), "callback_data": "c:resume"},
            {"text": "⏸ Pause" + (" ✅" if paused else ""),    "callback_data": "c:pause"},
        ],
    ]})}


def _kb_activate():
    """Single button shown on very first contact."""
    return {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "🚀 Activate Bot", "callback_data": "setup:activate"}],
    ]})}


def _kb_mode():
    """Paper vs Real choice."""
    return {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "📝 Paper Trading — $100 virtual, no risk", "callback_data": "setup:paper"}],
        [{"text": "🔴 Real Binance — live account",           "callback_data": "setup:live"}],
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
         "<b>Controls:</b>\n/menu · /status · /signal · /config · /trades\n\n"
         "<b>Settings:</b>\n/symbol BTCUSDT\n/method auto|turtle|livermore|soros|ptj|druckenmiller\n"
         "/risk 5 — % per trade\n/sl 1.6 — stop loss %\n/tp 3.2 — take profit %\n/confidence 70 — min AI confidence\n\n"
         "<b>Run:</b>\n/pause · /resume\n\n"
         "<b>Account:</b>\n/setup — switch paper ↔ real, re-run onboarding\n\n"
         "<b>💬 Smart assistant:</b>\nJust talk to me! \"analyze BTC\", \"buy ETH\", \"close position\"\n"
         "/claude sk-ant-KEY — full chat + trade execution (console.anthropic.com)\n"
         "/gemini AIza-KEY — FREE chat + analysis, 1500/day (aistudio.google.com)\n"
         "/groq gsk_KEY — free fast chat (console.groq.com)")


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
        elif kind == "scan":
            sig = user_loop._ensure_user(chat_id).get("state", {}).get("lastSignal")
            sig_txt = (f"🤖 Last signal: <b>{sig['action']}</b> ({sig['confidence']:.0f}% conf)"
                       if sig else "🤖 Scanning for setups…")
            send_to(chat_id, f"⚡ <b>Bot active</b> — ${data['balance']:.2f} · {data['symbol']} · tick #{data['tickCount']}\n{sig_txt}")
        elif kind == "groq_error":
            reason = data.get("reason", "")
            if reason == "GROQ_KEY_QUOTA":
                send_to(chat_id, "⏳ <b>Groq rate limit hit.</b> Bot retries automatically in 10 min.\n"
                                 "Rule-based signals active in the meantime — no action needed.")
            else:
                send_to(chat_id, "⚠️ <b>Groq key invalid.</b> Get a new free key at console.groq.com → API Keys, "
                                 "then send /groq gsk_NEW_KEY")
    return alert


def _ensure_running(chat_id):
    if not user_loop.is_running(chat_id):
        user_loop.start(chat_id, make_alert(chat_id))


# ─── Command handling ─────────────────────────────────────
def _upd(chat_id, key, value):
    u = user_loop._ensure_user(chat_id)
    u["settings"][key] = value
    user_store.save(chat_id, u)


def _handle_command(chat_id, text, msg_id=None):
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:]
    is_adm = access.is_admin(str(chat_id))
    s = _settings(chat_id)

    if cmd == "/setup":
        u = user_loop._ensure_user(chat_id)
        u["setup_done"] = False
        user_store.save(chat_id, u)
        return send_to(chat_id,
                       "🔄 <b>Setup reset.</b>\n\nHow do you want to trade?",
                       _kb_mode())
    if cmd in ("/start", "/menu", "/m"):
        u = user_loop._ensure_user(chat_id)
        if cmd == "/start" and not u.get("setup_done"):
            return send_to(chat_id,
                           "👋 <b>Welcome to APEX TRADE BOT!</b>\n\n"
                           "Your AI-powered crypto trading bot is ready.\n"
                           "Tap below to activate and configure it in 2 minutes.",
                           _kb_activate())
        _ensure_running(chat_id)
        paused = u["settings"].get("PAUSED", False)
        status = "⏸ PAUSED" if paused else "▶️ ACTIVE"
        return send_to(chat_id,
                       f"⚡ <b>APEX TRADE BOT</b> — {status}\n"
                       f"Symbol: <b>{u['settings']['SYMBOL']}</b>  Strategy: <b>{u['settings']['STRATEGY_MODE']}</b>",
                       _kb_menu(paused, u["settings"]["SYMBOL"]))
    if cmd in ("/signal", "/sig"):
        st = user_loop._ensure_user(chat_id)["state"]
        sig = st.get("lastSignal")
        if not sig:
            return send_to(chat_id, "🤖 No signal yet — bot hasn't scanned yet. Try again in 1 minute.")
        factors = "\n".join(f"  • {f}" for f in sig.get("keyFactors", []))
        return send_to(chat_id,
                       f"🤖 <b>Last signal — {s['SYMBOL']}</b>\n"
                       f"Action: <b>{sig['action']}</b>  Confidence: <b>{sig['confidence']:.0f}%</b>\n"
                       f"Criteria: {sig.get('criteriaScore', 0)}/5  Risk: {sig.get('riskLevel', '—')}\n"
                       f"Reasoning: <i>{sig.get('reasoning', '—')}</i>\n"
                       + (f"\nFactors:\n{factors}" if factors else ""))
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
        if msg_id:   # delete the message so the secret key doesn't linger in chat
            _delete_message(chat_id, msg_id)
        if not args or not args[0].startswith("gsk_"):
            return send_to(chat_id, "❌ Usage: <code>/groq gsk_YOUR_KEY</code>\nGet a free key at console.groq.com")
        send_to(chat_id, "🔍 Testing your Groq key…")
        ok, why = ai.test_key(args[0])
        if not ok:
            return send_to(chat_id, f"❌ <b>Key not working:</b> {why}\nGet a fresh key at console.groq.com → API Keys.")
        user_store.update(chat_id, {"groq_key": args[0]})
        return send_to(chat_id, "✅ <b>Groq key verified &amp; saved!</b> Your AI signals now run on YOUR personal quota. 🧠")
    if cmd == "/claude":
        if msg_id:   # delete so the secret key doesn't linger in chat
            _delete_message(chat_id, msg_id)
        if not args or not args[0].startswith("sk-ant-"):
            return send_to(chat_id,
                           "❌ Usage: <code>/claude sk-ant-YOUR_KEY</code>\n"
                           "Get a free key at console.anthropic.com → API Keys.\n"
                           "This unlocks the smart assistant: natural chat + real trade execution.")
        send_to(chat_id, "🔍 Testing your Claude key…")
        ok, why = assistant.test_key(args[0])
        if not ok:
            return send_to(chat_id, f"❌ <b>Key not working:</b> {why}\n"
                                    "Get a fresh key at console.anthropic.com → API Keys.")
        user_store.update(chat_id, {"anthropic_key": args[0]})
        assistant.clear_history(chat_id)
        return send_to(chat_id,
                       "✅ <b>Claude key verified &amp; saved!</b>\n"
                       "Now just talk to me naturally — I'll analyze markets and execute trades for you. 🧠⚡\n"
                       "Try: <i>\"analyze BTC\"</i> or <i>\"should I buy ETH now?\"</i>")
    if cmd == "/gemini":
        if msg_id:   # delete so the secret key doesn't linger in chat
            _delete_message(chat_id, msg_id)
        if not args:
            return send_to(chat_id,
                           "❌ Usage: <code>/gemini YOUR_KEY</code>\n"
                           "Get a FREE key at aistudio.google.com → Get API key.\n"
                           "Most generous free tier: 1,500 messages/day for chat + analysis.")
        gkey = args[0].strip()
        send_to(chat_id, "🔍 Testing your Gemini key…")
        ok, why = assistant.test_gemini_key(gkey)
        if not ok:
            return send_to(chat_id, f"❌ <b>Key not working:</b> {why}")
        user_store.update(chat_id, {"gemini_key": gkey})
        assistant.clear_history(chat_id)
        return send_to(chat_id,
                       "✅ <b>Gemini key verified &amp; saved!</b> 🆓\n"
                       "Free chat + market analysis on YOUR own quota (1,500/day).\n"
                       "For real trade execution, add a Claude key with /claude.")
    if cmd == "/pause":
        _upd(chat_id, "PAUSED", True)
        return send_to(chat_id, "⏸️ <b>Bot paused.</b>", _kb_menu(True))
    if cmd == "/resume":
        _upd(chat_id, "PAUSED", False)
        user_loop.reset_risk(chat_id)
        _ensure_running(chat_id)
        sym = s["SYMBOL"]
        return send_to(chat_id,
                       f"▶️ <b>Bot ACTIVE</b> — scanning <b>{sym}</b> every 60s.\n"
                       "You'll get a ping every 30 min + all trade alerts.",
                       _kb_menu(False, sym))

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
    if data == "setup:activate":   # tap on the first welcome button
        return _show_disclaimer(chat_id)
    if data == "setup:accept":     # accepted the risk disclaimer
        from datetime import datetime as _dt
        user_store.update(chat_id, {"disclaimer_accepted": _dt.utcnow().isoformat()})
        return _show_mode_choice(chat_id)
    if data == "setup:paper":
        return _start_paper(chat_id)
    if data == "setup:live":
        return _start_live_setup(chat_id)
    if data == "groq:skip":
        _wizard.pop(str(chat_id), None)
        return _ready(chat_id)
    if data == "c:chart":
        sym = s["SYMBOL"]
        url = f"{cfg.SITE_URL}/chart?s={sym}"
        return send_to(chat_id, f"📈 <b>{sym}</b> — live chart",
                       {"reply_markup": json.dumps({"inline_keyboard": [[
                           {"text": f"📈 Open {sym} chart", "web_app": {"url": url}}]]})})
    if data.startswith("sym:"):
        sym = data[4:]
        _upd(chat_id, "SYMBOL", sym)
        user_loop.reset_risk(chat_id)
        return send_to(chat_id, f"💎 Symbol → <b>{sym}</b>", _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if data.startswith("m:"):
        method = data[2:]
        _upd(chat_id, "STRATEGY_MODE", method)
        desc = METHOD_DESC.get(method, "")
        return send_to(chat_id, f"🎯 Strategy set → {desc or f'<b>{method}</b>'}",
                       _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if data == "c:status":
        return send_to(chat_id, _build_status(chat_id), _kb_menu(s.get("PAUSED", False), s["SYMBOL"]))
    if data == "c:config":
        return send_to(chat_id, _build_config(chat_id))
    if data == "c:trades":
        return send_to(chat_id, _build_trades(chat_id))
    if data == "c:symbol":
        return send_to(chat_id, f"💎 Choose trading pair:\nCurrent: <b>{s['SYMBOL']}</b>", _kb_symbols())
    if data == "c:method":
        guide = "\n".join(METHOD_DESC[m] for m in METHODS)
        return send_to(chat_id,
                       f"🎯 <b>Choose your strategy</b>\nCurrent: <b>{s['STRATEGY_MODE']}</b>\n"
                       f"━━━━━━━━━━━━━━━━━━━━\n{guide}",
                       _kb_methods())
    if data == "c:help":
        return send_to(chat_id, _HELP)
    if data == "c:pause":
        _upd(chat_id, "PAUSED", True)
        u = user_loop._ensure_user(chat_id)
        return send_to(chat_id,
                       f"⏸ <b>Bot paused.</b>\n"
                       f"Symbol: <b>{u['settings']['SYMBOL']}</b> — tap ▶️ Start to resume.",
                       _kb_menu(True))
    if data == "c:resume":
        _upd(chat_id, "PAUSED", False)
        user_loop.reset_risk(chat_id)
        _ensure_running(chat_id)
        u = user_loop._ensure_user(chat_id)
        sym = u["settings"]["SYMBOL"]
        mode = u["settings"]["STRATEGY_MODE"]
        return send_to(chat_id,
                       f"▶️ <b>Bot ACTIVE</b> — scanning <b>{sym}</b> every 60s.\n"
                       f"Strategy: <b>{mode}</b> · You'll get a ping every 30 min + all trade alerts.",
                       _kb_menu(False, sym))


# ─── Poll loop ────────────────────────────────────────────
def _activate(chat_id):
    """Step 1: brand new user — show welcome + risk disclaimer (must accept)."""
    access.grant(str(chat_id))
    send_to(chat_id,
            "👋 <b>Welcome to APEX TRADE BOT!</b>\n\n"
            "Your AI-powered crypto trading bot is ready.\n"
            "Tap below to activate and set it up in 2 minutes.",
            _kb_activate())
    _broadcast_owner(f"🆕 <b>New client!</b>\nID: <code>{chat_id}</code>")


_DISCLAIMER = (
    "⚠️ <b>Risk Disclaimer — please read</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "APEX TRADE BOT is a <b>trading tool</b>. <b>You</b> choose the symbol, "
    "strategy, risk and settings — and <b>you</b> control when it trades.\n\n"
    "• Crypto trading carries risk. You can lose money.\n"
    "• This is NOT financial advice and NOT a profit guarantee.\n"
    "• Past or simulated results don't predict future results.\n"
    "• <b>You are solely responsible</b> for your own trades, settings and funds.\n"
    "• Only trade with money you can afford to lose.\n\n"
    "By tapping <b>I Understand &amp; Accept</b> you agree you use this tool at "
    "your own risk and the seller is not liable for any losses."
)


def _show_disclaimer(chat_id):
    """Mandatory risk disclaimer — must accept before any setup (legal shield)."""
    send_to(chat_id, _DISCLAIMER,
            {"reply_markup": json.dumps({"inline_keyboard": [
                [{"text": "✅ I Understand & Accept", "callback_data": "setup:accept"}],
            ]})})


def _show_mode_choice(chat_id):
    """Step 2: choose Paper or Real."""
    send_to(chat_id,
            "⚙️ <b>How do you want to trade?</b>\n\n"
            "🧪 <b>Paper Trading</b> — trade with FREE virtual USDT on Binance Testnet.\n"
            "Real market prices, real orders, zero risk. You'll need a free testnet account.\n\n"
            "🔴 <b>Real Binance</b> — connect your real Binance account and trade with real funds.\n\n"
            "<i>You can switch any time with /setup.</i>",
            _kb_mode())


def _start_paper(chat_id):
    """Paper trading = Binance Testnet with free virtual USDT."""
    _wizard[str(chat_id)] = "KEYS"
    u = user_loop._ensure_user(chat_id)
    u["paper"] = True
    u["setup_done"] = True
    u["settings"]["PAUSED"] = True
    user_store.save(chat_id, u)
    send_to(chat_id,
            "🧪 <b>Paper Trading — Binance Testnet</b>\n\n"
            "You'll get <b>FREE virtual USDT</b> to trade with. Real market prices, zero risk.\n\n"
            "1️⃣ Tap <b>Open Binance Testnet</b> below\n"
            "2️⃣ Register (GitHub login) — takes 30 seconds\n"
            "3️⃣ Go to <b>API Management</b> → create API key (enable Spot trading)\n"
            "4️⃣ Send your keys here in ONE message:\n"
            "<code>API_KEY=your_key API_SECRET=your_secret</code>\n\n"
            "🔒 <i>Message deleted instantly after reading.</i>",
            {"reply_markup": json.dumps({"inline_keyboard": [
                [{"text": "🧪 Open Binance Testnet", "url": "https://testnet.binance.vision"}],
            ]})})


def _start_live_setup(chat_id):
    """Real trading = real Binance account."""
    _wizard[str(chat_id)] = "KEYS"
    u = user_loop._ensure_user(chat_id)
    u["paper"] = False
    user_store.save(chat_id, u)
    send_to(chat_id,
            "🔴 <b>Connect your real Binance account</b>\n\n"
            "1️⃣ Tap <b>Open Binance API Settings</b> below\n"
            "2️⃣ Create an API key — enable <b>Spot &amp; Margin Trading</b>\n"
            "3️⃣ Send both keys here in ONE message:\n"
            "<code>API_KEY=your_key API_SECRET=your_secret</code>\n\n"
            "🔒 <i>Message deleted instantly after reading.</i>",
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
    is_testnet = u.get("paper", True)

    # Validate the keys against Binance BEFORE saving — fail fast with a clear reason.
    send_to(chat_id, "🔍 Verifying your Binance keys…")
    try:
        ex = binance.LiveExchange(pairs["API_KEY"], pairs["API_SECRET"], testnet=is_testnet)
        ok, why, usdt = ex.verify()
    except Exception as e:
        ok, why, usdt = False, str(e), 0.0
    if not ok:
        return send_to(chat_id,
                       f"❌ <b>Connection failed:</b> {why}\n\n"
                       "Fix the API key and send both again:\n"
                       "<code>API_KEY=xxx API_SECRET=yyy</code>")

    u["setup_done"] = True
    u["api_key"] = pairs["API_KEY"]
    u["api_secret"] = pairs["API_SECRET"]
    u["settings"]["PAUSED"] = True
    user_store.save(chat_id, u)
    mode_label = "🧪 Binance Testnet (virtual USDT)" if is_testnet else "🔴 Real Binance (live funds)"
    send_to(chat_id,
            f"✅ <b>Binance connected &amp; verified!</b>\n"
            f"Mode: <b>{mode_label}</b>\n"
            f"💰 Balance: <b>${usdt:.2f} USDT</b>")
    _ask_groq(chat_id)


def _ask_groq(chat_id):
    """Onboarding step 3: collect the client's free Groq key (or skip)."""
    u = user_loop._ensure_user(chat_id)
    if u.get("groq_key"):
        return _ready(chat_id)
    _wizard[str(chat_id)] = "GROQ"
    send_to(chat_id,
            "🧠 <b>Set up your free AI key</b>\n\n"
            "The bot's brain runs on <b>Groq</b> (free, ~14,400 signals/day, your own personal quota).\n\n"
            "1️⃣ Tap <b>Get free Groq key</b> → create free account\n"
            "2️⃣ Copy your key (starts with <code>gsk_</code>)\n"
            "3️⃣ Send it here in this chat\n\n"
            "Or tap <b>Skip</b> to use the shared AI (limited quota).",
            {"reply_markup": json.dumps({"inline_keyboard": [
                [{"text": "🔑 Get free Groq key", "url": "https://console.groq.com/keys"}],
                [{"text": "⚡ Skip — use shared AI", "callback_data": "groq:skip"}],
            ]})})


def _finish_groq(chat_id, key, msg_id):
    _delete_message(chat_id, msg_id)
    key = key.strip()
    send_to(chat_id, "🔍 Testing your Groq key…")
    ok, why = ai.test_key(key)
    if not ok:
        return send_to(chat_id,
                       f"❌ <b>Key not working:</b> {why}\n\n"
                       "Send a valid key (<code>gsk_...</code>) or skip.",
                       {"reply_markup": json.dumps({"inline_keyboard": [
                           [{"text": "🔑 Get free Groq key", "url": "https://console.groq.com/keys"}],
                           [{"text": "⚡ Skip — use shared AI", "callback_data": "groq:skip"}],
                       ]})})
    user_store.update(chat_id, {"groq_key": key})
    _wizard.pop(str(chat_id), None)
    send_to(chat_id, "✅ <b>Groq key verified &amp; saved!</b> Your bot now runs on YOUR own AI quota. 🧠")
    _ready(chat_id)


def _ready(chat_id):
    """Setup complete — AUTO-START the bot and show the control panel."""
    u = user_loop._ensure_user(chat_id)
    # Auto-start: don't make the user press Start after onboarding.
    u["settings"]["PAUSED"] = False
    user_store.save(chat_id, u)
    _ensure_running(chat_id)
    s = u["settings"]
    ai_info = "your Groq key ✅" if u.get("groq_key") else "shared AI (add /groq key for better signals)"
    # Message 1: confirmation that bot is live
    send_to(chat_id,
            f"⚡ <b>Bot is LIVE and trading!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Mode: <b>{'📝 PAPER ($100 virtual)' if u.get('paper', True) else '🔴 REAL Binance'}</b>\n"
            f"Symbol: <b>{s['SYMBOL']}</b>   Strategy: <b>{s['STRATEGY_MODE']}</b>\n"
            f"AI: <b>{ai_info}</b>\n\n"
            "Scanning markets every 60s. You'll get an alert on every trade.\n"
            "Use the buttons below to control the bot any time.")
    # Message 2: control panel (separate so buttons are always visible)
    send_to(chat_id, "🎛 <b>Control Panel</b>", _kb_menu(False, s["SYMBOL"]))


def _auto_restore(chat_id):
    """Silently restart a user's trading thread after a server restart.

    On Render free tier the container is wiped on every deploy, so
    user files (and the 'active' flag) are gone after a redeploy.
    Any interaction from a setup-and-unpaused user should bring their
    thread back without requiring them to press ▶️ Start Trading again.
    """
    if user_loop.is_running(chat_id):
        return
    u = user_loop._ensure_user(chat_id)
    if u.get("setup_done") and not u["settings"].get("PAUSED", True):
        user_loop.start(chat_id, make_alert(chat_id))
        print(f"[TG] Auto-restored thread for user {chat_id}")


def _poll_loop():
    global _update_id
    try:
        requests.post(f"{_API}/deleteWebhook", json={"drop_pending_updates": False}, timeout=5)
    except Exception:
        pass
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
                    _auto_restore(chat_id)
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
                _auto_restore(chat_id)
                # Real-account setup: capture the API key message (not a command)
                step = _wizard.get(str(chat_id))
                if step == "KEYS" and not text.startswith("/"):
                    try:
                        _finish_live_setup(chat_id, text, msg_id)
                    except Exception as e:
                        print(f"[TG] keys error: {e}")
                    continue
                if step == "GROQ" and text.startswith("gsk_"):
                    try:
                        _finish_groq(chat_id, text.split()[0], msg_id)
                    except Exception as e:
                        print(f"[TG] groq error: {e}")
                    continue
                # Free text (non-command) → AI assistant
                if not text.startswith("/"):
                    _send_typing(chat_id)
                    assistant.chat(
                        chat_id, text,
                        send_fn=lambda reply, cid=chat_id: send_to(cid, reply),
                        send_status=lambda status, cid=chat_id: send_to(cid, status),
                    )
                    continue
                try:
                    _handle_command(chat_id, text, msg_id)
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
