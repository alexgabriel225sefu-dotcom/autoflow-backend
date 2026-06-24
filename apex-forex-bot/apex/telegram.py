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
_wizard = {}       # wizard state: {step: str, data: dict}
_bot_control = {}  # callbacks: {set_paused, get_paused, reload_broker}

_PAIR_RE = re.compile(r"^[A-Z]{3}_[A-Z]{3}$")


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
            f"💰 Balance: <b>${dash.get('balance', 0):.2f}</b>  ({sign}{pnl_pct:.2f}%){chart_line}\n"
            f"🕐 Market: {market} · Sessions: {sessions}\n\n"
            f"{pos_line}\n\n"
            f"📈 {total} trades · {wins}W/{total - wins}L · Win: {win_rate}\n"
            f"⏱️ Last tick: {dash.get('lastTick', '—')}")


def _handle_status(chat_id):
    # Per-user dash if their loop is running, else global dash
    dash = user_loop.get_dash(chat_id) or _get_dash()
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
        _wizard.clear()
        _wizard["step"] = "MODE"
        _wizard["data"] = {}
    send_to(chat_id,
            "🛠️ <b>APEX FOREX BOT SETUP</b>\n\n"
            "1/5 — <b>How do you want to trade?</b>\n\n"
            "Reply <code>1</code> or <code>2</code>:\n"
            "  <code>1</code> — 🧪 <b>Paper</b> (simulated $1000, real prices from "
            "Yahoo Finance). <b>No account, no keys, starts instantly. Zero risk.</b>\n"
            "  <code>2</code> — 🔴 <b>Live OANDA</b> (real account, real funds — needs "
            "OANDA API keys).\n\n"
            "<i>Most people start with 1 (paper).</i>")


def _handle_wizard_reply(chat_id, raw, msg_id):
    with _lock:
        step = _wizard.get("step")

    if step == "MODE":
        choice = raw.strip()
        if choice not in ("1", "2"):
            return send_to(chat_id, "❌ Reply <code>1</code> (paper) or <code>2</code> (live OANDA).")
        if choice == "1":
            # Paper — Yahoo data, no OANDA needed, skip straight to the pair
            with _lock:
                _wizard["data"]["paper"] = True
                _wizard["step"] = "SYMBOL"
            send_to(chat_id,
                    "🧪 <b>Paper mode</b> — free Yahoo Finance prices, no account.\n\n"
                    "2/5 — <b>Which pair do YOU want to trade?</b>\n\n"
                    "e.g. <code>EUR_USD</code>, <code>GBP_USD</code>, <code>USD_JPY</code>.\n\n"
                    "Reply with the pair. <i>You choose — the bot only trades what you pick.</i>")
        else:
            # Live — collect OANDA credentials next
            with _lock:
                _wizard["data"]["paper"] = False
                _wizard["step"] = "KEYS"
            send_to(chat_id,
                    "🔴 <b>Live OANDA</b> — enter your credentials in one message:\n\n"
                    "  <code>OANDA_API_TOKEN=your_token</code>\n"
                    "  <code>OANDA_ACCOUNT_ID=001-001-1234567-001</code>\n\n"
                    "Get them at <a href=\"https://www.oanda.com\">oanda.com</a> → "
                    "Manage API Access.\n\n"
                    "🔒 <i>Your message is deleted immediately after reading.</i>")

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
            _wizard["data"]["keys"] = pairs
            _wizard["step"] = "SYMBOL"
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
            _wizard["data"]["symbol"] = sym
            _wizard["step"] = "RISK"
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
            _wizard["data"]["risk"] = risk_map[choice]
            _wizard["step"] = "STYLE"
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
            _wizard["data"]["min_confidence"] = conf_map[choice]
            _wizard["step"] = "DISCLAIMER"
            d = dict(_wizard["data"])
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
            _wizard["step"] = None
            d = dict(_wizard["data"])
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

        # Auto-start trading immediately — no manual /start needed
        _auto_start_user(chat_id)

        paper_str = "ON (simulated)" if d.get("paper") else "OFF (live)"
        risk_pct = d.get("risk", 0.005) * 100
        send_to(chat_id,
                f"✅ <b>Setup complete — bot is LIVE!</b>\n\n"
                f"Broker: <b>OANDA (practice)</b>\n"
                f"Pair: <b>{sym}</b>  (your choice)\n"
                f"Risk/trade: <b>{risk_pct:g}%</b>  (your choice)\n"
                f"Paper mode: <b>{paper_str}</b>\n\n"
                f"⚡ Trading is active now. You'll get an alert on every trade,\n"
                f"plus a heartbeat so you always know the bot is awake.\n"
                f"Change anything with /setup · /status to check · /stop to pause.",
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
    _save_runtime({"OANDA_ENV": env})
    _apply("OANDA_ENV", env)
    if _bot_control.get("reload_broker"):
        _bot_control["reload_broker"]()
    icon = "🧪" if env == "practice" else "🔴"
    send_to(chat_id, f"{icon} OANDA environment set to <b>{env.upper()}</b>.\n"
                     f"<i>Make sure your token matches this environment.</i>")


def _handle_paper(chat_id, args):
    on = (args or "").strip().lower() in ("on", "true", "yes", "1")
    _save_runtime({"PAPER_TRADING": str(on).lower()})
    _apply("PAPER_TRADING", on)
    mode = "ON (simulated money)" if on else "OFF (real orders on your OANDA account)"
    send_to(chat_id, f"{'📝' if on else '🔴'} Paper trading <b>{mode}</b>.")


def _handle_risk(chat_id, args):
    try:
        pct = float((args or "").strip())
        if not (0.5 <= pct <= 10):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/risk 2</code>  (0.5–10%)")
    frac = pct / 100
    _save_runtime({"RISK_PER_TRADE": frac})
    _apply("RISK_PER_TRADE", frac)
    send_to(chat_id, f"⚖️ Risk per trade set to <b>{pct:g}%</b> of balance.")


def _handle_sl(chat_id, args):
    try:
        pips = float((args or "").strip())
        if not (2 <= pips <= 200):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/sl 15</code>  (2–200 pips)")
    _save_runtime({"STOP_LOSS_PIPS": pips})
    _apply("STOP_LOSS_PIPS", pips)
    send_to(chat_id, f"🛡 Stop loss set to <b>{pips:g} pips</b>.")


def _handle_tp(chat_id, args):
    try:
        pips = float((args or "").strip())
        if not (2 <= pips <= 500):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/tp 30</code>  (2–500 pips)")
    _save_runtime({"TAKE_PROFIT_PIPS": pips})
    _apply("TAKE_PROFIT_PIPS", pips)
    send_to(chat_id, f"🎯 Take profit set to <b>{pips:g} pips</b>.")


def _handle_symbol(chat_id, args):
    sym = (args or "").strip().upper().replace("/", "_").replace("-", "_")
    if not _PAIR_RE.match(sym):
        return send_to(chat_id, "❌ Usage: <code>/symbol EUR_USD</code>")
    _save_runtime({"TRADE_SYMBOL": sym})
    _apply("TRADE_SYMBOL", sym)
    cfg.SYMBOL = sym
    send_to(chat_id, f"💱 Currency pair set to <b>{sym}</b>.")


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
    elif action == "STOP":
        reasons = ", ".join(result.get("reasons", ["risk limit"]))
        send_to(uid, f"🛑 <b>Trading paused — risk limit hit</b>\n{reasons}")
    elif action in ("BUY", "SELL"):
        spread = result.get("spreadPips")
        spread_line = f" | Spread: {spread}p" if spread is not None else ""
        send_to(uid,
                f"⚡ <b>{action}</b> — {sym}\n"
                f"Price: <b>{result.get('price', '—')}</b> | "
                f"Confidence: <b>{result.get('confidence', 0)}%</b>{spread_line}")
    elif action == "CLOSE":
        net = result.get("netPnl")
        if net is not None:
            icon = "✅" if net >= 0 else "❌"
            send_to(uid,
                    f"🔒 <b>Position closed</b> — {sym}\n"
                    f"Exit: <b>{result.get('price', '—')}</b>\n"
                    f"{icon} Net P&amp;L: <b>{'+' if net >= 0 else ''}${net:.2f}</b> "
                    f"<i>(gross ${result.get('grossPnl', 0):.2f} − cost ${result.get('costUsd', 0):.2f})</i>\n"
                    f"💼 Balance: <b>${result.get('balance', 0):.2f}</b>")
        else:
            send_to(uid,
                    f"🔒 <b>Position closed</b> — {sym}\n"
                    f"Price: <b>{result.get('price', '—')}</b>")
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


def _handle_start(chat_id):
    user = user_store.load(chat_id)
    # Check user has credentials set up
    if not access.is_admin(str(chat_id)) and not user.get("oanda_token") and not user.get("paper"):
        return send_to(chat_id,
            "⚙️ <b>Setup required first!</b>\n\n"
            "Send /setup to configure your OANDA account or enable paper trading.")
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
                "/status — live trading snapshot\n"
                "/report — trade journal + net P&amp;L (for taxes)\n"
                "/help — this list")

_HELP_ADMIN = ("📋 <b>APEX FOREX BOT COMMANDS</b>\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/status — live trading snapshot\n"
               "/setup — guided setup wizard\n"
               "/config — show current settings\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/broker oanda|mt — OANDA API or MetaTrader\n"
               "/env practice|live — OANDA environment\n"
               "/paper on|off — toggle paper mode\n"
               "/risk &lt;0.5-10&gt; — risk % per trade\n"
               "/sl &lt;pips&gt; — stop loss in pips\n"
               "/tp &lt;pips&gt; — take profit in pips\n"
               "/symbol &lt;PAIR&gt; — set pair (EUR_USD)\n"
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
               "/help — this list")


# ─── Poll loop ────────────────────────────────────────────

_VERIFY_URL = "https://aicashsystem.space/api/verify-license"
_DEPLOY_URL = "https://railway.app/new/template?template=https://github.com/alexgabriel225sefu-dotcom/autoflow-backend"


def _handle_buyer_start(chat_id, license_key):
    """Validate license key and grant instant access to this bot."""
    key = license_key.strip().upper()
    if not re.match(r'^APEX-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$', key):
        send_to(chat_id,
            "❌ <b>Invalid license key.</b>\n\n"
            "Purchase Apex Forex Bot at:\n"
            "https://aicashsystem.space"
        )
        return

    valid = False
    try:
        r = requests.post(_VERIFY_URL, json={"key": key}, timeout=8)
        valid = r.json().get("valid", False)
    except Exception:
        valid = False  # server unreachable — deny access, nu grant automat

    if not valid:
        send_to(chat_id,
            "❌ <b>License not found.</b>\n\n"
            "Use the key from your purchase email.\n\n"
            "Need help? supportaicashsystem@gmail.com"
        )
        return

    # Grant instant access
    access.grant(str(chat_id))
    send_to(chat_id,
        f"✅ <b>Access granted! Welcome to Apex Forex Bot.</b>\n\n"
        f"⚡ EUR/USD | AI trading is now LIVE\n\n"
        f"Send /status to see live trading snapshot.\n"
        f"You'll receive alerts for every trade automatically.\n\n"
        f"Questions? supportaicashsystem@gmail.com"
    )
    # Notify owner
    send(f"🆕 <b>New client activated!</b>\nID: <code>{chat_id}</code>\nKey: <code>{key}</code>")


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
                                     "allowed_updates": json.dumps(["message"])},
                             timeout=15)
            data = r.json()
            if not data.get("ok"):
                print(f"[TELEGRAM] API error: {data.get('description')} (code {data.get('error_code')})")
                time.sleep(10)
                continue
            for u in data.get("result", []):
                _update_id = u["update_id"] + 1
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
                    # No license keys: the activation link is only handed out
                    # after payment (purchase email + thank-you page), so anyone
                    # who reaches the bot is a paying customer. Grant on contact.
                    access.grant(chat_id_str)
                    send_to(chat_id,
                            "✅ <b>Welcome to Apex Forex Bot!</b>\n\n"
                            "Your bot is now active. 🚀\n\n"
                            "Send /setup to connect your OANDA account, "
                            "then /status to see the live snapshot.")
                    send(f"🆕 <b>New client activated!</b>\nID: <code>{chat_id_str}</code>")
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
                    in_wizard = bool(_wizard.get("step")) and not raw.startswith("/")
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
                elif cmd_l == "/setup" and is_adm:
                    _handle_setup(chat_id)
                elif cmd_l == "/config" and is_adm:
                    _handle_config(chat_id)
                elif cmd_l == "/setkeys" and is_adm:
                    _handle_setkeys(chat_id, args, msg_id)
                elif cmd_l == "/broker" and is_adm:
                    _handle_broker(chat_id, args)
                elif cmd_l == "/env" and is_adm:
                    _handle_env(chat_id, args)
                elif cmd_l == "/paper" and is_adm:
                    _handle_paper(chat_id, args)
                elif cmd_l == "/risk" and is_adm:
                    _handle_risk(chat_id, args)
                elif cmd_l == "/sl" and is_adm:
                    _handle_sl(chat_id, args)
                elif cmd_l == "/tp" and is_adm:
                    _handle_tp(chat_id, args)
                elif cmd_l == "/symbol" and is_adm:
                    _handle_symbol(chat_id, args)
                elif cmd_l == "/start":
                    _handle_start(chat_id)
                elif cmd_l == "/stop" and is_adm:
                    _handle_stop(chat_id)
                elif not is_adm:
                    pass  # clients silently ignore unknown commands
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


def alert_open(side, symbol, price, units, stop_loss, take_profit, druck_mult=1.0):
    d = "🟢 LONG" if side == "BUY" else "🔴 SHORT"
    sl_pips = forex.to_pips(abs(price - stop_loss), symbol)
    tp_pips = forex.to_pips(abs(take_profit - price), symbol)
    mult = f"\n📐 <b>Druckenmiller:</b> ×{druck_mult:.2f}" if druck_mult != 1.0 else ""
    _broadcast(f"{d} <b>OPENED — {symbol}</b>\n💰 @ {price}  Units: {units:,}\n"
               f"🛡 SL: {stop_loss:.5f} ({sl_pips:.0f} pips)\n"
               f"🎯 TP: {take_profit:.5f} ({tp_pips:.0f} pips){mult}", _dashboard_keyboard())


def alert_close(reason, symbol, side, entry_price, close_price, pnl, balance):
    icons = {"TAKE_PROFIT": "🎯 TAKE PROFIT", "STOP_LOSS": "🛑 STOP LOSS", "AI_CLOSE": "🤖 AI CLOSE"}
    d = "LONG" if side == "BUY" else "SHORT"
    pips = forex.to_pips(abs(close_price - entry_price), symbol)
    _broadcast(f"{'✅' if pnl > 0 else '❌'} <b>{icons.get(reason, reason)} — {symbol}</b>\n"
               f"📊 {d}  {entry_price} → {close_price} ({pips:.0f} pips)\n"
               f"💵 PnL: <b>{'+' if pnl >= 0 else ''}${pnl:.2f}</b>\n💼 Balance: ${balance:.2f}",
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
