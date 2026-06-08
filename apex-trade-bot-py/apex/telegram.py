"""Telegram alerts + full interactive config/control commands.

Each client runs their own bot instance (self-hosted model) — the seller
never sees client API keys. All commands are restricted to TELEGRAM_CHAT_ID.
Polling runs in a background daemon thread.
"""
import os
import re
import json
import time
import threading
import requests
from apex import config as cfg

TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
CHAT_ID = (cfg.TELEGRAM_CHAT_ID or "").strip()
DASHBOARD_URL = cfg.DASHBOARD_URL
_API = f"https://api.telegram.org/bot{TOKEN}"
_RUNTIME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime.json")

_get_dash = lambda: None
_exchange = None
_update_id = 0
_lock = threading.Lock()
_wizard = {}       # wizard state: {step: str, data: dict}
_bot_control = {}  # callbacks: {set_paused, get_paused, reload_exchange}


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
    "EXCHANGE":        ("EXCHANGE",        lambda v: str(v).lower()),
    "PAPER_TRADING":   ("PAPER_TRADING",   lambda v: str(v).lower() in ("true", "1", "yes", "on")),
    "TRADE_SYMBOL":    ("SYMBOL",          str),
    "RISK_PER_TRADE":  ("RISK_PER_TRADE",  float),
    "STOP_LOSS_PCT":   ("STOP_LOSS_PCT",   float),
    "TAKE_PROFIT_PCT": ("TAKE_PROFIT_PCT", float),
    "MIN_CONFIDENCE":  ("MIN_CONFIDENCE",  int),
}

_EXCHANGE_KEYS = {
    "binance":  ["BINANCE_API_KEY", "BINANCE_API_SECRET"],
    "bybit":    ["BYBIT_API_KEY", "BYBIT_API_SECRET"],
    "okx":      ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"],
    "kraken":   ["KRAKEN_API_KEY", "KRAKEN_API_SECRET"],
    "kucoin":   ["KUCOIN_API_KEY", "KUCOIN_API_SECRET", "KUCOIN_API_PASSPHRASE"],
    "coinbase": ["COINBASE_API_KEY", "COINBASE_API_SECRET"],
    "bitget":   ["BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE"],
    "mexc":     ["MEXC_API_KEY", "MEXC_API_SECRET"],
}


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
    chart_line = (f"\n<code>{chart}</code>  <b>${dash.get('currentPrice', 0):.4f}</b>") if chart else ""
    pos_line = "📭 No open position"
    if dash.get("openPosition"):
        op = dash["openPosition"]
        d = "🟢 LONG" if op["side"] == "BUY" else "🔴 SHORT"
        pnl = op.get("currentPnl", 0)
        pos_line = (f"{d} <b>{op['symbol']}</b>\n  Entry: ${op['entryPrice']}  "
                    f"SL: ${(op.get('stopLoss') or 0):.4f}\n"
                    f"  PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.4f}</b>")
    paused = _bot_control.get("get_paused", lambda: False)()
    state_tag = "  ⏸️ PAUSED" if paused else ""
    return (f"⚡ <b>APEX TRADE BOT</b>  {dash.get('mode', '')} · "
            f"{dash.get('exchange', '')}{state_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: <b>${dash.get('balance', 0):.2f}</b>  ({sign}{pnl_pct:.2f}%){chart_line}\n\n"
            f"{pos_line}\n\n"
            f"📈 {total} trades · {wins}W/{total - wins}L · Win: {win_rate}\n"
            f"⏱️ Last tick: {dash.get('lastTick', '—')}")


def _handle_status(chat_id):
    dash = _get_dash()
    if not dash or not dash.get("exchange"):
        return send_to(chat_id, "⏳ Bot starting, please wait...")
    chart = ""
    if _exchange:
        try:
            candles = _exchange.get_candles(dash.get("currentSymbol"), "5m", 24)
            chart = mini_chart([c["close"] for c in candles])
        except Exception:
            pass
    send_to(chat_id, _build_status(dash, chart), _dashboard_keyboard())


# ─── Setup wizard ─────────────────────────────────────────

def _wizard_keys_prompt(exchange_name: str) -> str:
    keys = _EXCHANGE_KEYS.get(exchange_name, [])
    fmt = "\n".join(f"  <code>{k}=your_value</code>" for k in keys)
    return (f"3/4 — Enter your <b>{exchange_name.upper()}</b> API credentials "
            f"in one message:\n\n{fmt}\n\n"
            f"🔒 <i>Your message is deleted immediately after reading.</i>")


def _handle_setup(chat_id):
    with _lock:
        _wizard.clear()
        _wizard["step"] = "EXCHANGE"
        _wizard["data"] = {}
    exs = " · ".join(cfg.SUPPORTED_EXCHANGES)
    send_to(chat_id,
            f"🛠️ <b>APEX BOT SETUP WIZARD</b>\n\n"
            f"1/4 — Choose your exchange:\n<code>{exs}</code>\n\n"
            f"Reply with the exchange name.")


def _handle_wizard_reply(chat_id, raw, msg_id):
    with _lock:
        step = _wizard.get("step")
        data = dict(_wizard.get("data", {}))

    if step == "EXCHANGE":
        ex = raw.strip().lower()
        if ex not in cfg.SUPPORTED_EXCHANGES:
            return send_to(chat_id,
                           f"❌ Unknown exchange. Choose one of:\n"
                           f"<code>{' · '.join(cfg.SUPPORTED_EXCHANGES)}</code>")
        with _lock:
            _wizard["data"]["exchange"] = ex
            _wizard["step"] = "PAPER"
        send_to(chat_id,
                "2/4 — Enable <b>paper trading</b> (simulated money, zero risk)?\n\n"
                "Reply <code>yes</code> or <code>no</code>.")

    elif step == "PAPER":
        paper = raw.strip().lower() in ("yes", "y", "true", "on", "1")
        with _lock:
            _wizard["data"]["paper"] = paper
            _wizard["step"] = "SYMBOL" if paper else "KEYS"
        if paper:
            send_to(chat_id,
                    "3/4 — Trading pair (e.g. <code>SOLUSDT</code>, <code>BTCUSDT</code>).\n\n"
                    "Reply with the symbol.")
        else:
            ex = data.get("exchange") or _wizard["data"].get("exchange", cfg.EXCHANGE)
            send_to(chat_id, _wizard_keys_prompt(ex))

    elif step == "KEYS":
        _delete_message(chat_id, msg_id)
        pairs = {}
        for part in raw.replace("\n", " ").split():
            if "=" in part:
                k, _, v = part.partition("=")
                pairs[k.strip().upper()] = v.strip()
        if not pairs:
            return send_to(chat_id,
                           "❌ No valid <code>KEY=value</code> pairs found.\n"
                           "Try again — each pair separated by a space.")
        with _lock:
            _wizard["data"]["keys"] = pairs
            _wizard["step"] = "SYMBOL"
        send_to(chat_id,
                f"✅ {len(pairs)} credential(s) saved.\n\n"
                "4/4 — Trading pair (e.g. <code>SOLUSDT</code>).\n\nReply with the symbol.")

    elif step == "SYMBOL":
        sym = raw.strip().upper()
        if len(sym) < 4 or len(sym) > 12:
            return send_to(chat_id, "❌ Invalid symbol. Example: <code>SOLUSDT</code>")
        with _lock:
            _wizard["data"]["symbol"] = sym
            _wizard["step"] = None
            d = dict(_wizard["data"])

        updates: dict = {
            "EXCHANGE": d.get("exchange", cfg.EXCHANGE),
            "PAPER_TRADING": str(d.get("paper", True)).lower(),
            "TRADE_SYMBOL": sym,
        }
        if d.get("keys"):
            updates.update(d["keys"])
        _save_runtime(updates)
        for k, v in updates.items():
            _apply(k, v)
        if _bot_control.get("reload_exchange"):
            _bot_control["reload_exchange"]()

        paper_str = "ON (simulated)" if d.get("paper") else "OFF (live)"
        send_to(chat_id,
                f"✅ <b>Setup complete!</b>\n\n"
                f"Exchange: <b>{d.get('exchange', cfg.EXCHANGE).upper()}</b>\n"
                f"Symbol: <b>{sym}</b>\n"
                f"Paper mode: <b>{paper_str}</b>\n\n"
                f"Send /start to begin trading.")


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
    masked = "\n".join(f"  {k} = {_mask(v)}" for k, v in pairs.items())
    send_to(chat_id, f"🔑 <b>{len(pairs)} credential(s) updated:</b>\n<code>{masked}</code>")


def _handle_exchange(chat_id, args):
    ex = (args or "").strip().lower()
    if ex not in cfg.SUPPORTED_EXCHANGES:
        return send_to(chat_id,
                       f"❌ Supported exchanges:\n<code>{' · '.join(cfg.SUPPORTED_EXCHANGES)}</code>")
    _save_runtime({"EXCHANGE": ex})
    _apply("EXCHANGE", ex)
    if _bot_control.get("reload_exchange"):
        _bot_control["reload_exchange"]()
    send_to(chat_id, f"✅ Exchange set to <b>{ex.upper()}</b>.\n"
                     f"Use /setkeys to set API credentials if needed.")


def _handle_paper(chat_id, args):
    on = (args or "").strip().lower() in ("on", "true", "yes", "1")
    _save_runtime({"PAPER_TRADING": str(on).lower()})
    _apply("PAPER_TRADING", on)
    mode = "ON (simulated money)" if on else "OFF (live funds)"
    send_to(chat_id, f"{'📝' if on else '🔴'} Paper trading <b>{mode}</b>.")


def _handle_risk(chat_id, args):
    try:
        pct = float((args or "").strip())
        if not (1 <= pct <= 50):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/risk 20</code>  (1–50%)")
    frac = pct / 100
    _save_runtime({"RISK_PER_TRADE": frac})
    _apply("RISK_PER_TRADE", frac)
    send_to(chat_id, f"⚖️ Risk per trade set to <b>{pct:.0f}%</b> of balance.")


def _handle_symbol(chat_id, args):
    sym = (args or "").strip().upper()
    if len(sym) < 4 or len(sym) > 12:
        return send_to(chat_id, "❌ Usage: <code>/symbol SOLUSDT</code>")
    _save_runtime({"TRADE_SYMBOL": sym})
    _apply("TRADE_SYMBOL", sym)
    cfg.SYMBOL = sym
    send_to(chat_id, f"📊 Trading pair set to <b>{sym}</b>.")


def _handle_start(chat_id):
    if _bot_control.get("set_paused"):
        _bot_control["set_paused"](False)
    send_to(chat_id, "▶️ <b>Bot started.</b> Trading is now active.", _dashboard_keyboard())


def _handle_stop(chat_id):
    if _bot_control.get("set_paused"):
        _bot_control["set_paused"](True)
    send_to(chat_id, "⏸️ <b>Bot paused.</b> No new trades will open.\nSend /start to resume.")


def _handle_config(chat_id):
    ex = cfg.EXCHANGE.upper()
    keys = _EXCHANGE_KEYS.get(cfg.EXCHANGE, [])
    key_lines = "\n".join(
        f"  {k}: {_mask(getattr(cfg, k, '')) if getattr(cfg, k, '') else '—'}"
        for k in keys)
    paused = _bot_control.get("get_paused", lambda: False)()
    state_tag = "⏸️ PAUSED" if paused else "▶️ RUNNING"
    send_to(chat_id,
            f"⚙️ <b>Config</b>  [{state_tag}]\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Exchange:  <b>{ex}</b>\n"
            f"Symbol:    <b>{cfg.SYMBOL}</b>\n"
            f"Timeframe: <b>{cfg.TIMEFRAME}</b>\n"
            f"Paper:     <b>{'ON' if cfg.PAPER_TRADING else 'OFF'}</b>\n"
            f"Risk:      <b>{cfg.RISK_PER_TRADE * 100:.0f}%</b>\n"
            f"SL/TP:     <b>{cfg.STOP_LOSS_PCT * 100:.2f}% / {cfg.TAKE_PROFIT_PCT * 100:.2f}%</b>\n"
            f"Min conf:  <b>{cfg.MIN_CONFIDENCE}%</b>\n"
            f"Interval:  <b>{cfg.LOOP_INTERVAL_MS // 60000}m</b>\n\n"
            f"🔑 {ex} keys:\n{key_lines or '  (none set — use /setkeys)'}")


_HELP = ("📋 <b>APEX BOT COMMANDS</b>\n"
         "━━━━━━━━━━━━━━━━━━━━\n"
         "/setup — guided setup wizard\n"
         "/config — show current settings\n"
         "/status — live trading snapshot\n"
         "━━━━━━━━━━━━━━━━━━━━\n"
         "/exchange &lt;name&gt; — switch exchange\n"
         "/paper on|off — toggle paper mode\n"
         "/risk &lt;1-50&gt; — risk % per trade\n"
         "/symbol &lt;PAIR&gt; — set trading pair\n"
         "/setkeys KEY=val ... — set API keys\n"
         "  (message is auto-deleted for safety)\n"
         "━━━━━━━━━━━━━━━━━━━━\n"
         "/start — resume trading\n"
         "/stop — pause trading\n"
         "/help — this list")


# ─── Poll loop ────────────────────────────────────────────

_VERIFY_URL = "https://aicashsystem.onrender.com/api/verify-license"
_DEPLOY_URL = "https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/autoflow-backend"


def _handle_buyer_start(chat_id, license_key):
    """Validate a new buyer's license key and send deployment instructions."""
    key = license_key.strip().upper()
    if not re.match(r'^APEX-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$', key):
        send_to(chat_id,
            "❌ <b>Invalid license key.</b>\n\n"
            "Purchase Apex Trade Bot at:\n"
            "https://aicashsystem.space/apex-bot"
        )
        return

    # Validate via API (fall back to format-valid if server unreachable)
    valid = False
    try:
        r = requests.post(_VERIFY_URL, json={"key": key}, timeout=8)
        valid = r.json().get("valid", False)
    except Exception:
        valid = True  # server unreachable — key format already validated

    if not valid:
        send_to(chat_id,
            "❌ <b>License not found.</b>\n\n"
            "Use the key from your purchase email.\n\n"
            "Need help? supportaicashsystem@gmail.com"
        )
        return

    send_to(chat_id,
        f"✅ <b>License validated!</b>\n\n"
        f"Welcome to Apex Trade Bot.\n"
        f"Your key: <code>{key}</code>\n\n"
        f"<b>Deploy your bot in 1 click:</b>\n"
        f'👉 <a href="{_DEPLOY_URL}">Deploy to Railway</a>\n\n'
        f"<b>Add these variables in Railway:</b>\n"
        f"• <code>TELEGRAM_BOT_TOKEN</code> — from @BotFather\n"
        f"• <code>TELEGRAM_CHAT_ID</code> — from @userinfobot\n"
        f"• <code>LICENSE_KEY</code> — <code>{key}</code>\n\n"
        f"After deploying, send /setup to your new bot to configure exchange + API keys.\n\n"
        f"Questions? supportaicashsystem@gmail.com"
    )


def _poll_loop():
    global _update_id
    while True:
        try:
            r = requests.get(f"{_API}/getUpdates",
                             params={"offset": _update_id, "timeout": 10,
                                     "allowed_updates": json.dumps(["message"])},
                             timeout=15)
            for u in r.json().get("result", []):
                _update_id = u["update_id"] + 1
                msg = u.get("message", {})
                raw = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                msg_id = msg.get("message_id")
                if not raw or chat_id is None:
                    continue
                if str(chat_id) != str(CHAT_ID):
                    # Allow new buyers to activate via /start <license_key>
                    first = raw.splitlines()[0].strip()
                    ext_cmd, _, ext_args = first.partition(" ")
                    if ext_cmd.lower().split("@")[0] == "/start" and ext_args.strip():
                        _handle_buyer_start(chat_id, ext_args.strip())
                    continue

                # Active wizard step takes priority over /commands
                with _lock:
                    in_wizard = bool(_wizard.get("step")) and not raw.startswith("/")
                if in_wizard:
                    _handle_wizard_reply(chat_id, raw, msg_id)
                    continue

                first_line = raw.splitlines()[0].strip()
                cmd, _, args = first_line.partition(" ")
                cmd_l = cmd.lower().split("@")[0]  # strip @botname suffix
                args = args.split("\n")[0].strip()  # first line of args only

                if cmd_l in ("/status", "/s"):
                    _handle_status(chat_id)
                elif cmd_l == "/help":
                    send_to(chat_id, _HELP)
                elif cmd_l == "/setup":
                    _handle_setup(chat_id)
                elif cmd_l == "/config":
                    _handle_config(chat_id)
                elif cmd_l == "/setkeys":
                    _handle_setkeys(chat_id, args, msg_id)
                elif cmd_l == "/exchange":
                    _handle_exchange(chat_id, args)
                elif cmd_l == "/paper":
                    _handle_paper(chat_id, args)
                elif cmd_l == "/risk":
                    _handle_risk(chat_id, args)
                elif cmd_l == "/symbol":
                    _handle_symbol(chat_id, args)
                elif cmd_l == "/start":
                    _handle_start(chat_id)
                elif cmd_l == "/stop":
                    _handle_stop(chat_id)
        except Exception:
            pass
        time.sleep(2)


def start_polling(get_dash, exchange, control=None):
    global _get_dash, _exchange, _bot_control
    if not TOKEN or not CHAT_ID:
        print(f"[TELEGRAM] Missing TOKEN={bool(TOKEN)} CHAT_ID={bool(CHAT_ID)} — polling disabled")
        return
    _get_dash = get_dash
    _exchange = exchange
    _bot_control = control or {}
    threading.Thread(target=_poll_loop, daemon=True).start()
    print("[TELEGRAM] Polling started — /setup /start /stop /status /help")


# ─── Outbound alerts ─────────────────────────────────────

def alert_open(side, symbol, price, quantity, stop_loss, take_profit, druck_mult=1.0):
    d = "🟢 LONG" if side == "BUY" else "🔴 SHORT"
    mult = f"\n📐 <b>Druckenmiller:</b> ×{druck_mult:.2f}" if druck_mult != 1.0 else ""
    send(f"{d} <b>OPENED — {symbol}</b>\n💰 @ ${price}  Qty: {quantity}\n"
         f"🛡 SL: ${stop_loss:.5f}\n🎯 TP: ${take_profit:.5f}{mult}", _dashboard_keyboard())


def alert_close(reason, symbol, side, entry_price, close_price, pnl, balance):
    icons = {"TAKE_PROFIT": "🎯 TAKE PROFIT", "STOP_LOSS": "🛑 STOP LOSS", "AI_CLOSE": "🤖 AI CLOSE"}
    d = "LONG" if side == "BUY" else "SHORT"
    send(f"{'✅' if pnl > 0 else '❌'} <b>{icons.get(reason, reason)} — {symbol}</b>\n"
         f"📊 {d}  ${entry_price} → ${close_price}\n"
         f"💵 PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.4f}</b>\n💼 Balance: ${balance:.4f}",
         _dashboard_keyboard())


def alert_stop(reasons):
    send("🚨 <b>STRATEGY STOP</b>\n" + "\n".join(f"• {r}" for r in reasons))


def alert_filtered(action, livermore, turtle):
    send(f"⚡ <b>SIGNAL FILTERED</b>\nAI: {action} | Livermore: {livermore} | Turtle: {turtle}\n"
         f"<i>PTJ: Play defense</i>")


def alert_start(symbol, timeframe, balance, mode):
    send(f"🚀 <b>APEX TRADE BOT STARTED</b>\n📊 {symbol} | {timeframe} | ${balance:.2f}\n⚙️ {mode}\n"
         + (f"🌐 Dashboard: {DASHBOARD_URL}\n" if DASHBOARD_URL else "")
         + "<i>Send /setup to configure · /status to check · /help for all commands</i>",
         _dashboard_keyboard())


def alert_heartbeat(tick_count, balance, open_position, current_price):
    pos_line = "📭 No position"
    if open_position and current_price:
        d = "LONG" if open_position["side"] == "BUY" else "SHORT"
        pnl = ((current_price - open_position["entryPrice"]) * open_position["quantity"]
               if open_position["side"] == "BUY"
               else (open_position["entryPrice"] - current_price) * open_position["quantity"])
        pos_line = (f"{'🟢' if open_position['side'] == 'BUY' else '🔴'} {d} "
                    f"<b>{open_position['symbol']}</b> @ ${open_position['entryPrice']}\n"
                    f"PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.4f}</b>")
    send(f"💓 <b>ACTIVE</b>  tick #{tick_count}\n💼 Balance: ${balance:.4f}\n{pos_line}\n"
         f"<i>/status for details</i>", _dashboard_keyboard())
