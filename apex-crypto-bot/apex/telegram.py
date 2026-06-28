"""Telegram multi-tenant handler — crypto edition.

One bot token serves all paying clients. Keyless instant activation: the
purchase email / thank-you page hands out a t.me deep link, so anyone who
reaches the bot is a paying customer → granted on contact. Owner is set via
ADMIN_CHAT_ID. Polling runs in a background daemon thread.
"""
import json
import re
import time
import threading
import requests
from apex import config as cfg
from apex import access, user_store, user_loop, binance, ai, assistant, dca, grid

TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
_API = f"https://api.telegram.org/bot{TOKEN}"
_update_id = 0
_wizard = {}        # chat_id → step (e.g. "KEYS") for the real-account setup flow
_pending_key = {}   # chat_id → raw key waiting for provider confirmation

SYMBOLS = [
    [("₿ BTC", "BTCUSDT"), ("⟠ ETH", "ETHUSDT"), ("◎ SOL", "SOLUSDT")],
    [("✕ XRP", "XRPUSDT"), ("Ð DOGE", "DOGEUSDT"), ("△ ADA", "ADAUSDT")],
    [("⬡ BNB", "BNBUSDT"), ("☀ AVAX", "AVAXUSDT"), ("🔗 LINK", "LINKUSDT")],
    [("◆ TON", "TONUSDT"), ("🐕 SHIB", "SHIBUSDT"), ("🐸 PEPE", "PEPEUSDT")],
    [("Ξ MATIC", "MATICUSDT"), ("🦄 UNI", "UNIUSDT"), ("⬢ DOT", "DOTUSDT")],
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


# ── Pattern-based trade intent detection ─────────────────────────────────────
# Catches explicit trade commands in any language BEFORE hitting the AI quota.
# Trade execution should never depend on AI availability.

_RE_AMOUNT = re.compile(
    r"(?:cu\s+|with\s+|de\s+|pentru\s+|)(\d+(?:[.,]\d+)?)\s*(?:\$|usd|usdt|dolari?|bucks?)?",
    re.IGNORECASE,
)
_RE_BUY = re.compile(
    r"\b(intr[aă]|intr[aă]-?[oO]|cumpăr[aă]?|cumpara|buy|long|intru)\b",
    re.IGNORECASE,
)
_RE_SELL = re.compile(
    r"\b(vinde|vânz[iă]|short|sell)\b",
    re.IGNORECASE,
)
_RE_CLOSE = re.compile(
    r"\b(inchide|închide|close|exit|iesi|ieși|stop.?poziti|sell.?all)\b",
    re.IGNORECASE,
)
_RE_ALL_IN = re.compile(
    r"\ball.?in\b|toat[aă]\s+suma|tot\s+balant|full\s+balance",
    re.IGNORECASE,
)
_RE_CLOSE_MATH = re.compile(
    r"(inchide|close|iesi|exit|dac[aă]).{0,30}(cât|cat|cati|câți|rămâne|ramane|profit|lose|pierd)",
    re.IGNORECASE,
)


def _handle_trade_intent(chat_id, text) -> bool:
    """Return True if the message was a trade command handled directly (no AI needed)."""
    t = text.strip()

    # "if I close now, how much would I have?" → calculate from live price
    if _RE_CLOSE_MATH.search(t):
        u = user_loop._ensure_user(str(chat_id))
        pos = u["state"].get("openPosition")
        if not pos:
            send_to(chat_id, "📭 No open position right now.")
            return True
        sym = pos["symbol"]
        ex = u.get("exchange", "binance")
        price = binance.get_price(sym, exchange=ex) or pos["entryPrice"]
        entry, qty, side = pos["entryPrice"], pos["quantity"], pos["side"]
        pnl = (price - entry) * qty if side == "BUY" else (entry - price) * qty
        _fee_map = {"binance": 0.001, "binanceus": 0.001, "coinbase": 0.006,
                    "kraken": 0.0026, "bybit": 0.001, "okx": 0.001}
        fee_rate = _fee_map.get((u.get("exchange") or "binance").lower(), 0.001)
        fee = price * qty * fee_rate
        net = pnl - fee
        bal = u["state"].get("paperBalance", 0) + net
        sign = "+" if net >= 0 else ""
        send_to(chat_id,
                f"📊 <b>Dacă închizi acum:</b>\n"
                f"Preț curent: <b>${price:.4f}</b>\n"
                f"P&amp;L brut: <b>{sign}${pnl:.2f}</b>\n"
                f"Taxă: <b>−${fee:.2f}</b>\n"
                f"Net: <b>{sign}${net:.2f}</b>\n"
                f"Balanță după: <b>${bal:.2f}</b>\n\n"
                f"<i>Folosește</i> <code>/close</code> <i>pentru a închide efectiv.</i>")
        return True

    # Close intent
    if _RE_CLOSE.search(t) and not _RE_BUY.search(t):
        u = user_loop._ensure_user(str(chat_id))
        if not u["state"].get("openPosition"):
            send_to(chat_id, "📭 No open position to close.")
            return True
        _handle_command(chat_id, "/close")
        return True

    # All-in intent
    if _RE_ALL_IN.search(t):
        u = user_loop._ensure_user(str(chat_id))
        bal = u["state"].get("paperBalance", 0)
        sym = u["settings"].get("SYMBOL", "BTCUSDT")
        price = binance.get_price(sym, exchange=u.get("exchange", "binance")) or 1
        amount = round(bal * 0.98, 2)  # leave 2% for fees
        send_to(chat_id, f"⚡ <b>ALL IN</b> — entering BUY {sym} with <b>${amount:.2f}</b>…")
        result = user_loop.force_trade(str(chat_id), "BUY", sym, amount_usd=amount)
        _send_trade_result(chat_id, result, sym)
        return True

    # BUY intent (with or without amount)
    if _RE_BUY.search(t):
        u = user_loop._ensure_user(str(chat_id))
        sym = u["settings"].get("SYMBOL", "BTCUSDT")
        # Extract symbol if mentioned (e.g. "intra in BTC", "buy ETH")
        sym_match = re.search(r"\b([A-Z]{2,5})USDT?\b|\b(BTC|ETH|SOL|BNB|ADA|DOT|AVAX|MATIC|LINK|XRP)\b",
                               t.upper())
        if sym_match:
            raw_sym = (sym_match.group(1) or sym_match.group(2) or "").upper()
            sym = raw_sym + ("USDT" if not raw_sym.endswith("USDT") else "")
        # Extract amount
        amt_match = _RE_AMOUNT.search(t)
        amount_usd = float(amt_match.group(1).replace(",", ".")) if amt_match else None
        if amount_usd:
            send_to(chat_id, f"⚡ BUY <b>{sym}</b> cu <b>${amount_usd:.0f}</b>…")
        else:
            send_to(chat_id, f"⚡ BUY <b>{sym}</b>…")
        result = user_loop.force_trade(str(chat_id), "BUY", sym, amount_usd=amount_usd)
        _send_trade_result(chat_id, result, sym)
        return True

    # SELL/SHORT intent
    if _RE_SELL.search(t):
        u = user_loop._ensure_user(str(chat_id))
        sym = u["settings"].get("SYMBOL", "BTCUSDT")
        amt_match = _RE_AMOUNT.search(t)
        amount_usd = float(amt_match.group(1).replace(",", ".")) if amt_match else None
        send_to(chat_id, f"⚡ SELL <b>{sym}</b>…")
        result = user_loop.force_trade(str(chat_id), "SELL", sym, amount_usd=amount_usd)
        _send_trade_result(chat_id, result, sym)
        return True

    return False


def _send_trade_result(chat_id, result, sym):
    if result.get("ok"):
        pos = result
        send_to(chat_id,
                f"✅ <b>{result['side']} {sym}</b> deschis\n"
                f"Preț: <b>${result['price']:.4f}</b>\n"
                f"Sumă: <b>${result.get('amountUsd', '—')}</b>  Qty: {result.get('quantity', '—')}\n"
                f"SL: ${result['stopLoss']:.4f} | TP: ${result['takeProfit']:.4f}\n"
                f"<i>Închide cu</i> <code>/close</code>")
    else:
        err = result.get("error", "unknown error")
        send_to(chat_id, f"❌ Nu am putut deschide tranzacția: <i>{err}</i>")


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
        [{"text": "🔄 Paper / Real", "callback_data": "c:mode"}, {"text": "📈 Live Chart", "callback_data": "c:chart"}],
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
_BINANCEUS_KEYS_URL = "https://www.binance.us/usercenter/settings/api-management"
# Your Binance referral link — new clients who don't have an account yet open
# this to sign up (and you earn the referral commission). Code: CPA_00IH1SQY0U
_BINANCE_SIGNUP_URL = "https://www.binance.com/activity/referral-entry/CPA?ref=CPA_00IH1SQY0U"
_BINANCE_REF_CODE = "CPA_00IH1SQY0U"


def _kb_binance():
    return {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "🔑 Open Binance API page", "url": _BINANCE_KEYS_URL}],
    ]})}


def _kb_symbols():
    rows = [[{"text": label, "callback_data": f"sym:{sym}"} for label, sym in row] for row in SYMBOLS]
    # Make it explicit that ANY of the 600+ Binance pairs works, not just these.
    rows.append([{"text": "✏️ Type any other coin…", "callback_data": "sym:custom"}])
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
    dca_deal = st.get("dca_deal")
    if dca_deal:
        price = binance.get_price(dca_deal["symbol"])
        pos_line = dca.deal_summary(dca_deal, price or dca_deal["avg_entry"])
    elif pos:
        d = "🟢 LONG" if pos["side"] == "BUY" else "🔴 SHORT"
        p = pos.get("currentPnl", 0)
        pos_line = (f"{d} <b>{pos['symbol']}</b>\n  Entry: ${pos['entryPrice']:.4f}  "
                    f"PnL: <b>{'+' if p >= 0 else ''}${p:.4f}</b>")
    else:
        pos_line = "📭 No open position"
    dca_flag = "  🤖 DCA" if s.get("dca_enabled") else ""
    sig = st.get("lastSignal")
    sig_line = (f"🤖 Signal: <b>{sig['action']}</b> ({sig['confidence']:.0f}%)" if sig else "🤖 Signal: scanning…")
    return (f"⚡ <b>APEX TRADE BOT</b>  {'PAPER' if u.get('paper', True) else 'LIVE'}{dca_flag}\n"
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


def _build_report(user_id):
    st = user_loop._ensure_user(user_id)["state"]
    lst = st.get("trades", [])
    if not lst:
        return ("📒 <b>No closed trades yet.</b>\n"
                "Your tax journal fills up as the bot closes positions.")
    net = sum(t.get("pnl", 0) or 0 for t in lst)
    gross = sum(t.get("grossPnl", t.get("pnl", 0)) or 0 for t in lst)
    fees = sum(t.get("feeUsd", 0) or 0 for t in lst)
    wins = sum(1 for t in lst if t.get("win"))
    n = len(lst)
    wr = wins / n * 100 if n else 0
    rows = [f"{'✅' if t.get('win') else '❌'} {t.get('side')} <b>{t.get('symbol')}</b> "
            f"${t.get('entry')}→${t.get('exit')} <b>{'+' if t.get('pnl',0) >= 0 else ''}${t.get('pnl')}</b> "
            f"<i>{(t.get('time') or '')[:16]}</i>" for t in lst[:10]]
    return (f"📒 <b>Trade Journal &amp; Tax Report</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Closed trades: <b>{n}</b>   Win rate: <b>{wr:.0f}%</b>\n"
            f"Gross P&amp;L: <b>${gross:.2f}</b>\n"
            f"Fees (maker/taker): <b>−${fees:.2f}</b>\n"
            f"<b>NET P&amp;L: {'+' if net >= 0 else ''}${net:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Last {min(10, n)} trades:</b>\n" + "\n".join(rows) + "\n"
            f"<i>Each trade is logged with entry, exit, fees and net P&amp;L for taxes.</i>")


_HELP = ("📋 <b>APEX TRADE BOT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
         "Your AI bot trades crypto automatically. Just set it and watch.\n\n"
         "<b>Controls:</b>\n/menu · /status · /signal · /config · /trades · /report\n\n"
         "<b>Settings (you choose everything):</b>\n"
         "/symbol BTCUSDT — <b>ANY</b> of 600+ Binance pairs (PEPEUSDT, WIFUSDT, …)\n"
         "/method auto|turtle|livermore|soros|ptj|druckenmiller\n"
         "/risk 5 — % per trade\n/sl 1.6 — stop loss %\n/tp 3.2 — take profit %\n/confidence 70 — min AI confidence\n\n"
         "<b>🔄 Switch Paper ↔ Real:</b>\n/pause first, then /setup → pick the mode. "
         "Paper and real are fully separate.\n\n"
         "<b>🤖 DCA Bot (3Commas-style):</b>\n"
         "/dca — show DCA status &amp; settings\n"
         "/dca on · /dca off — enable/disable\n"
         "/dca base 5 — base order % · /dca safety 3 — safety order %\n"
         "/dca step 2.5 — % drop per safety · /dca tp 2 — take profit %\n"
         "/dca max 3 — max safety orders\n\n"
         "<b>📊 Grid Bot (passive income):</b>\n"
         "/grid — show grid status &amp; settings\n"
         "/grid on · /grid off — enable/disable\n"
         "/grid lower 95000 · /grid upper 105000 — set price range\n"
         "/grid levels 10 — number of grid lines · /grid step 2 — order size %\n"
         "/grid stop — cancel active grid\n\n"
         "<b>Manual trading:</b>\n/buy XRPUSDT — open LONG\n/sell ETHUSDT — open SHORT\n/close — close open position\n\n"
         "<b>Run:</b>\n/pause · /resume\n\n"
         "<b>Account:</b>\n/setup — switch paper ↔ real, re-run onboarding\n\n"
         "<b>💬 Smart assistant:</b>\nJust talk to me! \"analyze BTC\", \"buy ETH\", \"close position\"\n"
         "/ai — connect your own FREE AI key (Gemini / Groq / Claude) for unlimited chat\n"
         "/gemini AIza-KEY — FREE chat + analysis, 1500/day (aistudio.google.com)\n"
         "/groq gsk_KEY — free fast chat (console.groq.com)\n"
         "/claude sk-ant-KEY — full chat + trade execution (console.anthropic.com)")


# ─── Alerts (per-user callback) ───────────────────────────
def _why_block(data) -> str:
    """Human-readable 'why I took this trade' block for open alerts."""
    parts = []
    conf = data.get("confidence")
    if conf is not None:
        parts.append(f"🎯 Confidence: {conf:.0f}%")
    reasoning = (data.get("reasoning") or "").strip()
    if reasoning:
        parts.append(f"🧠 <i>{reasoning}</i>")
    factors = data.get("keyFactors") or []
    if factors:
        parts.append("📊 " + " · ".join(str(f) for f in factors[:4]))
    return ("\n" + "\n".join(parts)) if parts else ""


def _close_why(reason: str) -> str:
    """Plain-language explanation for a mechanical (non-AI) close."""
    m = {
        "TAKE_PROFIT": "Target reached — locking in the profit.",
        "STOP_LOSS": "Stop hit — cutting the loss to protect capital.",
        "MANUAL_CLOSE": "Closed manually at your request.",
        "AI_CLOSE": "The AI judged the setup had played out.",
    }
    txt = m.get(reason, "")
    return f"\n🧠 <i>{txt}</i>" if txt else ""


def make_alert(chat_id):
    def alert(kind, data):
        if kind == "open":
            d = "🟢 LONG" if data["side"] == "BUY" else "🔴 SHORT"
            mult = f"\n📐 Druckenmiller: ×{data['druckMult']:.2f}" if data.get("druckMult", 1) != 1 else ""
            send_to(chat_id, f"{d} <b>OPENED — {data['symbol']}</b>\n"
                             f"💰 Entry: ${data['price']:.4f}  Qty: {data['qty']}\n"
                             f"🛡 SL: ${data['stopLoss']:.4f}  🎯 TP: ${data['takeProfit']:.4f}{mult}"
                             + _why_block(data))
        elif kind == "close":
            icons = {"TAKE_PROFIT": "🎯 TAKE PROFIT", "STOP_LOSS": "🛑 STOP LOSS", "AI_CLOSE": "🤖 AI CLOSE"}
            why = (f"\n🧠 <i>{data['reasoning']}</i>" if data.get("reasoning")
                   else _close_why(data.get("reason", "")))
            send_to(chat_id, f"{'✅' if data['pnl'] > 0 else '❌'} <b>{icons.get(data['reason'], data['reason'])} — {data['symbol']}</b>\n"
                             f"${data['entryPrice']:.4f} → ${data['exitPrice']:.4f}\n"
                             f"PnL: <b>{'+' if data['pnl'] >= 0 else ''}${data['pnl']:.4f}</b>  💼 ${data['balance']:.2f}"
                             + why)
        elif kind == "skip_warn":
            send_to(chat_id,
                    f"⚠️ <b>Holding off on {data['symbol']}</b>\n"
                    f"<i>A {data['wanted']} setup appeared, but the {data['trend'].lower()} structure is "
                    f"strong ({data['strength']}%) — trading against it is low-probability.</i>\n"
                    "I'll act when the trend and signal line up.")
        elif kind == "suggest":
            d = "🟢 BUY" if data["side"] == "BUY" else "🔴 SELL"
            kb = {"reply_markup": json.dumps({"inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": "cp:y"},
                {"text": "❌ Reject", "callback_data": "cp:n"}]]})}
            send_to(chat_id,
                    f"🤖 <b>Copilot suggestion</b>\n{d} <b>{data['symbol']}</b> @ ${data['price']:.4f}"
                    + _why_block(data) +
                    "\n\n<i>You're in copilot mode — approve to execute, or reject to skip.</i>",
                    kb)
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
                send_to(chat_id,
                        "⏳ <b>Groq daily limit reached.</b> The bot keeps trading on its "
                        "rule-based engine (Turtle + Livermore + Soros) — no action needed.\n\n"
                        "💡 <b>Want unlimited AI chat?</b> Add a free Gemini key — 1,500/day, "
                        "no per-minute limits:\n"
                        "1. aistudio.google.com → <i>Get API key</i>\n"
                        "2. Send <code>/gemini YOUR_KEY</code> here\n\n"
                        "<i>(You'll only see this message once every ~30 min.)</i>")
            else:
                send_to(chat_id, "⚠️ <b>Groq key invalid.</b> Get a new free key at console.groq.com → API Keys, "
                                 "then send /groq gsk_NEW_KEY")
        elif kind == "auto_symbol":
            icon = "🟢" if data["action"] == "BUY" else "🔴"
            send_to(chat_id,
                    f"🔍 <b>Best setup found: {data['symbol']}</b>\n"
                    f"{icon} Signal: <b>{data['action']}</b>  Confidence: {data['confidence']:.0f}%\n"
                    f"<i>{data.get('reasoning', '')}</i>")
        elif kind == "grid_start":
            send_to(chat_id,
                    f"📊 <b>Grid Bot started — {data['symbol']}</b>\n"
                    f"Range: ${data['lower']:.4f} – ${data['upper']:.4f}  ({data['levels']} levels)\n"
                    f"Grid step: ${data['step']:.4f}  Profit per round-trip: ~${data['step']:.4f}/unit")
        elif kind == "grid_fill":
            sign = "+" if data["pnl"] >= 0 else ""
            send_to(chat_id,
                    f"💹 <b>Grid {data['type']}</b> — {data['symbol']} @ ${data['price']:.4f}\n"
                    f"Trip #{data['round_trips']}  Profit: <b>{sign}${data['pnl']:.4f}</b>  "
                    f"Total: ${data['total_pnl']:.4f}")
        elif kind == "grid_out_of_range":
            sign = "+" if data["total_pnl"] >= 0 else ""
            send_to(chat_id,
                    f"⚠️ <b>Grid stopped — price left range</b>\n"
                    f"{data['symbol']} @ ${data['price']:.4f}  "
                    f"(range was ${data['lower']:.4f}–${data['upper']:.4f})\n"
                    f"Total P&L: <b>{sign}${data['total_pnl']:.4f}</b>  "
                    f"Round-trips: {data['round_trips']}\n"
                    f"/grid on — restart with new auto-range")
        elif kind == "dca_open":
            side_icon = "🟢 LONG" if data["side"] == "BUY" else "🔴 SHORT"
            safety_prices = "  |  ".join(f"${p:.2f}" for p in data["safety_orders"])
            send_to(chat_id,
                    f"🤖 <b>DCA Deal opened</b> — {side_icon} <b>{data['symbol']}</b>\n"
                    f"Base entry: ${data['base_price']:.4f}  Qty: {data['base_qty']}\n"
                    f"Take profit: ${data['take_profit_price']:.4f}  (+{data['tp_pct']:.1f}%)\n"
                    f"Safety levels: {safety_prices}\n"
                    + (f"Stop loss: ${data['stop_loss_price']:.4f}" if data.get("stop_loss_price") else ""))
        elif kind == "dca_safety":
            sign = "+" if data["pnl_pct"] >= 0 else ""
            send_to(chat_id,
                    f"🔄 <b>DCA Safety #{data['index']}</b> triggered — <b>{data['symbol']}</b>\n"
                    f"Filled @ ${data['price']:.4f}  New avg: ${data['avg_entry']:.4f}\n"
                    f"New TP: ${data['take_profit_price']:.4f}  "
                    f"Safety: {data['safety_filled']}/{data['max_safety']}\n"
                    f"PnL so far: {sign}{data['pnl_pct']:.2f}%")
        elif kind == "dca_close":
            sign = "+" if data["pnl"] >= 0 else ""
            icon = {"TAKE_PROFIT": "✅", "STOP_LOSS": "🛑"}.get(data["reason"], "🔵")
            send_to(chat_id,
                    f"{icon} <b>DCA Deal closed — {data['symbol']}</b>\n"
                    f"Avg entry: ${data['avg_entry']:.4f} → Exit: ${data['exit_price']:.4f}\n"
                    f"Safety fills: {data['safety_filled']}  "
                    f"PnL: <b>{sign}${data['pnl']:.4f} ({sign}{data['pnl_pct']:.2f}%)</b>\n"
                    f"Balance: ${data['balance']:.2f}")
        elif kind == "error":
            sym = data.get("symbol", "")
            send_to(chat_id,
                    f"⚠️ <b>Order not placed{f' — {sym}' if sym else ''}</b>\n"
                    f"{data.get('message', 'unknown error')}")
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
    if cmd == "/report":
        return send_to(chat_id, _build_report(chat_id))
    if cmd == "/help":
        return send_to(chat_id, _HELP)
    if cmd == "/symbol":
        if not args:
            return send_to(chat_id,
                           f"💎 <b>Choose trading pair:</b>\nCurrent: <b>{s['SYMBOL']}</b>\n\n"
                           f"💡 <i>Tap a coin below, or type <code>/symbol PEPEUSDT</code> — "
                           f"<b>ANY</b> Binance pair works (600+ coins).</i>", _kb_symbols())
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
    if cmd == "/dca":
        u = user_loop._ensure_user(chat_id)
        s2 = u["settings"]
        if args and args[0] == "on":
            _upd(chat_id, "dca_enabled", True)
            return send_to(chat_id,
                           "🤖 <b>DCA Bot ENABLED</b>\n"
                           "Instead of single orders, the bot will open DCA deals with safety orders.\n\n"
                           f"Settings:\n"
                           f"• Base order: <b>{s2.get('dca_base_order_pct', 5):g}%</b> of balance\n"
                           f"• Safety order: <b>{s2.get('dca_safety_order_pct', 3):g}%</b> (×{s2.get('dca_safety_scale', 1.5):g} each)\n"
                           f"• Max safeties: <b>{s2.get('dca_max_safety_orders', 3)}</b>  Step: <b>{s2.get('dca_safety_step_pct', 2.5):g}%</b>\n"
                           f"• Take profit: <b>{s2.get('dca_take_profit_pct', 2):g}%</b> from avg entry\n\n"
                           "<i>Adjust: /dca base 5 · /dca safety 3 · /dca step 2.5 · /dca tp 2 · /dca max 3</i>")
        if args and args[0] == "off":
            _upd(chat_id, "dca_enabled", False)
            return send_to(chat_id, "⏹ <b>DCA Bot disabled.</b> Back to single-order strategy mode.")
        if args and args[0] == "base":
            try:
                v = float(args[1]); assert 1 <= v <= 50
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /dca base 5  (1–50%)")
            _upd(chat_id, "dca_base_order_pct", v)
            return send_to(chat_id, f"✅ DCA base order → <b>{v:g}%</b> of balance")
        if args and args[0] == "safety":
            try:
                v = float(args[1]); assert 1 <= v <= 50
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /dca safety 3  (1–50%)")
            _upd(chat_id, "dca_safety_order_pct", v)
            return send_to(chat_id, f"✅ DCA safety order → <b>{v:g}%</b> of balance")
        if args and args[0] == "step":
            try:
                v = float(args[1]); assert 0.5 <= v <= 20
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /dca step 2.5  (0.5–20%)")
            _upd(chat_id, "dca_safety_step_pct", v)
            return send_to(chat_id, f"✅ DCA safety step → <b>{v:g}%</b> per level")
        if args and args[0] == "tp":
            try:
                v = float(args[1]); assert 0.3 <= v <= 20
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /dca tp 2  (0.3–20%)")
            _upd(chat_id, "dca_take_profit_pct", v)
            return send_to(chat_id, f"✅ DCA take profit → <b>{v:g}%</b> from avg entry")
        if args and args[0] == "max":
            try:
                v = int(args[1]); assert 1 <= v <= 8
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /dca max 3  (1–8 orders)")
            _upd(chat_id, "dca_max_safety_orders", v)
            return send_to(chat_id, f"✅ DCA max safety orders → <b>{v}</b>")
        # Show current DCA status
        enabled = s2.get("dca_enabled", False)
        deal = u.get("state", {}).get("dca_deal")
        deal_line = ""
        if deal:
            price = binance.get_price(deal["symbol"])
            deal_line = f"\n\n<b>Active deal:</b>\n{dca.deal_summary(deal, price)}" if price else ""
        return send_to(chat_id,
                       f"🤖 <b>DCA Bot</b> — {'✅ ON' if enabled else '⏹ OFF'}\n"
                       f"━━━━━━━━━━━━━━━━━━━━\n"
                       f"Base order: <b>{s2.get('dca_base_order_pct', 5):g}%</b>  "
                       f"Safety: <b>{s2.get('dca_safety_order_pct', 3):g}%</b> ×{s2.get('dca_safety_scale', 1.5):g}\n"
                       f"Max orders: <b>{s2.get('dca_max_safety_orders', 3)}</b>  "
                       f"Step: <b>{s2.get('dca_safety_step_pct', 2.5):g}%</b>\n"
                       f"Take profit: <b>{s2.get('dca_take_profit_pct', 2):g}%</b>  "
                       f"SL: <b>{s2.get('dca_stop_loss_pct', 10):g}%</b>"
                       f"{deal_line}\n\n"
                       "<i>/dca on · /dca off · /dca base 5 · /dca safety 3 · /dca step 2.5 · /dca tp 2 · /dca max 3</i>")
    if cmd == "/grid":
        u = user_loop._ensure_user(chat_id)
        s2 = u["settings"]
        if args and args[0] == "on":
            _upd(chat_id, "grid_enabled", True)
            lower = s2.get("grid_lower", 0)
            upper = s2.get("grid_upper", 0)
            range_note = (f"Range: <b>${lower:,.2f} – ${upper:,.2f}</b>"
                          if lower and upper else
                          "Range: <b>auto</b> (set from last 50 candles)")
            return send_to(chat_id,
                           "📊 <b>Grid Bot ENABLED</b>\n"
                           "Passive income on sideways markets — profits on every price bounce.\n\n"
                           f"{range_note}\n"
                           f"Levels: <b>{s2.get('grid_levels', 10)}</b>  "
                           f"Order size: <b>{s2.get('grid_order_pct', 2):g}%</b> each\n\n"
                           "<i>Adjust: /grid lower 95000 · /grid upper 105000 · "
                           "/grid levels 10 · /grid step 2 · /grid off</i>")
        if args and args[0] == "off":
            _upd(chat_id, "grid_enabled", False)
            return send_to(chat_id, "⏹ <b>Grid Bot disabled.</b>")
        if args and args[0] == "stop":
            u2 = user_loop._ensure_user(chat_id)
            st = u2.get("state", {})
            if st.get("grid_deal"):
                st["grid_deal"] = None
                user_store.update(chat_id, {"state": st})
                return send_to(chat_id, "⏹ <b>Active grid stopped.</b> All virtual orders cancelled.")
            return send_to(chat_id, "ℹ️ No active grid to stop.")
        if args and args[0] == "lower":
            try:
                v = float(args[1]); assert v > 0
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /grid lower 95000  (price in $)")
            _upd(chat_id, "grid_lower", v)
            return send_to(chat_id, f"✅ Grid lower bound → <b>${v:,.2f}</b>")
        if args and args[0] == "upper":
            try:
                v = float(args[1]); assert v > 0
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /grid upper 105000  (price in $)")
            _upd(chat_id, "grid_upper", v)
            return send_to(chat_id, f"✅ Grid upper bound → <b>${v:,.2f}</b>")
        if args and args[0] == "levels":
            try:
                v = int(args[1]); assert 3 <= v <= 50
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /grid levels 10  (3–50)")
            _upd(chat_id, "grid_levels", v)
            return send_to(chat_id, f"✅ Grid levels → <b>{v}</b>")
        if args and args[0] == "step":
            try:
                v = float(args[1]); assert 0.5 <= v <= 20
            except (IndexError, ValueError, AssertionError):
                return send_to(chat_id, "❌ /grid step 2  (0.5–20% of balance per order)")
            _upd(chat_id, "grid_order_pct", v)
            return send_to(chat_id, f"✅ Grid order size → <b>{v:g}%</b> per level")
        # Show current grid status
        enabled = s2.get("grid_enabled", False)
        deal = u.get("state", {}).get("grid_deal")
        deal_line = ""
        if deal:
            price = binance.get_price(deal["symbol"])
            deal_line = f"\n\n<b>Active grid:</b>\n{grid.grid_status(deal, price)}" if price else ""
        lower = s2.get("grid_lower", 0)
        upper = s2.get("grid_upper", 0)
        range_str = (f"${lower:,.2f} – ${upper:,.2f}"
                     if lower and upper else "auto (last 50 candles)")
        return send_to(chat_id,
                       f"📊 <b>Grid Bot</b> — {'✅ ON' if enabled else '⏹ OFF'}\n"
                       f"━━━━━━━━━━━━━━━━━━━━\n"
                       f"Range: <b>{range_str}</b>\n"
                       f"Levels: <b>{s2.get('grid_levels', 10)}</b>  "
                       f"Order size: <b>{s2.get('grid_order_pct', 2):g}%</b> each"
                       f"{deal_line}\n\n"
                       "<i>/grid on · /grid off · /grid stop · /grid lower 95000 · "
                       "/grid upper 105000 · /grid levels 10 · /grid step 2</i>")
    if cmd == "/ai":
        # Let a client (re)connect their own free AI key any time.
        return _ask_groq(chat_id)
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
                       "Smart chat + market analysis on YOUR own quota (1,500/day).\n"
                       "The bot trades automatically 24/7 — no extra key needed. 🤖")
    if cmd == "/copilot":
        arg = (args or "").strip().lower()
        if arg in ("on", "1", "yes", "true"):
            user_store.update(chat_id, {"copilot": True})
            return send_to(chat_id,
                "🤖 <b>Copilot mode ON.</b>\nThe bot will now <b>suggest</b> trades and wait for your "
                "✅ Approve before opening anything. You stay in control.\n\n<i>Turn off with /copilot off.</i>")
        if arg in ("off", "0", "no", "false"):
            user_store.update(chat_id, {"copilot": False})
            return send_to(chat_id,
                "🚀 <b>Autopilot mode ON.</b>\nThe bot will open trades automatically when a setup meets "
                "your thresholds. (Use /copilot on to require approval.)")
        cur = user_store.load(chat_id).get("copilot")
        return send_to(chat_id,
            f"🤖 Copilot is currently <b>{'ON (approval required)' if cur else 'OFF (autopilot)'}</b>.\n"
            "Use <code>/copilot on</code> or <code>/copilot off</code>.")
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
    if cmd in ("/buy", "/sell", "/close"):
        _ensure_running(chat_id)
        alert = make_alert(chat_id)
        if cmd == "/close":
            res = user_loop.force_close(chat_id, alert)
            if res.get("ok"):
                sign = "+" if res.get("pnl", 0) >= 0 else ""
                return send_to(chat_id,
                               f"✅ <b>Position closed.</b>\n"
                               f"PnL: <b>{sign}${res.get('pnl', 0):.4f} ({sign}{res.get('pnlPct', 0):.2f}%)</b>")
            return send_to(chat_id, f"❌ {res.get('error', 'No open position')}")
        side = "BUY" if cmd == "/buy" else "SELL"
        symbol = args[0].upper() if args else None
        res = user_loop.force_trade(chat_id, side, symbol, alert)
        if res.get("ok"):
            sym = res["symbol"]
            icon = "🟢 LONG" if side == "BUY" else "🔴 SHORT"
            return send_to(chat_id,
                           f"{icon} <b>{sym}</b> @ ${res['price']:.4f}\n"
                           f"SL: ${res['stopLoss']:.4f}  TP: ${res['takeProfit']:.4f}")
        return send_to(chat_id, f"❌ {res.get('error', 'Could not open trade')}")

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
    if data == "cp:y":   # copilot — approve the pending suggestion
        sug = user_loop.pending_suggestion(chat_id)
        user_loop.clear_suggestion(chat_id)
        if not sug:
            return send_to(chat_id, "⌛ That suggestion expired. I'll send a fresh one on the next setup.")
        send_to(chat_id, f"✅ Approved — opening {sug['side']} {sug['symbol']}…")
        res = user_loop.force_trade(chat_id, sug["side"], sug["symbol"], alert_fn=make_alert(chat_id))
        if not res.get("ok"):
            send_to(chat_id, f"❌ Could not open: {res.get('error', '?')}")
        return
    if data == "cp:n":   # copilot — reject the suggestion
        user_loop.clear_suggestion(chat_id)
        return send_to(chat_id, "❌ Skipped. I'll keep watching and suggest the next setup.")
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
    if data == "ex:binance" or data == "ex:binanceus":
        user_store.update(chat_id, {"exchange": data[3:]})
        return _ask_live_keys(chat_id)
    if data == "groq:skip":
        _wizard.pop(str(chat_id), None)
        _pending_key.pop(str(chat_id), None)
        return _ready(chat_id)
    if data.startswith("kk:"):
        # User confirmed which provider their unknown-format key belongs to
        kind = data[3:]  # "gemini" | "groq" | "claude"
        key = _pending_key.pop(str(chat_id), None)
        if not key:
            return send_to(chat_id, "⚠️ Key session expired. Please paste your key again.")
        _wizard.pop(str(chat_id), None)
        label = {"claude": "Claude", "groq": "Groq", "gemini": "Gemini"}.get(kind, kind)
        send_to(chat_id, f"🔍 Testing your {label} key…")
        if kind == "claude":
            ok, why = assistant.test_key(key)
            field = "anthropic_key"
        elif kind == "gemini":
            ok, why = assistant.test_gemini_key(key)
            field = "gemini_key"
        else:
            ok, why = ai.test_key(key)
            field = "groq_key"
        _retry_kb = {"reply_markup": json.dumps({"inline_keyboard": [
            [{"text": "🥇 Get free Gemini key", "url": "https://aistudio.google.com/apikey"}],
            [{"text": "🥈 Get free Groq key", "url": "https://console.groq.com/keys"}],
            [{"text": "⚡ Skip — use shared AI", "callback_data": "groq:skip"}],
        ]})}
        if not ok:
            return send_to(chat_id,
                           f"❌ <b>{label} key not working:</b> {why}\n\n"
                           "Paste a different key or skip.", _retry_kb)
        user_store.update(chat_id, {field: key})
        assistant.clear_history(chat_id)
        send_to(chat_id, f"✅ <b>{label} key verified &amp; saved!</b> "
                         "Smart signals + unlimited chat now run on YOUR own quota. 🧠")
        return _ready(chat_id)
    if data == "c:chart":
        sym = s["SYMBOL"]
        url = f"{cfg.SITE_URL}/chart?s={sym}"
        return send_to(chat_id, f"📈 <b>{sym}</b> — live chart",
                       {"reply_markup": json.dumps({"inline_keyboard": [[
                           {"text": f"📈 Open {sym} chart", "web_app": {"url": url}}]]})})
    if data.startswith("sym:"):
        sym = data[4:]
        if sym == "custom":
            return send_to(chat_id,
                           "✏️ <b>Type any Binance pair you want to trade.</b>\n\n"
                           "Just send <code>/symbol PEPEUSDT</code> (or any of the 600+ "
                           "pairs — <code>FETUSDT</code>, <code>WIFUSDT</code>, "
                           "<code>JUPUSDT</code>, …).\n\n"
                           "<i>You're not limited to the coins on the buttons — the bot "
                           "trades whatever you choose.</i>")
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
    if data == "c:mode":
        u = user_loop._ensure_user(chat_id)
        cur = "📝 PAPER ($100 virtual)" if u.get("paper", True) else "🔴 REAL Binance (live funds)"
        return send_to(chat_id,
                       "🔄 <b>Paper ↔ Real — switch any time</b>\n"
                       "━━━━━━━━━━━━━━━━━━━━\n"
                       f"You're currently in: <b>{cur}</b>\n\n"
                       "<b>To switch safely:</b>\n"
                       "1️⃣ Tap <b>⏸ Pause</b> (or send /pause) to stop the current mode "
                       "and let any open position close first.\n"
                       "2️⃣ Send /setup and pick the mode you want:\n"
                       "   • 📝 <b>Paper</b> — practice, $100 virtual, no keys.\n"
                       "   • 🔴 <b>Real Binance</b> — your account &amp; real funds.\n"
                       "3️⃣ The bot restarts in the new mode and auto-resumes.\n\n"
                       "<i>Paper and real are fully separate — switching never touches "
                       "your real funds unless you choose Real and connect your keys.</i>",
                       {"reply_markup": json.dumps({"inline_keyboard": [
                           [{"text": "⏸ Pause first", "callback_data": "c:pause"}],
                           [{"text": "🔄 Switch mode (/setup)", "callback_data": "setup:reset"}],
                       ]})})
    if data == "setup:reset":
        u = user_loop._ensure_user(chat_id)
        u["setup_done"] = False
        user_store.save(chat_id, u)
        return send_to(chat_id, "🔄 <b>Switch mode</b> — how do you want to trade?", _kb_mode())
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
_VERIFY_URL = f"{cfg.LICENSE_SERVER.rstrip('/')}/api/verify-license"


def _license_ok(chat_id, text):
    """Validate the buyer's license before granting access to the bot.

    The activation deep link from the purchase email is `/start APEX-...`.
    Returns True if access should be granted. FAIL-OPEN: if our verify server
    is unreachable we still let a real-looking key through, so a server hiccup
    never locks out a paying customer. Only a server that actively says
    "invalid" (or a malformed/missing key) is refused.
    """
    cid = str(chat_id)
    # Returning customer whose access store was wiped (e.g. a redeploy) — they
    # already validated once and we kept their key. Let them straight back in.
    try:
        if user_store.load(cid).get("license_key"):
            return True
    except Exception:
        pass

    first = (text or "").splitlines()[0].strip()
    cmd, _, karg = first.partition(" ")
    key = karg.strip().upper()
    if cmd.lower().split("@")[0] != "/start" or not key:
        send_to(chat_id,
                "🔒 <b>Activation required</b>\n\n"
                "Open the activation link from your purchase email to unlock the bot.\n\n"
                "Don't have Apex Trade Bot yet? Get it at https://aicashsystem.space")
        return False
    if not re.match(r'^APEX-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$', key):
        send_to(chat_id,
                "❌ <b>That doesn't look like a valid key.</b>\n\n"
                "Use the <code>APEX-XXXX-XXXX-XXXX</code> key from your purchase email, "
                "or buy at https://aicashsystem.space")
        return False
    try:
        r = requests.post(_VERIFY_URL, json={"key": key, "product": "apex-bot"}, timeout=8)
        data = r.json()
        if not data.get("valid"):
            send_to(chat_id,
                    f"❌ <b>{data.get('message', 'License not found.')}</b>\n\n"
                    "Need help? supportaicashsystem@gmail.com")
            return False
    except Exception as e:
        print(f"[TG] verify-license unreachable ({e}) — fail-open grant for {key}")
    try:
        user_store.update(cid, {"license_key": key})
    except Exception:
        pass
    return True


_REVALIDATE_SEC = 12 * 3600  # re-check a granted client's license at most this often


def _revalidate_license(chat_id):
    """Periodically re-check a granted client's license so refunded/charged-back
    keys lose access without waiting for a redeploy.

    FAIL-OPEN: any network/parse error keeps access — a server hiccup must never
    lock out a paying customer. Only an EXPLICIT {valid: false} from the server
    (refund, chargeback, deactivated key) revokes. Returns False if access was
    revoked, so the caller stops handling this update.
    """
    cid = str(chat_id)
    if access.is_admin(cid):
        return True
    try:
        u = user_store.load(cid)
    except Exception:
        return True
    key = u.get("license_key")
    if not key:
        return True  # legacy grant with no stored key — nothing to re-check
    if time.time() - u.get("license_checked_at", 0) < _REVALIDATE_SEC:
        return True
    try:
        r = requests.post(_VERIFY_URL, json={"key": key, "product": "apex-bot"}, timeout=8)
        data = r.json()
    except Exception:
        return True  # fail-open
    if data.get("valid") is False:
        try:
            user_store.update(cid, {"license_key": None})
        except Exception:
            pass
        access.revoke(cid)
        try:
            user_loop.stop(cid)
        except Exception:
            pass
        send_to(chat_id,
                f"⛔ <b>{data.get('message', 'Your license is no longer active.')}</b>\n"
                "Questions? supportaicashsystem@gmail.com")
        return False
    try:
        user_store.update(cid, {"license_checked_at": int(time.time())})
    except Exception:
        pass
    return True


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
            "🧪 <b>Paper Trading</b> — practice with $100 virtual USDT and REAL market "
            "prices. No keys, no signup, starts instantly. Zero risk.\n"
            "   → Pick <b>any</b> coin (600+ pairs), any strategy, your own risk.\n\n"
            "🔴 <b>Real Binance</b> — connect your real Binance account and trade with real funds.\n"
            "   → No Binance account yet? I'll give you the signup link in the next step.\n\n"
            "<i>You can switch between paper and real any time with /setup.</i>",
            _kb_mode())


def _start_paper(chat_id):
    """Paper trading = instant internal simulation with REAL market prices (no keys)."""
    u = user_loop._ensure_user(chat_id)
    u["paper"] = True
    u["setup_done"] = True
    # Keyless paper: clear any old keys so the loop uses internal simulation.
    u.pop("api_key", None)
    u.pop("api_secret", None)
    u["settings"]["PAUSED"] = True
    user_store.save(chat_id, u)
    send_to(chat_id,
            "🧪 <b>Paper Trading ready!</b>\n\n"
            "You're starting with <b>$100 virtual USDT</b> and REAL live market prices.\n"
            "No keys, no signup — the bot trades a simulation so you can test risk-free.\n\n"
            "Next: set up the AI brain 👇")
    _ask_groq(chat_id)


def _start_live_setup(chat_id):
    """Real trading — first pick the exchange (global vs US)."""
    u = user_loop._ensure_user(chat_id)
    u["paper"] = False
    user_store.save(chat_id, u)
    send_to(chat_id,
            "🌍 <b>Which exchange is your account on?</b>\n\n"
            "🟡 <b>Binance.com</b> — global (Europe, Asia, LatAm, most countries)\n"
            "🇺🇸 <b>Binance.US</b> — for United States clients\n\n"
            "🆕 <b>No Binance account yet?</b> Tap <b>Create Binance account</b> "
            "below to sign up first (takes ~3 minutes), then come back and pick "
            "your exchange.\n\n"
            "<i>Pick the one where your account &amp; funds are.</i>",
            {"reply_markup": json.dumps({"inline_keyboard": [
                [{"text": "🆕 Create Binance account", "url": _BINANCE_SIGNUP_URL}],
                [{"text": "🟡 Binance.com (Global)", "callback_data": "ex:binance"}],
                [{"text": "🇺🇸 Binance.US", "callback_data": "ex:binanceus"}],
            ]})})


def _ask_live_keys(chat_id):
    """Show API-key instructions for the chosen exchange."""
    _wizard[str(chat_id)] = "KEYS"
    u = user_loop._ensure_user(chat_id)
    is_us = u.get("exchange") == "binanceus"
    url = _BINANCEUS_KEYS_URL if is_us else _BINANCE_KEYS_URL
    name = "Binance.US" if is_us else "Binance.com"
    send_to(chat_id,
            f"🔴 <b>Connect your {name} account</b>\n\n"
            "1️⃣ Tap <b>Open API page</b> below (log in to Binance)\n"
            "2️⃣ Create an API key — enable <b>Spot &amp; Margin Trading</b>, "
            "leave <b>withdrawals OFF</b> (the bot only needs trade access)\n"
            "3️⃣ Copy the <b>API Key</b> and <b>Secret Key</b> Binance shows you\n"
            "4️⃣ Send both here in ONE message:\n"
            "<code>API_KEY=your_key API_SECRET=your_secret</code>\n\n"
            "🔒 <i>Your message is deleted instantly after reading — keys are stored "
            "encrypted and can never withdraw your funds.</i>",
            {"reply_markup": json.dumps({"inline_keyboard": [
                [{"text": f"🔑 Open {name} API page", "url": url}],
                [{"text": "🆕 No account yet? Create Binance", "url": _BINANCE_SIGNUP_URL}],
            ]})})


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
    exchange = u.get("exchange", "binance")

    # Validate the keys against Binance BEFORE saving — fail fast with a clear reason.
    send_to(chat_id, "🔍 Verifying your Binance keys…")
    try:
        ex = binance.LiveExchange(pairs["API_KEY"], pairs["API_SECRET"],
                                  testnet=is_testnet, exchange=exchange)
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
    """Onboarding step 3: collect ANY free AI key (Gemini / Claude / Groq) or skip."""
    u = user_loop._ensure_user(chat_id)
    if u.get("groq_key") or u.get("gemini_key") or u.get("anthropic_key"):
        return _ready(chat_id)
    _wizard[str(chat_id)] = "GROQ"
    send_to(chat_id,
            "🧠 <b>Activate your AI brain (free)</b>\n\n"
            "Your bot already trades on its built-in rule engine — but a free AI key "
            "unlocks <b>smart signals + unlimited chat</b> (\"how's my trade?\", \"buy ETH\", etc.).\n\n"
            "Pick ONE — all free, takes 1 minute:\n\n"
            "🥇 <b>Gemini</b> — best free option, 1,500/day, no limits.\n"
            "   → aistudio.google.com → <i>Get API key</i>\n"
            "🥈 <b>Groq</b> — fast, ~14,400/day.\n"
            "   → console.groq.com/keys (key starts <code>gsk_</code>)\n"
            "🥉 <b>Claude</b> — smartest, executes trades from chat.\n"
            "   → console.anthropic.com (key starts <code>sk-ant-</code>)\n\n"
            "📋 <b>Just paste the key here</b> — I auto-detect which one it is.\n"
            "Or tap <b>Skip</b> to ride the shared AI (may hit limits).",
            {"reply_markup": json.dumps({"inline_keyboard": [
                [{"text": "🥇 Get free Gemini key", "url": "https://aistudio.google.com/apikey"}],
                [{"text": "🥈 Get free Groq key", "url": "https://console.groq.com/keys"}],
                [{"text": "⚡ Skip — use shared AI", "callback_data": "groq:skip"}],
            ]})})


def _detect_key_kind(key):
    """Return 'claude' | 'groq' | 'gemini' from a pasted key, or None if unknown."""
    k = (key or "").strip()
    if k.startswith("sk-ant-"):
        return "claude"
    if k.startswith("gsk_"):
        return "groq"
    # Google AI Studio Gemini keys: AIza prefix OR any long key without provider prefix
    if k.startswith("AIza") or k.startswith("AIzaSy"):
        return "gemini"
    # Fallback: long alphanumeric key — likely Gemini (but ask user to confirm)
    return None


def _finish_groq(chat_id, key, msg_id):
    """Verify & save ANY supported AI key, auto-detecting the provider."""
    _delete_message(chat_id, msg_id)
    key = key.strip()
    kind = _detect_key_kind(key)
    _retry_kb = {"reply_markup": json.dumps({"inline_keyboard": [
        [{"text": "🥇 Get free Gemini key", "url": "https://aistudio.google.com/apikey"}],
        [{"text": "🥈 Get free Groq key", "url": "https://console.groq.com/keys"}],
        [{"text": "⚡ Skip — use shared AI", "callback_data": "groq:skip"}],
    ]})}
    if kind is None:
        # Unknown prefix — store key and ask user to confirm provider
        _pending_key[str(chat_id)] = key
        _wizard[str(chat_id)] = "KEY_KIND"
        return send_to(chat_id,
                       "🤔 <b>Which provider is this key for?</b>",
                       {"reply_markup": json.dumps({"inline_keyboard": [
                           [{"text": "🥇 Gemini (Google AI Studio)", "callback_data": "kk:gemini"}],
                           [{"text": "🥈 Groq", "callback_data": "kk:groq"}],
                           [{"text": "🥉 Claude (Anthropic)", "callback_data": "kk:claude"}],
                           [{"text": "❌ Cancel", "callback_data": "groq:skip"}],
                       ]})})

    label = {"claude": "Claude", "groq": "Groq", "gemini": "Gemini"}[kind]
    send_to(chat_id, f"🔍 Testing your {label} key…")
    if kind == "claude":
        ok, why = assistant.test_key(key)
        field = "anthropic_key"
    elif kind == "gemini":
        ok, why = assistant.test_gemini_key(key)
        field = "gemini_key"
    else:
        ok, why = ai.test_key(key)
        field = "groq_key"

    if not ok:
        return send_to(chat_id,
                       f"❌ <b>{label} key not working:</b> {why}\n\n"
                       "Paste a different key or skip.", _retry_kb)
    user_store.update(chat_id, {field: key})
    assistant.clear_history(chat_id)
    _wizard.pop(str(chat_id), None)
    send_to(chat_id, f"✅ <b>{label} key verified &amp; saved!</b> "
                     "Smart signals + unlimited chat now run on YOUR own quota. 🧠")
    _ready(chat_id)


def _ready(chat_id):
    """Setup complete — AUTO-START the bot and show the control panel."""
    u = user_loop._ensure_user(chat_id)
    # Auto-start: don't make the user press Start after onboarding.
    u["settings"]["PAUSED"] = False
    user_store.save(chat_id, u)
    _ensure_running(chat_id)
    s = u["settings"]
    if u.get("anthropic_key"):
        ai_info = "Claude (yours) ✅ — smart chat + voice trade commands"
    elif u.get("gemini_key"):
        ai_info = "Gemini (yours) ✅ — unlimited smart chat"
    elif u.get("groq_key"):
        ai_info = "Groq (yours) ✅ — unlimited smart chat"
    else:
        ai_info = "rule-based engine (add a free AI key via /ai for smart chat)"
    # Message 1: confirmation that bot is live
    send_to(chat_id,
            f"⚡ <b>Bot is LIVE and trading!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Mode: <b>{'📝 PAPER ($100 virtual)' if u.get('paper', True) else '🔴 REAL Binance'}</b>\n"
            f"Symbol: <b>{s['SYMBOL']}</b>   Strategy: <b>{s['STRATEGY_MODE']}</b>\n"
            f"AI: <b>{ai_info}</b>\n\n"
            "📡 Market data: live from Binance (free, no key needed).\n"
            "🤖 Trading: automatic 24/7 — rule-based engine, zero quota.\n"
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
                        _license_ok(chat_id, "")  # button press w/o a key → prompt for activation
                        continue
                    if not _revalidate_license(chat_id):
                        continue  # license refunded/revoked
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
                    # Gate access behind a valid purchase license (fail-open on
                    # server errors). Admins are already is_allowed, so they skip
                    # this. The deep-link /start APEX-... key lands here.
                    if _license_ok(chat_id, text):
                        _activate(chat_id)
                    continue
                if not _revalidate_license(chat_id):
                    continue  # license refunded/revoked
                _auto_restore(chat_id)
                # SECURITY: any message that looks like API keys is deleted
                # instantly and NEVER reaches the AI assistant or chat history.
                low = text.lower()
                looks_like_keys = ("api_key=" in low and "api_secret=" in low) or \
                                  (len(text) > 40 and text.count("=") >= 2 and " " not in text.strip() and "_" in text)
                step = _wizard.get(str(chat_id))
                if looks_like_keys:
                    _delete_message(chat_id, msg_id)
                    if step == "KEYS":
                        try:
                            _finish_live_setup(chat_id, text, msg_id)
                        except Exception as e:
                            print(f"[TG] keys error: {e}")
                    else:
                        send_to(chat_id,
                                "🔒 <b>Keys detected &amp; deleted for your safety.</b>\n"
                                "To connect an account, start setup with /setup → Real Binance, "
                                "then send your keys when asked.")
                    continue
                # Real-account setup: capture the API key message (not a command)
                if step == "KEYS" and not text.startswith("/"):
                    try:
                        _finish_live_setup(chat_id, text, msg_id)
                    except Exception as e:
                        print(f"[TG] keys error: {e}")
                    continue
                if step == "GROQ" and not text.startswith("/"):
                    # Accept any pasted AI key (Gemini / Groq / Claude) — auto-detected.
                    try:
                        _finish_groq(chat_id, text.split()[0], msg_id)
                    except Exception as e:
                        print(f"[TG] ai-key error: {e}")
                    continue
                # Free text (non-command) → intent check first, then AI
                if not text.startswith("/"):
                    handled = _handle_trade_intent(chat_id, text)
                    if not handled:
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
