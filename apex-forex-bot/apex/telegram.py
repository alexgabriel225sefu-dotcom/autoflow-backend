"""Telegram alerts + full interactive config/control commands (Forex edition).

Access model: owner bootstraps on first /start, then grants clients via /grant.
All admin commands are owner-only. Clients get /status and /help.
Polling runs in a background daemon thread.
"""
import os
import re
import json
import time
import threading
import requests
from apex import config as cfg
from apex import forex
from apex import access
from apex import user_store
from apex import user_loop
from apex import assistant
from apex import affiliate_store

TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
CHAT_ID = (cfg.TELEGRAM_CHAT_ID or "").strip()
DASHBOARD_URL = cfg.DASHBOARD_URL
_API = f"https://api.telegram.org/bot{TOKEN}"


def refresh_from_config():
    # TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are also settable from the web
    # configurator (configurator-forex.html cfg.TELEGRAM_BOT_TOKEN/CHAT_ID)
    # and only land on cfg after load_remote() resolves in main(). This
    # module is imported at the top of bot.py, before that — without a
    # refresh, a customer who set their Telegram token via the configurator
    # (instead of a Railway env var) would silently get no Telegram bot at all.
    global TOKEN, CHAT_ID, _API
    TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
    CHAT_ID = (cfg.TELEGRAM_CHAT_ID or "").strip()
    _API = f"https://api.telegram.org/bot{TOKEN}"
_RUNTIME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime.json")

_get_dash = lambda: None
_broker = None
_update_id = 0
_lock = threading.Lock()
_wizards = {}      # per-chat wizard state: {chat_id: {step: str, data: dict}}
                   # MUST be per-chat — many clients run /setup on the same shared
                   # bot at once; a single global dict would clobber their flows.
_bot_control = {}  # callbacks: {set_paused, get_paused, reload_broker}

_PAIR_RE = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")

# ─── Trade intent patterns (work without any AI key) ─────
_RE_AMOUNT_FX = re.compile(
    r"(?:cu\s+|with\s+|de\s+|pentru\s+)(\d+(?:[.,]\d+)?)\s*(?:\$|usd|dolari?|bucks?)?",
    re.IGNORECASE,
)
_RE_BUY_FX = re.compile(
    r"\b(intr[aă]|intr[aă]-?[oO]|cumpăr[aă]?|cumpara|buy|long|intru)\b",
    re.IGNORECASE,
)
_RE_SELL_FX = re.compile(
    r"\b(vinde|vânz[iă]|short|sell)\b",
    re.IGNORECASE,
)
_RE_CLOSE_FX = re.compile(
    r"\b(inchide|închide|close|exit|iesi|ieși)\b",
    re.IGNORECASE,
)
_RE_ALL_IN_FX = re.compile(
    r"\ball.?in\b|toat[aă]\s+suma|tot\s+balant|full\s+balance",
    re.IGNORECASE,
)
_RE_CLOSE_MATH_FX = re.compile(
    r"(inchide|close|iesi|exit|dac[aă]).{0,30}(cât|cat|cati|câți|rămâne|ramane|profit|pierd|lose)",
    re.IGNORECASE,
)
_RE_PAIR_FX = re.compile(r"\b([A-Z]{3})[/_]([A-Z]{3})\b|\b(XAU|XAG|EUR|GBP|USD|JPY|AUD|CAD|CHF|NZD)\b")


def _user_symbol(chat_id) -> str:
    dash = user_loop.get_dash(chat_id)
    if dash and dash.get("symbol"):
        return dash["symbol"]
    user = user_store.load(chat_id)
    return user.get("symbol", cfg.SYMBOL)


def _handle_trade_intent_fx(chat_id, text) -> bool:
    """Return True if the message was a direct trade command — no AI needed."""
    t = text.strip()

    # "if I close now, how much would I have?"
    if _RE_CLOSE_MATH_FX.search(t):
        dash = user_loop.get_dash(chat_id) or {}
        open_pos = dash.get("openPosition")
        if not open_pos:
            send_to(chat_id, "📭 Nicio poziție deschisă momentan.")
            return True
        from apex.brokers import yahoo
        from apex.brokers.oanda import OandaBroker
        import types as _types
        user = user_store.load(chat_id)
        sym = open_pos.get("symbol", _user_symbol(chat_id))
        try:
            paper = user.get("paper", True)
            fake_cfg = _types.SimpleNamespace(
                OANDA_API_TOKEN=user.get("oanda_token", ""),
                OANDA_ACCOUNT_ID=user.get("oanda_account_id", ""),
                OANDA_ENV="practice", SYMBOL=sym, TIMEFRAME="5m", CANDLES=5,
                PAPER_TRADING=paper, PAPER_BALANCE=1000,
                STOP_LOSS_PIPS=20.0, TAKE_PROFIT_PIPS=40.0,
                RISK_PER_TRADE=0.005, LEVERAGE=30.0, MARGIN_CAP=0.5,
                MAX_SPREAD_PIPS=3.0, MIN_CONFIDENCE=62,
            )
            broker = yahoo if (paper and not user.get("oanda_token")) else OandaBroker(fake_cfg)
            candles = broker.get_candles(sym, "5m", 5)
            price = candles[-1]["close"] if candles else open_pos["entryPrice"]
        except Exception:
            price = open_pos["entryPrice"]
        entry = open_pos["entryPrice"]
        units = open_pos.get("units", 1000)
        side = open_pos["side"]
        gross = forex.pnl_usd(side, entry, price, units, sym)
        pv = forex.pip_value_per_unit(sym, price)
        cost = open_pos.get("entrySpreadPips", 0.0) * pv * units
        net = gross - cost
        bal = dash.get("balance", 1000.0) + net
        sign = "+" if net >= 0 else ""
        send_to(chat_id,
                f"📊 <b>Dacă închizi acum:</b>\n"
                f"Preț curent: <b>{price:.5f}</b>\n"
                f"P&amp;L brut: <b>{sign}${gross:.2f}</b>\n"
                f"Cost spread: <b>−${cost:.2f}</b>\n"
                f"Net: <b>{sign}${net:.2f}</b>\n"
                f"Balanță după: <b>${bal:.2f}</b>\n\n"
                f"<i>Folosește</i> <code>/close</code> <i>pentru a închide efectiv.</i>")
        return True

    # Close intent
    if _RE_CLOSE_FX.search(t) and not _RE_BUY_FX.search(t):
        dash = user_loop.get_dash(chat_id) or {}
        if not dash.get("openPosition"):
            send_to(chat_id, "📭 Nicio poziție deschisă.")
            return True
        _handle_close(chat_id)
        return True

    # All-in
    if _RE_ALL_IN_FX.search(t):
        sym = _user_symbol(chat_id)
        dash = user_loop.get_dash(chat_id) or {}
        bal = dash.get("balance", 1000.0)
        send_to(chat_id, f"⚡ <b>ALL IN</b> — BUY <b>{sym}</b> cu <b>${bal * 0.98:.0f}</b>…")
        result = user_loop.force_trade(str(chat_id), "BUY", sym)
        _send_fx_trade_result(chat_id, result, sym)
        return True

    # BUY intent
    if _RE_BUY_FX.search(t):
        sym = _user_symbol(chat_id)
        # detect pair in message
        pm = _RE_PAIR_FX.search(t.upper())
        if pm:
            raw = pm.group(0).replace("/", "_").replace("-", "_")
            if "_" not in raw:
                raw = raw + "_USD"
            if _PAIR_RE.match(raw):
                sym = raw
        send_to(chat_id, f"⚡ Deschid <b>BUY {sym}</b>…")
        result = user_loop.force_trade(str(chat_id), "BUY", sym)
        _send_fx_trade_result(chat_id, result, sym)
        return True

    # SELL/SHORT intent
    if _RE_SELL_FX.search(t):
        sym = _user_symbol(chat_id)
        pm = _RE_PAIR_FX.search(t.upper())
        if pm:
            raw = pm.group(0).replace("/", "_").replace("-", "_")
            if "_" not in raw:
                raw = raw + "_USD"
            if _PAIR_RE.match(raw):
                sym = raw
        send_to(chat_id, f"⚡ Deschid <b>SELL {sym}</b>…")
        result = user_loop.force_trade(str(chat_id), "SELL", sym)
        _send_fx_trade_result(chat_id, result, sym)
        return True

    return False


def _send_fx_trade_result(chat_id, result, sym):
    if result.get("ok"):
        send_to(chat_id,
                f"✅ <b>{result['side']} {sym}</b> deschis\n"
                f"Preț: <b>{result['price']:.5f}</b> | Unități: {result.get('units', '—')}\n"
                f"SL: {result['sl']:.5f} | TP: {result['tp']:.5f}\n"
                f"Spread: {result.get('spread', '—')}p\n"
                f"<i>Închide cu</i> <code>/close</code>")
    else:
        err = result.get("error", "unknown error")
        send_to(chat_id, f"❌ Nu am putut deschide tranzacția: <i>{err}</i>")


# ─── Telegram API helpers ─────────────────────────────────

def send(text, extra=None):
    if not TOKEN or not CHAT_ID:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                            **(extra or {})}, timeout=6)
    except Exception as e:
        print(f"[TELEGRAM] Send error: {e}")


def send_to(chat_id, text, extra=None):
    if not TOKEN:
        return
    try:
        requests.post(f"{_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                            **(extra or {})}, timeout=6)
    except Exception as e:
        print(f"[TELEGRAM] Send error: {e}")


def _delete_message(chat_id, message_id):
    try:
        requests.post(f"{_API}/deleteMessage",
                      json={"chat_id": chat_id, "message_id": message_id}, timeout=6)
    except Exception:
        pass


# ─── Runtime config persistence ──────────────────────────

def _load_runtime() -> dict:
    try:
        with open(_RUNTIME) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_runtime(updates: dict):
    data = _load_runtime()
    data.update(updates)
    with open(_RUNTIME, "w") as f:
        json.dump(data, f, indent=2)


# Env-key → (cfg attribute, cast)
_CFG_MAP = {
    "BROKER":           ("BROKER",           lambda v: str(v).lower()),
    "PAPER_TRADING":    ("PAPER_TRADING",    lambda v: str(v).lower() in ("true", "1", "yes", "on")),
    "TRADE_SYMBOL":     ("SYMBOL",           str),
    "RISK_PER_TRADE":   ("RISK_PER_TRADE",   float),
    "STOP_LOSS_PIPS":   ("STOP_LOSS_PIPS",   float),
    "TAKE_PROFIT_PIPS": ("TAKE_PROFIT_PIPS", float),
    "MIN_CONFIDENCE":   ("MIN_CONFIDENCE",   int),
    "OANDA_ENV":        ("OANDA_ENV",        lambda v: str(v).lower()),
    "LEVERAGE":         ("LEVERAGE",         float),
}

_BROKER_KEYS = {
    "oanda": ["OANDA_API_TOKEN", "OANDA_ACCOUNT_ID"],
    "mt": ["MT_BRIDGE_SECRET"],
}


def _broker_label():
    return "MetaTrader Bridge" if cfg.BROKER == "mt" else f"OANDA ({cfg.OANDA_ENV})"


def _apply(env_key: str, value):
    """Set a key on cfg module and os.environ so it takes effect immediately."""
    os.environ[env_key] = str(value)
    if env_key in _CFG_MAP:
        attr, cast = _CFG_MAP[env_key]
        setattr(cfg, attr, cast(value))
    else:
        setattr(cfg, env_key, str(value))


def _mask(v: str) -> str:
    return (v[:4] + "***") if len(v) > 4 else "***"


# ─── Status / dashboard ──────────────────────────────────

def mini_chart(closes):
    n = min(len(closes), 24)
    sl = closes[-n:]
    lo, hi = min(sl), max(sl)
    rng = hi - lo or 1
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min(7, int((c - lo) / rng * 8))] for c in sl)


def _dashboard_keyboard():
    if not DASHBOARD_URL:
        return {}
    return {"reply_markup": json.dumps(
        {"inline_keyboard": [[{"text": "📊 Live Dashboard", "web_app": {"url": DASHBOARD_URL}}]]})}


def _build_status(dash, chart=""):
    sb = dash.get("startBalance", 0)
    pnl_pct = ((dash.get("balance", 0) - sb) / sb * 100) if sb > 0 else 0.0
    sign = "+" if pnl_pct >= 0 else ""
    trades = dash.get("trades", [])
    wins = sum(1 for t in trades if t.get("win"))
    total = len(trades)
    win_rate = f"{wins / total * 100:.0f}%" if total else "—"
    chart_line = (f"\n<code>{chart}</code>  <b>{dash.get('currentPrice', 0):.5f}</b>") if chart else ""
    market = "🟢 OPEN" if forex.is_market_open() else "🔴 CLOSED (weekend)"
    sessions = ", ".join(forex.active_sessions()) or "—"
    pos_line = "📭 No open position"
    if dash.get("openPosition"):
        op = dash["openPosition"]
        d = "🟢 LONG" if op["side"] == "BUY" else "🔴 SHORT"
        pnl = op.get("currentPnl", 0)
        pos_line = (f"{d} <b>{op['symbol']}</b>\n  Entry: {op['entryPrice']}  "
                    f"SL: {(op.get('stopLoss') or 0):.5f}\n"
                    f"  PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.2f}</b>")
    paused = _bot_control.get("get_paused", lambda: False)()
    state_tag = "  ⏸️ PAUSED" if paused else ""
    return (f"💱 <b>APEX FOREX BOT</b>  {dash.get('mode', '')} · "
            f"{dash.get('broker', '')}{state_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: <b>${dash.get('balance', 0):.2f}</b>  ({sign}{pnl_pct:.2f}%)"
            f"{' ⏳ <i>refreshing…</i>' if dash.get('balStale') else ''}{chart_line}\n"
            f"🕐 Market: {market} · Sessions: {sessions}\n"
            f"🎯 Method: {dash.get('strategy', 'Mean Reversion')}\n"
            + (f"🌊 Regime: {dash['regime']['label']}\n" if isinstance(dash.get('regime'), dict) else "")
            + (f"🩺 Broker: {dash['brokerHealth']}\n" if str(dash.get('brokerHealth', '')).startswith('degraded') else "") + "\n"
            f"{pos_line}\n\n"
            f"📈 {total} trades · {wins}W/{total - wins}L · Win: {win_rate}\n"
            f"⏱️ Last tick: {_ago(dash)}")


def _ago(dash):
    """Human 'Xm ago' — absolute server timestamps (UTC) kept reading as
    hours-stale to clients in other timezones."""
    import time as _t
    ts = dash.get("lastTickTs")
    if not ts:
        return dash.get("lastTick", "—")
    mins = int((_t.time() - ts) / 60)
    if mins < 1:
        return "just now ✅"
    if mins < 60:
        return f"{mins}m ago"
    return f"{mins // 60}h {mins % 60}m ago"


def _handle_status(chat_id):
    dash = user_loop.get_dash(chat_id)
    # REAL mode: pull the balance from the broker at REQUEST time — a cached
    # figure looked frozen the moment the client deposited/withdrew between
    # the loop's 5-minute ticks.
    user_loop.live_balance(chat_id)
    dash = user_loop.get_dash(chat_id) or dash
    # If user's loop hasn't ticked yet, build a minimal dash from their settings
    if not dash or not dash.get("broker"):
        user = user_store.load(chat_id)
        if user.get("symbol") or user.get("paper") is not None:
            sym = user.get("symbol", cfg.SYMBOL)
            bal = float(user.get("paper_balance", cfg.PAPER_BALANCE))
            paper = user.get("paper", True)
            is_open = forex.is_market_open()
            mode_label = "Paper" if paper else "Live"
            send_to(chat_id,
                    f"💱 <b>APEX FOREX BOT</b>  {mode_label}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Balance: <b>${bal:.2f}</b>\n"
                    f"💱 Pair: <b>{sym}</b> | "
                    f"{'🟢 OPEN' if is_open else '🔴 CLOSED (weekend)'}\n\n"
                    f"📭 No open position. Bot is scanning automatically.\n"
                    f"<i>Force entry:</i> <code>/buy {sym}</code> or <code>/sell {sym}</code>")
            return
        dash = _get_dash()
    if not dash or not dash.get("broker"):
        return send_to(chat_id, "⏳ Bot not started yet. Send /start to begin trading.")
    chart = ""
    if _broker:
        try:
            candles = _broker.get_candles(dash.get("currentSymbol"), "5m", 24)
            chart = mini_chart([c["close"] for c in candles])
        except Exception:
            pass
    send_to(chat_id, _build_status(dash, chart), _dashboard_keyboard())


# ─── Setup wizard ─────────────────────────────────────────

def _handle_setup(chat_id):
    with _lock:
        _wizards[chat_id] = {"step": "MODE", "data": {}}
    send_to(chat_id,
            "🛠️ <b>APEX FOREX BOT SETUP</b>\n\n"
            "1/5 — <b>How do you want to trade?</b>\n\n"
            "Reply <code>1</code> or <code>2</code>:\n"
            "  <code>1</code> — 🧪 <b>Paper</b> (simulated $1000, real prices from "
            "Yahoo Finance). <b>No account, no keys, starts instantly. Zero risk.</b>\n"
            "  <code>2</code> — 🔴 <b>Live</b> (real money via <b>cTrader</b> — any broker "
            "worldwide, connected with /ctrader).\n\n"
            "<i>Most people start with 1 (paper).</i>")


def _handle_wizard_reply(chat_id, raw, msg_id):
    with _lock:
        w = _wizards.get(chat_id)
        step = w.get("step") if w else None
    if not w:
        return   # no active wizard for this chat

    if step == "MODE":
        choice = raw.strip()
        if choice not in ("1", "2"):
            return send_to(chat_id, "❌ Reply <code>1</code> (paper) or <code>2</code> (live).")
        if choice == "1":
            # Paper — Yahoo data, no account needed, skip straight to the pair
            with _lock:
                w["data"]["paper"] = True
                w["step"] = "SYMBOL"
            send_to(chat_id,
                    "🧪 <b>Paper mode</b> — free Yahoo Finance prices, no account.\n\n"
                    "2/5 — <b>Which pair do YOU want to trade?</b>\n\n"
                    "e.g. <code>EUR_USD</code>, <code>GBP_USD</code>, <code>USD_JPY</code>.\n\n"
                    "Reply with the pair. <i>You choose — the bot only trades what you pick.</i>")
        else:
            # Live — real money runs through cTrader (any broker worldwide).
            # Keep the user safe in paper until cTrader is actually linked.
            with _lock:
                _wizards.pop(chat_id, None)
            send_to(chat_id,
                    "🔴 <b>Live trading — via cTrader</b>\n\n"
                    "Real money runs through your own <b>cTrader</b> account (works with "
                    "any cTrader broker worldwide — IC Markets, Pepperstone, FxPro…).\n\n"
                    "<b>To go live:</b>\n"
                    "1️⃣ Send <b>/ctrader</b> → tap <b>Authorize</b> → log in and approve\n"
                    "2️⃣ Test in paper first, then switch to live when you're ready\n\n"
                    "<i>Until you connect cTrader you stay in safe paper mode. Send "
                    "/ctrader now to link your account.</i>")

    elif step == "KEYS":
        _delete_message(chat_id, msg_id)
        pairs = {}
        for part in raw.replace("\n", " ").split():
            if "=" in part:
                k, _, v = part.partition("=")
                pairs[k.strip().upper()] = v.strip()
        if "OANDA_API_TOKEN" not in pairs or "OANDA_ACCOUNT_ID" not in pairs:
            return send_to(chat_id,
                           "❌ I need both values. Send them in one message:\n"
                           "<code>OANDA_API_TOKEN=... OANDA_ACCOUNT_ID=...</code>")
        with _lock:
            w["data"]["keys"] = pairs
            w["step"] = "SYMBOL"
        send_to(chat_id,
                "✅ Credentials saved.\n\n"
                "2/5 — <b>Which pair do YOU want to trade?</b>\n\n"
                "e.g. <code>EUR_USD</code>, <code>GBP_USD</code>, <code>USD_JPY</code>.\n\n"
                "Reply with the pair. <i>You choose — the bot only trades what you pick.</i>")

    elif step == "SYMBOL":
        sym = raw.strip().upper().replace("/", "_").replace("-", "_")
        if not _PAIR_RE.match(sym):
            return send_to(chat_id, "❌ Invalid pair. Example: <code>EUR_USD</code>")
        with _lock:
            w["data"]["symbol"] = sym
            w["step"] = "RISK"
        send_to(chat_id,
                f"✅ Pair: <b>{sym}</b>\n\n"
                "3/5 — <b>How much do YOU want to risk per trade?</b>\n\n"
                "Reply <code>1</code>, <code>2</code> or <code>3</code>:\n"
                "  <code>1</code> — 🟢 Conservative (0.5% of balance per trade)\n"
                "  <code>2</code> — 🟡 Balanced (1% per trade)\n"
                "  <code>3</code> — 🔴 Aggressive (2% per trade)\n\n"
                "<i>You decide the risk. Smaller = safer.</i>")

    elif step == "RISK":
        choice = raw.strip()
        risk_map = {"1": 0.005, "2": 0.01, "3": 0.02}
        if choice not in risk_map:
            return send_to(chat_id, "❌ Reply <code>1</code>, <code>2</code> or <code>3</code>.")
        with _lock:
            w["data"]["risk"] = risk_map[choice]
            w["step"] = "STYLE"
        send_to(chat_id,
                "4/5 — <b>How should the bot trade?</b>\n\n"
                "Reply <code>1</code>, <code>2</code> or <code>3</code>:\n"
                "  <code>1</code> — 🛡 Defensive — only the strongest setups (fewer trades)\n"
                "  <code>2</code> — ⚖️ Balanced — standard selectivity\n"
                "  <code>3</code> — ⚡ Active — more trades, lower bar\n\n"
                "<i>You set the style — this controls how often it enters.</i>")

    elif step == "STYLE":
        choice = raw.strip()
        conf_map = {"1": 70, "2": 62, "3": 55}
        if choice not in conf_map:
            return send_to(chat_id, "❌ Reply <code>1</code>, <code>2</code> or <code>3</code>.")
        with _lock:
            w["data"]["min_confidence"] = conf_map[choice]
            w["step"] = "DISCLAIMER"
            d = dict(w["data"])
        risk_pct = d.get("risk", 0.005) * 100
        send_to(chat_id,
                "5/5 — ⚠️ <b>Risk acknowledgment</b>\n\n"
                "Forex trading carries a real risk of loss. <b>You alone</b> chose:\n"
                f"  • Pair: <b>{d.get('symbol')}</b>\n"
                f"  • Risk per trade: <b>{risk_pct:g}%</b>\n"
                f"  • Mode: <b>{'paper (simulated)' if d.get('paper') else 'LIVE funds'}</b>\n\n"
                "By continuing you confirm that <b>you are solely responsible</b> for all "
                "trades and any losses. The bot and its provider are not liable.\n\n"
                "Reply <code>ACCEPT</code> to activate, or /cancel to abort.")

    elif step == "DISCLAIMER":
        if raw.strip().upper() != "ACCEPT":
            return send_to(chat_id,
                           "Type <code>ACCEPT</code> (in capitals) to activate, or /cancel to abort.")
        with _lock:
            d = dict(w["data"])
            _wizards.pop(chat_id, None)
        sym = d.get("symbol", "EUR_USD")

        # Save per-user settings — every risk parameter was chosen by the client
        user_data = {
            "paper": d.get("paper", True),
            "symbol": sym,
            "risk": d.get("risk", 0.005),
            "min_confidence": d.get("min_confidence", 62),
            "accepted_risk": True,
            "active": True,
        }
        if d.get("keys"):
            user_data["oanda_token"]      = d["keys"].get("OANDA_API_TOKEN", "")
            user_data["oanda_account_id"] = d["keys"].get("OANDA_ACCOUNT_ID", "")
            # Live branch → point this user at OANDA's real fxtrade endpoint.
            # Without this, oanda_env stays "practice" and "live" trades silently
            # execute on the practice server. Default to the live host they asked
            # for; they can flip back with /env practice if it's a demo token.
            user_data["oanda_env"]        = d.get("oanda_env", "live")
        else:
            user_data["oanda_env"]        = "practice"
        user_store.update(chat_id, user_data)

        # Also apply globally if admin (for owner's own bot)
        if access.is_admin(str(chat_id)):
            updates: dict = {
                "PAPER_TRADING": str(d.get("paper", True)).lower(),
                "TRADE_SYMBOL": sym,
                "RISK_PER_TRADE": str(d.get("risk", 0.005)),
                "MIN_CONFIDENCE": str(d.get("min_confidence", 62)),
            }
            if d.get("keys"):
                updates.update(d["keys"])
                updates["BROKER"] = "oanda"
            else:
                # Paper with no OANDA keys → free Yahoo Finance data globally too
                updates["BROKER"] = "yahoo"
            _save_runtime(updates)
            for k, v in updates.items():
                _apply(k, v)
            if _bot_control.get("reload_broker"):
                _bot_control["reload_broker"]()

        # Auto-start trading immediately — no manual /start needed.
        # Restart first so a re-run of /setup applies the new broker/env/keys
        # even if the loop was already running.
        _restart_user_loop(chat_id)
        _auto_start_user(chat_id)

        paper_str = "ON (simulated)" if d.get("paper") else "OFF (live)"
        risk_pct = d.get("risk", 0.005) * 100
        if d.get("paper"):
            broker_str = "Yahoo data (paper)"
        else:
            broker_str = f"OANDA ({user_data.get('oanda_env', 'live')})"
        send_to(chat_id,
                f"✅ <b>Setup complete — bot is LIVE!</b>\n\n"
                f"Broker: <b>{broker_str}</b>\n"
                f"Pair: <b>{sym}</b>  (your choice)\n"
                f"Risk/trade: <b>{risk_pct:g}%</b>  (your choice)\n"
                f"Paper mode: <b>{paper_str}</b>\n\n"
                f"⚡ Trading is active now. You'll get an alert on every trade,\n"
                f"plus a heartbeat so you always know the bot is awake.\n"
                f"Change anything with /setup · /status to check · /stop to pause.\n\n"
                f"🧠 <b>Want AI chat to help you trade?</b> Send /ai to connect a free "
                f"Gemini/Groq key (or paid Claude) — your choice.",
                _dashboard_keyboard())


# ─── Individual command handlers ──────────────────────────

def _handle_setkeys(chat_id, args_text, msg_id):
    _delete_message(chat_id, msg_id)
    pairs = {}
    for part in args_text.replace("\n", " ").split():
        if "=" in part:
            k, _, v = part.partition("=")
            pairs[k.strip().upper()] = v.strip()
    if not pairs:
        return send_to(chat_id, "❌ Format: <code>/setkeys KEY=value KEY2=value2</code>")
    _save_runtime(pairs)
    for k, v in pairs.items():
        _apply(k, v)
    if _bot_control.get("reload_broker"):
        _bot_control["reload_broker"]()
    masked = "\n".join(f"  {k} = {_mask(v)}" for k, v in pairs.items())
    send_to(chat_id, f"🔑 <b>{len(pairs)} credential(s) updated:</b>\n<code>{masked}</code>")


_AI_KB = {"reply_markup": json.dumps({"inline_keyboard": [
    [{"text": "🥇 Get free Gemini key", "url": "https://aistudio.google.com/apikey"}],
    [{"text": "🥈 Get free Groq key", "url": "https://console.groq.com/keys"}],
]})}


def _handle_ai_setup(chat_id):
    """Explain the AI-chat key options — client connects their OWN free/paid key."""
    u = user_store.load(chat_id)
    if u.get("groq_key") or u.get("gemini_key") or u.get("anthropic_key"):
        return send_to(chat_id,
                       "🧠 <b>AI chat is already connected</b> on your own key. ✅\n"
                       "Just talk to me — \"analyze EUR_USD\", \"should I buy gold?\".\n"
                       "Paste a different key any time to switch.")
    send_to(chat_id,
            "🧠 <b>Activate AI chat (helps you trade)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Your bot already trades on its built-in rule engine. A free AI key adds "
            "<b>smart chat</b> — ask it to analyze a pair, explain a trade, or enter for you.\n\n"
            "⚠️ <b>AI chat needs a key — your choice, free or paid:</b>\n"
            "🥇 <b>Gemini</b> — free, 1,500/day → aistudio.google.com/apikey\n"
            "🥈 <b>Groq</b> — free, fast (key starts <code>gsk_</code>) → console.groq.com/keys\n"
            "🥉 <b>Claude</b> — paid, smartest (key starts <code>sk-ant-</code>) → console.anthropic.com\n\n"
            "📋 <b>Just paste your key here</b> — I auto-detect which one it is and verify it.\n"
            "<i>Trading works fine without a key; this only powers the chat.</i>",
            _AI_KB)


def _detect_ai_key(key):
    k = (key or "").strip()
    if k.startswith("sk-ant-"):
        return "claude"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("AIza"):
        return "gemini"
    return None


def _handle_ai_key(chat_id, key, msg_id):
    """Verify & save a pasted AI key (any provider, auto-detected)."""
    _delete_message(chat_id, msg_id)
    key = (key or "").strip().split()[0] if key else ""
    kind = _detect_ai_key(key)
    if kind is None:
        return send_to(chat_id,
                       "🤔 <b>I couldn't tell which provider that key is for.</b>\n"
                       "Gemini keys start with <code>AIza</code>, Groq with <code>gsk_</code>, "
                       "Claude with <code>sk-ant-</code>.\n"
                       "Copy the full key again, or tap a button below to get a free one.",
                       _AI_KB)
    label = {"claude": "Claude", "groq": "Groq", "gemini": "Gemini"}[kind]
    send_to(chat_id, f"🔍 Testing your {label} key…")
    if kind == "claude":
        ok, why = assistant.test_key(key); field = "anthropic_key"
    elif kind == "groq":
        ok, why = assistant.test_groq_key(key); field = "groq_key"
    else:
        ok, why = assistant.test_gemini_key(key); field = "gemini_key"
    if not ok:
        return send_to(chat_id, f"❌ <b>{label} key not working:</b> {why}\n\nPaste a different key.", _AI_KB)
    user_store.update(chat_id, {field: key})
    assistant.clear_history(chat_id)
    send_to(chat_id,
            f"✅ <b>{label} key verified &amp; saved!</b>\n"
            "AI chat now runs on YOUR own quota. Try: <i>\"analyze EUR_USD\"</i> 🧠")


def _handle_broker(chat_id, args):
    b = (args or "").strip().lower()
    if b not in cfg.SUPPORTED_BROKERS:
        return send_to(chat_id,
                       "❌ Usage: <code>/broker oanda</code> or <code>/broker mt</code>\n\n"
                       "• <b>oanda</b> — direct API (easiest)\n"
                       "• <b>mt</b> — MetaTrader 5 via the ApexBridge EA "
                       "(IC Markets &amp; any MT5 broker)")
    _save_runtime({"BROKER": b})
    _apply("BROKER", b)
    if _bot_control.get("reload_broker"):
        _bot_control["reload_broker"]()
    if b == "mt":
        send_to(chat_id,
                "🔗 Broker set to <b>MetaTrader Bridge</b>.\n\n"
                "1. Set a secret: <code>/setkeys MT_BRIDGE_SECRET=choose_something_long</code>\n"
                "2. Install <b>ApexBridge.mq5</b> in MetaTrader (see docs/METATRADER.md)\n"
                "3. Put the same secret + your bot URL in the EA settings\n\n"
                "I'll start trading as soon as the EA connects.")
    else:
        send_to(chat_id, "✅ Broker set to <b>OANDA</b>. Use /setup if you need to enter credentials.")


def _handle_env(chat_id, args):
    env = (args or "").strip().lower()
    if env not in ("practice", "live"):
        return send_to(chat_id, "❌ Usage: <code>/env practice</code> or <code>/env live</code>")
    # cTrader users: the account type (demo/live) is fixed by the account they
    # linked — what /env really means for them is paper simulation vs. real
    # orders in that account. Route it there, or the command changes nothing.
    user = user_store.load(chat_id)
    if user.get("ctrader_access_token") and user.get("ctrader_account_id"):
        return _handle_paper(chat_id, "on" if env == "practice" else "off")
    # Per-user: the multi-user loop builds each broker from the user record, so the
    # env MUST be stored there or the change never reaches the running loop.
    user_store.update(chat_id, {"oanda_env": env})
    _restart_user_loop(chat_id)
    # Admin: also flip the global runtime config for the owner's own engine.
    if access.is_admin(str(chat_id)):
        _save_runtime({"OANDA_ENV": env})
        _apply("OANDA_ENV", env)
        if _bot_control.get("reload_broker"):
            _bot_control["reload_broker"]()
    icon = "🧪" if env == "practice" else "🔴"
    send_to(chat_id, f"{icon} OANDA environment set to <b>{env.upper()}</b>.\n"
                     f"<i>Make sure your token matches this environment.</i>")


def _handle_ctrader(chat_id):
    """Start the cTrader OAuth onboarding — sends the client an authorize link."""
    from apex import ctrader_oauth
    from apex.brokers import ctrader as ct
    if not ct.is_configured():
        return send_to(chat_id,
            "⚠️ cTrader isn't available yet — the operator must set "
            "CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET first.")
    link = ctrader_oauth.authorize_link(chat_id)
    if not link or "client_id=" not in link:
        return send_to(chat_id,
            "⚠️ cTrader redirect URL isn't configured (CTRADER_REDIRECT_URI / "
            "RENDER_EXTERNAL_URL). Ask the operator to set it.")
    scope = (getattr(cfg, "CTRADER_SCOPE", "trading") or "trading").lower()
    scope_line = ("🔐 Access requested: <b>trading</b> (place &amp; manage orders)\n\n" if scope == "trading" else
                  "⚠️ Access requested: <b>accounts — READ-ONLY</b>. Orders will be rejected! "
                  "The operator must set <code>CTRADER_SCOPE=trading</code> and redeploy first.\n\n")
    send_to(chat_id,
        "🟢 <b>Connect your cTrader account</b>\n\n"
        "1. Tap the button below\n"
        "2. Log in to cTrader and approve access\n"
        "3. You'll be sent back here automatically\n\n"
        f"{scope_line}"
        "Works with any cTrader broker (IC Markets, Pepperstone, FxPro…). "
        "Demo or live — your choice.\n\n"
        "<i>The link is valid for 10 minutes.</i>",
        extra={"reply_markup": {"inline_keyboard": [[
            {"text": "🔗 Authorize cTrader", "url": link}]]}})


def _handle_ctaccount(chat_id, args):
    """Pick which cTrader trading account to trade when the client has several."""
    want = (args or "").strip()
    user = user_store.load(chat_id)
    accounts = user.get("ctrader_accounts") or []
    if not accounts:
        return send_to(chat_id, "No cTrader accounts linked yet. Send /ctrader first.")
    if not want:
        lines = "\n".join(
            f"• <code>{a['ctid']}</code> — {'LIVE 🔴' if a.get('live') else 'demo 🧪'}"
            for a in accounts)
        return send_to(chat_id, f"Your cTrader accounts:\n{lines}\n\n"
                                "Pick one: <code>/ctaccount &lt;id&gt;</code>")
    match = next((a for a in accounts if str(a["ctid"]) == want), None)
    if not match:
        return send_to(chat_id, f"❌ No linked account with id <code>{want}</code>.")
    ct_env = "live" if match.get("live") else "demo"
    updates = {"ctrader_account_id": match["ctid"], "ctrader_env": ct_env}
    try:
        from apex.brokers import ctrader as _ct
        bal = _ct.account_balance(user.get("ctrader_access_token", ""), match["ctid"], ct_env)
        updates["paper_balance"] = bal
        bal_line = f"💰 Balance detected: <b>${bal:,.2f}</b> — paper mode starts from your real balance.\n"
    except Exception as e:
        bal_line = f"⚠️ Could not read the account balance yet: <i>{str(e)[:140]}</i>\n"
    user_store.update(chat_id, updates)
    _restart_user_loop(chat_id)
    env = "LIVE 🔴" if match.get("live") else "demo 🧪"
    send_to(chat_id, f"✅ Trading account set to <code>{match['ctid']}</code> ({env}).\n{bal_line}"
                     "Let's set you up — 3 quick taps and the bot is trading. 👇")
    onboard_start(chat_id)


_OB_SYMS = [
    ("EUR/USD", "EURUSD"), ("GBP/USD", "GBPUSD"), ("USD/JPY", "USDJPY"),
    ("AUD/USD", "AUDUSD"), ("USD/CHF", "USDCHF"), ("USD/CAD", "USDCAD"),
    ("🥇 Gold", "XAUUSD"), ("🥈 Silver", "XAGUSD"), ("₿ Bitcoin", "BTCUSD"),
    ("Ξ Ethereum", "ETHUSD"), ("📈 US30", "US30"), ("📈 NAS100", "NAS100"),
]

_RISK_TEXT = ("⚠️ <b>Before I place real orders — read this once.</b>\n\n"
              "This bot executes <b>your</b> strategy, with <b>your</b> settings, on <b>your</b> account.\n\n"
              "• No profit is guaranteed — results depend on your settings and the market\n"
              "• Trading with leverage carries substantial risk; losses are possible and they are <b>yours</b>\n"
              "• We provide the software — not financial advice, not a promised return\n"
              "• Only trade money you can afford to lose; test in paper mode first\n\n"
              "<i>Demo account = fake money 🧪 · Live account = real money 🔴</i>")


def onboard_start(chat_id):
    """Guided setup after the broker is connected: symbol → method → mode → go."""
    rows, row = [], []
    for label, code in _OB_SYMS:
        row.append({"text": label, "callback_data": f"ob:sym:{code}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    send_to(chat_id,
            "🧭 <b>Setup 1/3 — What do you want to trade?</b>\n\n"
            "Pick one to start — you can switch any time with /symbol, "
            "or browse your broker's full list with /pairs.",
            extra={"reply_markup": {"inline_keyboard": rows}})


def _ob_step_strategy(chat_id):
    from apex.ai import STRATEGY_MODES
    kb = [[{"text": "🤖 Auto — adapts to the market (recommended)", "callback_data": "ob:strat:auto"}],
          [{"text": "⭐ Mean Reversion", "callback_data": "ob:strat:mean_reversion"}],
          [{"text": "📈 Trend Following", "callback_data": "ob:strat:trend"}],
          [{"text": "🚀 Turtle Breakout", "callback_data": "ob:strat:breakout"}]]
    body = "\n\n".join(f"<b>{m['label']}</b> — <i>{m['blurb']}</i>" for m in STRATEGY_MODES.values())
    send_to(chat_id, f"🧭 <b>Setup 2/3 — Pick your trading method:</b>\n\n{body}",
            extra={"reply_markup": {"inline_keyboard": kb}})


def _ob_step_mode(chat_id):
    kb = [[{"text": "🧪 Paper — simulated, zero risk (recommended)", "callback_data": "ob:mode:paper"}],
          [{"text": "🔴 Real orders in my connected account", "callback_data": "ob:mode:real"}]]
    send_to(chat_id,
            "🧭 <b>Setup 3/3 — How should I trade?</b>\n\n"
            "📝 <b>Paper</b>: simulated balance on live prices — watch it work, risk-free.\n"
            "🔴 <b>Real</b>: every order executes in your connected account "
            "(demo account = still fake money 🧪).",
            extra={"reply_markup": {"inline_keyboard": kb}})


def _finish_onboard(chat_id):
    from apex.ai import STRATEGY_MODES
    u = user_store.load(chat_id)
    strat = STRATEGY_MODES.get((u.get("strategy") or "mean_reversion").lower(),
                               STRATEGY_MODES["mean_reversion"])["label"]
    mode = "📝 Paper (simulation)" if u.get("paper", True) else "🔴 Real orders"
    user_loop.stop(chat_id)
    user_loop.start(chat_id, alert_fn=_user_alert)
    send_to(chat_id,
            "🎉 <b>You're all set — the bot is running!</b>\n\n"
            f"💱 Symbol: <b>{u.get('symbol', 'EUR_USD')}</b>\n"
            f"🎯 Method: <b>{strat}</b>\n"
            f"⚙️ Mode: <b>{mode}</b>\n"
            f"⚖️ Risk: <b>{float(u.get('risk', 0.005)) * 100:g}%</b> per trade\n\n"
            "I analyze the market every few minutes and alert you on every move — "
            "with the reason in plain language.\n\n"
            "/terminal — live chart &amp; news terminal 📈\n"
            "/status — live overview\n"
            "/pairs · /strategy · /risk · /sl · /tp — tune anytime\n"
            "/env live · /env practice — real ↔ paper")


def _handle_cb(chat_id, data):
    """Inline-button presses (copilot approve/reject, risk acceptance, onboarding)."""
    if data.startswith("ob:sym:"):
        sym = data[7:]
        user_store.update(chat_id, {"symbol": sym})
        sugg = ("Suggested stops for gold: /sl 150 · /tp 300 (set after setup)" if sym.startswith("XAU")
                else "Suggested stops for indices: /sl 60 · /tp 120" if sym in ("US30", "NAS100")
                else "Suggested stops for crypto: /sl 200 · /tp 400" if sym.startswith(("BTC", "ETH"))
                else "")
        send_to(chat_id, f"✅ Trading symbol: <b>{sym}</b>" + (f"\n💡 <i>{sugg}</i>" if sugg else ""))
        return _ob_step_strategy(chat_id)
    if data.startswith("ob:strat:"):
        mode = data[9:]
        user_store.update(chat_id, {"strategy": mode})
        return _ob_step_mode(chat_id)
    if data == "ob:mode:paper":
        user_store.update(chat_id, {"paper": True})
        return _finish_onboard(chat_id)
    if data == "ob:mode:real":
        u = user_store.load(chat_id)
        if not u.get("risk_accepted"):
            return send_to(chat_id, _RISK_TEXT,
                           extra={"reply_markup": {"inline_keyboard": [[
                               {"text": "✅ I understand — I accept the risk", "callback_data": "ob:risk"}]]}})
        user_store.update(chat_id, {"paper": False})
        return _finish_onboard(chat_id)
    if data == "ob:risk":
        from datetime import datetime as _dt
        user_store.update(chat_id, {"risk_accepted": _dt.utcnow().isoformat(), "paper": False})
        return _finish_onboard(chat_id)
    if data == "risk:ok":
        from datetime import datetime as _dt
        user_store.update(chat_id, {"risk_accepted": _dt.utcnow().isoformat()})
        return _handle_paper(chat_id, "off")
    if data == "cp:y":
        sug = user_loop.pending_suggestion(str(chat_id))
        user_loop.clear_suggestion(str(chat_id))
        if not sug:
            return send_to(chat_id, "⌛ That suggestion expired. I'll send a fresh one on the next setup.")
        send_to(chat_id, f"✅ Approved — opening {sug['side']} {sug['symbol']}…")
        res = user_loop.force_trade(str(chat_id), sug["side"], sug["symbol"])
        if res.get("ok"):
            send_to(chat_id,
                    f"✅ <b>{sug['side']} {sug['symbol']}</b> @ {res['price']:.5f} | Units: {res['units']}\n"
                    f"SL: {res['sl']:.5f} | TP: {res['tp']:.5f}")
        else:
            send_to(chat_id, f"❌ Could not open: {_trade_err(res.get('error'))}")
    elif data == "cp:n":
        user_loop.clear_suggestion(str(chat_id))
        send_to(chat_id, "❌ Skipped. I'll keep watching and suggest the next setup.")


def _handle_market(chat_id):
    """Market Pulse: session awareness + the last computed volatility/trend read."""
    from apex import market
    user = user_store.load(chat_id)
    sym = user.get("symbol", cfg.SYMBOL)
    sess = market.session()
    dash = user_loop.get_dash(chat_id) if hasattr(user_loop, "get_dash") else None
    mp = (dash or {}).get("market") if dash else None

    lines = [f"📡 <b>Market Pulse — {sym}</b>", "━━━━━━━━━━━━━━━━━━━━",
             f"🕐 Session: <b>{sess['label']}</b>  (expected volatility: {sess['vol']})"]
    if not forex.is_market_open():
        lines.append("🔴 <b>Market closed</b> (weekend) — reopens Sunday 21:00 UTC.")
    if mp:
        lines.append(f"📊 Trend: <b>{mp['trend']}</b>")
        lines.append(f"🌊 Volatility: <b>{mp['volatility']}</b>  (ATR {mp['atrPct']}%)")
        if mp.get("volume"):
            lines.append(f"🔊 Volume: <b>{mp['volume']}</b>")
        lines.append(f"🎯 Momentum: <b>{mp['momentum']}</b>  (RSI {mp['rsi']})")
    lines.append(f"\n💡 <i>{sess['note']}</i>")
    lines.append("<i>How the market is moving right now — read before you trade.</i>")
    send_to(chat_id, "\n".join(lines))


def _handle_news(chat_id):
    from apex import news
    if not news.enabled():
        return send_to(chat_id, "📰 News guard is <b>off</b>. The bot is not avoiding news windows.")
    user = user_store.load(chat_id)
    pair = (user.get("symbol", cfg.SYMBOL) or "").split("_")
    events = news.upcoming(hours=24)
    if not events:
        return send_to(chat_id,
            "📰 <b>No high-impact events</b> in the next 24h (or the calendar feed is "
            "unavailable). Trading proceeds normally — the news guard is fail-open.")
    lines = []
    for e in events:
        flag = "⭐" if e["currency"] in [c.upper() for c in pair] else "•"
        h, m = divmod(e["in_min"], 60)
        when = f"{h}h {m}m" if h else f"{m}m"
        lines.append(f"{flag} <b>{e['currency']}</b> · {e['title']} — in {when}")
    send_to(chat_id, "📰 <b>Upcoming high-impact news (24h)</b>\n" + "\n".join(lines)
            + "\n\n<i>⭐ = affects your pair. The bot stays flat around these.</i>")


def _handle_copilot(chat_id, args):
    arg = (args or "").strip().lower()
    if arg in ("on", "1", "yes", "true"):
        user_store.update(chat_id, {"copilot": True})
        return send_to(chat_id,
            "🤖 <b>Copilot mode ON.</b>\nThe bot will <b>suggest</b> trades and wait for your "
            "✅ Approve before opening anything. You stay in control.\n\n<i>Turn off with /copilot off.</i>")
    if arg in ("off", "0", "no", "false"):
        user_store.update(chat_id, {"copilot": False})
        return send_to(chat_id,
            "🚀 <b>Autopilot mode ON.</b>\nThe bot opens trades automatically when a setup meets your "
            "thresholds. (Use /copilot on to require approval.)")
    cur = user_store.load(chat_id).get("copilot")
    return send_to(chat_id,
        f"🤖 Copilot is currently <b>{'ON (approval required)' if cur else 'OFF (autopilot)'}</b>.\n"
        "Use <code>/copilot on</code> or <code>/copilot off</code>.")


def _handle_paper(chat_id, args):
    on = (args or "").strip().lower() in ("on", "true", "yes", "1")
    # Real-order mode is gated behind an explicit, recorded risk acceptance —
    # the client owns the strategy, the settings and every loss.
    if not on:
        u0 = user_store.load(chat_id)
        if not u0.get("risk_accepted"):
            return send_to(chat_id, _RISK_TEXT,
                extra={"reply_markup": {"inline_keyboard": [[
                    {"text": "✅ I understand — I accept the risk", "callback_data": "risk:ok"}]]}})
    # Per-user first — the client's loop reads the user record, not the global cfg.
    user_store.update(chat_id, {"paper": on})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"PAPER_TRADING": str(on).lower()})
        _apply("PAPER_TRADING", on)
    if on:
        return send_to(chat_id, "📝 Paper trading <b>ON</b> — simulated balance, zero risk.")
    u = user_store.load(chat_id)
    env = (u.get("ctrader_env") or u.get("oanda_env") or "").lower()
    where = ("your <b>demo</b> account — still fake money 🧪" if env in ("demo", "practice")
             else "your <b>LIVE</b> account — real money 🔴")
    send_to(chat_id, f"🔴 Paper trading <b>OFF</b> — orders now execute in {where}.\n"
                     "Send /start if the bot isn't running.")


def _handle_risk(chat_id, args):
    try:
        pct = float((args or "").strip())
        if not (0.5 <= pct <= 10):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/risk 2</code>  (0.5–10%)")
    frac = pct / 100
    user_store.update(chat_id, {"risk": frac})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"RISK_PER_TRADE": frac})
        _apply("RISK_PER_TRADE", frac)
    send_to(chat_id, f"⚖️ Risk per trade set to <b>{pct:g}%</b> of balance.")


def _rr_note(chat_id):
    """Warn when the configured TP is smaller than the SL (RR < 1)."""
    u = user_store.load(chat_id)
    try:
        slv, tpv = float(u.get("sl_pips", 20)), float(u.get("tp_pips", 40))
    except (TypeError, ValueError):
        return ""
    if tpv < slv:
        return (f"\n⚠️ <i>Your TP ({tpv:g}p) is smaller than your SL ({slv:g}p) — "
                f"risk/reward {tpv / slv:.2f}. Winners must outpay losers: consider /tp {int(slv * 2)}.</i>")
    return ""


def _handle_sl(chat_id, args):
    try:
        pips = float((args or "").strip())
        if not (2 <= pips <= 200):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/sl 15</code>  (2–200 pips)")
    user_store.update(chat_id, {"sl_pips": pips})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"STOP_LOSS_PIPS": pips})
        _apply("STOP_LOSS_PIPS", pips)
    send_to(chat_id, f"🛡 Stop loss set to <b>{pips:g} pips</b>." + _rr_note(chat_id))


def _handle_tp(chat_id, args):
    try:
        pips = float((args or "").strip())
        if not (2 <= pips <= 500):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/tp 30</code>  (2–500 pips)")
    user_store.update(chat_id, {"tp_pips": pips})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"TAKE_PROFIT_PIPS": pips})
        _apply("TAKE_PROFIT_PIPS", pips)
    send_to(chat_id, f"🎯 Take profit set to <b>{pips:g} pips</b>." + _rr_note(chat_id))


def _handle_symbol(chat_id, args):
    sym = (args or "").strip().upper().replace("/", "_").replace("-", "_").replace(" ", "")
    user = user_store.load(chat_id)
    is_ct = bool(user.get("ctrader_access_token") and user.get("ctrader_account_id"))
    if is_ct:
        # cTrader accounts offer far more than FX majors (gold, indices, crypto
        # CFDs…) — validate against what THIS account actually offers.
        if not re.match(r"^[A-Z0-9_]{3,16}$", sym):
            return send_to(chat_id, "❌ Usage: <code>/symbol EUR_USD</code> — see /pairs for everything you can trade.")
        try:
            from apex import user_loop as _ul
            br, _ = _ul._make_broker(user)
            br._symbol_id(sym)   # raises if the account doesn't offer it
        except ValueError:
            return send_to(chat_id, f"❌ Your broker doesn't offer <b>{sym}</b>. Send /pairs to see what's available.")
        except Exception as e:
            return send_to(chat_id, f"⚠️ Couldn't verify the symbol right now: <i>{str(e)[:120]}</i>. Try again in a minute.")
    elif not _PAIR_RE.match(sym):
        return send_to(chat_id, "❌ Usage: <code>/symbol EUR_USD</code>")
    user_store.update(chat_id, {"symbol": sym})
    running = _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"TRADE_SYMBOL": sym})
        _apply("TRADE_SYMBOL", sym)
        cfg.SYMBOL = sym
    warn = ""
    if not running and not user_loop.is_running(chat_id):
        warn += "\n⏸ <i>The bot is currently stopped — send /start to trade this symbol.</i>"
    if is_ct and not _PAIR_RE.match(sym):
        s_norm = sym.replace("_", "")
        sugg = ("/sl 150 · /tp 300" if s_norm.startswith("XAU")
                else "/sl 60 · /tp 120" if s_norm.startswith(("US30", "NAS", "GER", "SPX", "US500", "USTEC", "JPN", "UK100"))
                else "/sl 200 · /tp 400" if s_norm.startswith(("BTC", "ETH"))
                else None)
        warn += ("\n💡 <i>Pip conventions for metals, indices and crypto CFDs are handled "
                "automatically. Volatile instruments need wider stops than FX"
                + (f" — suggested here: <b>{sugg}</b>" if sugg else "")
                + ". Watch the first trades in paper mode.</i>")
    send_to(chat_id, f"💱 Trading symbol set to <b>{sym}</b>.{warn}")


def _sim_strategy(mode, candles, symbol, sl_pips, tp_pips, risk, balance0):
    """Compact real-data simulator for /backtest — same signal engines and the
    live exit checker, evaluated on candle closes. Spread/slippage not modeled,
    so treat results as method COMPARISON, not a profit forecast."""
    from apex.position import check_position
    from apex import ai as _ai, strategies as _st, indicators as _ind, forex as _fx
    pip = _fx.pip_size(symbol, candles[-1]["close"] if candles else None)
    bal, pos, trades = balance0, None, []
    for i in range(220, len(candles)):
        win = candles[:i + 1]
        px = win[-1]["close"]
        ind = _ind.analyze(win)
        st = _st.analyze(win)
        if pos:
            trig = check_position(pos, px)
            if not trig:
                sx = _ai.signal_for_mode(mode, ind, st, pos)
                if sx.get("action") == "CLOSE":
                    trig = "STRATEGY"
            if trig:
                pnl = _fx.pnl_usd(pos["side"], pos["entryPrice"], px, pos["quantity"], symbol)
                bal += pnl
                trades.append(pnl)
                pos = None
            continue
        sx = _ai.signal_for_mode(mode, ind, st, None)
        if sx.get("action") in ("BUY", "SELL") and sx.get("confidence", 0) >= 62:
            d = 1 if sx["action"] == "BUY" else -1
            sl = px - d * sl_pips * pip
            tp = px + d * tp_pips * pip
            units = _fx.calc_units(bal, risk, sl_pips, symbol, px)
            pos = {"symbol": symbol, "side": sx["action"], "entryPrice": px,
                   "quantity": max(int(units), 1000), "stopLoss": sl, "takeProfit": tp,
                   "initialStop": sl, "trailHigh": px if d == 1 else None,
                   "trailLow": px if d == -1 else None}
    if pos:
        pnl = _fx.pnl_usd(pos["side"], pos["entryPrice"], candles[-1]["close"], pos["quantity"], symbol)
        bal += pnl
        trades.append(pnl)
    wins = [t for t in trades if t > 0]
    return {"n": len(trades), "w": len(wins), "net": bal - balance0}


def _handle_backtest(chat_id, args):
    """Admin: compare all strategy methods on REAL candles from the linked broker."""
    if not access.is_admin(str(chat_id)):
        return send_to(chat_id, "⛔ Admin only.")
    user = user_store.load(chat_id)
    sym = user.get("symbol", cfg.SYMBOL)
    send_to(chat_id, f"⏳ Pulling real {sym} candles and simulating all methods — 1-2 minutes…")

    def run():
        try:
            from apex import user_loop as _ul
            from apex.ai import STRATEGY_MODES
            br, ucfg = _ul._make_broker(user)
            candles = br.get_candles(sym, "5m", 1000)
            if not candles or len(candles) < 400:
                return send_to(chat_id, f"❌ Not enough data ({len(candles or [])} candles).")
            days = (len(candles) - 220) * 5 / 1440
            bal0 = float(user.get("paper_balance", 1000))
            lines = []
            for key, m in STRATEGY_MODES.items():
                r = _sim_strategy(key, candles, sym, ucfg.STOP_LOSS_PIPS,
                                  ucfg.TAKE_PROFIT_PIPS, ucfg.RISK_PER_TRADE, bal0)
                wr = f"{r['w'] / r['n'] * 100:.0f}%" if r["n"] else "—"
                lines.append(f"<b>{m['label']}</b>: {r['n']} trades · win {wr} · "
                             f"net {'+' if r['net'] >= 0 else ''}${r['net']:.2f}")
            send_to(chat_id,
                    f"📊 <b>Method comparison — {sym}, last ~{days:.1f} days (real data)</b>\n\n"
                    + "\n".join(lines) +
                    "\n\n<i>Same entries/exits as live, evaluated on candle closes; spread "
                    "not modeled — use for comparing methods, not as a profit promise. "
                    "Short sample: markets change. Switch with /strategy.</i>")
        except Exception as e:
            send_to(chat_id, f"❌ Backtest failed: {str(e)[:180]}")

    threading.Thread(target=run, daemon=True).start()


def _handle_strategy(chat_id, args):
    """Pick the trading method — the per-user loop and the AI prompt follow it."""
    from apex.ai import STRATEGY_MODES
    aliases = {"mean": "mean_reversion", "mr": "mean_reversion", "mean_reversion": "mean_reversion",
               "reversion": "mean_reversion", "trend": "trend", "trending": "trend",
               "breakout": "breakout", "turtle": "breakout",
               "auto": "auto", "adaptive": "auto", "ai": "auto"}
    want = aliases.get((args or "").strip().lower().replace("-", "_"))
    user = user_store.load(chat_id)
    current = (user.get("strategy") or "auto").lower()
    if not want:
        lines = "\n\n".join(
            f"{'✅ ' if key == current else ''}<b>{m['label']}</b> — <code>/strategy {key.split('_')[0]}</code>\n<i>{m['blurb']}</i>"
            for key, m in STRATEGY_MODES.items())
        return send_to(chat_id,
            f"🎯 <b>Trading method</b> (current: <b>{STRATEGY_MODES[current]['label']}</b>)\n\n{lines}\n\n"
            "<i>Switching restarts your loop instantly. Test a new method in paper mode first.</i>")
    user_store.update(chat_id, {"strategy": want})
    running = _restart_user_loop(chat_id)
    m = STRATEGY_MODES[want]
    tail = ("Applied immediately — check /status." if running
            else "⏸ The bot is currently <b>stopped</b> — send /start to begin trading with it.")
    send_to(chat_id, f"🎯 Method set to <b>{m['label']}</b>.\n<i>{m['blurb']}</i>\n\n{tail}")


def _handle_pairs(chat_id):
    """List everything the client's linked cTrader account can trade."""
    user = user_store.load(chat_id)
    if not (user.get("ctrader_access_token") and user.get("ctrader_account_id")):
        return send_to(chat_id,
            "💱 <b>Available pairs</b> (connect cTrader with /ctrader to see your broker's full list):\n"
            "EUR_USD · GBP_USD · USD_JPY · AUD_USD · USD_CAD · NZD_USD · USD_CHF · EUR_GBP")
    try:
        from apex import user_loop as _ul
        br, _ = _ul._make_broker(user)
        br._load_symbols()
        names = sorted(br._sym_id.keys())
    except Exception as e:
        return send_to(chat_id, f"⚠️ Couldn't load the symbol list: <i>{str(e)[:140]}</i>. Try again in a minute.")
    if not names:
        return send_to(chat_id, "⚠️ Your broker returned no tradable symbols. Check the account in cTrader.")
    # Curate: a raw alphabetical dump starts with thousands of stock-CFD codes.
    ccy = {"EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "SEK", "NOK", "DKK",
           "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH", "NOK", "RON"}
    fx      = [n for n in names if len(n) == 6 and n[:3] in ccy and n[3:] in ccy]
    metals  = [n for n in names if n.startswith(("XAU", "XAG", "XPT", "XPD"))]
    crypto  = [n for n in names if n[:3] in {"BTC", "ETH", "SOL", "XRP", "ADA", "LTC", "BNB", "DOT", "BCH", "DOG"}]
    indices = [n for n in names if re.match(r"^[A-Z]{2,6}\d{2,3}$", n) and n not in fx]
    other   = len(names) - len(fx) - len(metals) - len(crypto) - len(indices)
    def _sec(title, lst, cap):
        if not lst:
            return ""
        cut = lst[:cap]
        extra = f" <i>+{len(lst) - cap} more</i>" if len(lst) > cap else ""
        return f"\n<b>{title}</b>\n{' · '.join(cut)}{extra}\n"
    send_to(chat_id,
            f"💱 <b>Your broker offers {len(names)} instruments.</b> The bot can trade any of them:\n"
            + _sec("Forex", fx, 36)
            + _sec("Metals", metals, 8)
            + _sec("Indices", indices, 14)
            + _sec("Crypto CFDs", crypto, 14)
            + (f"\n…plus <b>{other}</b> stock CFDs &amp; other instruments — find the code in cTrader "
               "and set it directly.\n" if other > 0 else "")
            + "\nPick one with <code>/symbol NAME</code> (e.g. <code>/symbol XAUUSD</code>).\n"
              "<i>Metals, indices and crypto pip conventions are handled automatically — still, watch a new symbol in paper first.</i>")


def _trade_err(err):
    """Human explanation for the errors clients actually hit."""
    e = str(err or "?")
    if "permission" in e.lower():
        return (e + "\n\n💡 Your cTrader authorization is <b>read-only</b>. "
                "Send /ctrader and approve again — the new link requests <b>trading</b> access. "
                "(If it still says read-only, the operator must set CTRADER_SCOPE=trading and redeploy.)")
    if "not offered" in e.lower():
        return e + "\n\n💡 Send /pairs to see what your broker offers."
    return e


def send_photo(chat_id, png, caption=""):
    """Send a PNG to the chat (used for /chart and entry snapshots)."""
    try:
        requests.post(f"{_API}/sendPhoto",
                      data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                      files={"photo": ("chart.png", png, "image/png")}, timeout=25)
    except Exception as e:
        print(f"[TELEGRAM] send_photo failed: {e}")


def _send_chart_async(chat_id, symbol=None, position=None, caption=""):
    """Render + send the chart without blocking the caller (alerts, commands)."""
    def run():
        try:
            from apex import chart, user_loop as _ul
            user = user_store.load(chat_id)
            sym = symbol or user.get("symbol", cfg.SYMBOL)
            br, ucfg = _ul._make_broker(user)
            candles = br.get_candles(sym, ucfg.TIMEFRAME, 130)
            if not candles:
                return send_to(chat_id, "⚠️ No chart data available right now.")
            pos = position
            if pos is None:
                dash = _ul.get_dash(chat_id) or {}
                pos = dash.get("openPosition")
            png = chart.render(candles, sym, ucfg.TIMEFRAME, pos)
            send_photo(chat_id, png, caption)
        except Exception as e:
            print(f"[TELEGRAM] chart failed: {e}")
    threading.Thread(target=run, daemon=True).start()


def _handle_atr(chat_id, args):
    on = (args or "").strip().lower() in ("on", "true", "1", "yes")
    user_store.update(chat_id, {"atr_stops": on})
    running = _restart_user_loop(chat_id)
    if on:
        msg = ("📐 <b>Dynamic ATR stops ON</b> — SL = 1.5×ATR, TP = 3×ATR: distances "
               "breathe with the market's volatility instead of fixed pips. "
               "Position size still respects your /risk %.")
    else:
        msg = "📏 Dynamic ATR stops <b>OFF</b> — using your fixed /sl and /tp pip distances."
    if not running and not user_loop.is_running(chat_id):
        msg += "\n⏸ <i>The bot is stopped — send /start to apply.</i>"
    send_to(chat_id, msg)


def _handle_stats(chat_id):
    """Performance report from the persistent trade journal (premium spec #10)."""
    from apex import stats as stats_mod
    trades = user_store.load_trades(chat_id)
    dash = user_loop.get_dash(chat_id) or {}
    st = stats_mod.compute(trades, dash.get("skipsToday", 0))
    if not st["trades"]:
        return send_to(chat_id, "📊 No closed trades in the journal yet — run the bot and stats will build up here.")
    pf = st["profitFactor"]
    pf_s = "∞" if pf == float("inf") else (f"{pf:.2f}" if pf is not None else "—")
    def money(v):
        return f"+${v:,.2f}" if v >= 0 else f"−${abs(v):,.2f}"
    t = st["today"]
    send_to(chat_id,
            f"📊 <b>Performance</b> — last {st['trades']} closed trades\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ {st['wins']}W / ❌ {st['losses']}L · Win rate <b>{st['winRate']:.0f}%</b>\n"
            f"⚖️ Profit factor: <b>{pf_s}</b> · Net: <b>{money(st['netPnl'])}</b>\n"
            f"📈 Avg win {money(st['avgWin'])} · Avg loss {money(st['avgLoss'])}\n"
            f"🏆 Best {money(st['best'])} · 💥 Worst {money(st['worst'])}\n"
            f"📉 Max drawdown: <b>{st['maxDrawdownPct']:.1f}%</b>\n\n"
            f"<b>Today:</b> {t['trades']} trades · {money(t['netPnl'])} · "
            f"{t['skips']} weak setups rejected 🛡\n\n"
            f"<i>Full breakdown, equity curve &amp; rejection journal: /terminal</i>")


def _handle_terminal(chat_id):
    """Open the Telegram Mini App — live interactive chart, position, news."""
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base:
        return send_to(chat_id, "⚠️ Terminal URL not configured (RENDER_EXTERNAL_URL).")
    send_to(chat_id,
            "📈 <b>Apex Terminal</b>\n\n"
            "Live interactive chart (pinch to zoom, drag to pan), your position with "
            "entry/SL/TP lines, balance, upcoming market events and your trade history — "
            "all in one screen.",
            extra={"reply_markup": {"inline_keyboard": [[
                {"text": "📈 Open Terminal", "web_app": {"url": f"{base}/app"}}]]}})


def _handle_chart(chat_id, args=None):
    sym = (args or "").strip().upper().replace("/", "_").replace("-", "_") or None
    send_to(chat_id, "🖼 Rendering your chart…")
    _send_chart_async(chat_id, symbol=sym or None,
                      caption="Live view — candles, EMA 20/50" +
                              (", entry/SL/TP" if not sym else ""))


def _handle_buy(chat_id, args):
    sym = (args or "").strip().upper().replace("/", "_").replace("-", "_")
    if not sym:
        user = user_store.load(chat_id)
        sym = user.get("symbol", cfg.SYMBOL)
    send_to(chat_id, f"⚡ Opening <b>BUY {sym}</b>…")
    result = user_loop.force_trade(str(chat_id), "BUY", sym)
    if result.get("ok"):
        send_to(chat_id,
                f"✅ <b>BUY {sym}</b> entered\n"
                f"Price: <b>{result['price']:.5f}</b> | Units: {result['units']}\n"
                f"SL: {result['sl']:.5f} | TP: {result['tp']:.5f}\n"
                f"Spread: {result['spread']}p")
    else:
        send_to(chat_id, f"❌ Could not open trade: {_trade_err(result.get('error'))}")


def _handle_sell(chat_id, args):
    sym = (args or "").strip().upper().replace("/", "_").replace("-", "_")
    if not sym:
        user = user_store.load(chat_id)
        sym = user.get("symbol", cfg.SYMBOL)
    send_to(chat_id, f"⚡ Opening <b>SELL {sym}</b>…")
    result = user_loop.force_trade(str(chat_id), "SELL", sym)
    if result.get("ok"):
        send_to(chat_id,
                f"✅ <b>SELL {sym}</b> entered\n"
                f"Price: <b>{result['price']:.5f}</b> | Units: {result['units']}\n"
                f"SL: {result['sl']:.5f} | TP: {result['tp']:.5f}\n"
                f"Spread: {result['spread']}p")
    else:
        send_to(chat_id, f"❌ Could not open trade: {_trade_err(result.get('error'))}")


def _handle_close(chat_id):
    result = user_loop.force_close(str(chat_id))
    if result.get("ok"):
        net = result.get("netPnl", 0)
        icon = "✅" if net >= 0 else "❌"
        send_to(chat_id,
                f"🔒 <b>Position closed</b>\n"
                f"Price: <b>{result.get('price', '—')}</b>\n"
                f"{icon} Net P&amp;L: <b>{'+' if net >= 0 else ''}${net:.2f}</b> "
                f"<i>(gross ${result.get('grossPnl', 0):.2f} − cost ${result.get('costUsd', 0):.2f})</i>")
    else:
        send_to(chat_id, f"❌ {result.get('error', 'No open position')}")


def _handle_deploy(chat_id):
    import subprocess
    import threading
    send_to(chat_id, "🔄 <b>Deploying latest code...</b>\n<i>This takes ~30 seconds.</i>")
    pull_cmd = " && ".join([
        "export PATH=/usr/local/bin:/usr/bin:/usr/local/sbin:/usr/sbin:/bin:/sbin:$PATH",
        "cd /opt/apex-forex",
        "git fetch origin claude/arcads-external-api-gExX7",
        "git reset --hard origin/claude/arcads-external-api-gExX7",
        "cd apex-forex-bot",
        "pip3 install -q -r requirements.txt",
    ])

    def _run():
        result = subprocess.run(pull_cmd, shell=True, executable="/bin/bash",
                                capture_output=True, text=True, timeout=110)
        if result.returncode != 0:
            send_to(chat_id, f"❌ <b>Deploy failed:</b>\n<code>{(result.stderr or result.stdout)[:500]}</code>")
            return
        send_to(chat_id, "✅ <b>Deploy successful!</b> Restarting Forex Bot...\n\nSend /status when ready.")
        import time
        time.sleep(1)
        subprocess.run("systemctl restart apex-forex", shell=True, executable="/bin/bash")

    threading.Thread(target=_run, daemon=True).start()


def _handle_grant(chat_id, args):
    target = (args or "").strip()
    if not target.lstrip("-").isdigit():
        return send_to(chat_id, "❌ Usage: <code>/grant 123456789</code>")
    if access.grant(target):
        send_to(chat_id, f"✅ Access granted to <code>{target}</code>.")
        send_to(target, "✅ <b>You now have access to Apex Forex Bot!</b>\nSend /status to check trading.")
    else:
        send_to(chat_id, f"ℹ️ <code>{target}</code> already has access.")


def _handle_revoke(chat_id, args):
    target = (args or "").strip()
    if not target.lstrip("-").isdigit():
        return send_to(chat_id, "❌ Usage: <code>/revoke 123456789</code>")
    if access.revoke(target):
        send_to(chat_id, f"✅ Access revoked for <code>{target}</code>.")
        send_to(target, "⛔ Your access to Apex Forex Bot has been revoked.")
    else:
        send_to(chat_id, f"ℹ️ <code>{target}</code> not found or is an admin.")


def _handle_users(chat_id):
    admins  = access.list_admins()
    clients = access.list_clients()
    admin_lines  = "\n".join(f"👑 {a}" for a in admins) or "—"
    client_lines = "\n".join(f"✅ {c}" for c in clients) or "— none yet —"
    send_to(chat_id,
            f"👥 <b>ACCESS LIST</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Admins:</b>\n{admin_lines}\n\n"
            f"<b>Paying clients ({len(clients)}):</b>\n{client_lines}\n\n"
            f"<code>/grant ID</code> — give access\n"
            f"<code>/revoke ID</code> — remove access")


def _fx_why_block(result) -> str:
    """Human-readable 'why I took this trade' block for open alerts."""
    parts = []
    reasoning = (result.get("reasoning") or "").strip()
    if reasoning:
        parts.append(f"🧠 <i>{reasoning}</i>")
    factors = result.get("keyFactors") or []
    if factors:
        parts.append("📊 " + " · ".join(str(f) for f in factors[:4]))
    return ("\n" + "\n".join(parts)) if parts else ""


def _fx_close_why(reason: str) -> str:
    """Plain-language explanation for a mechanical (non-AI) close."""
    m = {
        "TAKE_PROFIT": "Target reached — locking in the profit.",
        "STOP_LOSS": "Stop hit — cutting the loss to protect capital.",
        "AI_CLOSE": "The AI judged the setup had played out.",
    }
    txt = m.get(reason, "")
    return f"\n🧠 <i>{txt}</i>" if txt else ""


def _user_alert(uid, result):
    """Per-user trade/heartbeat/error alert — module-level so setup auto-start,
    /start and auto-restore all share the same notification formatting."""
    action = result.get("action", "")
    sym = result.get("symbol", cfg.SYMBOL)
    if action == "HEARTBEAT":
        send_to(uid,
                f"💓 <b>Bot alive</b> — {sym}\n"
                f"Price: <b>{result.get('price', '—')}</b> | "
                f"Balance: <b>${result.get('balance', 0):.2f}</b>"
                f"{result.get('posInfo', '')}")
    elif action == "AI_ERROR":
        send_to(uid,
                f"⚠️ <b>AI temporarily unavailable</b>\n"
                f"Bot continues with rule-based signals — trading is not interrupted.\n"
                f"<i>{result.get('reason', '')[:120]}</i>")
    elif action == "DATA_ERROR":
        send_to(uid,
                f"⚠️ <b>Market data problem</b> — {sym}\n"
                f"I can't fetch prices from <b>{result.get('broker', 'your broker')}</b>:\n"
                f"<i>{result.get('reason', '')[:160]}</i>\n\n"
                "I retry every 30s automatically. If this keeps up, "
                "send /ctrader to re-connect your account.")
    elif action == "STOP":
        reasons = ", ".join(result.get("reasons", ["risk limit"]))
        send_to(uid, f"🛑 <b>Trading paused — risk limit hit</b>\n{reasons}")
    elif action == "SKIP_WARN":
        send_to(uid, f"⚠️ <b>Holding off on {result.get('symbol', sym)}</b>\n"
                     f"<i>{result.get('reason', 'market conditions are unfavourable right now')}.</i>\n"
                     "I'll take the trade as soon as conditions normalise.")
    elif action == "MARKET_PULSE":
        vol = f" · Volume: <b>{result['volume']}</b>" if result.get("volume") else ""
        send_to(uid,
                f"📡 <b>Market Pulse — {result.get('symbol', sym)}</b>\n"
                f"Volatility: <b>{result.get('volatility')}</b>{vol}\n"
                f"Trend: {result.get('trend')} · Momentum: {result.get('momentum')}\n"
                "<i>Conditions just shifted — trade with extra care.</i>")
    elif action == "FLASH_WARN":
        send_to(uid, f"🚨 <b>Extreme volatility on {result.get('symbol', sym)}</b>\n"
                     "<i>A violent price spike just printed — opening into it is too risky.</i>\n"
                     "Trading pauses until the market settles.")
    elif action == "NEWS_WARN":
        ev = result.get("event", {})
        send_to(uid, f"📰 <b>High-impact news — staying flat on {result.get('symbol', sym)}</b>\n"
                     f"<i>{ev.get('currency', '')} · {ev.get('title', 'event')} in ~{ev.get('mins', 0)} min.</i>\n"
                     "Spreads blow out and price gaps around releases — I'll resume once it passes.")
    elif action == "SUGGEST":
        d = "🟢 BUY" if result.get("side") == "BUY" else "🔴 SELL"
        send_to(uid,
                f"🤖 <b>Copilot suggestion</b>\n{d} <b>{sym}</b> @ {result.get('price', '—')}"
                + _fx_why_block(result) +
                "\n\n<i>You're in copilot mode — approve to execute, or reject to skip.</i>",
                extra={"reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Approve", "callback_data": "cp:y"},
                    {"text": "❌ Reject", "callback_data": "cp:n"}]]}})
    elif action in ("BUY", "SELL"):
        spread = result.get("spreadPips")
        spread_line = f" | Spread: {spread}p" if spread is not None else ""
        d = "🟢 LONG" if action == "BUY" else "🔴 SHORT"
        rr_line = ""
        try:
            sl_, tp_, px_ = result.get("stopLoss"), result.get("takeProfit"), result.get("price")
            if sl_ and tp_ and px_ and abs(px_ - sl_) > 0:
                rr_line = f"\n🎯 SL <b>{sl_:g}</b> · TP <b>{tp_:g}</b> · RR <b>1:{abs(tp_ - px_) / abs(px_ - sl_):.1f}</b>"
        except (TypeError, ValueError):
            pass
        send_to(uid,
                f"{d} <b>{action}</b> — {sym}\n"
                f"Price: <b>{result.get('price', '—')}</b> | "
                f"Confidence: <b>{result.get('confidence', 0)}%</b>{spread_line}{rr_line}"
                + _fx_why_block(result))
        _send_chart_async(uid, symbol=sym, position={
            "side": action, "entryPrice": result.get("price"),
            "stopLoss": result.get("stopLoss"), "takeProfit": result.get("takeProfit")},
            caption=f"{d} {sym} — entry, SL &amp; TP on the chart")
    elif action == "CLOSE":
        net = result.get("netPnl")
        _reason_lbl = {"STOP_LOSS": "🛑 Stop loss hit",
                       "TAKE_PROFIT": "🎯 Take profit hit"}.get(result.get("reason"))
        why = (f"\n🧠 <i>{result['reasoning']}</i>" if result.get("reasoning")
               else _fx_close_why(result.get("reason", "")))
        if net is not None:
            icon = "✅" if net >= 0 else "❌"
            head = f"🔒 <b>Position closed</b> — {sym}"
            if _reason_lbl:
                head = f"{_reason_lbl} — {sym}"
            send_to(uid,
                    f"{head}\n"
                    f"Exit: <b>{result.get('price', '—')}</b>\n"
                    f"{icon} Net P&amp;L: <b>{'+' if net >= 0 else ''}${net:.2f}</b> "
                    f"<i>(gross ${result.get('grossPnl', 0):.2f} − cost ${result.get('costUsd', 0):.2f})</i>\n"
                    f"💼 Balance: <b>${result.get('balance', 0):.2f}</b>"
                    + why)
        else:
            send_to(uid,
                    f"🔒 <b>Position closed</b> — {sym}\n"
                    f"Price: <b>{result.get('price', '—')}</b>" + why)
    elif action == "BROKER_HEALTH":
        if result.get("status") == "degraded":
            send_to(uid,
                    f"🩺 <b>Broker health warning</b> — {sym}\n"
                    f"<i>{result.get('reason', 'execution conditions degraded')}</i>\n\n"
                    "Entries are <b>suspended</b> until conditions normalise — degraded "
                    "execution silently eats the edge. Open positions stay protected by their stops.")
        else:
            send_to(uid, f"🩺 <b>Broker conditions back to normal</b> — {sym}. Trading resumes.")
    elif action == "BROKER_CLOSE":
        pnl = result.get("netPnl")
        icon = "✅" if (pnl or 0) >= 0 else "❌"
        pnl_line = (f"{icon} Realized P&amp;L: <b>{'+' if pnl >= 0 else ''}${pnl:.2f}</b>\n"
                    if pnl is not None else "")
        send_to(uid,
                f"🎯 <b>Your broker closed the position</b> — {sym}\n"
                f"{result.get('side', '')} from <b>{result.get('entryPrice', '—')}</b> → "
                f"≈ <b>{result.get('price', '—')}</b> (stop-loss or take-profit executed at cTrader)\n"
                f"{pnl_line}"
                f"💼 Balance: <b>${result.get('balance', 0):.2f}</b>")
    else:
        send_to(uid, f"⚡ <b>{action}</b> — {sym}")


def _handle_report(chat_id):
    """Trade journal summary — net P&L, costs, win rate. For tax reporting."""
    trades = user_store.load_trades(chat_id)
    if not trades:
        return send_to(chat_id,
                       "📒 <b>No closed trades yet.</b>\n"
                       "Your tax journal fills up as the bot closes positions.")
    total_net = sum(t.get("netPnl", 0) or 0 for t in trades)
    total_cost = sum(t.get("costUsd", 0) or 0 for t in trades)
    total_gross = sum(t.get("grossPnl", 0) or 0 for t in trades)
    wins = sum(1 for t in trades if (t.get("netPnl", 0) or 0) > 0)
    n = len(trades)
    win_rate = wins / n * 100 if n else 0
    lines = []
    for t in trades[-10:][::-1]:
        net = t.get("netPnl", 0) or 0
        icon = "✅" if net >= 0 else "❌"
        lines.append(f"{icon} {t.get('symbol','?')}  {t.get('entry','?')}→{t.get('exit','?')}  "
                     f"<b>{'+' if net >= 0 else ''}${net:.2f}</b>  <i>{(t.get('time') or '')[:16]}</i>")
    send_to(chat_id,
            f"📒 <b>Trade Journal &amp; Tax Report</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Closed trades: <b>{n}</b>   Win rate: <b>{win_rate:.0f}%</b>\n"
            f"Gross P&amp;L: <b>${total_gross:.2f}</b>\n"
            f"Costs (spread): <b>−${total_cost:.2f}</b>\n"
            f"<b>NET P&amp;L: {'+' if total_net >= 0 else ''}${total_net:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Last {min(10, n)} trades:</b>\n" + "\n".join(lines) + "\n"
            f"<i>Every closed trade is logged with entry, exit, fees and net P&amp;L "
            f"for your tax records.</i>")


def _auto_start_user(chat_id):
    """Start a user's trading loop with the shared alert function."""
    if user_loop.is_running(chat_id):
        return False
    return user_loop.start(chat_id, alert_fn=_user_alert)


def _restart_user_loop(chat_id):
    """Restart a running loop so it rebuilds the broker from the user record.

    The loop reads the user record + builds the broker ONCE at start
    (user_loop._loop), so config changes like oanda_env only take effect on a
    fresh loop. No-op if the user isn't currently trading.
    """
    if not user_loop.is_running(chat_id):
        return False
    user_loop.stop(chat_id)
    return user_loop.start(chat_id, alert_fn=_user_alert)


def _handle_start(chat_id):
    user = user_store.load(chat_id)
    # Check user has credentials set up
    if not access.is_admin(str(chat_id)) and not user.get("oanda_token") and not user.get("paper"):
        return send_to(chat_id,
            "⚙️ <b>Setup required first!</b>\n\n"
            "Send /setup to start in paper mode, or /ctrader to connect a live account.")
    if user_loop.is_running(chat_id):
        return send_to(chat_id, "▶️ Bot is already running. Send /status to check.")

    _auto_start_user(chat_id)
    send_to(chat_id, "▶️ <b>Your bot started!</b> Trading is now active.\nSend /status to monitor.", _dashboard_keyboard())


def _handle_stop(chat_id):
    user_loop.stop(chat_id)
    # Also pause global bot for admin
    if access.is_admin(str(chat_id)) and _bot_control.get("set_paused"):
        _bot_control["set_paused"](True)
    send_to(chat_id, "⏸️ <b>Bot paused.</b> No new trades will open.\nSend /start to resume.")


def _handle_config(chat_id):
    keys = _BROKER_KEYS.get(cfg.BROKER, [])
    key_lines = "\n".join(
        f"  {k}: {_mask(getattr(cfg, k, '')) if getattr(cfg, k, '') else '—'}"
        for k in keys)
    paused = _bot_control.get("get_paused", lambda: False)()
    state_tag = "⏸️ PAUSED" if paused else "▶️ RUNNING"
    key_title = "MT bridge" if cfg.BROKER == "mt" else "OANDA"
    send_to(chat_id,
            f"⚙️ <b>Config</b>  [{state_tag}]\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Broker:    <b>{_broker_label()}</b>\n"
            f"Pair:      <b>{cfg.SYMBOL}</b>\n"
            f"Timeframe: <b>{cfg.TIMEFRAME}</b>\n"
            f"Paper:     <b>{'ON' if cfg.PAPER_TRADING else 'OFF'}</b>\n"
            f"Risk:      <b>{cfg.RISK_PER_TRADE * 100:g}%</b>\n"
            f"SL/TP:     <b>{cfg.STOP_LOSS_PIPS:g} / {cfg.TAKE_PROFIT_PIPS:g} pips</b>\n"
            f"Leverage:  <b>1:{cfg.LEVERAGE:g}</b>\n"
            f"Min conf:  <b>{cfg.MIN_CONFIDENCE}%</b>\n"
            f"Interval:  <b>{cfg.LOOP_INTERVAL_MS // 60000}m</b>\n\n"
            f"🔑 {key_title} keys:\n{key_lines or '  (none set — use /setup)'}")


_HELP_CLIENT = ("📋 <b>APEX FOREX BOT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "/setup — choose paper/live, pair, risk (start here)\n"
                "/status — live trading snapshot\n"
                "/market — session + how the market is moving now\n"
                "/report — trade journal + net P&amp;L (for taxes)\n"
                "/buy EUR_USD — open a BUY manually (any pair you want)\n"
                "/sell EUR_USD — open a SELL manually\n"
                "/close — close current position\n"
                "/ctrader — connect your cTrader account (any broker, worldwide)\n"
                "/copilot on|off — approve trades yourself vs auto-trade\n"
                "/news — high-impact events (bot stays flat around them)\n"
                "/ai — connect your own free/paid AI key for smart chat\n"
                "/stop — pause your bot · /cancel — abort setup\n"
                "/help — this list\n\n"
                "<b>🔄 Switch Paper ↔ Real:</b>\n"
                "Start in paper with /setup. To go live, send /ctrader and connect "
                "your own cTrader account (any broker worldwide). Paper (simulated) "
                "and live (real funds) are fully separate — switching never touches "
                "your real money unless you connect cTrader and go live.\n\n"
                "💬 <i>Or just talk to me in any language!</i>\n"
                "<i>Example: \"enter now\", \"intru acum\", \"analyzeaza EUR_USD\"</i>")

_HELP_ADMIN = ("📋 <b>APEX FOREX BOT COMMANDS</b>\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/status — live trading snapshot\n"
               "/market — session + market pulse\n"
               "/setup — guided setup wizard\n"
               "/config — show current settings\n"
               "/report — trade journal + net P&amp;L\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/buy &lt;PAIR&gt; — open BUY manually\n"
               "/sell &lt;PAIR&gt; — open SELL manually\n"
               "/close — close current position\n"
               "/ctrader — connect cTrader · /copilot on|off · /news\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/broker oanda|mt — OANDA API or MetaTrader\n"
               "/env practice|live — OANDA environment\n"
               "/paper on|off — toggle paper mode\n"
               "/risk &lt;0.5-10&gt; — risk % per trade\n"
               "/sl &lt;pips&gt; — stop loss in pips\n"
               "/tp &lt;pips&gt; — take profit in pips\n"
               "/symbol &lt;PAIR&gt; — set pair (EUR_USD)\n"
               "/pairs — everything your broker lets you trade\n"
               "/strategy — trading method (auto · mean reversion · trend · breakout)\n"
               "/atr on|off — dynamic ATR stops (SL 1.5×ATR / TP 3×ATR)\n"
               "/wizard — guided setup (symbol → method → mode)\n"
               "/terminal — live trading terminal (interactive chart + news)\n"
               "/stats — performance report (win rate · profit factor · drawdown)\n"
               "/chart — quick chart snapshot\n"
               "/setkeys KEY=val ... — set credentials\n"
               "  (message is auto-deleted for safety)\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/start — resume trading\n"
               "/stop — pause trading\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "👑 <b>Admin</b>\n"
               "/grant &lt;id&gt; — give client access\n"
               "/revoke &lt;id&gt; — remove access\n"
               "/users — list clients\n"
               "/help — this list\n\n"
               "💬 <i>Free text → AI assistant (any language)</i>")


# ─── Poll loop ────────────────────────────────────────────

_VERIFY_URL = "https://aicashsystem.space/api/verify-license"
_DEPLOY_URL = "https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/autoflow-backend"


def _license_ok(chat_id, text):
    """Validate the buyer's license before granting access to the bot.

    The activation deep link from the purchase email is `/start FORX-...`.
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
            "Don't have Apex Forex Bot yet? Get it at https://aicashsystem.space")
        return False
    if not re.match(r'^FORX-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$', key):
        send_to(chat_id,
            "❌ <b>That doesn't look like a valid key.</b>\n\n"
            "Use the <code>FORX-XXXX-XXXX-XXXX</code> key from your purchase email, "
            "or buy at https://aicashsystem.space")
        return False
    try:
        r = requests.post(_VERIFY_URL, json={"key": key, "product": "apex-forex"}, timeout=8)
        data = r.json()
        if not data.get("valid"):
            send_to(chat_id,
                f"❌ <b>{data.get('message', 'License not found.')}</b>\n\n"
                "Need help? supportaicashsystem@gmail.com")
            return False
    except Exception as e:
        print(f"[TELEGRAM] verify-license unreachable ({e}) — fail-open grant for {key}")
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
        r = requests.post(_VERIFY_URL, json={"key": key, "product": "apex-forex"}, timeout=8)
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


def _poll_loop():
    global _update_id
    # Clear any webhook — getUpdates returns 409 while a webhook is active,
    # which silently stops the bot from ever seeing messages.
    try:
        wr = requests.post(f"{_API}/deleteWebhook",
                           json={"drop_pending_updates": False}, timeout=5)
        print(f"[TELEGRAM] deleteWebhook → {wr.json()}")
    except Exception as e:
        print(f"[TELEGRAM] deleteWebhook failed: {e}")
    # Confirm the token is valid so the cause is obvious in the logs
    try:
        me = requests.get(f"{_API}/getMe", timeout=8).json()
        if me.get("ok"):
            print(f"[TELEGRAM] Bot identity OK → @{me['result'].get('username')}")
        else:
            print(f"[TELEGRAM] getMe FAILED → {me.get('description')} "
                  f"(check TELEGRAM_BOT_TOKEN)")
    except Exception as e:
        print(f"[TELEGRAM] getMe error: {e}")
    print(f"[TELEGRAM] Poll loop started. TOKEN={bool(TOKEN)} CHAT_ID={CHAT_ID}")
    while True:
        try:
            r = requests.get(f"{_API}/getUpdates",
                             params={"offset": _update_id, "timeout": 10,
                                     "allowed_updates": json.dumps(["message", "callback_query"])},
                             timeout=15)
            data = r.json()
            if not data.get("ok"):
                print(f"[TELEGRAM] API error: {data.get('description')} (code {data.get('error_code')})")
                time.sleep(10)
                continue
            for u in data.get("result", []):
                _update_id = u["update_id"] + 1
                # Inline button presses (copilot approve/reject)
                cb = u.get("callback_query")
                if cb:
                    try:
                        requests.post(f"{_API}/answerCallbackQuery",
                                      json={"callback_query_id": cb.get("id")}, timeout=5)
                    except Exception:
                        pass
                    cb_chat = cb.get("message", {}).get("chat", {}).get("id")
                    if cb_chat is not None and access.is_allowed(str(cb_chat)):
                        _handle_cb(cb_chat, cb.get("data", ""))
                    continue
                msg = u.get("message", {})
                raw = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                msg_id = msg.get("message_id")
                if not raw or chat_id is None:
                    continue
                chat_id_str = str(chat_id)

                # Owner is set via the ADMIN_CHAT_ID env var — no first-message
                # bootstrap, so a customer can never become the owner.

                if not access.is_allowed(chat_id_str):
                    # Gate access behind a valid purchase license (fail-open on
                    # server errors). Admins are already is_allowed, so they skip
                    # this. _license_ok sends the prompt/error on refusal.
                    if not _license_ok(chat_id, raw):
                        continue
                    access.grant(chat_id_str)
                    send_to(chat_id,
                            "✅ <b>Welcome to Apex Forex Bot!</b>\n\n"
                            "Your bot is now active. 🚀\n\n"
                            "Send /setup to choose paper/live, your pair and risk, "
                            "then /status to see the live snapshot.")
                    send(f"🆕 <b>New client activated!</b>\nID: <code>{chat_id_str}</code>")
                    continue

                # Refunded/charged-back licenses lose access (fail-open re-check).
                if not _revalidate_license(chat_id):
                    continue

                # Auto-restore: if this user was active but their loop died
                # (e.g. server restart), silently bring it back on interaction.
                try:
                    if user_store.load(chat_id_str).get("active") and not user_loop.is_running(chat_id_str):
                        _auto_start_user(chat_id_str)
                except Exception as e:
                    print(f"[TELEGRAM] auto-restore-on-msg error: {e}")

                # Active wizard step takes priority over /commands
                with _lock:
                    in_wizard = bool(_wizards.get(chat_id, {}).get("step")) and not raw.startswith("/")
                if in_wizard:
                    _handle_wizard_reply(chat_id, raw, msg_id)
                    continue

                first_line = raw.splitlines()[0].strip()
                cmd, _, args = first_line.partition(" ")
                cmd_l = cmd.lower().split("@")[0]  # strip @botname suffix
                args = args.split("\n")[0].strip()  # first line of args only

                is_adm = access.is_admin(chat_id_str)

                if cmd_l == "/deploy" and is_adm:
                    _handle_deploy(chat_id)
                elif cmd_l in ("/status", "/s"):
                    _handle_status(chat_id)
                elif cmd_l == "/report":
                    _handle_report(chat_id)
                elif cmd_l == "/help":
                    send_to(chat_id, _HELP_ADMIN if is_adm else _HELP_CLIENT)
                elif cmd_l == "/users" and is_adm:
                    _handle_users(chat_id)
                elif cmd_l == "/grant" and is_adm:
                    _handle_grant(chat_id, args)
                elif cmd_l == "/revoke" and is_adm:
                    _handle_revoke(chat_id, args)
                elif cmd_l == "/setup":
                    # Every paying client self-configures their OWN trading via the
                    # wizard (writes only their user record); admin extras apply
                    # globally inside _handle_wizard_reply.
                    _handle_setup(chat_id)
                elif cmd_l == "/cancel":
                    with _lock:
                        _had = _wizards.pop(chat_id, None)
                    send_to(chat_id, "✖️ Setup cancelled." if _had else "Nothing to cancel.")
                elif cmd_l == "/config" and is_adm:
                    _handle_config(chat_id)
                elif cmd_l == "/setkeys" and is_adm:
                    _handle_setkeys(chat_id, args, msg_id)
                elif cmd_l == "/broker" and is_adm:
                    _handle_broker(chat_id, args)
                elif cmd_l == "/env" and is_adm:
                    _handle_env(chat_id, args)
                elif cmd_l == "/ctrader":
                    _handle_ctrader(chat_id)
                elif cmd_l == "/ctaccount":
                    _handle_ctaccount(chat_id, args)
                elif cmd_l == "/copilot":
                    _handle_copilot(chat_id, args)
                elif cmd_l == "/news":
                    _handle_news(chat_id)
                elif cmd_l in ("/market", "/m"):
                    _handle_market(chat_id)
                elif cmd_l == "/paper":
                    _handle_paper(chat_id, args)
                elif cmd_l == "/risk":
                    _handle_risk(chat_id, args)
                elif cmd_l == "/sl":
                    _handle_sl(chat_id, args)
                elif cmd_l == "/tp":
                    _handle_tp(chat_id, args)
                elif cmd_l == "/symbol":
                    _handle_symbol(chat_id, args)
                elif cmd_l in ("/pairs", "/symbols"):
                    _handle_pairs(chat_id)
                elif cmd_l in ("/strategy", "/method"):
                    _handle_strategy(chat_id, args)
                elif cmd_l == "/backtest":
                    _handle_backtest(chat_id, args)
                elif cmd_l == "/wizard":
                    onboard_start(chat_id)
                elif cmd_l == "/chart":
                    _handle_chart(chat_id, args)
                elif cmd_l in ("/terminal", "/app"):
                    _handle_terminal(chat_id)
                elif cmd_l == "/atr":
                    _handle_atr(chat_id, args)
                elif cmd_l in ("/stats", "/performance"):
                    _handle_stats(chat_id)
                elif cmd_l == "/buy":
                    _handle_buy(chat_id, args)
                elif cmd_l == "/sell":
                    _handle_sell(chat_id, args)
                elif cmd_l == "/close":
                    _handle_close(chat_id)
                elif cmd_l == "/start":
                    _handle_start(chat_id)
                elif cmd_l == "/stop":
                    # Per-user: stops only this client's loop (admin also pauses global).
                    _handle_stop(chat_id)
                elif cmd_l == "/ai":
                    _handle_ai_setup(chat_id)
                elif cmd_l in ("/groq", "/gemini", "/claude", "/key"):
                    # Explicit key command — the key is the argument.
                    _handle_ai_key(chat_id, args, msg_id)
                elif not raw.startswith("/"):
                    # A bare pasted AI key → connect it (and keep it out of chat history).
                    if _detect_ai_key(raw.strip()):
                        _handle_ai_key(chat_id, raw.strip(), msg_id)
                        continue
                    # Intent detection first (works with zero AI key)
                    handled = _handle_trade_intent_fx(chat_id, raw)
                    if not handled:
                        # Fall through to AI assistant
                        def _typing_reply(reply, cid=chat_id):
                            send_to(cid, reply)
                        def _typing_status(status, cid=chat_id):
                            send_to(cid, status)
                        assistant.chat(
                            chat_id, raw,
                            send_fn=_typing_reply,
                            send_status=_typing_status,
                        )
                # Unknown /commands → silently ignored
        except Exception as e:
            print(f"[TELEGRAM] Poll error: {e}")
        time.sleep(2)


def start_polling(get_dash, broker, control=None):
    global _get_dash, _broker, _bot_control
    if not TOKEN:
        print("[TELEGRAM] Missing TOKEN — polling disabled")
        return
    _get_dash = get_dash
    _broker = broker
    _bot_control = control or {}
    threading.Thread(target=_poll_loop, daemon=True).start()
    # Auto-restore: restart trading loops for everyone who was active before
    # the server restarted (Render free tier wipes the container on redeploy).
    try:
        user_loop.start_all(alert_fn=_user_alert)
    except Exception as e:
        print(f"[TELEGRAM] auto-restore error: {e}")
    print("[TELEGRAM] Polling started — /grant /revoke /users /status /help")


# ─── Outbound alerts ─────────────────────────────────────

def _broadcast(text, extra=None):
    """Send to owner + all granted clients."""
    all_ids = set(access.list_admins() + access.list_clients())
    if CHAT_ID:
        all_ids.add(CHAT_ID)
    for cid in all_ids:
        send_to(cid, text, extra)


def alert_open(side, symbol, price, units, stop_loss, take_profit, druck_mult=1.0,
               reasoning="", key_factors=None):
    d = "🟢 LONG" if side == "BUY" else "🔴 SHORT"
    sl_pips = forex.to_pips(abs(price - stop_loss), symbol)
    tp_pips = forex.to_pips(abs(take_profit - price), symbol)
    mult = f"\n📐 <b>Druckenmiller:</b> ×{druck_mult:.2f}" if druck_mult != 1.0 else ""
    why = _fx_why_block({"reasoning": reasoning, "keyFactors": key_factors or []})
    _broadcast(f"{d} <b>OPENED — {symbol}</b>\n💰 @ {price}  Units: {units:,}\n"
               f"🛡 SL: {stop_loss:.5f} ({sl_pips:.0f} pips)\n"
               f"🎯 TP: {take_profit:.5f} ({tp_pips:.0f} pips){mult}{why}", _dashboard_keyboard())


def alert_close(reason, symbol, side, entry_price, close_price, pnl, balance, reasoning=""):
    icons = {"TAKE_PROFIT": "🎯 TAKE PROFIT", "STOP_LOSS": "🛑 STOP LOSS", "AI_CLOSE": "🤖 AI CLOSE"}
    d = "LONG" if side == "BUY" else "SHORT"
    pips = forex.to_pips(abs(close_price - entry_price), symbol)
    why = f"\n🧠 <i>{reasoning}</i>" if reasoning else _fx_close_why(reason)
    _broadcast(f"{'✅' if pnl > 0 else '❌'} <b>{icons.get(reason, reason)} — {symbol}</b>\n"
               f"📊 {d}  {entry_price} → {close_price} ({pips:.0f} pips)\n"
               f"💵 PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.2f}</b>\n💼 Balance: ${balance:.2f}{why}",
               _dashboard_keyboard())


def alert_stop(reasons):
    _broadcast("🚨 <b>STRATEGY STOP</b>\n" + "\n".join(f"• {r}" for r in reasons))


def alert_filtered(action, livermore, turtle):
    send(f"⚡ <b>SIGNAL FILTERED</b>\nAI: {action} | Livermore: {livermore} | Turtle: {turtle}\n"
         f"<i>PTJ: Play defense</i>")


def alert_market_closed():
    send("🕐 <b>Market closed</b> (weekend). The bot resumes automatically at the Sunday open (21:00 UTC).")


def alert_start(symbol, timeframe, balance, mode):
    send(f"🚀 <b>APEX FOREX BOT STARTED</b>\n💱 {symbol} | {timeframe} | ${balance:.2f}\n⚙️ {mode}\n"
         + (f"🌐 Dashboard: {DASHBOARD_URL}\n" if DASHBOARD_URL else "")
         + "<i>Send /setup to configure · /status to check · /help for all commands</i>",
         _dashboard_keyboard())


def alert_heartbeat(tick_count, balance, open_position, current_price):
    pos_line = "📭 No position"
    if open_position and current_price:
        d = "LONG" if open_position["side"] == "BUY" else "SHORT"
        pnl = forex.pnl_usd(open_position["side"], open_position["entryPrice"],
                            current_price, open_position["quantity"],
                            open_position.get("symbol", cfg.SYMBOL))
        pos_line = (f"{'🟢' if open_position['side'] == 'BUY' else '🔴'} {d} "
                    f"<b>{open_position['symbol']}</b> @ {open_position['entryPrice']}\n"
                    f"PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.2f}</b>")
    send(f"💓 <b>ACTIVE</b>  tick #{tick_count}\n💼 Balance: ${balance:.2f}\n{pos_line}\n"
         f"<i>/status for details</i>", _dashboard_keyboard())
