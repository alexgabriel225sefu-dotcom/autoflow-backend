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
from apex import builder
from apex import quick_answers

TOKEN = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
CHAT_ID = (cfg.TELEGRAM_CHAT_ID or "").strip()
DASHBOARD_URL = cfg.DASHBOARD_URL
_API = f"https://api.telegram.org/bot{TOKEN}"

# Growth-phase gate mirror (see ctrader_oauth.broker_gate_reason) — used only
# to keep static help/onboarding copy honest: while this is on, a demo
# account (or a live account at any other broker) never qualifies for free
# access, so nothing shown to a new client should suggest otherwise.
_LIVE_BROKER_REQUIRED = (os.getenv("REQUIRE_LIVE_FP_MARKETS", "true").strip().lower() not in ("0", "false", "no"))
_REQUIRED_BROKER_LABEL = (os.getenv("REQUIRED_BROKER_NAME", "").strip() or "FP Markets")


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
_purge_pending = {}  # chat_id -> target user_id awaiting /purgebad confirmation
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
_CCY_FX = "XAU|XAG|EUR|GBP|USD|JPY|AUD|CAD|CHF|NZD"
_RE_PAIR_FX = re.compile(
    rf"\b({_CCY_FX})\s*[/_-]?\s*({_CCY_FX})\b"   # EURUSD, EUR/USD, EUR_USD
    rf"|\b(GOLD|SILVER)\b"                        # what people actually type
    rf"|\b({_CCY_FX})\b",                         # a lone currency → vs USD
    re.IGNORECASE)

# A question about closing is not an instruction to close. The original
# close-math pattern needed a Romanian second half (cat/profit/pierd/lose), so
# "if i close now how much would i have" missed it, fell through to the close
# branch and shut a live position — in English only.
_RE_HYPOTHETICAL_FX = re.compile(
    r"\?|\b(dac[aă]|if|how\s+much|c[âa]t|c[âa]ți|cati|would|ar\s+fi|"
    r"a[șs]\s+avea|r[ăa]m[âa]ne)\b", re.IGNORECASE)


def _pair_from_text(text):
    """The instrument named in a free-text order, or None to keep the current one.

    `cumpara EURUSD` used to match nothing — the pattern wanted EUR/USD or a
    lone EUR, and a bare six-letter pair has no word boundary in the middle.
    The order then fell back to whatever Auto-Pilot happened to be focused on,
    silently. Asking for EURUSD while the loop sat on USDCAD bought USDCAD: a
    real position, on the wrong instrument, with no warning. It only looked
    right in testing because focus and request happened to agree.
    """
    m = _RE_PAIR_FX.search((text or "").upper())
    if not m:
        return None
    base, quote, metal, single = m.group(1), m.group(2), m.group(3), m.group(4)
    if base and quote:
        raw = f"{base}_{quote}"
    elif metal:
        raw = "XAU_USD" if metal == "GOLD" else "XAG_USD"
    else:
        raw = f"{single}_USD"
    # "buy USD" is not an instrument. Nor is any pair against itself.
    if raw.split("_")[0] == raw.split("_")[1]:
        return None
    return raw if _PAIR_RE.match(raw) else None


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
    if (_RE_CLOSE_MATH_FX.search(t)
            or (_RE_CLOSE_FX.search(t) and _RE_HYPOTHETICAL_FX.search(t))):
        dash = user_loop.get_dash(chat_id) or {}
        open_pos = dash.get("openPosition")
        if not open_pos:
            send_to(chat_id, "📭 No open position right now.")
            return True
        from apex.brokers.ctrader import CtraderBroker
        import types as _types
        user = user_store.load(chat_id)
        sym = open_pos.get("symbol", _user_symbol(chat_id))
        try:
            fake_cfg = _types.SimpleNamespace(
                CTRADER_ACCESS_TOKEN=user.get("ctrader_access_token", ""),
                CTRADER_REFRESH_TOKEN=user.get("ctrader_refresh_token", ""),
                CTRADER_ACCOUNT_ID=user.get("ctrader_account_id", ""),
                CTRADER_ENV=user.get("ctrader_env", "demo"),
                SYMBOL=sym, TIMEFRAME="5m", CANDLES=5,
                PAPER_TRADING=user.get("paper", True), PAPER_BALANCE=1000,
                STOP_LOSS_PIPS=20.0, TAKE_PROFIT_PIPS=40.0,
                RISK_PER_TRADE=0.005, LEVERAGE=30.0, MARGIN_CAP=0.5,
                MAX_SPREAD_PIPS=3.0, MIN_CONFIDENCE=62,
            )
            broker = CtraderBroker(fake_cfg)
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
                f"📊 <b>If you close right now:</b>\n"
                f"Current price: <b>{_fmt_px(price)}</b>\n"
                f"Gross P&amp;L: <b>{sign}${gross:.2f}</b>\n"
                f"Spread cost: <b>−${cost:.2f}</b>\n"
                f"Net: <b>{sign}${net:.2f}</b>\n"
                f"Balance after: <b>${bal:.2f}</b>\n\n"
                f"<i>Send</i> <code>/close</code> <i>to actually close it.</i>")
        return True

    # Close intent
    if _RE_CLOSE_FX.search(t) and not _RE_BUY_FX.search(t):
        dash = user_loop.get_dash(chat_id) or {}
        if not dash.get("openPosition"):
            send_to(chat_id, "📭 No open position.")
            return True
        _handle_close(chat_id)
        return True

    # All-in
    if _RE_ALL_IN_FX.search(t):
        sym = _user_symbol(chat_id)
        dash = user_loop.get_dash(chat_id) or {}
        bal = dash.get("balance", 1000.0)
        send_to(chat_id, f"⚡ <b>ALL IN</b> — BUY <b>{sym}</b> with <b>${bal * 0.98:.0f}</b>…")
        result = user_loop.force_trade(str(chat_id), "BUY", sym)
        _send_fx_trade_result(chat_id, result, sym)
        return True

    # BUY intent
    if _RE_BUY_FX.search(t):
        sym = _pair_from_text(t) or _user_symbol(chat_id)
        send_to(chat_id, f"⚡ Opening <b>BUY {sym}</b>…")
        result = user_loop.force_trade(str(chat_id), "BUY", sym)
        _send_fx_trade_result(chat_id, result, sym)
        return True

    # SELL/SHORT intent
    if _RE_SELL_FX.search(t):
        sym = _pair_from_text(t) or _user_symbol(chat_id)
        send_to(chat_id, f"⚡ Opening <b>SELL {sym}</b>…")
        result = user_loop.force_trade(str(chat_id), "SELL", sym)
        _send_fx_trade_result(chat_id, result, sym)
        return True

    return False


def _handle_why_no_trade(chat_id):
    """"Why isn't it trading?" — the question a waiting client actually asks.

    Answered from what the loop already recorded: whether it is on, whether a
    position is already open, and the reasons it refused today's candidates.
    Silence here is what makes a working bot look broken.
    """
    dash = user_loop.get_dash(chat_id) or {}
    if not user_loop.is_running(chat_id):
        return send_to(chat_id,
                       "⏸ <b>The bot is OFF</b> — that's why nothing is "
                       "happening. Send /start to switch it on.",
                       _dashboard_keyboard(chat_id))
    lines = ["🔍 <b>Why no trade right now</b>", ""]
    if dash.get("openPosition"):
        lines.append(f"You already have a position open on "
                     f"<b>{dash['openPosition'].get('symbol', '—')}</b>, and "
                     f"the limit is {dash.get('maxpos', 1)} at a time. It "
                     f"looks for the next setup once this one closes.")
    else:
        lines.append("It's on and watching — it only enters when a setup "
                     "passes every check, which is the point. Most candidates "
                     "are refused.")
    skips = dash.get("skips") or []
    if skips:
        lines.append(f"\n<b>Refused today ({dash.get('skipsToday', len(skips))}):</b>")
        for s in skips[:4]:
            lines.append(f"• {_esc(s.get('time', ''))} — {_esc(s.get('reason', ''))}")
    market = "open" if forex.is_market_open() else "closed (weekend)"
    lines.append(f"\n🕐 Market: <b>{market}</b>")
    lines.append("\n<i>No setup is better than a bad one — a refused trade "
                 "costs nothing.</i>")
    send_to(chat_id, "\n".join(lines), _dashboard_keyboard(chat_id))


# Common questions → the handler that already answers them. Routing rather
# than re-answering: a second copy of /status drifts from the real one, which
# is how /ctaccount ended up with three different formatters.
_QUICK_ROUTES = {
    "status":       lambda cid: _handle_status(cid),
    "why_no_trade": lambda cid: _handle_why_no_trade(cid),
    "strategy":     lambda cid: _handle_strategy(cid, ""),
    "risk":         lambda cid: _handle_risk(cid, ""),
    "news":         lambda cid: _handle_news(cid),
    "market":       lambda cid: _handle_market(cid),
    "help":         lambda cid: _handle_quick_help(cid),
    "summary":      lambda cid: (send_daily_summary(cid)
                                 or send_to(cid, "📊 No closed trades today yet.")),
    "greeting":     lambda cid: _handle_quick_help(cid),
    "thanks":       lambda cid: send_to(cid, "👍 Any time."),
}


def _handle_quick_answer(chat_id, text) -> bool:
    """Answer from the dashboard when the question is a plain lookup.

    Every AI provider here shares one free-tier quota with the trading signal,
    so spending a model call on "what's my balance" takes budget from the
    decision the client is paying for. Returns False for anything that is a
    real question — the assistant is better at those, and a canned reply in
    its place is a downgrade, not a saving.
    """
    try:
        key = quick_answers.resolve(text)
    except Exception as e:
        print(f"[QuickAnswer] resolve failed: {e}")
        return False
    route = _QUICK_ROUTES.get(key)
    if not route:
        return False
    try:
        route(chat_id)
    except Exception as e:
        # Never swallow the message: fall back to the assistant.
        print(f"[QuickAnswer] '{key}' failed: {e}")
        return False
    return True


def _send_fx_trade_result(chat_id, result, sym):
    if result.get("ok"):
        send_to(chat_id,
                f"✅ <b>{result['side']} {sym}</b> opened\n"
                f"Price: <b>{_fmt_px(result['price'])}</b> | Units: {result.get('units', '—')}\n"
                f"SL: {_fmt_px(result['sl'])} | TP: {_fmt_px(result['tp'])}\n"
                f"Spread: {result.get('spread', '—')}p\n"
                f"<i>Close it with</i> <code>/close</code>")
    else:
        err = result.get("error", "unknown error")
        send_to(chat_id, f"❌ Couldn't open the trade: <i>{err}</i>")


# ─── Telegram API helpers ─────────────────────────────────

def _esc(v) -> str:
    """Escape dynamic text for Telegram HTML. A bare '<' (e.g. 'EMA50<EMA200'
    in a signal reasoning) makes the API reject the WHOLE message with a parse
    error — and it used to be dropped silently, so trade alerts never arrived."""
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt_px(v) -> str:
    """Human price: kills float noise like 0.7017249999999999 in alerts."""
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return "—"


def _post_message(chat_id, text, extra=None):
    """sendMessage with a visible failure path: log the API error and, on an
    HTML parse error, resend as plain text — an alert must never vanish."""
    r = requests.post(f"{_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                            **(extra or {})}, timeout=6)
    try:
        data = r.json()
    except Exception:
        return
    if not data.get("ok"):
        desc = str(data.get("description", ""))
        print(f"[TELEGRAM] send to {chat_id} failed: {desc[:140]}")
        if "parse" in desc.lower():
            plain = re.sub(r"<[^>]+>", "", text)
            requests.post(f"{_API}/sendMessage",
                          json={"chat_id": chat_id, "text": plain, **(extra or {})},
                          timeout=6)


def send(text, extra=None):
    if not TOKEN or not CHAT_ID:
        return
    try:
        _post_message(CHAT_ID, text, extra)
    except Exception as e:
        print(f"[TELEGRAM] Send error: {e}")


def send_to(chat_id, text, extra=None):
    if not TOKEN:
        return
    try:
        _post_message(chat_id, text, extra)
    except Exception as e:
        print(f"[TELEGRAM] Send error: {e}")


def _delete_message(chat_id, message_id):
    try:
        requests.post(f"{_API}/deleteMessage",
                      json={"chat_id": chat_id, "message_id": message_id}, timeout=6)
    except Exception:
        pass


# ─── Runtime config persistence ──────────────────────────

def _load_runtime_raw() -> dict:
    try:
        with open(_RUNTIME) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_runtime(updates: dict):
    """Persist settings to runtime.json, with broker secrets encrypted at rest.

    This file used to hold CTRADER_CLIENT_SECRET and MT_BRIDGE_SECRET in
    plaintext on disk, while user_store had been Fernet-encrypting the very
    same class of value all along — two stores, one threat model, one of them
    ignoring it. Anyone with the filesystem (a stray backup, a shared volume,
    a container image layer) could read live broker credentials.

    Encryption needs TOKEN_ENCRYPTION_KEY. Without it there is nothing to
    encrypt WITH, so a secret is refused rather than written in the clear:
    losing a setting is recoverable, leaking a broker credential is not.
    """
    # RAW, not the decrypting reader: re-reading decrypted and writing the
    # whole dict back would put every previously-encrypted secret on disk in
    # plaintext — the exact leak this function exists to close.
    data = _load_runtime_raw()
    safe = {}
    for k, v in updates.items():
        if is_secret_key(k):
            enc = user_store.encrypt_value(str(v))
            if enc == str(v):          # unchanged → no key configured
                print(f"[Telegram] refusing to persist {k}: TOKEN_ENCRYPTION_KEY "
                      f"is not set, so it would be written in plaintext. It is "
                      f"live for this process; set it as a platform env var to "
                      f"make it survive a restart.")
                continue
            safe[k] = enc
        else:
            safe[k] = v
    data.update(safe)
    with open(_RUNTIME, "w") as f:
        json.dump(data, f, indent=2)


def _load_runtime() -> dict:
    """runtime.json with any encrypted secret opened back up."""
    raw = _load_runtime_raw()
    for k in list(raw):
        if is_secret_key(k):
            raw[k] = user_store.decrypt_value(raw[k])
    return raw



_BROKER_KEYS = {
    "ctrader": ["CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET"],
    "mt": ["MT_BRIDGE_SECRET"],
}


def _broker_label():
    if cfg.BROKER == "ctrader":
        return f"cTrader ({cfg.CTRADER_ENV})"
    if cfg.BROKER == "mt":
        return "MetaTrader Bridge"
    return f"cTrader ({cfg.CTRADER_ENV})"


# ─── Strict settings allowlist ───────────────────────────
# /setkeys used to accept ANY key: it uppercased whatever was typed, wrote it
# to os.environ, setattr'd it onto the cfg module, and persisted it to
# runtime.json. Nine keys had a type cast; everything else went through raw.
# That is a generic mutation surface over live trading configuration, and
# admin-only is not a substitute for validation — a fat-fingered
# RISK_PER_TRADE=50 was as accepted as a typo'd key that silently did nothing.
#
# Every settable value now declares its own validator. Unknown keys are
# rejected, out-of-range values are rejected, and credentials are a separate
# category from trading settings so rotating a secret is never mixed up with
# changing risk.

def _num(cast, lo, hi):
    def check(v):
        try:
            x = cast(str(v).strip())
        except (TypeError, ValueError):
            raise ValueError(f"expected a number between {lo} and {hi}")
        if not (lo <= x <= hi):
            raise ValueError(f"must be between {lo} and {hi}, got {x}")
        return x
    return check


def _choice(*allowed):
    def check(v):
        s = str(v).strip().lower()
        if s not in allowed:
            raise ValueError("must be one of: " + ", ".join(allowed))
        return s
    return check


def _flag(v):
    s = str(v).strip().lower()
    if s not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise ValueError("must be true or false")
    return s in ("true", "1", "yes", "on")


def _symbol(v):
    s = re.sub(r"[^A-Z0-9]", "", str(v).strip().upper())
    if not (5 <= len(s) <= 8) or not s.isalnum():
        raise ValueError("expected a symbol like EURUSD or XAUUSD")
    return s


def _secret(min_len):
    def check(v):
        s = str(v).strip()
        if len(s) < min_len:
            raise ValueError(f"too short — expected at least {min_len} characters")
        if any(c.isspace() for c in s):
            raise ValueError("must not contain whitespace")
        return s
    return check


# key → (cfg attribute, validator). Trading settings: safe to echo back.
_SETTABLE = {
    "BROKER":           ("BROKER",           _choice("ctrader", "mt")),
    "PAPER_TRADING":    ("PAPER_TRADING",    _flag),
    "TRADE_SYMBOL":     ("SYMBOL",           _symbol),
    "RISK_PER_TRADE":   ("RISK_PER_TRADE",   _num(float, 0.0001, 0.10)),
    "STOP_LOSS_PIPS":   ("STOP_LOSS_PIPS",   _num(float, 1.0, 500.0)),
    "TAKE_PROFIT_PIPS": ("TAKE_PROFIT_PIPS", _num(float, 1.0, 1000.0)),
    "MIN_CONFIDENCE":   ("MIN_CONFIDENCE",   _num(int, 0, 100)),
    "CTRADER_ENV":      ("CTRADER_ENV",      _choice("demo", "live")),
    "LEVERAGE":         ("LEVERAGE",         _num(float, 1.0, 500.0)),
}

# Credentials: same validation discipline, but the VALUE is never echoed,
# logged or audited — only the fact that it changed.
_SETTABLE_SECRETS = {
    "CTRADER_CLIENT_ID":     ("CTRADER_CLIENT_ID",     _secret(6)),
    "CTRADER_CLIENT_SECRET": ("CTRADER_CLIENT_SECRET", _secret(12)),
    "MT_BRIDGE_SECRET":      ("MT_BRIDGE_SECRET",      _secret(16)),
}

_ALL_SETTABLE = {**_SETTABLE, **_SETTABLE_SECRETS}


def is_secret_key(key):
    return str(key).strip().upper() in _SETTABLE_SECRETS


def validate_setting(key, raw):
    """(canonical_key, coerced_value) or raise ValueError. Rejects unknown keys."""
    k = str(key).strip().upper()
    if k not in _ALL_SETTABLE:
        raise ValueError("unknown setting")
    _attr, check = _ALL_SETTABLE[k]
    return k, check(raw)


def _safe_repr(key, value):
    """What may appear in a message or an audit record."""
    return "***" if is_secret_key(key) else str(value)


def _apply(env_key: str, value):
    """Set a key on cfg module and os.environ so it takes effect immediately.

    Allowlist-only. Callers inside this module pass keys from _SETTABLE, so
    this is not a behaviour change for them — it closes the path where an
    arbitrary attribute could be written onto the live cfg module.
    """
    env_key = str(env_key).strip().upper()
    if env_key not in _ALL_SETTABLE:
        raise ValueError(f"refusing to set unknown config key {env_key!r}")
    attr, check = _ALL_SETTABLE[env_key]
    # Coerce through the same validator the command path uses, so an
    # internal caller cannot install a type the rest of the code will not
    # expect (PAPER_TRADING must be a bool, RISK_PER_TRADE a float).
    coerced = check(value)
    os.environ[env_key] = str(coerced)
    setattr(cfg, attr, coerced)


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


def _guide_url():
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    return f"{base}/guide-app" if base else ""


def _guide_button():
    url = _guide_url()
    return ({"reply_markup": {"inline_keyboard": [[
        {"text": "📖 How it works — open the guide", "web_app": {"url": url}}]]}}
        if url else None)


def _handle_guide(chat_id):
    url = _guide_url()
    if not url:
        return send_to(chat_id, "⚠️ Guide isn't available (RENDER_EXTERNAL_URL not set).")
    send_to(chat_id,
        "📖 <b>Apex — How it works</b>\n\nA 2-minute visual guide: connecting, setup, "
        "how it trades, the controls and the terminal. Tap to open.",
        _guide_button())


_QUICK_HELP = (
    "❓ <b>How this works</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "The bot watches the market for you and trades on its own. You don't need "
    "to keep anything open — it runs in the cloud, 24/5.\n\n"
    "<b>You only need three things:</b>\n"
    "▶️ <b>Turn it ON</b> — it starts looking for setups\n"
    "📈 <b>How am I doing</b> — balance, open trade, results\n"
    "🛡 <b>Risk</b> — how much of your account each trade may lose\n\n"
    "I message you when a trade opens, when it closes, and once at the end of "
    "the day. Nothing else, unless you ask for it with /verbose.\n\n"
    "<i>Trading carries risk. You can stop the bot any time with /stop — an "
    "open trade keeps its protective stop.</i>"
)


def _handle_quick_help(chat_id):
    """What a beginner needs, in a card they can read in ten seconds.

    /controls lists 24 commands. That is the right reference and the wrong
    first thing to hand somebody — it reads as "this is complicated", which
    is the opposite of true here.
    """
    send_to(chat_id, _QUICK_HELP, extra={"reply_markup": {"inline_keyboard": [
        [{"text": "📋 See every command", "callback_data": "go:controls"}]]}})


# ─── Navigation ───────────────────────────────────────────
#
# Buttons first, commands second. Every command still works — they are the
# power-user path and several people rely on them — but nobody should have to
# discover a 24-line list to find out how much their bot is risking.
#
# Callback payloads are short, stable and say nothing about the internals: a
# screen is `nav:<screen>`, an action is `<verb>:<what>`. No user ids, no
# account numbers, no strategy-registry keys that would leak the shape of the
# engine into a string the client can read off a button.


def _kb(rows):
    """`extra` for a list of rows of (label, callback) pairs. Empty → no markup."""
    kb = [[{"text": t, "callback_data": d} for t, d in row] for row in rows if row]
    return {"reply_markup": {"inline_keyboard": kb}} if kb else None


def _menu_rows(chat_id=None):
    """The main menu. Pause/Resume reflects the real running state."""
    running = False
    if chat_id is not None:
        try:
            running = bool(user_loop.is_running(chat_id))
        except Exception:
            running = False
    return [
        [("🏠 Home", "nav:home"), ("📊 Overview", "nav:over")],
        [("📈 Positions", "nav:pos"), ("👤 Account", "nav:acct")],
        [("🎯 Strategy", "nav:strat"), ("🛡 Risk", "nav:risk")],
        [("🤖 Automation", "nav:auto"), ("📒 Performance", "nav:perf")],
        [("📡 Market", "nav:mkt"), ("📰 News", "nav:news")],
        [("⚙️ Settings", "nav:set"), ("🔔 Notifications", "nav:notif")],
        [("🎙 Voice control", "nav:voice")],
        [("❓ Help", "nav:help")],
        [("⏸ Pause Trading", "nav:pause")] if running
        else [("▶️ Resume Trading", "nav:resume")],
        [("🚨 Emergency", "nav:emg")],
    ]


def _menu_kb(chat_id=None):
    return _kb(_menu_rows(chat_id))


def _back_kb(chat_id=None, extra_rows=None):
    """Every screen has a way back. A screen you can only leave by typing a
    command is a dead end, and dead ends are where clients stop exploring."""
    return _kb(list(extra_rows or []) + [[("☰ Menu", "nav:menu")]])


# ─── Authoritative account state ──────────────────────────
#
# `refresh=True` is passed at exactly the moments the specification names:
# /start, connecting an account, reconnecting, switching account, refreshing
# the dashboard, and before anything that touches real money. Everywhere else
# reads what is already known — a screen that opened a broker socket per tap
# would be slower than the client's patience and would still be a cache one
# tick later.

def _ui(chat_id, refresh=False, force=False):
    from apex import ui_state
    return ui_state.resolve(chat_id, refresh_broker=refresh, force=force)


def _screen_home(chat_id, refresh=True):
    """The state-aware home. One bot; which of A–H it is decides the screen."""
    from apex import screens
    st = _ui(chat_id, refresh=refresh)
    dash = {}
    try:
        dash = user_loop.get_dash(chat_id) or {}
    except Exception as e:
        print(f"[Telegram] home: dash unreadable for {chat_id}: {e}")
    bal = dash.get("balance") if st.connected else None
    n = None
    try:
        n = user_loop.open_position_count(chat_id)
    except Exception as e:
        print(f"[Telegram] home: position count unreadable for {chat_id}: {e}")
    send_to(chat_id, screens.home(st, balance=bal, open_count=n),
            _kb(screens.home_rows(st)))


def _handle_menu(chat_id):
    send_to(chat_id,
            f"☰ <b>{cfg.BOT_NAME.upper()} — Menu</b>\n"
            f"{_state_line(chat_id)}\n\n"
            "<i>Everything the bot does, in one place. You can also type any "
            "command directly — /allcommands lists them.</i>",
            _menu_kb(chat_id))


# ─── Always-visible state ─────────────────────────────────
#
# Three facts have to be on every screen where a client might act: whether
# this is real money, how much the bot may do without asking, and whether the
# risk guard is currently holding trading. Each is read from real state; when
# a fact is not known yet it says so rather than defaulting to the reassuring
# answer.

def _mode_label(user):
    """Demo / Live / Paper, read straight off a record with nothing else.

    Kept deliberately record-shaped and dependency-free: it is used where a
    single dict is all there is (the onboarding summary), and its honest-label
    rule — an unread record is UNKNOWN, never "Paper" — is pinned by its own
    test.

    It is NOT the authoritative environment. That question is
    `ui_state.environment`, which asks the connected broker account rather
    than a cached flag, and it is what every screen and every alert reads.

    `None` means the record could not be read, and that is NOT the same as an
    empty record. `{}.get("paper", True)` is True, so falling back to a bare
    dict would print "Paper · simulated" across a live account whenever the
    store hiccuped — the one direction this badge must never be wrong in.
    """
    if user is None:
        return "⚠️ account mode unknown"
    u = user or {}
    if u.get("paper", True):
        return "📝 Paper · simulated"
    return ("🔴 LIVE · real money"
            if (u.get("ctrader_env") or "demo").lower() == "live"
            else "🧪 Demo")


def _guard_label(chat_id):
    """Risk Guard state, or an honest 'not reported yet'.

    Read from what the loop published. Recomputing it here would mean calling
    strategies.should_stop(), which advances the peak-balance and daily-reset
    state — drawing a badge must not move the risk engine.
    """
    g = (user_loop.get_dash(chat_id) or {}).get("riskGuard")
    if not isinstance(g, dict):
        return "🛡 Risk Guard: <i>no report yet</i>"
    if g.get("halted"):
        why = "; ".join(str(r) for r in (g.get("reasons") or [])) or "risk limit hit"
        return f"🛑 Risk Guard: <b>HOLDING</b> — {_esc(why)}"
    return "🛡 Risk Guard: <b>active</b>"


def _state_line(chat_id, guard=False):
    """The one-line state banner. `guard=True` on screens where money moves.

    Total by construction. This runs inside the trade alerts, so every part of
    it is wrapped: a decorative banner must never be the reason a client is not
    told that their money moved. `_guard_label` in particular reads the
    published dash, which is a network hop on Upstash — one timeout there would
    otherwise take the whole "position opened" message down with it.

    Each piece degrades to an honest shorter line. None of them degrade to a
    reassuring one.

    The environment half now comes from `ui_state`, which derives it from the
    account the client actually connected rather than from the `ctrader_env`
    flag this used to trust. The flag is writable by a command; the account is
    not.
    """
    try:
        from apex import screens, ui_state
        return screens.banner(ui_state.resolve(chat_id), guard=guard)
    except Exception as e:
        print(f"[Telegram] state banner failed for {chat_id}: {e}")
    # Last resort. A banner is decoration and must never be the reason a
    # client is not told their money moved, so even a total failure of the
    # state layer still returns a string — one that claims nothing.
    line = "🟠 VERIFICATION REQUIRED — your account state is unknown right now"
    if guard:
        line += "\n🛡 Risk Guard: <i>no report yet</i>"
    return line


def _dashboard_keyboard(chat_id=None):
    """One clear control surface: a big ON/OFF toggle + the live terminal.
    The toggle reflects the real running state so nobody has to remember
    /start vs /stop — you just tap."""
    rows = []
    if chat_id is not None:
        if user_loop.is_running(chat_id):
            rows.append([{"text": "⏸  Turn bot OFF", "callback_data": "bot:off"}])
        else:
            rows.append([{"text": "▶️  Turn bot ON — start trading", "callback_data": "bot:on"}])
    term_url = DASHBOARD_URL or ((os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/") + "/app"
                                 if os.getenv("RENDER_EXTERNAL_URL") else "")
    if term_url:
        rows.append([{"text": "📊 Open Terminal", "web_app": {"url": term_url}}])
    if chat_id is not None:
        # The three questions a beginner actually has, as taps rather than
        # commands they must first discover in a 24-line list: how am I
        # doing, how do I change what it trades, how do I change how much it
        # risks. "Build strategy" answered none of them.
        rows.append([{"text": "📈 How am I doing?", "callback_data": "go:status"},
                     {"text": "🛡 Risk", "callback_data": "go:risk"}])
        rows.append([{"text": "🎯 Trading method", "callback_data": "go:strategy"},
                     {"text": "❓ Help", "callback_data": "go:help"}])
        rows.append([{"text": "⚙️ Build strategy", "callback_data": "bld:open"}])
        # Everything else lives one tap away rather than behind a command the
        # client would first have to find in /allcommands.
        rows.append([{"text": "☰ Menu — everything else", "callback_data": "nav:menu"}])
    # Discoverable path from demo → real money without knowing a command.
    if chat_id is not None:
        try:
            # Offered from the connected account, not from the cached flag —
            # the same rule the rest of the interface follows. No refresh here:
            # drawing a keyboard must not open a broker socket.
            from apex import ui_state
            u = user_store.load(chat_id)
            env, _p, _w = ui_state.environment(u)
            if u.get("ctrader_access_token") and env != ui_state.LIVE:
                rows.append([{"text": "🔴 Switch to Live", "callback_data": "acct:switch"}])
        except Exception as e:
            print(f"[Telegram] dashboard keyboard: state unreadable: {e}")
    if not rows:
        return {}
    return {"reply_markup": json.dumps({"inline_keyboard": rows})}


def _build_status(dash, chart=""):
    sb = dash.get("startBalance", 0)
    pnl_pct = ((dash.get("balance", 0) - sb) / sb * 100) if sb > 0 else 0.0
    sign = "+" if pnl_pct >= 0 else ""
    trades = dash.get("trades", [])
    wins = sum(1 for t in trades if t.get("win"))
    total = len(trades)
    win_rate = f"{wins / total * 100:.0f}%" if total else "—"
    chart_line = (f"\n<code>{chart}</code>  <b>{_fmt_px(dash.get('currentPrice', 0))}</b>") if chart else ""
    # Crypto trades 24/7 and has no forex "sessions" — showing London/New York
    # on a crypto bot is wrong. Forex keeps the session line.
    if getattr(cfg, "MARKET_24_7", False):
        market_line = "🕐 Market: 🟢 <b>24/7</b> · crypto never sleeps"
    else:
        market = "🟢 OPEN" if forex.is_market_open() else "🔴 CLOSED (weekend)"
        sessions = ", ".join(forex.active_sessions()) or "—"
        market_line = f"🕐 Market: {market} · Sessions: {sessions}"
    oc = dash.get("openCount", 0)
    if dash.get("openPosition"):
        op = dash["openPosition"]
        d = "🟢 LONG" if op["side"] == "BUY" else "🔴 SHORT"
        # Floating P&L, written by user_loop._price_open_position. This used to
        # read `currentPnl`, a key nothing in the codebase has ever written, so
        # every open position reported exactly +$0.00 for its whole life. When
        # the number genuinely isn't there yet (first tick after a restart),
        # say so instead of printing a zero that looks like a real result.
        pnl = op.get("pnlUsd")
        pips = op.get("pnlPips")
        if pnl is None:
            pnl_txt = "…" if pips is None else f"{pips:+.1f} pips"
        else:
            pnl_txt = f"{'+' if pnl >= 0 else '−'}${abs(pnl):.2f}"
            if pips is not None:
                pnl_txt += f"  ({pips:+.1f} pips)"
        pos_line = (f"{d} <b>{op['symbol']}</b>\n  Entry: {op['entryPrice']}  "
                    f"SL: {_fmt_px(op.get('stopLoss') or 0)}\n"
                    f"  PnL: <b>{pnl_txt}</b>")
        if oc > 1:
            pos_line += f"\n  <i>+{oc - 1} more open — see the terminal / cTrader</i>"
    elif oc > 0:
        pos_line = f"📊 <b>{oc} position{'s' if oc != 1 else ''} open</b> — managed by their broker stops. See the terminal."
    else:
        pos_line = "📭 No open position"
    return (f"{cfg.ASSET_EMOJI} <b>{cfg.BOT_NAME.upper()}</b>  {dash.get('mode', '')} · "
            f"{dash.get('broker', '')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: <b>${dash.get('balance', 0):.2f}</b>  ({sign}{pnl_pct:.2f}%)"
            f"{' ⏳ <i>refreshing…</i>' if dash.get('balStale') else ''}{chart_line}\n"
            f"{market_line}\n"
            f"🎯 Method: {dash.get('strategy', 'Mean Reversion')}\n"
            + (f"📊 Positions: {dash.get('openCount', 0)}/{dash['maxpos']} open\n" if dash.get('maxpos', 1) > 1 else "")
            + (f"🤖 Auto-Pilot: scanning {len(dash['watchlist'])} instruments — focus {dash.get('symbol', '')}\n" if dash.get('autopilot') and dash.get('watchlist')
               else f"👁 Scanning: {' · '.join(dash['watchlist'])} — focus {dash.get('symbol', '')}\n" if dash.get('watchlist') else "")
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
    # A dashboard refresh is one of the moments the account environment is
    # re-established from the broker rather than from what we last stored.
    # Nothing else on this screen means anything until "whose money is this"
    # has a current answer.
    st = _ui(chat_id, refresh=True)
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
            running = user_loop.is_running(chat_id)
            header = ("✅ <b>BOT IS ON</b> — watching the market.\n\n" if running
                      else "⏸ <b>BOT IS OFF</b> — tap ▶️ below to start.\n\n")
            send_to(chat_id,
                    header + _state_line(chat_id) + "\n\n" +
                    f"{cfg.ASSET_EMOJI} <b>{cfg.BOT_NAME.upper()}</b>  {mode_label}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Balance: <b>${bal:.2f}</b>\n"
                    f"{cfg.ASSET_EMOJI} Pair: <b>{sym}</b> | "
                    f"{'🟢 OPEN' if is_open else '🔴 CLOSED (weekend)'}",
                    _dashboard_keyboard(chat_id))
            return
        dash = _get_dash()
    if not dash or not dash.get("broker"):
        return send_to(chat_id,
            "⏸ <b>Bot is OFF.</b> Tap the button to start trading.",
            _dashboard_keyboard(chat_id))
    chart = ""
    if _broker:
        try:
            candles = _broker.get_candles(dash.get("currentSymbol"), "5m", 24)
            chart = mini_chart([c["close"] for c in candles])
        except Exception:
            pass
    # Crystal-clear ON/OFF header so 'running but no position' never reads as
    # 'broken'. Running = watching, will trade when a valid setup appears.
    running = user_loop.is_running(chat_id)
    header = ("✅ <b>BOT IS ON</b> — watching the market, it trades automatically when a valid setup appears.\n\n"
              if running else
              "⏸ <b>BOT IS OFF</b> — tap ▶️ below to start.\n\n")
    # Demo-or-live, how much the bot may do alone, and whether the risk guard
    # is holding — the three things that must be visible wherever a client
    # might act on what they are reading. Plus, when this is a live account
    # with something critical unestablished, the fact that new real-money
    # entries are switched off — stated on the screen the client is reading,
    # not left for them to infer from the bot never trading.
    from apex import screens
    blocked = (screens._blocked_note(st)
               if st.is_live and not st.live_orders_offered else "")
    send_to(chat_id,
            header + _state_line(chat_id, guard=True) + "\n\n"
            + _build_status(dash, chart) + blocked, _dashboard_keyboard(chat_id))


# ─── Setup wizard ─────────────────────────────────────────

def _handle_setup(chat_id):
    with _lock:
        _wizards[chat_id] = {"step": "MODE", "data": {}}
    if _LIVE_BROKER_REQUIRED:
        send_to(chat_id,
                f"🛠️ <b>{cfg.BOT_NAME.upper()} SETUP</b>\n\n"
                "1/5 — <b>How do you want to trade?</b>\n\n"
                "Reply <code>1</code> or <code>2</code>:\n"
                "  <code>1</code> — 🧪 <b>Demo</b> (test the bot risk-free — note: free access "
                f"needs a <b>live {_REQUIRED_BROKER_LABEL}</b> account, so this won't unlock trading).\n"
                f"  <code>2</code> — 🔴 <b>Live</b> (real money via a live <b>{_REQUIRED_BROKER_LABEL}</b> "
                "account — required for free access).\n\n"
                f"<i>Free access requires a live {_REQUIRED_BROKER_LABEL} account — most people pick 2.</i>")
    else:
        send_to(chat_id,
                f"🛠️ <b>{cfg.BOT_NAME.upper()} SETUP</b>\n\n"
                "1/5 — <b>How do you want to trade?</b>\n\n"
                "Reply <code>1</code> or <code>2</code>:\n"
                "  <code>1</code> — 🧪 <b>Demo</b> (free demo account on cTrader — "
                "real market data, no risk).\n"
                "  <code>2</code> — 🔴 <b>Live</b> (real money via <b>cTrader</b> — any broker "
                "worldwide).\n\n"
                "<i>Most people start with 1 (demo) to test the bot risk-free.</i>")


def _handle_wizard_reply(chat_id, raw, msg_id):
    with _lock:
        w = _wizards.get(chat_id)
        step = w.get("step") if w else None
    if not w:
        return   # no active wizard for this chat

    if step == "MODE":
        choice = raw.strip()
        if choice not in ("1", "2"):
            return send_to(chat_id, "❌ Reply <code>1</code> (demo) or <code>2</code> (live).")
        if choice == "1":
            with _lock:
                w["data"]["paper"] = False
                w["data"]["env"] = "demo"
                _wizards.pop(chat_id, None)
            if _LIVE_BROKER_REQUIRED:
                send_to(chat_id,
                        "🧪 <b>Demo mode</b>\n\n"
                        f"⚠️ Free access needs a <b>live {_REQUIRED_BROKER_LABEL}</b> account — "
                        "a demo account won't unlock trading. Create a demo only if you want "
                        f"to test the bot first, then open a live {_REQUIRED_BROKER_LABEL} "
                        "account when you're ready.\n\n"
                        "<b>Next:</b> Send <b>/ctrader</b> to connect your account.")
            else:
                send_to(chat_id,
                        "🧪 <b>Demo mode</b>\n\n"
                        "Create a free demo account on any <b>cTrader</b> broker "
                        "(IC Markets, Pepperstone, FxPro…) and link it here.\n\n"
                        "<b>Next:</b> Send <b>/ctrader</b> to connect your account.")
        else:
            with _lock:
                w["data"]["paper"] = False
                w["data"]["env"] = "live"
                _wizards.pop(chat_id, None)
            if _LIVE_BROKER_REQUIRED:
                send_to(chat_id,
                        "🔴 <b>Live trading — via cTrader</b>\n\n"
                        f"Free access runs through a live <b>{_REQUIRED_BROKER_LABEL}</b> "
                        "account specifically — that's who verifies and funds your free bot.\n\n"
                        "<b>Next step:</b>\n"
                        "1️⃣ Send <b>/ctrader</b> → tap <b>Authorize</b> → log in and approve\n\n"
                        "<i>Send /ctrader now to link your account.</i>")
            else:
                send_to(chat_id,
                        "🔴 <b>Live trading — via cTrader</b>\n\n"
                        "Real money runs through your own <b>cTrader</b> account (works with "
                        "any cTrader broker worldwide — IC Markets, Pepperstone, FxPro…).\n\n"
                        "<b>Next step:</b>\n"
                        "1️⃣ Send <b>/ctrader</b> → tap <b>Authorize</b> → log in and approve\n\n"
                        "<i>Send /ctrader now to link your account.</i>")

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
                f"{cfg.ASSET_NOUN.capitalize()} trading carries a real risk of loss. <b>You alone</b> chose:\n"
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
        # Forex + metals only — never let onboarding persist a crypto/index symbol.
        if not forex.is_tradeable(sym):
            sym = "EUR_USD"

        # Save per-user settings — every risk parameter was chosen by the client
        user_data = {
            "paper": d.get("paper", True),
            "symbol": sym,
            "risk": d.get("risk", 0.005),
            "min_confidence": d.get("min_confidence", 62),
            "accepted_risk": True,
            "active": True,
        }
        user_data["ctrader_env"] = d.get("env", "demo")
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
                # The configurator posts whatever it likes here. Keep only
                # keys this bot actually recognises, validated -- an unknown
                # or malformed one used to be written straight onto cfg.
                for rk, rv in (d["keys"] or {}).items():
                    try:
                        ck, _cv = validate_setting(rk, rv)
                        updates[ck] = rv
                    except ValueError as e:
                        print(f"[Telegram] /setup ignoring {rk}: {e}")
            updates["BROKER"] = "ctrader"
            applied = {}
            for k, v in updates.items():
                try:
                    ck, cv = validate_setting(k, v)
                except ValueError as e:
                    print(f"[Telegram] /setup ignoring {k}: {e}")
                    continue
                applied[ck] = cv
                _apply(ck, cv)
            _save_runtime({k: str(v) for k, v in applied.items()})
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
            broker_str = f"cTrader ({user_data.get('ctrader_env', 'demo')})"
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
                f"Gemini or Groq key — your choice, both free.",
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

    # Validate EVERYTHING before applying ANYTHING. A half-applied batch
    # leaves the bot in a state the operator did not ask for and cannot see.
    accepted, rejected = {}, []
    for k, v in pairs.items():
        try:
            ck, cv = validate_setting(k, v)
            accepted[ck] = cv
        except ValueError as e:
            rejected.append(f"  {k} — {e}")

    if rejected:
        known = ", ".join(sorted(_SETTABLE)) + "\nSecrets: " + ", ".join(sorted(_SETTABLE_SECRETS))
        return send_to(
            chat_id,
            "❌ <b>Nothing was changed.</b> Rejected:\n<code>"
            + "\n".join(rejected)
            + f"</code>\n\nAllowed settings:\n<code>{known}</code>")

    _save_runtime({k: str(v) for k, v in accepted.items()})
    for k, v in accepted.items():
        _apply(k, v)
    if _bot_control.get("reload_broker"):
        _bot_control["reload_broker"]()

    # Audit: who, when, what changed — with secret VALUES never recorded.
    try:
        from apex import control
        control._audit({
            "ts": int(time.time()), "actor": str(chat_id), "action": "setkeys",
            "changed": {k: _safe_repr(k, v) for k, v in accepted.items()},
        })
    except Exception as e:
        print(f"[Telegram] setkeys audit failed: {e}")

    shown = "\n".join(f"  {k} = {_safe_repr(k, v)}" for k, v in accepted.items())
    send_to(chat_id, f"🔑 <b>{len(accepted)} setting(s) updated:</b>\n<code>{shown}</code>")


_AI_KB = {"reply_markup": json.dumps({"inline_keyboard": [
    [{"text": "🥇 Get free Gemini key", "url": "https://aistudio.google.com/apikey"}],
    [{"text": "🥈 Get free Groq key", "url": "https://console.groq.com/keys"}],
]})}


def _handle_ai_setup(chat_id, args="", msg_id=None):
    """The activation screen — or, if a key came with the command, the key.

    `/ai <key>` is the obvious thing to type and it used to be read as a bare
    `/ai`: the key was dropped on the floor, the instructions came back, and
    the client was left staring at a screen telling them to do the thing they
    had just done. Worse, the key stayed sitting in the chat history.
    """
    supplied = (args or "").strip().split()[0] if (args or "").strip() else ""
    if supplied:
        # Route it through the same verification a bare paste gets, including
        # deleting the message so the key does not linger in the chat.
        return _handle_ai_key(chat_id, supplied, msg_id)
    return _ai_setup_screen(chat_id)


def _ai_setup_screen(chat_id):
    """Explain the AI-chat key options — client connects their OWN free/paid key."""
    u = user_store.load(chat_id)
    if u.get("groq_key") or u.get("gemini_key"):
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

            "📋 <b>Just paste your key here</b> — I auto-detect which one it is and verify it.\n"
            "<i>Trading works fine without a key; this only powers the chat.</i>",
            _AI_KB)


# Credential-shaped: one unbroken token, long, mixing letters and digits.
# Used only where the client has SAID they are handing over a key.
_KEYISH = re.compile(r"^[A-Za-z0-9._\-]{30,200}$")


def _detect_ai_key(key, explicit=False):
    """Which provider a pasted key belongs to, or None.

    Prefixes are a hint, not a specification. Google AI Studio issued keys
    beginning `AIza` for years and now issues them beginning `AQ.`, and a
    client whose brand-new key was refused as "not an AI key" has no way to
    know the bot is simply out of date — the key is right there in their hand,
    working. Any prefix list will go stale the same way.

    So `explicit` (the client typed /ai, /gemini or /key, or tapped a button)
    accepts anything credential-shaped and lets GOOGLE decide, since Google is
    the only authority on whether a Gemini key is a Gemini key. `gsk_` still
    wins outright because Groq's prefix is distinctive and unambiguous.

    Without `explicit` — a bare message that might just be chat — the strict
    prefixes still apply, so an ordinary sentence is never swallowed and
    deleted as though it were a secret.
    """
    k = (key or "").strip()
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("AIza") or k.startswith("AQ."):
        return "gemini"
    if explicit and _KEYISH.match(k):
        return "gemini"
    return None


def _handle_ai_key(chat_id, key, msg_id):
    """Verify & save a pasted AI key (any provider, auto-detected)."""
    _delete_message(chat_id, msg_id)
    key = (key or "").strip().split()[0] if key else ""
    # Reached only from /ai, /gemini, /groq, /key or a bare paste that already
    # matched a known prefix — in every case the client meant "this is a key".
    kind = _detect_ai_key(key, explicit=True)
    if kind is None:
        # Name the prefix we actually got. "I couldn't tell" with no detail
        # sends people back to copy the same wrong string again — a Google
        # ephemeral token (AQ.…) looks like a key and is not one.
        seen = (key[:4] + "…") if len(key) > 4 else (key or "nothing")
        return send_to(chat_id,
                       "🤔 <b>That doesn't look like a full key.</b>\n"
                       f"I got <code>{_esc(seen)}</code> — {len(key)} characters.\n\n"
                       "Copy the <b>whole</b> key, with no spaces or line "
                       "breaks:\n"
                       "• <b>Gemini</b> → aistudio.google.com/apikey → "
                       "<b>Create API key</b>\n"
                       "• <b>Groq</b> → console.groq.com/keys "
                       "(starts <code>gsk_</code>)",
                       _AI_KB)
    label = {"groq": "Groq", "gemini": "Gemini"}[kind]
    send_to(chat_id, f"🔍 Testing your {label} key…")
    if kind == "groq":
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
                       "❌ Usage: <code>/broker ctrader</code>\n\n"
                       "• <b>ctrader</b> — cTrader Open API (connect via /ctrader)")
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
        send_to(chat_id, "✅ Broker set to <b>cTrader</b>. Use /ctrader to connect your account.")


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
    user_store.update(chat_id, {"ctrader_env": "demo" if env == "practice" else "live"})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"CTRADER_ENV": "demo" if env == "practice" else "live"})
        _apply("CTRADER_ENV", "demo" if env == "practice" else "live")
        if _bot_control.get("reload_broker"):
            _bot_control["reload_broker"]()
    icon = "🧪" if env == "practice" else "🔴"
    send_to(chat_id, f"{icon} cTrader environment set to <b>{('DEMO' if env == 'practice' else 'LIVE')}</b>.\n"
                     f"<i>Make sure your account matches this environment.</i>")


def _broker_signup_rows():
    """Broker sign-up buttons carrying the operator's IB/partner referral links
    (set via env: BROKER_NAME + BROKER_DEMO_LINK [+ BROKER_LIVE_LINK], or a
    JSON list in BROKER_LINKS for several brokers). Empty if none configured."""
    rows = []
    raw = os.getenv("BROKER_LINKS", "").strip()
    if raw:
        try:
            for b in json.loads(raw):
                if b.get("name") and b.get("url"):
                    rows.append([{"text": f"🏦 Open {b['name']} account", "url": b["url"]}])
        except Exception as e:
            print(f"[TELEGRAM] BROKER_LINKS parse error: {e}")
    else:
        name = os.getenv("BROKER_NAME", "").strip()
        demo = os.getenv("BROKER_DEMO_LINK", "").strip()
        live = os.getenv("BROKER_LIVE_LINK", "").strip()
        # Growth-phase gate: a demo account never qualifies for free access, so
        # don't hand new clients a button that leads straight to a rejection.
        if name and demo and not _LIVE_BROKER_REQUIRED:
            rows.append([{"text": f"🧪 Create a free {name} DEMO account", "url": demo}])
        if name and live:
            label = "🏦 Open a LIVE account (required for free access)" if _LIVE_BROKER_REQUIRED else f"🏦 Open a {name} live account"
            rows.append([{"text": label, "url": live}])
    return rows


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
    broker_rows = _broker_signup_rows()
    if _LIVE_BROKER_REQUIRED:
        tip = (f"💡 <b>New here?</b> Free access requires a <b>live</b> account with our "
               f"partner broker, <b>{_REQUIRED_BROKER_LABEL}</b> — a demo account or another "
               "broker won't unlock trading.\n\n")
    else:
        tip = ("💡 <b>New here?</b> Start on a demo account — test the bot risk-free, "
               "switch to live when you're confident.\n\n")
    if broker_rows:
        tip += "Don't have a cTrader account yet? Create one below, then come back and Authorize.\n\n"
    kb = broker_rows + [[{"text": "🔗 Authorize cTrader", "url": link}]]
    broker_line = (f"Free access needs a live <b>{_REQUIRED_BROKER_LABEL}</b> account specifically.\n\n"
                   if _LIVE_BROKER_REQUIRED else
                   "Works with any cTrader broker (IC Markets, Pepperstone, FxPro…).\n\n")
    send_to(chat_id,
        "🟢 <b>Connect your cTrader account</b>\n\n"
        f"{tip}"
        "1. Tap Authorize below\n"
        "2. Log in to cTrader and approve access\n"
        "3. You'll be sent back here automatically\n\n"
        f"{scope_line}"
        f"{broker_line}"
        "<i>The link is valid for 10 minutes.</i>",
        extra={"reply_markup": {"inline_keyboard": kb}})


def _apply_account(chat_id, ctid):
    """Bind the bot to a linked cTrader account by id and restart the loop.

    Switching account is one of the moments the environment is re-read from
    the broker. The list this picks from is the broker's own answer, so a
    stale entry cannot decide whether the client lands on real money.
    """
    from apex import ui_state
    user, _refreshed, _why = ui_state.refresh(chat_id, force=True)
    if user is None:
        user = user_store.load(chat_id)
    acc = next((a for a in (user.get("ctrader_accounts") or [])
                if str(a.get("ctid")) == str(ctid)), None)
    if not acc:
        return send_to(chat_id,
                       "❌ <b>That account is no longer available</b>\n\n"
                       "Your broker did not list it just now. Nothing changed "
                       "— pick another below.",
                       _kb([[("🔄 Switch account", "acct:switch")],
                            [("☰ Menu", "nav:menu")]]))
    from apex import ctrader_oauth
    gate_reason = ctrader_oauth.broker_gate_reason(acc, user.get("ctrader_access_token", ""))
    if gate_reason:
        live_link = os.getenv("BROKER_LIVE_LINK", "").strip()
        link_line = f"\n\n👉 {live_link}" if live_link else ""
        return send_to(chat_id, f"❌ <b>Account not eligible</b>\n\n"
                                f"Account <code>{ctid}</code> — {gate_reason}.{link_line}")
    ct_env = "live" if acc.get("live") else "demo"
    updates = {"ctrader_account_id": acc["ctid"], "ctrader_env": ct_env}
    # LIVE = real money: turn OFF the internal simulation so orders actually execute.
    if acc.get("live"):
        updates["paper"] = False
    bal, bal_line = balance_line(user.get("ctrader_access_token", ""),
                                 acc["ctid"], ct_env,
                                 last_known=user.get("paper_balance"))
    if bal is not None:
        updates["paper_balance"] = bal
    user_store.update(chat_id, updates)
    _restart_user_loop(chat_id)
    # Re-resolve AFTER the write, so the confirmation names the environment
    # the bot is now actually on rather than the one it was asked for.
    st = _ui(chat_id)
    send_to(chat_id,
            f"✅ <b>Now trading: {st.env_badge}</b> (account {acc['ctid']}).\n"
            f"{bal_line}"
            "Every screen from here on is about this account.",
            _dashboard_keyboard(chat_id))


def _handle_switch(chat_id):
    """Let the client change which account the bot trades — pick a linked
    account, or disconnect and connect a different one (e.g. demo → live).

    The list is re-read from the broker first: an account removed at the
    broker must not still be offered, and an account whose demo/live status
    changed must not be offered under the old label.
    """
    from apex import screens, ui_state
    user, refreshed, why = ui_state.refresh(chat_id, force=True)
    if user is None:
        user = user_store.load(chat_id)
    accounts = user.get("ctrader_accounts") or []
    if not accounts:
        return send_to(chat_id,
                       "🔌 <b>No accounts to switch between</b>\n\n"
                       f"{why.capitalize()}.\n\n"
                       "Connect an account and it will appear here.",
                       _kb([[("🔗 Connect my account", "go:connect")],
                            [("☰ Menu", "nav:menu")]]))
    head, rows = screens.account_switch(accounts, user.get("ctrader_account_id"))
    if not refreshed:
        head += f"\n\n<i>Shown from what we last saw — {why}.</i>"
    send_to(chat_id, head, _kb(rows))


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
    from apex import ctrader_oauth
    gate_reason = ctrader_oauth.broker_gate_reason(match, user.get("ctrader_access_token", ""))
    if gate_reason:
        live_link = os.getenv("BROKER_LIVE_LINK", "").strip()
        link_line = f"\n\n👉 {live_link}" if live_link else ""
        return send_to(chat_id, f"❌ <b>Account not eligible</b>\n\n"
                                f"Account <code>{want}</code> — {gate_reason}.{link_line}")
    ct_env = "live" if match.get("live") else "demo"
    updates = {"ctrader_account_id": match["ctid"], "ctrader_env": ct_env}
    # Same two problems the single-account OAuth path had, in the
    # multi-account one: a cold connection right after linking can time out
    # even though the loop reads the balance fine moments later, and
    # onboard_start() fired unconditionally — so switching accounts threw an
    # already-configured client back into "what do you want to trade?".
    bal, bal_line = balance_line(user.get("ctrader_access_token", ""),
                                 match["ctid"], ct_env,
                                 last_known=user.get("paper_balance"))
    if bal is not None:
        updates["paper_balance"] = bal
    user_store.update(chat_id, updates)
    _restart_user_loop(chat_id)
    env = "LIVE 🔴" if match.get("live") else "demo 🧪"
    if already_onboarded(user):
        send_to(chat_id, reconnect_summary(
            user, f"✅ Account <code>{match['ctid']}</code> ({env}) linked.\n{bal_line}"))
    else:
        send_to(chat_id, f"✅ Account <code>{match['ctid']}</code> ({env}) linked.\n{bal_line}"
                         "Setting up — 2 quick taps. 👇")
        onboard_start(chat_id)


# Quick-pick trade symbols — asset-class aware (crypto majors first for the
# crypto build, FX majors first for the forex build). Clients can still type
# any symbol their broker offers.
_OB_SYMS_FOREX = [
    ("EUR/USD", "EURUSD"), ("GBP/USD", "GBPUSD"), ("USD/JPY", "USDJPY"),
    ("AUD/USD", "AUDUSD"), ("USD/CHF", "USDCHF"), ("USD/CAD", "USDCAD"),
    ("🥇 Gold", "XAUUSD"), ("🥈 Silver", "XAGUSD"), ("₿ Bitcoin", "BTCUSD"),
    ("Ξ Ethereum", "ETHUSD"), ("📈 US30", "US30"), ("📈 NAS100", "NAS100"),
]
_OB_SYMS_CRYPTO = [
    ("₿ Bitcoin", "BTCUSD"), ("Ξ Ethereum", "ETHUSD"), ("◎ Solana", "SOLUSD"),
    ("✕ XRP", "XRPUSD"), ("Ł Litecoin", "LTCUSD"), ("● Cardano", "ADAUSD"),
    ("Ð Dogecoin", "DOGEUSD"), ("⬡ Polkadot", "DOTUSD"), ("🔗 Chainlink", "LINKUSD"),
    ("Ƀ Bitcoin Cash", "BCHUSD"), ("🥇 Gold", "XAUUSD"), ("🥈 Silver", "XAGUSD"),
]
_OB_SYMS = _OB_SYMS_CRYPTO if cfg.PRODUCT == "crypto" else _OB_SYMS_FOREX

_RISK_TEXT = ("⚠️ <b>Risk disclaimer</b>\n\n"
              "• No profit is guaranteed — results depend on the market\n"
              "• Losses are possible and they are <b>yours</b>\n"
              "• We provide software, not financial advice\n\n"
              "<i>Demo 🧪 · Live 🔴</i>")


# Plain-language names, because a beginner who just connected an account does
# not know what an Inverse Fair Value Gap is. The technical id stays visible
# underneath — an experienced client wants it, and it is what /strategy takes.
FRIENDLY_LABEL = {
    "auto":            "🤖 Automatic — the bot picks the method",
    "trend":           "📈 Trend Follower — rides sustained moves",
    "mean_reversion":  "↩️ Bounce Trader — buys dips, sells spikes",
    "breakout":        "🚀 Breakout — enters when price escapes a range",
    "momentum":        "⚡ Momentum — joins a move already running",
    "session_breakout": "🌍 Session Breakout — trades the London/NY open",
    "opening_range":   "🕐 Opening Range — first move of the session",
    "zscore":          "📐 Statistical — fades unusual deviations",
    "vol_regime":      "🌊 Volatility — waits for quiet, trades the burst",
    "fibonacci":       "🌀 Fibonacci — enters at retracement levels",
    "fvg":             "🕳 Gap Filler — trades unfilled price gaps",
    "ifvg":            "🔄 Reverse Gap — trades gaps that failed",
    "supply_demand":   "🏦 Supply & Demand — trades institutional zones",
    "liquidity_sweep": "🎣 Stop Hunt — enters after the market grabs stops",
    "evc":             "📊 Volume Balance — trades volume imbalances",
    "grid":            "⚠️ Grid — many small entries (high risk)",
    "martingale":      "⚠️ Martingale — larger after a loss (high risk)",
}


def friendly_strategy(key):
    """(display name, technical id). Falls back to the registry label."""
    nice = FRIENDLY_LABEL.get(key)
    if nice:
        return nice, key
    from apex import strategy_api
    cls = strategy_api._REGISTRY.get(key)
    return (getattr(cls, "label", key) if cls else key), key


def balance_line(access_token, ctid, env, last_known=None):
    """(balance_or_None, one display line) for a freshly linked account.

    The single place that decides what a client is told about their balance
    while an account is being linked. There were three, and they disagreed:
    different wording, different amount of retrying, and two of them printed
    a raw exception string that reads like the account is broken when the
    real cause is a cold connection that succeeds moments later.

    A failed read falls back to the last known figure, LABELLED as such —
    a number the client recognises beats an error they cannot act on, and
    pretending it is live would be worse than either.
    """
    from apex.brokers import ctrader as _ct
    bal, err = _ct.account_balance_retry(access_token, ctid, env)
    return bal, balance_line_from(bal, err, last_known)


def balance_line_from(bal, err=None, last_known=None):
    """The same line, from a value someone else already fetched.

    The OAuth callback needs the balance BEFORE it builds the message (it has
    to persist it), so it cannot use balance_line()'s fetch — but it must not
    grow a fourth private copy of this formatting either.
    """
    if bal is not None:
        return f"💰 Balance: <b>${bal:,.2f}</b>\n"
    if isinstance(last_known, (int, float)) and last_known:
        return (f"💰 Balance: <b>${last_known:,.2f}</b> "
                f"<i>(last known — refreshing)</i>\n")
    return f"⏳ Balance loading… <i>{(err or '')[:60]}</i>\n"


def already_onboarded(user):
    """True when this client has completed setup and must not be re-asked.

    Linking or re-linking an account is not a first run. Every path that
    connects a broker used to call onboard_start() unconditionally, so a
    reconnect or an account switch threw a configured client back into
    "what do you want to trade?" while holding an open position — which is
    indistinguishable from the bot having reset itself.
    """
    return bool((user or {}).get("symbol") and (user or {}).get("strategy"))


def reconnect_summary(user, header):
    """The message a RETURNING client gets: what is running, and the position."""
    pos = (user or {}).get("open_position_snapshot") or {}
    if pos.get("symbol"):
        pos_line = (f"📊 Open position kept: <b>{pos.get('entrySide') or pos.get('side')} "
                    f"{pos['symbol']}</b> @ {pos.get('entryPrice')}\n"
                    f"   SL {pos.get('sl')} · TP {pos.get('tp')}\n")
    else:
        pos_line = "📊 No open position.\n"
    what = "🤖 Auto-Pilot" if user.get("autopilot") else f"📈 {user.get('symbol')}"
    try:
        risk_txt = f", risk {float(user.get('risk', 0)):.1%}"
    except (TypeError, ValueError):
        risk_txt = ""
    return (f"{header}{pos_line}\n"
            f"Your setup is unchanged — {what}, {user.get('strategy')}{risk_txt}.\n"
            "Nothing was reset. Send /settings to change anything.")


# ─── Onboarding ───────────────────────────────────────────
#
# One wizard, five steps, numbered the same way the whole distance. It used to
# announce "Setup 1/2" and then "Setup 2/2" and then ask three more questions,
# which tells a new client on their first minute with the product that the
# counter cannot be trusted.
#
# The five steps are the five decisions, in the order they have to be made:
#
#   1  Connect cTrader  the broker account itself
#   2  Your Account     what we detected, confirmed by the client
#   3  Trading Style    how fast it trades (timeframe + stop scale)
#   4  Trading Method   what it looks for, and on what
#   5  Risk             how much of the balance one loss may cost
#
# THE ORDER CHANGED, AND IT MATTERS. Step 1 used to be "Demo or Live?" — a
# question asked before any account existed, whose answer was then stored as
# `account_mode` and shown around the product as though it were a fact. It was
# never a fact. A client who picked "Live" and then authorised a demo account
# was shown "Live" on every screen, and the setting they had chosen was the
# thing telling them so.
#
# Nobody is asked any more. Connecting the account IS the answer, and the
# answer comes from the broker: step 2 shows what was detected and asks only
# whether this is the account they meant.
#
# It resumes rather than restarts. Every step knows whether it is already
# satisfied, so a client arriving from the OAuth callback lands on step 3 with
# steps 1 and 2 already ticked and named.

_OB_STEPS = ("connect", "account", "style", "method", "risk")
_OB_TOTAL = len(_OB_STEPS)

_OB_TITLES = {
    "connect": "Connect cTrader",
    "account": "Your Account",
    "style":   "Trading Style",
    "method":  "Trading Method",
    "risk":    "Risk",
}


def _ob_satisfied(u, step):
    """Whether this client has already made this decision."""
    u = u or {}
    if step == "connect":
        return bool(u.get("ctrader_access_token") and u.get("ctrader_account_id"))
    if step == "account":
        # A client who has been trading a configured account for months has
        # already answered this by using it. Re-asking on a reconnect would be
        # the same "the bot reset itself" failure `already_onboarded` exists
        # to prevent, one step further in.
        return bool(u.get("account_confirmed") or already_onboarded(u))
    if step == "style":
        return bool(u.get("style"))
    if step == "method":
        return bool(u.get("strategy")) and bool(u.get("symbol") or u.get("autopilot"))
    if step == "risk":
        return bool(u.get("risk_tier"))
    return True


def _ob_trail(u, upto):
    """The 'done so far' line. Names the choice, not just a tick — a client
    who is four screens in should not have to remember what they picked."""
    done = []
    for s in _OB_STEPS[:upto]:
        if not _ob_satisfied(u, s):
            continue
        if s == "account":
            # Read from the connected account, never from a stored choice.
            from apex import ui_state
            env, _proven, _why = ui_state.environment(u)
            what = ui_state.BADGE.get(env, ui_state.BADGE[ui_state.UNKNOWN])
        elif s == "connect":
            what = "connected"
        elif s == "style":
            what = str(u.get("style", "")).title()
        elif s == "method":
            what = ("Auto-Pilot" if u.get("autopilot")
                    else friendly_strategy(u.get("strategy"))[0].split(" — ")[0])
        else:
            what = str(u.get("risk_tier", ""))
        done.append(f"✅ {_OB_TITLES[s]}: <b>{_esc(what)}</b>")
    return ("\n".join(done) + "\n\n") if done else ""


def _ob_head(chat_id, step):
    i = _OB_STEPS.index(step)
    u = user_store.load(chat_id)
    return (f"🧭 <b>Setup — Step {i + 1} of {_OB_TOTAL}: {_OB_TITLES[step]}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n" + _ob_trail(u, i))


def onboard_start(chat_id):
    """Guided setup. Renders the first step this client has not yet made.

    This is the single entry point every caller uses — the OAuth callback,
    /wizard and the account-switch path — so there is exactly one wizard and
    one place its numbering is defined.
    """
    return _ob_render(chat_id)


def _ob_render(chat_id):
    u = user_store.load(chat_id)
    for step in _OB_STEPS:
        if not _ob_satisfied(u, step):
            return _OB_RENDER[step](chat_id)
    return _ob_summary(chat_id)


# ── Step 1: Connect cTrader ──

def _ob_step_connect(chat_id):
    if _LIVE_BROKER_REQUIRED:
        note = (f"⚠️ Free access needs a <b>live {_REQUIRED_BROKER_LABEL}</b> "
                "account. A demo account lets you watch the bot work, but it "
                "will not unlock trading.")
    else:
        note = ("Most people connect a demo account first — real market data, "
                "no money at risk — and connect a live one when they've seen "
                "it work.")
    send_to(chat_id,
            _ob_head(chat_id, "connect") +
            "<b>Connect your broker account.</b>\n\n"
            "The bot never holds your money — it places orders on your own "
            "cTrader account, which stays yours and which you can disconnect "
            "at any time with /reset.\n\n"
            f"<i>{note}</i>\n\n"
            "<i>Whether that account is demo or real money is something I read "
            "from the account itself once it's connected — you don't have to "
            "tell me, and I won't take your word for it.</i>",
            _kb([[("🔗 Connect my account", "go:connect")]]))


# ── Step 2: Your Account ──
#
# Not a choice. The environment is already decided by what was authorised in
# step 1; this step exists so the client SEES what was detected and confirms
# it is the account they meant, before anything is configured around it.

def _ob_step_account(chat_id):
    from apex import ui_state
    st = _ui(chat_id, refresh=True, force=True)
    u = st.user or {}
    if st.env == ui_state.LIVE:
        body = ("This is a <b>real-money</b> account. Nothing will trade on it "
                "until you finish setup and activate it deliberately — and "
                "activation asks for a code you type back.")
    elif st.env == ui_state.DEMO:
        body = ("This is a <b>demo</b> account. Real prices, simulated money: "
                "nothing here can cost you anything.")
    else:
        body = ("We could not confirm with your broker whether this account is "
                "demo or real money. Setup can continue, but no real-money "
                "order will be placed while that is unresolved.")
    send_to(chat_id,
            _ob_head(chat_id, "account") +
            f"<b>{st.env_badge}</b>\n"
            f"Account: <code>{_esc(str(u.get('ctrader_account_id') or '—'))}</code>\n\n"
            f"{body}\n\n"
            "<i>If this is the wrong account, switch it now rather than after "
            "everything is configured around it.</i>",
            _kb([[("✅ Yes — use this account", "ob:acct:ok")],
                 [("🔄 Use a different account", "acct:switch")],
                 [("🔁 Re-check with my broker", "ob:acct:recheck")]]))


# ── Step 3: Trading Style ──

def _ob_style_options():
    """The Strategy Builder's own style step, reused verbatim.

    These four patches are what the builder already applies, so onboarding and
    /builder cannot recommend different timeframes for the same word. Adding a
    second table here is how "Scalping" ends up meaning 1m in one place and 5m
    in another.
    """
    return builder._style_step()["options"]


def _ob_step_style(chat_id):
    opts = _ob_style_options()
    rows = [[(o["label"], f"ob:style:{i}")] for i, o in enumerate(opts)]
    rows.append([("🛠 Custom — set it up myself", "ob:style:c")])
    body = "\n".join(
        f"<b>{o['label']}</b> — stop {o['patch'].get('sl_pips', 'ATR')}"
        + (f" / target {o['patch']['tp_pips']}" if o["patch"].get("tp_pips") else "")
        + (" pips" if o["patch"].get("sl_pips") else " (volatility-scaled)")
        for o in opts)
    send_to(chat_id,
            _ob_head(chat_id, "style") +
            "<b>How fast should it trade?</b>\n\n" + body + "\n\n"
            "<i>This sets the timeframe it reads and how wide its stops are. "
            "Faster means more trades and smaller moves; slower means fewer "
            "trades and wider swings. Neither is safer by itself — the risk "
            "per trade is step 5, and that is the one that decides what a "
            "loss costs.</i>",
            _kb(rows))


# ── Step 4: Trading Method ──

def _ob_step_instrument(chat_id):
    """What to trade. Part of the Method step — a method has to be applied to
    something, and splitting them would make the counter lie again."""
    syms = _OB_SYMS
    try:
        u = user_store.load(chat_id)
        token, ctid = u.get("ctrader_access_token"), u.get("ctrader_account_id")
        if token and ctid:
            from apex.brokers import ctrader as _ct
            offered = _ct.available_symbol_names(token, ctid, u.get("ctrader_env", "demo"))
            filtered = [(label, code) for label, code in _OB_SYMS if code in offered]
            # Only narrow the list if the broker actually offers a useful
            # subset — an empty/near-empty result usually means the lookup
            # itself is unreliable (e.g. thin demo symbol set), not that
            # nothing is tradeable, so fall back to the full list instead
            # of showing the client almost no options.
            if len(filtered) >= 3:
                syms = filtered
    except Exception as e:
        print(f"[TELEGRAM] onboard symbol filter failed, using full list: {e}")
    rows = [[{"text": "🤖 Auto-Pilot — let the bot pick everything (recommended)", "callback_data": "ob:sym:__auto__"}]]
    row = []
    for label, code in syms:
        row.append({"text": label, "callback_data": f"ob:sym:{code}"})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    send_to(chat_id,
            _ob_head(chat_id, "method") +
            "<b>What should it trade?</b>\n\n"
            "🤖 <b>Auto-Pilot</b> — the bot scans a basket of liquid "
            "instruments and takes the strongest setup anywhere, one position "
            "at a time.\n\n"
            "Or pick a single instrument and it watches only that.",
            extra={"reply_markup": {"inline_keyboard": rows}})


_STRAT_EMOJI = {
    "auto": "🤖", "mean_reversion": "⭐", "trend": "📈", "breakout": "🚀",
    "fibonacci": "🌀", "fvg": "🕳️", "ifvg": "🔄", "supply_demand": "🏛️",
    "liquidity_sweep": "🎯", "evc": "⚖️",
}


def _ob_step_strategy(chat_id):
    from apex.ai import STRATEGY_MODES
    kb = [[{"text": f"{_STRAT_EMOJI.get(key, '▫️')} {m['label']}" + (" (recommended)" if key == "auto" else ""),
            "callback_data": f"ob:strat:{key}"}]
          for key, m in STRATEGY_MODES.items()]
    body = "\n\n".join(f"<b>{m['label']}</b> — <i>{m['blurb']}</i>" for m in STRATEGY_MODES.values())
    send_to(chat_id,
            _ob_head(chat_id, "method") +
            f"<b>What should it look for?</b>\n\n{body}\n\n"
            "<i>Not sure? Take Automatic — it picks the method that suits "
            "current conditions, and /strategy can change it at any time.</i>",
            extra={"reply_markup": {"inline_keyboard": kb}})


# ── Step 5: Risk ──
#
# First-run shows three tiers and nothing else. The full ladder goes to 35%
# per trade, which is a real setting a client may deliberately want — but
# offering it on the screen where somebody is still learning what "risk per
# trade" means is not offering a choice, it is offering a mistake. The rest
# live behind Advanced Risk, which says what they do.

def _ob_step_risk(chat_id):
    lines = "\n\n".join(
        f"<b>{label}</b> — {pct:g}% per trade · {daily:g}% daily stop · "
        f"{dd:g}% max drawdown"
        for label, pct, daily, dd in _RISK_TIERS_CORE)
    kb = [[{"text": label, "callback_data": f"ob:risk:{pct}"}]
          for label, pct, _, _ in _RISK_TIERS_CORE]
    kb.append([{"text": "⚙️ Custom / advanced", "callback_data": "risk:adv"}])
    send_to(chat_id,
            _ob_head(chat_id, "risk") +
            "<b>How much may one trade lose?</b>\n\n" + lines + "\n\n"
            "<i>This is the share of your balance at stake if a trade hits its "
            "stop. It is the setting that decides what a bad run costs, so it "
            "is yours to choose — not a default you inherited. Change it any "
            "time with /risk.</i>",
            extra={"reply_markup": {"inline_keyboard": kb}})


# Take-profit choices offered during manual setup — each with what it actually
# means, so the client is the one deciding the trade-off, not guessing.
_OB_TP_OPTIONS = [
    ("tp20", "🎯 Conservative — 20 pips",
     "Closes quickly once price moves a little in your favor. Wins more often, but each win is smaller.",
     {"tp_pips": 20, "tp_target_pct": 0}),
    ("tp40", "📊 Balanced — 40 pips",
     "The default target. Waits for a moderate move before closing — a middle ground between how often "
     "you win and how much each win pays.",
     {"tp_pips": 40, "tp_target_pct": 0}),
    ("tp80", "🚀 Aggressive — 80 pips",
     "Waits for a bigger move before closing. Wins less often, but each win pays roughly double the "
     "Balanced option.",
     {"tp_pips": 80, "tp_target_pct": 0}),
    ("tp5pct", "📈 Scales with balance — 5%",
     "Recalculated every trade to target 5% of your CURRENT balance — grows automatically as your "
     "account grows, instead of sitting at a fixed pip count.",
     {"tp_target_pct": 5}),
]


def _ob_step_tp(chat_id):
    """Manual-symbol pickers also set their own take-profit, with what each
    option means spelled out — Auto-Pilot skips this too."""
    lines = "\n\n".join(f"<b>{label}</b> — <i>{blurb}</i>" for _, label, blurb, _ in _OB_TP_OPTIONS)
    kb = [[{"text": label, "callback_data": f"ob:tp:{key}"}] for key, label, _, _ in _OB_TP_OPTIONS]
    send_to(chat_id,
            f"🧭 <b>Take-profit target:</b>\n\n{lines}\n\n"
            "<i>This decides when the bot closes a winning trade. Change it any time with /tp or /tptarget.</i>",
            extra={"reply_markup": {"inline_keyboard": kb}})


def _ob_step_mode(chat_id):
    """The risk acknowledgment, kept on the path it has always been on.

    Reached from the take-profit sub-screen and from stale buttons in older
    chats. It ends at the configuration summary rather than starting the bot
    directly — nothing should begin trading from a screen whose last word was
    about take-profit.
    """
    u = user_store.load(chat_id)
    if not u.get("risk_accepted"):
        return send_to(chat_id, _RISK_TEXT,
                       extra={"reply_markup": {"inline_keyboard": [[
                           {"text": "✅ I understand — I accept the risk", "callback_data": "ob:risk"}]]}})
    return _ob_summary(chat_id)


# The five step renderers, by key. Defined after all of them exist.
_OB_RENDER = {
    "connect": lambda cid: _ob_step_connect(cid),
    "account": lambda cid: _ob_step_account(cid),
    "style":   lambda cid: _ob_step_style(cid),
    "method":  lambda cid: _ob_step_instrument(cid),
    "risk":    lambda cid: _ob_step_risk(cid),
}


def _ob_summary(chat_id):
    """Everything that was chosen, on one screen, before anything runs.

    The wizard used to start trading straight off the last question. That is
    the one moment a client can still catch a mis-tap for free, and it was
    spent on a congratulations message. Nothing here is computed for display —
    every line is read back out of the record the loop will actually use.
    """
    from apex import automation
    u = user_store.load(chat_id)
    strat = friendly_strategy(u.get("strategy") or "auto")[0]
    what = "🤖 Auto-Pilot — bot picks the instrument" if u.get("autopilot") \
        else f"<b>{_esc(u.get('symbol', '—'))}</b>"
    try:
        risk_pct = float(u.get("risk", cfg.RISK_PER_TRADE) or 0) * 100
    except (TypeError, ValueError):
        risk_pct = 0.0
    send_to(chat_id,
            "🧭 <b>Setup — your configuration</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Account: <b>{_ui(chat_id).env_badge}</b>\n"
            f"Trades: {what}\n"
            f"Style: <b>{str(u.get('style', '—')).title()}</b> · "
            f"{u.get('timeframe', '—')} charts\n"
            f"Method: <b>{_esc(strat)}</b>\n"
            f"Risk: <b>{risk_pct:g}%</b> per trade "
            f"({u.get('risk_tier', 'custom')})\n"
            f"Stop / target: <b>{u.get('sl_pips', cfg.STOP_LOSS_PIPS)}p / "
            f"{u.get('tp_pips', cfg.TAKE_PROFIT_PIPS)}p</b>\n"
            f"Daily loss stop: <b>{u.get('max_daily_loss_pct', '—')}%</b> · "
            f"Max drawdown: <b>{u.get('max_dd_pct', '—')}%</b>\n"
            f"Automation: <b>{automation.label(automation.mode(u))}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Check it over. Nothing is running yet — the bot starts when "
            "you tap Start, and every line above can be changed afterwards.</i>",
            _kb([[("▶️ Start trading", "ob:go")],
                 [("🎯 Change method", "nav:strat"), ("🛡 Change risk", "nav:risk")],
                 [("🤖 Automation", "nav:auto")]]))


def _finish_onboard(chat_id):
    """Start the bot, and say exactly what is now running."""
    from apex import automation
    u = user_store.load(chat_id)
    strat = friendly_strategy(u.get("strategy") or "mean_reversion")[0]
    user_store.update(chat_id, {"onboarded": True})
    user_loop.stop(chat_id)
    user_loop.start(chat_id, alert_fn=_user_alert)
    mode = automation.mode(u)
    doing = ("It reports every setup it finds and places nothing."
             if mode == "signals" else
             "It asks you before opening anything." if mode == "approval" else
             "It trades automatically when a valid setup appears.")
    send_to(chat_id,
            "✅ <b>Bot is ON</b>\n"
            f"{_state_line(chat_id)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Trading: <b>{_esc(u.get('symbol', 'EUR_USD')) if not u.get('autopilot') else 'Auto-Pilot'}</b>\n"
            f"Method: <b>{_esc(strat)}</b>\n"
            f"Risk: <b>{float(u.get('risk', 0.025)) * 100:g}%</b> per trade\n\n"
            f"{doing}\n"
            "<i>Everything is one tap away in</i> ☰ <i>Menu.</i>",
            _dashboard_keyboard(chat_id))


_builder_drafts = {}  # chat_id -> {"i": step_index, "d": draft-fields dict}


def _handle_builder(chat_id):
    """Entry: one-tap presets for THIS market + a custom step-by-step path.
    Framed as a setup assistant — the bot executes what the user picks."""
    ps = builder.presets()
    rows = [[{"text": p["label"], "callback_data": f"bld:preset:{k}"}] for k, p in ps.items()]
    rows.append([{"text": "🛠 Custom (step by step)", "callback_data": "bld:custom"}])
    desc = "\n".join(f"<b>{p['label']}</b> — <i>{p['desc']}</i>" for p in ps.values())
    return send_to(chat_id,
        "⚙️ <b>Strategy Builder</b>\n\n"
        "Compose how your bot trades. Pick a ready preset, or build it step by step. "
        "Every choice changes real behaviour — you stay in control.\n\n"
        f"{desc}",
        extra={"reply_markup": {"inline_keyboard": rows}})


def _apply_builder_patch(chat_id, patch):
    """Persist a composed strategy and restart the loop so it takes effect."""
    user_store.update(chat_id, patch)
    running = _restart_user_loop(chat_id)
    return running


def _builder_preset(chat_id, key):
    p = builder.presets().get(key)
    if not p:
        return send_to(chat_id, "That preset isn't available. Tap ⚙️ Build strategy again.")
    running = _apply_builder_patch(chat_id, p["patch"])
    send_to(chat_id, builder.summary(dict(user_store.load(chat_id))))
    return send_to(chat_id,
        f"✅ <b>{p['label']} applied.</b> The bot now trades with these settings."
        + ("" if running or user_loop.is_running(chat_id) else "\n⏸ <i>Bot is off — tap ▶️ to start.</i>"),
        _dashboard_keyboard(chat_id))


def _builder_render_step(chat_id):
    st = _builder_drafts.get(chat_id)
    steps = builder.steps()
    if not st or st["i"] >= len(steps):
        return _builder_show_summary(chat_id)
    step = steps[st["i"]]
    rows = [[{"text": o["label"], "callback_data": f"bld:pick:{st['i']}:{j}"}]
            for j, o in enumerate(step["options"])]
    rows.append([{"text": "✖️ Cancel", "callback_data": "bld:cancel"}])
    return send_to(chat_id,
        f"<b>{step['title']}</b>\n<i>{step['sub']}</i>",
        extra={"reply_markup": {"inline_keyboard": rows}})


def _builder_pick(chat_id, step_i, opt_i):
    st = _builder_drafts.get(chat_id)
    steps = builder.steps()
    if not st or step_i != st["i"] or st["i"] >= len(steps):
        return  # stale button press from an old message
    try:
        patch = steps[step_i]["options"][opt_i]["patch"]
    except (IndexError, KeyError):
        return
    st["d"].update(patch)
    st["i"] += 1
    return _builder_render_step(chat_id)


def _builder_show_summary(chat_id):
    st = _builder_drafts.get(chat_id)
    d = dict(st["d"]) if st else {}
    # crypto build has no news/session steps — keep the engine's default news guard off
    if builder._is_crypto():
        d.setdefault("news_filter", False)
    else:
        d.setdefault("news_filter", True)
    return send_to(chat_id, builder.summary(d),
        extra={"reply_markup": {"inline_keyboard": [
            [{"text": "✅ Activate this strategy", "callback_data": "bld:activate"}],
            [{"text": "🔁 Start over", "callback_data": "bld:custom"},
             {"text": "✖️ Cancel", "callback_data": "bld:cancel"}]]}})


def _builder_activate(chat_id):
    st = _builder_drafts.pop(chat_id, None)
    d = dict(st["d"]) if st else {}
    if builder._is_crypto():
        d.setdefault("news_filter", False)
    else:
        d.setdefault("news_filter", True)
    if not d:
        return send_to(chat_id, "Nothing to activate — tap ⚙️ Build strategy to start.")
    running = _apply_builder_patch(chat_id, d)
    return send_to(chat_id,
        "✅ <b>Strategy activated.</b> The bot now trades exactly this."
        + ("" if running or user_loop.is_running(chat_id) else "\n⏸ <i>Bot is off — tap ▶️ to start.</i>"),
        _dashboard_keyboard(chat_id))


def _handle_cb(chat_id, data):
    """The only entrance for a button press. Shape, then repeat, then route.

    Every inline keyboard this bot has ever sent is still in somebody's chat
    and is still pressable. So a press is treated as untrusted input twice
    over: `callback_guard.parse` rejects anything that is not a callback this
    bot issues before a handler reads it, and `callback_guard.once` collapses
    the double-tap that a slow network produces into one action with one
    answer.

    Neither is a financial control. `gates.authorize_order` and
    `gates.authorize_close` remain the only things that can permit an order,
    and the ledger claim inside them is what makes a duplicate impossible
    rather than merely unlikely. This layer stops the INTERFACE from lying
    about it.
    """
    from apex import callback_guard, screens
    parsed = callback_guard.parse(data)
    if not parsed:
        # Not a button this bot drew. Say nothing about why — the client who
        # sent it either has a very old chat open or is probing, and neither
        # is served by a description of the routing table.
        print(f"[Telegram] discarded an unroutable callback from {chat_id}: {data!r}")
        return send_to(chat_id, screens.stale_action(),
                       _kb([[("☰ Menu", "nav:menu")]]))
    if callback_guard.is_action(data) and not callback_guard.once(chat_id, data):
        print(f"[Telegram] ignored a repeated action from {chat_id}: {data}")
        return send_to(chat_id,
                       "✅ Already done — that was counted once.\n\n"
                       "<i>Tapping twice never does it twice.</i>",
                       _kb([[("☰ Menu", "nav:menu")]]))
    try:
        return _route_cb(chat_id, data)
    except Exception as e:
        # A handler that raises must not leave the client staring at a button
        # that did nothing, and must never show them a traceback.
        print(f"[Telegram] callback {data!r} failed for {chat_id}: {e}")
        return send_to(chat_id,
                       "⚠️ <b>That didn't go through</b>\n\n"
                       "Nothing was changed on your account. Open the screen "
                       "again — it will show you where things actually stand.",
                       _kb([[("🏠 Home", "nav:home")], [("☰ Menu", "nav:menu")]]))


def _route_cb(chat_id, data):
    """Inline-button presses (copilot approve/reject, risk acceptance, onboarding)."""
    try:
        from apex import control
        control.event("tg_in", f"btn:{data}"[:120], user_id=str(chat_id))
    except Exception:
        pass
    if data == "bld:open":
        return _handle_builder(chat_id)
    if data == "bld:custom":
        _builder_drafts[chat_id] = {"i": 0, "d": {}}
        return _builder_render_step(chat_id)
    if data == "bld:cancel":
        _builder_drafts.pop(chat_id, None)
        return send_to(chat_id, "✖️ Builder cancelled. Nothing changed.")
    if data == "bld:activate":
        return _builder_activate(chat_id)
    if data.startswith("bld:preset:"):
        return _builder_preset(chat_id, data.split(":", 2)[2])
    if data.startswith("bld:pick:"):
        _, _, rest = data.split(":", 2)
        try:
            step_i, opt_i = (int(x) for x in rest.split(":"))
        except ValueError:
            return
        return _builder_pick(chat_id, step_i, opt_i)
    # ── Daily "keep or change it" offer (the recap's keyboard). "Change" is
    # not handled here: those two buttons reuse the existing nav:strat picker
    # and bld:open builder, so there is exactly one place that edits a setup.
    if data == "strat:keep":
        _u = user_store.load(chat_id) or {}
        try:
            _name = friendly_strategy(_u.get("strategy") or "auto")[0]
        except Exception:
            _name = _u.get("strategy") or "your current strategy"
        return send_to(chat_id,
                       f"✅ Sticking with <b>{_name}</b> — nothing changed.\n"
                       f"<i>You can switch any time with /strategy.</i>")
    # ── Navigation. Screens only; nothing here moves money or settings. ──
    if data == "nav:menu":
        return _handle_menu(chat_id)
    if data == "nav:home":
        return _screen_home(chat_id)
    if data == "nav:over":
        return _handle_status(chat_id)
    if data == "nav:pos":
        return _screen_positions(chat_id)
    if data == "nav:strat":
        return _handle_strategy(chat_id, "")
    if data == "nav:risk":
        return _handle_risk(chat_id, "")
    if data == "nav:auto":
        return _screen_automation(chat_id)
    if data == "nav:perf":
        return _screen_performance(chat_id, "today")
    if data == "nav:mkt":
        return _handle_market(chat_id)
    if data == "nav:news":
        return _handle_news(chat_id)
    if data == "nav:set":
        return send_to(chat_id, _with_counts(_CONTROLS_TEXT), _back_kb(chat_id))
    if data == "nav:help":
        return _handle_quick_help(chat_id)
    if data == "nav:notif":
        return _screen_notifications(chat_id)
    if data == "nav:voice":
        return _handle_voice(chat_id)
    if data == "voice:new":
        return _handle_voice(chat_id, "new")
    if data == "voice:off":
        return _handle_voice(chat_id, "off")
    if data == "notif:toggle":
        return _toggle_notifications(chat_id)
    if data == "nav:acct":
        return _screen_account(chat_id)
    if data == "nav:emg":
        return _screen_emergency(chat_id)
    if data in ("nav:pause", "emg:pause"):
        return _handle_stop(chat_id)
    if data == "nav:resume":
        return _handle_start(chat_id)

    # ── Automation ──
    if data.startswith("am:go:"):
        return _apply_automation(chat_id, data[6:])
    if data.startswith("am:"):
        return _set_automation(chat_id, data[3:])

    # ── Performance ──
    if data in ("pf:today", "pf:week", "pf:month", "pf:all"):
        return _screen_performance(chat_id, data[3:])
    if data == "pf:strat":
        return _screen_perf_split(chat_id, "strategy")
    if data == "pf:sym":
        return _screen_perf_split(chat_id, "symbol")

    # ── Emergency. Close All is confirmed on its own screen, never in one tap. ──
    if data == "emg:closeall":
        return _screen_emergency_confirm(chat_id)
    if data == "emg:go":
        return _emergency_close_all(chat_id)
    if data == "emg:cancel":
        return send_to(chat_id, "↩️ Cancelled — your positions are untouched.",
                       _back_kb(chat_id, [[("📈 Positions", "nav:pos")]]))

    # ── Closing a position: two taps, and the second one carries a token. ──
    #
    # The token is what makes an old screen inert. Without it, a "Yes, close
    # it" button scrolled back to an hour later still closes whatever is open
    # NOW — which is not the position the client was looking at when they
    # decided.
    if data == "pos:detail":
        return _screen_position_detail(chat_id)
    if data == "pos:close":
        return _screen_close_confirm(chat_id)
    if data.startswith("pos:goclose:"):
        return _do_close(chat_id, data.split(":", 2)[2])

    # ── Live activation. Both of these lead INTO the existing gate. ──
    if data == "live:start":
        return _screen_live_activation(chat_id)
    if data == "live:go":
        return _handle_paper(chat_id, "off")

    if data == "go:connect":
        return _handle_ctrader(chat_id)
    if data == "go:controls":
        return send_to(chat_id, _with_counts(_CONTROLS_TEXT))
    if data == "go:status":
        return _handle_status(chat_id)
    if data == "go:risk":
        return _handle_risk(chat_id, "")
    if data == "go:strategy":
        return _handle_strategy(chat_id, "")
    if data == "go:help":
        return _handle_quick_help(chat_id)
    if data == "acct:switch":
        return _handle_switch(chat_id)
    if data in ("acct:refresh", "acct:recheck"):
        # "Ask my broker again" as a button, because the alternative was
        # telling a client to send a command to fix a screen.
        return _screen_account(chat_id, refresh=True)
    if data == "acct:new":
        # Disconnect the current cTrader link and start a fresh authorization
        # (e.g. moving from a demo login to a real-money broker account).
        user_store.update(chat_id, {"ctrader_access_token": "", "ctrader_refresh_token": "",
                                    "ctrader_account_id": "", "ctrader_accounts": []})
        send_to(chat_id, "🔌 Old account disconnected. Now connect the account you want to trade 👇")
        return _handle_ctrader(chat_id)
    if data.startswith("acct:use:"):
        ctid = data.split(":", 2)[2]
        # This button may be years old. Re-ask the broker before labelling the
        # account demo or live: a confirmation prompt that says "demo" from a
        # stale list is how somebody taps through onto real money.
        from apex import ui_state as _uis3
        u, _r, _w = _uis3.refresh(chat_id, force=True)
        if u is None:
            u = user_store.load(chat_id)
        acc = next((a for a in (u.get("ctrader_accounts") or [])
                    if str(a.get("ctid")) == ctid), None)
        if not acc:
            return send_to(chat_id,
                           "❌ <b>That account is no longer available</b>\n\n"
                           "Your broker did not list it just now. Nothing "
                           "changed.",
                           _kb([[("🔄 Switch account", "acct:switch")],
                                [("☰ Menu", "nav:menu")]]))
        if acc.get("live"):
            # Real money → require an explicit confirmation.
            return send_to(chat_id,
                f"🔴 <b>Switch to LIVE account {ctid}?</b>\n\n"
                "This account trades <b>REAL money</b>. The bot will place real orders on it. "
                "Make sure you've watched it work on demo first.\n\n"
                "<i>You accept full responsibility for live trading — results are yours.</i>",
                extra={"reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Yes, trade my real-money account", "callback_data": f"acct:go:{ctid}"}],
                    [{"text": "↩️ Cancel — stay on demo", "callback_data": "acct:cancel"}]]}})
        return _apply_account(chat_id, ctid)
    if data.startswith("acct:go:"):
        return _apply_account(chat_id, data.split(":", 2)[2])
    if data == "acct:cancel":
        return send_to(chat_id, "↩️ Staying on your current account. Test as long as you like.")
    if data == "bot:on":
        if access.is_admin(str(chat_id)) and _bot_control.get("set_paused"):
            _bot_control["set_paused"](False)
        try:
            user_store.update(chat_id, {"emergency_stop": False})
        except Exception as e:
            print(f"[Telegram] could not clear the emergency hold for {chat_id}: {e}")
        _auto_start_user(chat_id)
        return send_to(chat_id,
            "✅ <b>Bot is ON.</b>\nIt's watching the market now and will trade automatically "
            "when a valid setup appears — you'll get an alert on every move.",
            _dashboard_keyboard(chat_id))
    if data == "bot:off":
        user_loop.stop(chat_id)
        if access.is_admin(str(chat_id)) and _bot_control.get("set_paused"):
            _bot_control["set_paused"](True)
        return send_to(chat_id,
            "⏸ <b>Bot is OFF.</b>\nNo new trades will open. Any open position stays protected by its stop. "
            "Tap ▶️ to turn it back on.",
            _dashboard_keyboard(chat_id))
    # ── Onboarding. Every step ends by asking the wizard what comes next,
    # so the order lives in _OB_STEPS alone and cannot drift per-branch. ──
    if data == "ob:acct:ok":
        user_store.update(chat_id, {"account_confirmed": True})
        return _ob_render(chat_id)
    if data == "ob:acct:recheck":
        return _ob_step_account(chat_id)
    if data in ("ob:acct:demo", "ob:acct:live"):
        # Buttons from chats that predate this: the wizard used to ask the
        # client to pick demo or live before an account existed. The answer
        # was never evidence of anything, so it is not stored — the client is
        # told where the answer actually comes from and put back on the step
        # that reads it.
        send_to(chat_id,
                "ℹ️ <b>I read that from your account now.</b>\n\n"
                "Whether you're on demo or real money is decided by the "
                "account you connect, not by a setting — so I check with your "
                "broker instead of asking you.")
        return _ob_render(chat_id)
    if data.startswith("ob:style:"):
        key = data[9:]
        if key == "c":
            # Custom hands straight to the Strategy Builder rather than
            # growing a second builder inside onboarding.
            _builder_drafts[chat_id] = {"i": 0, "d": {}}
            return _builder_render_step(chat_id)
        try:
            opt = _ob_style_options()[int(key)]
        except (ValueError, IndexError):
            return
        user_store.update(chat_id, opt["patch"])
        send_to(chat_id, f"✅ Style: <b>{_esc(opt['label'])}</b>")
        return _ob_render(chat_id)
    if data == "ob:go":
        return _finish_onboard(chat_id)
    if data == "risk:adv":
        return _screen_risk_advanced(chat_id)

    if data == "ob:sym:__auto__":
        _handle_autopilot(chat_id, "on")
        return _ob_step_strategy(chat_id)
    if data.startswith("ob:sym:"):
        sym = data[7:]
        user_store.update(chat_id, {"symbol": sym, "autopilot": False})
        sugg = ("Suggested stops for gold: /sl 150 · /tp 300 (set after setup)" if sym.startswith("XAU")
                else "Suggested stops for indices: /sl 60 · /tp 120" if sym in ("US30", "NAS100")
                else "Suggested stops for crypto: /sl 200 · /tp 400" if sym.startswith(("BTC", "ETH"))
                else "")
        send_to(chat_id, f"✅ Trading symbol: <b>{sym}</b>" + (f"\n💡 <i>{sugg}</i>" if sugg else ""))
        return _ob_step_strategy(chat_id)
    if data.startswith("ob:strat:"):
        mode = data[9:]
        user_store.update(chat_id, {"strategy": mode})
        # Auto-Pilot no longer skips the risk step. It picks the instrument;
        # it does not get to pick what a losing trade costs the client. That
        # question belongs to the person whose money it is, and skipping it
        # meant the busiest configuration was the one nobody consented to.
        return _ob_render(chat_id)
    if data.startswith("ob:risk:"):
        try:
            pct = float(data[8:])
        except ValueError:
            return
        _apply_risk(chat_id, pct)
        return _ob_render(chat_id)
    if data.startswith("ob:tp:"):
        key = data[6:]
        opt = next((o for o in _OB_TP_OPTIONS if o[0] == key), None)
        if not opt:
            return
        _, label, blurb, patch = opt
        user_store.update(chat_id, patch)
        _restart_user_loop(chat_id)
        send_to(chat_id, f"🎯 Take-profit set to <b>{label}</b>.\n<i>{blurb}</i>")
        return _ob_step_mode(chat_id)
    if data.startswith("risk:set:"):
        try:
            pct = float(data[9:])
        except ValueError:
            return
        return _apply_risk(chat_id, pct)
    if data == "reset:yes":
        try:
            user_loop.stop(chat_id)
        except Exception:
            pass
        user_store.save(chat_id, {})
        return send_to(chat_id,
            "✅ <b>Reset complete.</b>\n\n"
            "Your cTrader connection and all bot settings have been cleared. "
            "Send /start whenever you're ready to connect an account and set up again.")
    if data == "reset:no":
        return send_to(chat_id, "Cancelled — nothing changed.")
    # Buttons from older chats. They still work, and they now land on the
    # configuration summary rather than starting the bot from a message the
    # client may have scrolled back to weeks later.
    # These two used to write `paper` straight onto the record. For
    # `ob:mode:real` that was a live-money activation with NONE of the gates
    # the real one applies: no recorded risk acceptance, no broker-verified
    # account environment, no single-use typed confirmation, no initial risk
    # cap, no audit entry. And the comment above is the reason it mattered —
    # these buttons survive in old chats, so a message from weeks ago could
    # still flip an account to real money by being tapped, or by its
    # callback_data being replayed.
    #
    # They now go through `_handle_paper`, which is the one authoritative
    # activation path. Nothing is lost: for a demo account it is still one
    # step, and for a live account it asks for exactly what activation has
    # always required.
    if data == "ob:mode:paper":
        return _handle_paper(chat_id, "on")
    if data == "ob:mode:real":
        return _handle_paper(chat_id, "off")
    if data == "ob:risk":
        from datetime import datetime as _dt
        user_store.update(chat_id, {"risk_accepted": _dt.utcnow().isoformat()})
        return _ob_summary(chat_id)
    if data == "risk:ok":
        from datetime import datetime as _dt
        user_store.update(chat_id, {"risk_accepted": _dt.utcnow().isoformat()})
        return _handle_paper(chat_id, "off")
    if data == "cp:y":
        # The suggestion is cleared BEFORE the order is attempted, so a second
        # Approve on the same alert finds nothing to approve. That is the
        # interface half of the duplicate problem; the half that actually
        # prevents two positions is the idempotency claim inside
        # gates.authorize_order, which refuses an identical order whatever
        # asked for it.
        sug = user_loop.pending_suggestion(str(chat_id))
        user_loop.clear_suggestion(str(chat_id))
        if not sug:
            from apex import screens
            return send_to(chat_id,
                           screens.stale_action("That trade opportunity")
                           + "\n\nI'll send a fresh one on the next setup.",
                           _kb([[("📈 Positions", "nav:pos")],
                                [("☰ Menu", "nav:menu")]]))
        send_to(chat_id, f"✅ Approved — opening {sug['side']} {sug['symbol']}…")
        res = user_loop.force_trade(str(chat_id), sug["side"], sug["symbol"])
        if _report_order_result(chat_id, res, sug["side"], sug["symbol"]):
            send_to(chat_id,
                    f"✅ <b>{sug['side']} {sug['symbol']}</b> @ {_fmt_px(res['price'])} | Units: {res['units']}\n"
                    f"SL: {_fmt_px(res['sl'])} | TP: {_fmt_px(res['tp'])}",
                    _kb([[("📈 Positions", "nav:pos")], [("☰ Menu", "nav:menu")]]))
        return
    elif data == "cp:n":
        user_loop.clear_suggestion(str(chat_id))
        send_to(chat_id, "❌ Skipped. I'll keep watching and suggest the next setup.",
                _kb([[("🤖 Automation", "nav:auto")], [("☰ Menu", "nav:menu")]]))
    elif data == "purgebad:yes":
        with _lock:
            target = _purge_pending.pop(str(chat_id), None)
        if not target:
            return send_to(chat_id, "⌛ That request expired — send /purgebad again.")
        trades = user_store.load_trades(target)
        good = [t for t in trades if abs(t.get("netPnl") or 0) <= _PURGE_THRESHOLD
                and abs(t.get("grossPnl") or 0) <= _PURGE_THRESHOLD]
        removed = len(trades) - len(good)
        key = f"{user_store._NS}:trades:{target}"
        if user_store._USE_REDIS:
            user_store._redis_set(key, json.dumps(good))
        else:
            with open(user_store._path(target) + ".trades", "w") as f:
                f.write(json.dumps(good))
        send_to(chat_id, f"✅ Removed {removed} corrupted record(s) — {len(good)} remain in the journal.")
    elif data == "purgebad:no":
        with _lock:
            _purge_pending.pop(str(chat_id), None)
        send_to(chat_id, "✖️ Cancelled — nothing changed.")
    elif data.startswith("tr:"):
        parts = data.split(":")
        if len(parts) == 3:
            _, side, sym = parts
            send_to(chat_id, f"📊 <b>{side} {sym}</b> — choose size ({forex.unit_label(sym)}):",
                    extra={"reply_markup": {"inline_keyboard": _trade_lots_kb(side, sym)}})
        elif len(parts) == 4:
            _, side, sym, lot_str = parts
            lots = None if lot_str == "auto" else float(lot_str)
            _exec_trade(chat_id, side, sym, lots)


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
    else:
        # An omission a client cannot see is indistinguishable from a calm
        # market. Say the read has not been taken rather than showing fewer
        # lines and letting them infer.
        lines.append("\n📊 <i>Trend, volatility and momentum have not been "
                     "computed yet — the bot writes them on its next scan.</i>")
    lines.append(f"\n💡 <i>{sess['note']}</i>")
    lines.append("<i>How the market is moving right now — read before you trade.</i>")
    send_to(chat_id, "\n".join(lines),
            _back_kb(chat_id, [[("📰 News", "nav:news"), ("📈 Positions", "nav:pos")]]))


def _handle_voice(chat_id, args=""):
    """The phone channel: issue, revoke, and explain the voice token.

    The token is shown exactly once. Only its hash is stored, so it cannot be
    read back later — a lost one is re-issued, and re-issuing invalidates the
    old one, which is also the answer to "I lost my phone".
    """
    from apex import voice_api
    arg = (args or "").strip().lower()
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

    if arg in ("off", "revoke", "stop"):
        gone = voice_api.revoke(chat_id)
        return send_to(chat_id,
            "🔇 Voice access <b>revoked</b>. The old key stops working "
            "immediately — your shortcut will need a new one."
            if gone else "🔇 There was no voice key to revoke.",
            _back_kb(chat_id))

    if arg in ("confirm on", "confirm off"):
        want = arg.endswith("on")
        user_store.update(chat_id, {"voice_confirm": want})
        return send_to(chat_id,
            ("🛡 Voice confirmation <b>ON</b> — I'll read a trade back to you "
             "and place it only after you say yes."
             if want else
             "⚡ Voice confirmation <b>OFF</b> — spoken trades go straight to "
             "the broker.\n<i>Dictation mishears 0.5 as 5 and \"close\" as "
             "\"closed\". With this off, a misheard word is a real order.</i>"),
            _back_kb(chat_id))

    if arg in ("new", "key", "on", "setup"):
        if not base:
            return send_to(chat_id,
                "⚠️ Voice isn't available — the service URL isn't configured "
                "(RENDER_EXTERNAL_URL). Ask the operator to set it.",
                _back_kb(chat_id))
        token = voice_api.mint(chat_id)
        send_to(chat_id,
            "🎙 <b>Your voice key — copy it now</b>\n"
            "<i>Shown once. Only a hash is kept, so it can't be shown again.</i>")
        send_to(chat_id, f"<code>{_esc(token)}</code>")

        # One tap, once the operator has published a signed Shortcut.
        #
        # Apple refuses to import an unsigned .shortcut file and only an Apple
        # device can sign one, so the first copy has to be built on an iPhone
        # and shared — which yields a permanent iCloud link that every client
        # afterwards installs with a single tap. Until that link exists the
        # same button explains the three steps, so nothing here has to change
        # later: setting VOICE_SHORTCUT_URL upgrades every client at once.
        ready = (getattr(cfg, "VOICE_SHORTCUT_URL", "") or "").strip()
        if ready:
            return send_to(chat_id,
                f"<a href=\"{_esc(ready)}\">📥 Install the Apex shortcut</a>\n"
                "<i>Tap it, then <b>Add Shortcut</b>, and paste the key above "
                "when it asks.</i>\n\n"
                "Then say <b>\"Siri, Apex\"</b> — it asks what you want to "
                "know, out loud, and reads the answer back. Ask about your "
                "balance or your position, or say <i>buy gbpusd</i> and it "
                "reads the trade back before placing it.\n\n"
                "🔊 <b>To hear alerts too:</b> Settings → Notifications → "
                "Announce Notifications → Telegram. With AirPods or CarPlay, "
                "Siri reads every trade and news alert aloud as it arrives.\n\n"
                "🔇 <code>/voice off</code> revokes the key.",
                _back_kb(chat_id))

        return send_to(chat_id,
            "<b>Build it — 3 steps, 2 minutes</b>\n\n"
            "Open <b>Shortcuts</b> → <b>+</b> for a <b>new, empty</b> one, "
            "then add these <b>in this order</b> (each lands at the bottom, so "
            "nothing needs moving):\n\n"
            "<b>1.</b> <code>Ask for Input</code>\n"
            "   • Prompt: <i>What do you want to know?</i>\n\n"
            "<b>2.</b> <code>Get Contents of URL</code>\n"
            f"   • URL: <code>{_esc(base)}/api/voice/say</code>\n"
            "   • tap <b>›</b> → Method: <b>POST</b> → Request Body: <b>JSON</b>\n"
            "   • Add field <b>Text</b>: <code>token</code> = the key above\n"
            "   • Add field <b>Text</b>: <code>text</code> = tap the value, then "
            "pick <b>Provided Input</b> above the keyboard\n\n"
            "<b>3.</b> <code>Speak Text</code> — leave it alone, it fills "
            "itself in\n\n"
            "Rename it <b>Apex</b>, then say <b>\"Siri, Apex\"</b>.\n\n"
            "🔊 <b>To hear alerts too:</b> Settings → Notifications → "
            "Announce Notifications → Telegram. With AirPods or CarPlay, Siri "
            "reads every trade and news alert aloud as it arrives.\n\n"
            "🔇 <code>/voice off</code> revokes the key.",
            _back_kb(chat_id))

    user = user_store.load(chat_id)
    on = voice_api.has_token(user)
    guard = voice_api.confirm_required(user)
    ready = bool((getattr(cfg, "VOICE_SHORTCUT_URL", "") or "").strip())
    btn = [[("🔁 New key", "voice:new"), ("🔇 Turn off", "voice:off")]] if on else \
          [[("🎙 Activate voice control", "voice:new")]]
    return send_to(chat_id,
        "🎙 <b>Voice control</b>\n"
        f"Key: <b>{'issued' if on else 'not set up'}</b>\n"
        f"Trade confirmation: <b>{'ON' if guard else 'OFF'}</b>\n\n"
        "Ask your bot anything from your phone through Siri Shortcuts — "
        "balance, open positions, why it skipped a setup — and place or close "
        "trades by voice.\n\n"
        "<code>/voice new</code> — issue a key and get the setup steps\n"
        "<code>/voice off</code> — revoke it\n"
        "<code>/voice confirm off</code> — stop asking before spoken trades\n\n"
        "<i>Siri itself can't be replaced — Apple doesn't allow it. This runs "
        "as a shortcut Siri launches by name.</i>",
        _back_kb(chat_id, btn))


def _handle_news(chat_id, args=""):
    """The calendar screen — and the switch for the messages it pushes.

    This used to list `news.upcoming()`, which is the trading guard's view:
    high impact only, still ahead of us. A normal week holds ~8 of those
    against ~90 other releases and plenty of days have none at all, so the
    screen answered "no high-impact events" almost every time it was opened
    and read as a broken feed. It now shows the same rolling, medium-included
    view as the Mini App.
    """
    from apex import news, news_alerts
    arg = (args or "").strip().lower()
    if arg in ("on", "off", "1", "0", "yes", "no", "true", "false"):
        want = arg in ("on", "1", "yes", "true")
        user_store.update(chat_id, {"news_alerts": want})
        return send_to(chat_id,
            ("🔔 News alerts <b>ON</b> — I'll message you before a high-impact "
             "release on a pair you trade, and again once it passes."
             if want else
             "🔕 News alerts <b>OFF</b> — no more calendar messages.") +
            "\n\n<i>This is only about the messages. Whether I stand aside "
            "around releases is the news guard, in Strategy Builder.</i>",
            _back_kb(chat_id, [[("📡 Market", "nav:mkt")]]))

    user = user_store.load(chat_id)
    pair = [c.upper() for c in (user.get("symbol", cfg.SYMBOL) or "").split("_")]
    events = news.feed()
    alerts_on = news_alerts.enabled_for(user)
    foot = ("\n\n<i>⭐ = affects your pair. 🔔 alerts are ON — /news off to "
            "stop them.</i>" if alerts_on else
            "\n\n<i>⭐ = affects your pair. 🔕 alerts are OFF — /news on to "
            "get a heads-up before high-impact releases.</i>")
    if not events:
        return send_to(chat_id,
            "📰 <b>Nothing on the calendar right now.</b>\n"
            "<i>No releases due in the next day and a half, or the feed is "
            "unreachable — either way trading proceeds, the guard fail-opens.</i>"
            + foot,
            _back_kb(chat_id, [[("📡 Market", "nav:mkt")]]))
    lines = []
    for e in events[:10]:
        flag = "⭐" if e["currency"] in pair else "•"
        am = abs(e["mins"])
        h, m = divmod(am, 60)
        when = (f"{h}h {m}m" if h else f"{m}m")
        when = f"{when} ago" if e["released"] else f"in {when}"
        tag = "🔴" if e["impact"] == "high" else "🟠"
        fig = ""
        if e.get("forecast"):
            fig = f" <i>(exp {_esc(str(e['forecast']))})</i>"
        lines.append(f"{flag} {tag} <b>{_esc(e['currency'])}</b> · "
                     f"{_esc(e['title'])} — {when}{fig}")
    send_to(chat_id, "📰 <b>Economic calendar</b>\n" + "\n".join(lines) + foot,
            _back_kb(chat_id, [[("📡 Market", "nav:mkt"), ("📈 Positions", "nav:pos")]]))


# ─── Positions ────────────────────────────────────────────

def _screen_positions(chat_id):
    """What is open right now, priced from what the loop actually recorded.

    Every figure here comes off the dashboard the trading loop writes. When a
    number is not there yet — the first tick after a restart has not landed —
    this says so. `PnL: +$0.00` on a position $22 down shipped once because a
    missing key read as a zero; a blank is honest and a zero is not.
    """
    user_loop.live_balance(chat_id)
    dash = user_loop.get_dash(chat_id) or {}
    op = dash.get("openPosition")
    oc = dash.get("openCount", 0)
    head = ("📈 <b>Positions</b>\n" + _state_line(chat_id, guard=True) + "\n"
            "━━━━━━━━━━━━━━━━━━━━\n")

    if not op and not oc:
        return send_to(chat_id, head +
                       "📭 <b>Nothing open.</b>\n\n"
                       "The bot opens a position only when a setup passes every "
                       "check. Most candidates are refused — that is the point, "
                       "and a refused trade costs nothing.",
                       _back_kb(chat_id, [[("📊 Overview", "nav:over"),
                                           ("🎯 Strategy", "nav:strat")]]))

    lines = []
    if op:
        side = "🟢 LONG" if op.get("side") == "BUY" else "🔴 SHORT"
        pnl, pips = op.get("pnlUsd"), op.get("pnlPips")
        if pnl is None:
            pnl_txt = "…" if pips is None else f"{pips:+.1f} pips"
        else:
            pnl_txt = f"{'+' if pnl >= 0 else '−'}${abs(pnl):.2f}"
            if pips is not None:
                pnl_txt += f"  ({pips:+.1f} pips)"
        sl = op.get("stopLoss")
        lines += [
            f"{side} <b>{_esc(op.get('symbol', '—'))}</b>",
            f"  Entry: <b>{_fmt_px(op.get('entryPrice'))}</b>"
            f"   Size: {op.get('units', '—')}",
            f"  Stop: <b>{_fmt_px(sl) if sl else '⚠️ none at the broker'}</b>"
            f"   Target: {_fmt_px(op.get('takeProfit')) if op.get('takeProfit') else '—'}",
            f"  P&amp;L: <b>{pnl_txt}</b>",
        ]
    if oc and oc > (1 if op else 0):
        extra = oc - (1 if op else 0)
        lines.append(f"\n📊 <b>+{extra} more open</b> on this account, each managed "
                     f"by its own stop at the broker. The bot tracks one at a "
                     f"time here — the terminal and cTrader show them all.")
    fl = dash.get("floatingPnl")
    if isinstance(fl, (int, float)):
        lines.append(f"\n💵 Floating P&amp;L: <b>{'+' if fl >= 0 else '−'}${abs(fl):.2f}</b>")

    send_to(chat_id, head + "\n".join(lines),
            _back_kb(chat_id, [[("🔍 Position details", "pos:detail")],
                               [("🔒 Close position", "pos:close")],
                               [("📊 Overview", "nav:over"),
                                ("🚨 Emergency", "nav:emg")]]))


def _screen_position_detail(chat_id):
    """One position, in full. Blank where the loop has not priced it yet."""
    from apex import screens
    st = _ui(chat_id)
    dash = user_loop.get_dash(chat_id) or {}
    op = dash.get("openPosition")
    if not op:
        return send_to(chat_id,
                       screens.unavailable(st, "Position detail",
                                           "Nothing is open on this account "
                                           "right now."),
                       _kb([[("📈 Positions", "nav:pos")],
                            [("☰ Menu", "nav:menu")]]))
    send_to(chat_id, screens.position_detail(st, op),
            _kb([[("🔒 Close position", "pos:close")],
                 [("← Back", "nav:pos"), ("☰ Menu", "nav:menu")]]))


def _screen_close_confirm(chat_id):
    """Step one of two. The token issued here is what makes step two specific
    to this decision rather than to whatever happens to be open later."""
    from apex import callback_guard, screens
    st = _ui(chat_id)
    dash = user_loop.get_dash(chat_id) or {}
    op = dash.get("openPosition")
    if not op:
        return send_to(chat_id,
                       "📭 <b>Nothing is open</b> — there is nothing to close.",
                       _kb([[("📈 Positions", "nav:pos")],
                            [("☰ Menu", "nav:menu")]]))
    token = callback_guard.issue(chat_id, "close")
    if not token:
        return send_to(chat_id,
                       screens.unavailable(st, "The close confirmation",
                                           "We could not set up a "
                                           "confirmation for this close."),
                       _kb([[("📈 Positions", "nav:pos")],
                            [("☰ Menu", "nav:menu")]]))
    send_to(chat_id, screens.close_confirm(st, op.get("symbol")),
            _kb(screens.close_confirm_rows(token)))


def _do_close(chat_id, token):
    """Step two. Refuses a token that is expired, wrong, or already redeemed."""
    from apex import callback_guard, screens
    if not callback_guard.consume(chat_id, "close", token):
        return send_to(chat_id,
                       screens.stale_action("That close confirmation"),
                       _kb([[("📈 Positions", "nav:pos")],
                            [("☰ Menu", "nav:menu")]]))
    return _handle_close(chat_id)


# ─── Automation ───────────────────────────────────────────
#
# The protection stack, spelled out. This is the list a client is entitled to
# see BEFORE handing over execution, and every line of it names a mechanism
# that is really in the loop — not a reassurance written for the screen.

def _protection_stack(chat_id):
    u = user_store.load(chat_id)
    try:
        risk_pct = float(u.get("risk", cfg.RISK_PER_TRADE) or 0) * 100
    except (TypeError, ValueError):
        risk_pct = 0.0
    return (
        "<b>What stands between a setup and your balance:</b>\n"
        f"• Every trade risks <b>{risk_pct:g}%</b> of the balance and no more — "
        "the size is computed from your stop, not guessed\n"
        "• A stop-loss is attached at the broker. If it cannot be attached, the "
        "position is closed immediately\n"
        f"• Daily loss stop at <b>{u.get('max_daily_loss_pct', '—')}%</b> and "
        f"drawdown stop at <b>{u.get('max_dd_pct', '—')}%</b> — both halt new "
        "trades on their own\n"
        "• Three losses in a row on an instrument stands the bot aside on it\n"
        "• High-impact news and violent candles suspend entries\n"
        "• Positions are flattened before the weekend gap\n\n"
        "<i>None of this makes a loss impossible. It caps how fast one can "
        "happen.</i>")


def _screen_automation(chat_id):
    """The three levels, and — where it applies — why the chosen one is held.

    Full Automation is a PREFERENCE. It has never been permission to trade and
    is not treated as one here: the level is shown exactly as the client set
    it, and when a live prerequisite is unestablished the screen says the level
    is on hold rather than rendering it as running. Both halves matter — hiding
    the setting would be its own lie, and drawing it as active while the gate
    refuses every order is the lie this screen existed to tell.
    """
    from apex import automation, screens
    st = _ui(chat_id)
    cur = st.automation
    body = "\n\n".join(
        f"{'✅ ' if m == cur else ''}<b>{automation.LABEL[m]}</b>\n"
        f"<i>{automation.BLURB[m]}</i>"
        for m in automation.MODES)
    rows = [[(automation.LABEL[m] + (" ✅" if m == cur else ""), f"am:{m}")]
            for m in automation.MODES]
    held = ""
    if cur == "full" and not st.live_orders_offered and st.is_live:
        held = ("\n\n⚠️ <b>Full Automation is set but on hold.</b>\n"
                + screens._blocked_note(st).lstrip("\n").replace(
                    "⚠️ <b>New real-money trades are switched off</b>",
                    "New real-money trades stay switched off"))
    send_to(chat_id,
            "🤖 <b>Automation</b>\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{body}{held}\n\n"
            "<i>You can change this at any time, including with a position "
            "open — it only decides what happens to the NEXT setup. Whatever "
            "you pick, every order still passes the same checks.</i>",
            _back_kb(chat_id, rows))


def _screen_notifications(chat_id):
    """What the bot will and will not message about — named, not numbered.

    The tiers come from `alert_policy`, which is the module the alert path
    actually consults. Listing them from a second hand-written table here is
    how a screen ends up promising a message the policy silently drops.
    """
    from apex import alert_policy
    u = user_store.load(chat_id) or {}
    on = bool(u.get("verbose_alerts"))
    send_to(chat_id,
            "🔔 <b>Notifications</b>\n"
            f"{_state_line(chat_id)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Always sent</b> — what happened to your money, and whether the "
            "bot is running:\n"
            "<i>positions opened and closed, a stop that moved past your entry, "
            "a position left without a stop, an exit that failed, the daily "
            "summary, the market opening and closing.</i>\n\n"
            "<b>Sent</b> — something changed you might want to act on:\n"
            "<i>a setup awaiting your approval, a signal on Signals Only, news "
            "and volatility standing the bot aside, a degraded broker feed.</i>\n\n"
            f"<b>Diagnostics</b> — how the bot is thinking: "
            f"<b>{'shown' if on else 'hidden'}</b>\n"
            "<i>every trailing-stop move, skipped setups, refused-setup "
            "tracking, market pulses, heartbeats.</i>\n\n"
            "<i>Nothing you turn off here can hide a trade. The first group is "
            "not optional, at any setting.</i>",
            _back_kb(chat_id, [
                [("🙈 Hide diagnostics" if on else "🔍 Show diagnostics",
                  "notif:toggle")],
                [("🤖 Automation", "nav:auto")]]))


def _toggle_notifications(chat_id):
    u = user_store.load(chat_id) or {}
    user_store.update(chat_id, {"verbose_alerts": not bool(u.get("verbose_alerts"))})
    return _screen_notifications(chat_id)


def _set_automation(chat_id, m):
    """Apply a level. Full Automation shows the protection stack first."""
    from apex import automation
    if m not in automation.MODES:
        return
    if m == "full" and automation.mode(user_store.load(chat_id)) != "full":
        # Handing over execution is the one change worth a second screen. Not
        # a scare — a statement of what is actually protecting the account,
        # so the decision is made with the mechanisms in view.
        return send_to(chat_id,
                       "🚀 <b>Turn on Full Automation?</b>\n"
                       f"{_state_line(chat_id, guard=True)}\n"
                       "━━━━━━━━━━━━━━━━━━━━\n\n"
                       "The bot will open and manage trades without asking you "
                       "first.\n\n" + _protection_stack(chat_id),
                       _back_kb(chat_id, [
                           [("✅ Yes — full automation", "am:go:full")],
                           [("↩️ Keep asking me first", "nav:auto")]]))
    return _apply_automation(chat_id, m)


def _apply_automation(chat_id, m):
    from apex import automation
    user_store.update(chat_id, automation.patch(m))
    running = _restart_user_loop(chat_id)
    tail = ("" if running or user_loop.is_running(chat_id)
            else "\n\n⏸ <i>The bot is off — tap ▶️ to start it.</i>")
    send_to(chat_id,
            f"✅ Automation set to <b>{automation.LABEL[m]}</b>.\n"
            f"<i>{automation.BLURB[m]}</i>{tail}",
            _back_kb(chat_id, [[("🤖 Automation", "nav:auto"),
                                ("📊 Overview", "nav:over")]]))


def _handle_automation(chat_id, args):
    """/automation [signals|approval|full] — the command behind the screen."""
    from apex import automation
    arg = (args or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias = {"signals": "signals", "signal": "signals", "signals_only": "signals",
             "alerts": "signals", "off": "signals",
             "approval": "approval", "approve": "approval", "copilot": "approval",
             "approval_required": "approval", "ask": "approval",
             "full": "full", "auto": "full", "autopilot": "full",
             "full_automation": "full", "on": "full"}
    want = alias.get(arg)
    if not want:
        return _screen_automation(chat_id)
    return _set_automation(chat_id, want)


def _handle_copilot(chat_id, args):
    """The original two-way toggle, kept working exactly as documented.

    `/copilot on` has meant "ask me before every trade" for the whole life of
    this bot and people have it in their muscle memory. It now writes through
    the same three-way setting so the two can never disagree, and on/off keep
    their old meanings.

    With one carve-out. `off` is a two-way word and there are now three levels,
    so it cannot mean "full automation" unconditionally: on an account set to
    Signals Only, a command whose entire text is "off" would start placing real
    orders. It means "stop asking me" — and on an account that was never going
    to trade, there is nothing to stop asking about.
    """
    from apex import automation
    arg = (args or "").strip().lower()
    cur = automation.mode(user_store.load(chat_id))
    if arg in ("on", "1", "yes", "true"):
        return _apply_automation(chat_id, "approval")
    if arg in ("off", "0", "no", "false"):
        if cur == "signals":
            return send_to(chat_id,
                "📣 You're on <b>Signals Only</b> — I already don't ask, "
                "because I don't trade. Nothing changed.\n\n"
                "<i>If you meant \"start trading for me\", that is Full "
                "Automation — pick it below so the change is deliberate.</i>",
                _back_kb(chat_id, [[("🤖 Automation", "nav:auto")]]))
        return _apply_automation(chat_id, "full")
    return send_to(chat_id,
        f"🤖 Automation is <b>{automation.LABEL[cur]}</b> — "
        f"<i>{automation.BLURB[cur]}</i>\n\n"
        "<code>/copilot on</code> — ask me before every trade\n"
        "<code>/copilot off</code> — full automation\n"
        "<code>/automation signals</code> — tell me, place nothing",
        _back_kb(chat_id, [[("🤖 Automation", "nav:auto")]]))


# Turning paper OFF on a LIVE account starts sending real-money orders. The
# only thing standing in front of that was a risk acceptance clicked once,
# possibly months earlier — so a single mistyped command, or a Telegram
# session in the wrong hands, was enough. Activation now needs a fresh,
# short-lived token the user has to type back, after seeing the account and
# the risk settings it will trade with.
_LIVE_CONFIRM_TTL_S = 300


def consume_live_confirm(chat_id, token) -> bool:
    """Burn a live-activation token exactly once, atomically.

    The check was read-then-write: read the stored token, compare, then clear
    it. Two confirmations arriving together both read the same valid token,
    both compare equal, and both activate — and the second one activates an
    account whose risk cap the first had already applied.

    SET NX on the token itself decides it in one step, in the shared store, so
    two processes cannot both win. An unreachable store means we cannot prove
    this token is unused, and an unprovable confirmation must not switch an
    account to real money — so that is a refusal, not a fallback.
    """
    key = f"liveconfirm:{chat_id}:{token}"
    got = user_store.claim(key, ttl_s=_LIVE_CONFIRM_TTL_S * 2)
    if got is True:
        return True
    if got is False:
        print(f"[LIVE] confirmation token for {chat_id} was already used")
        return False
    if getattr(user_store, "_USE_REDIS", False):
        print(f"[LIVE] ⛔ cannot verify the confirmation token for {chat_id} — "
              f"refusing to activate live trading on an unprovable confirmation")
        return False
    return True          # declared single-process development only

# And it lands with a hard ceiling on risk-per-trade regardless of what the
# account was configured with while it was only ever simulating.
_LIVE_INITIAL_RISK_CAP = float(os.getenv("LIVE_INITIAL_RISK_CAP") or 0.01)


def _live_activation_summary(chat_id, u, token):
    bal = (user_loop.get_dash(chat_id) or {}).get("balance")
    risk = float(u.get("risk", cfg.RISK_PER_TRADE) or 0)
    capped = min(risk, _LIVE_INITIAL_RISK_CAP)
    return (
        "🔴 <b>REAL MONEY ACTIVATION</b>\n\n"
        "You are about to let the bot place orders with real funds.\n\n"
        f"<b>Account:</b> <code>{u.get('ctrader_account_id', '—')}</code> (LIVE)\n"
        f"<b>Balance:</b> {('$%.2f' % bal) if isinstance(bal, (int, float)) else '—'}\n"
        f"<b>Risk / trade:</b> {capped:.2%}"
        + (f"  <i>(capped down from {risk:.2%} for activation)</i>" if capped < risk else "")
        + f"\n<b>Stop / target:</b> {u.get('sl_pips', cfg.STOP_LOSS_PIPS)}p / "
        f"{u.get('tp_pips', cfg.TAKE_PROFIT_PIPS)}p\n"
        f"<b>Max trades/day:</b> {u.get('max_trades_day', '—')}\n"
        f"<b>Max daily loss:</b> {u.get('max_daily_loss_pct', '—')}%\n"
        f"<b>Max drawdown:</b> {u.get('max_dd_pct', '—')}%\n\n"
        "Losses are real and are yours. To confirm, send exactly:\n"
        f"<code>/paper off {token}</code>\n\n"
        f"<i>This code expires in {_LIVE_CONFIRM_TTL_S // 60} minutes. "
        "Ignore this message to stay in simulation.</i>")


def _handle_paper(chat_id, args):
    parts = (args or "").strip().split()
    on = (parts[0].lower() if parts else "") in ("on", "true", "yes", "1")
    supplied_token = parts[1].strip().upper() if len(parts) > 1 else ""
    # Real-order mode is gated behind an explicit, recorded risk acceptance —
    # the client owns the strategy, the settings and every loss.
    if not on:
        u0 = user_store.load(chat_id)
        if not u0.get("risk_accepted"):
            return send_to(chat_id, _RISK_TEXT,
                extra={"reply_markup": {"inline_keyboard": [[
                    {"text": "✅ I understand — I accept the risk", "callback_data": "risk:ok"}]]}})

        # Second gate, only where real money is at stake. A demo account keeps
        # the old one-step behaviour — friction there protects nothing.
        #
        # WHICH account this is comes from `ui_state`, which asks the broker
        # rather than reading `ctrader_env`. That flag is writable by /env; the
        # connected account is not, and this is the branch where getting it
        # wrong means a client believes they are simulating.
        from apex import ui_state as _uis
        _u_ref, _, _ = _uis.refresh(chat_id, user=u0)
        _env, _proven, _ = _uis.environment(_u_ref if _u_ref is not None else u0)
        if _env == _uis.LIVE:
            import secrets
            pending = u0.get("live_confirm") or {}
            fresh = (pending.get("token")
                     and time.time() - float(pending.get("ts") or 0) < _LIVE_CONFIRM_TTL_S)
            if not (fresh and supplied_token
                    and secrets.compare_digest(supplied_token, str(pending["token"]))
                    and consume_live_confirm(chat_id, str(pending["token"]))):
                token = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                                for _ in range(6))
                user_store.update(chat_id, {"live_confirm": {"token": token,
                                                             "ts": time.time()}})
                return send_to(chat_id, _live_activation_summary(chat_id, u0, token))

            # Confirmed. Burn the token so it cannot be replayed, and cap risk.
            capped = min(float(u0.get("risk", cfg.RISK_PER_TRADE) or 0),
                         _LIVE_INITIAL_RISK_CAP)
            user_store.update(chat_id, {"live_confirm": None, "risk": capped})
            try:
                from apex import control
                control._audit({"ts": int(time.time()), "actor": str(chat_id),
                                "action": "live_trading_activated",
                                "account": str(u0.get("ctrader_account_id", "")),
                                "risk_per_trade": capped})
            except Exception as e:
                print(f"[Telegram] live activation audit failed: {e}")
            print(f"[Telegram] LIVE trading activated by {chat_id} "
                  f"on account {u0.get('ctrader_account_id')} at risk {capped}")
    # Per-user first — the client's loop reads the user record, not the global cfg.
    user_store.update(chat_id, {"paper": on})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"PAPER_TRADING": str(on).lower()})
        _apply("PAPER_TRADING", on)
    if on:
        return send_to(chat_id, "📝 Paper trading <b>ON</b> — simulated balance, zero risk.")
    from apex import ui_state as _uis2
    _st = _ui(chat_id)
    where = ("your <b>DEMO</b> account 🧪" if _st.env == _uis2.DEMO
             else "your <b>LIVE</b> account 🔴" if _st.env == _uis2.LIVE
             else "the account you connected — <b>which we could not confirm "
                  "just now</b> 🟠")
    send_to(chat_id, f"🔴 Paper trading <b>OFF</b> — orders now execute in {where}.\n"
                     f"{_st.env_badge}\n"
                     "Send /start if the bot isn't running.")


# Risk tiers for the /risk button menu — each bundles the daily-loss/drawdown
# safety stops with the risk %, so a high-risk pick doesn't get strangled by a
# low default guard (one loss at 20% risk would blow past a 4% daily cap and
# halt the bot). The real ceiling on position size is still cTrader's own
# margin/leverage (see forex.calc_units' margin_cap) — these tiers just decide
# how much of that headroom the bot is allowed to use per trade.
_RISK_TIERS = [
    ("🟢 Conservative", 0.5, 3, 15),
    ("🟡 Balanced", 1, 4, 20),
    ("🟠 Aggressive", 2, 6, 25),
    ("🔴 High", 5, 12, 35),
    ("🟣 Very High", 10, 20, 50),
    ("⚫ Extreme", 20, 35, 70),
    ("🔥 Adrenaline (max)", 35, 50, 90),
]
_RISK_MIN, _RISK_MAX = 0.5, 50.0

# The ladder is split for display only — _RISK_TIERS above stays the single
# source for _guards_for_risk_pct, so the daily-loss and drawdown caps that go
# with any given percentage are unchanged.
#
# Everything past Aggressive is a real setting somebody may deliberately want,
# and none of it is hidden: /risk N still reaches all of it, and the Advanced
# screen lists it in full. What it is not is an option on the screen where a
# beginner is still working out what "risk per trade" means. At 35% per trade
# three losses in a row take roughly three quarters of the account, and a
# first-run menu that puts that one tap from Conservative is not presenting a
# choice — it is presenting a mistake.
_RISK_TIERS_CORE = _RISK_TIERS[:3]        # Conservative · Balanced · Aggressive
_RISK_TIERS_ADVANCED = _RISK_TIERS[3:]    # High · Very High · Extreme · Adrenaline


def _risk_tier_name(pct):
    """The tier label a percentage falls in — for reading a setting back."""
    for label, tier_pct, _, _ in _RISK_TIERS:
        if pct <= tier_pct:
            return label
    return _RISK_TIERS[-1][0]


def _guards_for_risk_pct(pct):
    """Daily-loss/drawdown caps that go with a given risk %, from the tier table."""
    for _, tier_pct, daily, dd in _RISK_TIERS:
        if pct <= tier_pct:
            return daily, dd
    return _RISK_TIERS[-1][2], _RISK_TIERS[-1][3]


def _apply_risk(chat_id, pct):
    frac = pct / 100
    daily, dd = _guards_for_risk_pct(pct)
    user_store.update(chat_id, {"risk": frac, "max_daily_loss_pct": daily,
                                "max_dd_pct": dd,
                                # Records that this was CHOSEN, not inherited.
                                # The wizard needs to know the difference: a
                                # default is not an answer to step 5.
                                "risk_tier": _risk_tier_name(pct)})
    _restart_user_loop(chat_id)
    if access.is_admin(str(chat_id)):
        _save_runtime({"RISK_PER_TRADE": frac})
        _apply("RISK_PER_TRADE", frac)
    send_to(chat_id, f"⚖️ Risk per trade set to <b>{pct:g}%</b> of balance.\n"
            f"<i>Daily loss stop scaled to {daily:g}% · max drawdown to {dd:g}% to match.</i>")


def _risk_rows(tiers, current):
    return [[{"text": label + (" ✅" if abs(current - pct) < 0.001 else ""),
              "callback_data": f"risk:set:{pct}"}]
            for label, pct, _, _ in tiers]


def _risk_lines(tiers):
    return "\n".join(f"<b>{label}</b> — {pct:g}% risk · {daily:g}% daily stop · "
                     f"{dd:g}% max drawdown"
                     for label, pct, daily, dd in tiers)


def _risk_menu(chat_id):
    user = user_store.load(chat_id)
    current = float(user.get("risk", 0.025)) * 100
    tiers = list(_RISK_TIERS_CORE)
    # A client already ON an advanced tier must see it, ticked. Showing three
    # options none of which is the live setting reads as "your setting is
    # gone" and invites a tap that quietly halves the account's risk.
    if current > _RISK_TIERS_CORE[-1][1]:
        tiers += [t for t in _RISK_TIERS_ADVANCED
                  if abs(current - t[1]) < 0.001] or [
            (f"⚙️ Current — {current:g}%", current,
             *_guards_for_risk_pct(current))]
    kb = _risk_rows(tiers, current)
    kb.append([{"text": "⚙️ Advanced risk (higher tiers)", "callback_data": "risk:adv"}])
    send_to(chat_id,
            f"🛡 <b>Risk per trade</b> (current: <b>{current:g}%</b>)\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{_risk_lines(tiers)}\n\n"
            "<i>This is what one losing trade costs you. The daily-loss and "
            "drawdown stops move with it, so a bigger appetite does not get "
            "strangled by a cap set for a smaller one. Position size is still "
            "capped by your broker's margin on top of this.</i>",
            extra={"reply_markup": {"inline_keyboard": kb}})


def _screen_risk_advanced(chat_id):
    """The high tiers, with the arithmetic that makes them what they are.

    Not a warning banner — the actual numbers. "Extreme" means nothing; "three
    losses in a row costs 49% of the account" is a fact somebody can decide
    against.
    """
    user = user_store.load(chat_id)
    current = float(user.get("risk", 0.025)) * 100
    rows = []
    for label, pct, daily, dd in _RISK_TIERS_ADVANCED:
        after3 = (1 - pct / 100) ** 3
        rows.append(f"<b>{label}</b> — {pct:g}% per trade\n"
                    f"   Three losses in a row: <b>−{(1 - after3) * 100:.0f}%</b> "
                    f"of the account\n"
                    f"   Daily stop {daily:g}% · max drawdown {dd:g}%")
    kb = _risk_rows(_RISK_TIERS_ADVANCED, current)
    send_to(chat_id,
            "⚠️ <b>Advanced risk</b>\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n\n".join(rows) +
            "\n\n<i>These are real settings and they are yours to pick. They "
            "are here rather than on the first screen because the difference "
            "between 2% and 20% is not a matter of taste — it is the "
            "difference between a bad week and a closed account.</i>\n\n"
            "<i>Or send</i> <code>/risk 7.5</code> <i>for any exact value "
            f"between {_RISK_MIN:g}% and {_RISK_MAX:g}%.</i>",
            {"reply_markup": {"inline_keyboard": kb + [
                [{"text": "🛡 Back to the standard tiers", "callback_data": "nav:risk"}],
                [{"text": "☰ Menu", "callback_data": "nav:menu"}]]}})


def _handle_risk(chat_id, args):
    args = (args or "").strip()
    if not args:
        return _risk_menu(chat_id)
    try:
        pct = float(args)
        if not (_RISK_MIN <= pct <= _RISK_MAX):
            raise ValueError
    except ValueError:
        return send_to(chat_id, f"❌ Usage: <code>/risk 2</code>  ({_RISK_MIN:g}–{_RISK_MAX:g}%) "
                        "— or send /risk alone to pick from presets.")
    _apply_risk(chat_id, pct)


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


def _handle_tptarget(chat_id, args):
    """Balance-relative TP: instead of a fixed pip count, target a % of the
    current balance as profit on a full win — recalculated fresh every trade
    off that trade's actual position size, so it grows with the account."""
    args = (args or "").strip().lower()
    user = user_store.load(chat_id)
    current = float(user.get("tp_target_pct", 0) or 0)
    if not args:
        if current > 0:
            return send_to(chat_id,
                f"🎯 <b>Balance-target TP</b> is <b>ON</b> — targeting <b>{current:g}%</b> of your balance "
                "per full winning trade. It widens or narrows automatically as your balance moves, "
                "instead of sitting at a fixed pip count.\n\n"
                "Send <code>/tptarget 8</code> to change it, or <code>/tptarget off</code> to go back to a fixed /tp.")
        return send_to(chat_id,
            "🎯 <b>Balance-target TP</b> is currently <b>off</b> — using your fixed /tp pip count.\n\n"
            "Send <code>/tptarget 5</code> to make TP scale with your account instead (5% of balance per "
            "full win, recalculated every trade) — up to 25%.")
    if args in ("off", "0", "no"):
        user_store.update(chat_id, {"tp_target_pct": 0})
        _restart_user_loop(chat_id)
        return send_to(chat_id, "✅ Balance-target TP turned <b>off</b> — back to your fixed /tp pip count.")
    try:
        pct = float(args)
        if not (0.5 <= pct <= 25):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/tptarget 5</code>  (0.5–25% of balance), or <code>/tptarget off</code>.")
    user_store.update(chat_id, {"tp_target_pct": pct})
    _restart_user_loop(chat_id)
    send_to(chat_id,
        f"🎯 Balance-target TP set to <b>{pct:g}%</b> of your balance per full winning trade.\n"
        "<i>Recalculated fresh on every trade — grows with your account automatically. "
        "Still bounded 2×-20× your stop-loss distance so it stays realistic.</i>")


def _handle_symbol(chat_id, args):
    sym = (args or "").strip().upper().replace("/", "_").replace("-", "_").replace(" ", "")
    # Forex + metals only — this is a forex bot; reject crypto CFDs / indices.
    if not forex.is_tradeable(sym):
        return send_to(chat_id, "❌ This is a forex bot — pick a forex pair or a metal "
                                "(e.g. <code>/symbol EUR_USD</code> or <code>/symbol XAUUSD</code>). "
                                "Crypto and indices aren't supported here (crypto has its own bot).")
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
                + ". Watch the first few trades closely.</i>")
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
            units = _fx.round_units(max(_fx.calc_units(bal, risk, sl_pips, symbol, px),
                                        _fx.min_units(symbol)), symbol)
            pos = {"symbol": symbol, "side": sx["action"], "entryPrice": px,
                   "quantity": units, "stopLoss": sl, "takeProfit": tp,
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
    from apex import strategy_api
    strategy_api.load_builtins()
    # Selectable = whatever the registry holds. Sourcing this from
    # STRATEGY_MODES meant a registered strategy with no engine in ai.py was
    # invisible to clients — which is every strategy added after V1.
    _registered = {sid: sid for sid in strategy_api.available()}
    aliases = {"mean": "mean_reversion", "mr": "mean_reversion", "mean_reversion": "mean_reversion",
               "reversion": "mean_reversion", "trend": "trend", "trending": "trend",
               "breakout": "breakout", "turtle": "breakout",
               "auto": "auto", "adaptive": "auto", "ai": "auto",
               "fibonacci": "fibonacci", "fib": "fibonacci",
               "fvg": "fvg",
               "ifvg": "ifvg",
               "supply": "supply_demand", "demand": "supply_demand", "supply_demand": "supply_demand",
               "liquidity": "liquidity_sweep", "sweep": "liquidity_sweep", "liquidity_sweep": "liquidity_sweep",
               "evc": "evc",
               # blueprint §2 families added after V1
               "momentum": "momentum", "mom": "momentum",
               "session": "session_breakout", "session_breakout": "session_breakout",
               "london": "session_breakout", "asian": "session_breakout",
               "opening_range": "opening_range", "orb": "opening_range",
               "zscore": "zscore", "z": "zscore", "stat": "zscore",
               "vol_regime": "vol_regime", "volatility": "vol_regime",
               "squeeze": "vol_regime",
               "grid": "grid", "martingale": "martingale"}
    aliases.update(_registered)
    want = aliases.get((args or "").strip().lower().replace("-", "_"))
    user = user_store.load(chat_id)
    current = (user.get("strategy") or "auto").lower()
    def _meta(key):
        """Label + blurb for any registered strategy.

        STRATEGY_MODES only describes the ten with an engine in ai.py, and
        indexing it directly raised KeyError for every strategy added after
        that — including the one the client had just selected.
        """
        nice, _ = friendly_strategy(key)
        m = STRATEGY_MODES.get(key)
        if m:
            return nice, m.get("blurb", "")
        cls = strategy_api._REGISTRY.get(key)
        if cls:
            doc = (cls.__doc__ or "").strip().split("\n")[0]
            return nice, doc
        return nice, ""

    if not want:
        _SPECIAL = {"grid", "martingale"}
        ordinary, special = [], []
        for key in strategy_api.available():
            label, blurb = _meta(key)
            row = (f"{'✅ ' if key == current else ''}<b>{label}</b>\n"
                   f"<code>/strategy {key}</code> — <i>{blurb}</i>")
            (special if key in _SPECIAL else ordinary).append(row)
        body = "\n\n".join(ordinary)
        if special:
            body += ("\n\n⚠️ <b>High risk — add size to losing positions</b>\n"
                     "<i>Capped at 1.2x and halted after 3 consecutive losses, "
                     "but they can still lose faster than the others.</i>\n\n"
                     + "\n\n".join(special))
        cur_label, _ = _meta(current)
        return send_to(chat_id,
            f"🎯 <b>Trading method</b> (current: <b>{cur_label}</b>)\n\n{body}\n\n"
            "<i>Switching restarts your loop instantly — watch the first few trades closely.</i>")
    user_store.update(chat_id, {"strategy": want})
    running = _restart_user_loop(chat_id)
    label, blurb = _meta(want)
    warn = ("\n\n⚠️ <b>This strategy adds size after a loss.</b> It is capped at "
            "1.2x and stops after 3 losses in a row, but it is still the "
            "riskiest option here."
            if want in ("grid", "martingale") else "")
    tail = ("Applied immediately — check /status." if running
            else "⏸ The bot is currently <b>stopped</b> — send /start to begin trading with it.")
    send_to(chat_id, f"🎯 Method set to <b>{label}</b>.\n<i>{blurb}</i>{warn}\n\n{tail}")


# Curated liquid universe the Auto-Pilot scans — asset-class aware (FX majors +
# gold for the forex build, crypto-CFD majors for the crypto build). Configured
# in config.py (AUTOPILOT_UNIVERSE, env-overridable). Non-FX candidates are
# validated per account before use.
_AUTOPILOT_CANDIDATES = cfg.AUTOPILOT_UNIVERSE


def _handle_maxpos(chat_id, args):
    """Set how many positions the bot may hold at once (multi-position mode)."""
    arg = (args or "").strip()
    user = user_store.load(chat_id)
    if not arg:
        cur = int(user.get("maxpos", 1))
        risk = float(user.get("max_total_risk", 0.05)) * 100
        return send_to(chat_id,
            f"📊 <b>Max positions: {cur}</b> · total-risk cap {risk:g}%\n\n"
            "The bot can hold several trades at once and closes each on its own "
            "target/stop. Total risk stays capped no matter how many are open.\n\n"
            "<code>/maxpos 5</code> — allow up to 5 at once (1–8)\n"
            "<code>/maxpos 1</code> — one at a time (default)")
    try:
        n = int(arg)
        if not (1 <= n <= 8):
            raise ValueError
    except ValueError:
        return send_to(chat_id, "❌ Usage: <code>/maxpos 5</code> (a number 1–8)")
    user_store.update(chat_id, {"maxpos": n})
    running = _restart_user_loop(chat_id)
    per = 5.0 / n
    send_to(chat_id,
        f"📊 <b>Max positions set to {n}.</b>\n"
        + ("One trade at a time.\n" if n == 1 else
           f"Up to {n} trades at once — each risks ~{per:.1f}% so all {n} together "
           f"never risk more than 5% of the account. Correlated same-direction "
           f"trades are limited automatically.\n")
        + ("" if running or user_loop.is_running(chat_id) else "⏸ <i>Bot stopped — tap ▶️ to start.</i>"),
        _dashboard_keyboard(chat_id))


def _handle_autopilot(chat_id, args):
    """Full hands-off mode: the bot picks the instruments itself from a curated
    liquid universe (validated against the client's broker) and trades the
    strongest setup anywhere — one position at a time."""
    arg = (args or "").strip().lower()
    user = user_store.load(chat_id)
    if arg in ("off", "stop", "0", "false"):
        user_store.update(chat_id, {"autopilot": False})
        running = _restart_user_loop(chat_id)
        return send_to(chat_id,
            "🤖 <b>Auto-Pilot OFF.</b> Back to your chosen instrument (/symbol) or basket (/watch).",
            _dashboard_keyboard(chat_id))
    if arg not in ("on", "start", "1", "true", ""):
        return send_to(chat_id, "Usage: <code>/autopilot on</code> or <code>/autopilot off</code>")
    # Validate the candidate universe against what THIS broker actually offers.
    universe = []
    is_ct = bool(user.get("ctrader_access_token") and user.get("ctrader_account_id"))
    if is_ct:
        send_to(chat_id, "🤖 Setting up Auto-Pilot — checking which instruments your broker offers…")
        try:
            from apex import user_loop as _ul
            br, _ = _ul._make_broker(user)
            br._load_symbols()
            offered = set(br._sym_id.keys())
            universe = [c for c in _AUTOPILOT_CANDIDATES if c in offered]
        except Exception as e:
            return send_to(chat_id, f"⚠️ Couldn't read your broker's instruments: <i>{str(e)[:120]}</i>. Try again in a minute.")
    else:
        universe = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "XAU_USD"]
    if not universe:
        return send_to(chat_id, "⚠️ Couldn't build the Auto-Pilot list for your broker. Use /watch to pick instruments manually.")
    universe = universe[:8]
    user_store.update(chat_id, {"autopilot": True, "autopilot_universe": universe})
    running = _restart_user_loop(chat_id)
    send_to(chat_id,
        "🤖 <b>Auto-Pilot ON.</b>\n\n"
        f"I'll scan these every cycle and trade the strongest setup anywhere — one position at a time:\n"
        f"<b>{' · '.join(universe)}</b>\n\n"
        "You stay in control: /symbol or /watch to take over, /autopilot off to stop."
        + ("" if running or user_loop.is_running(chat_id) else "\n⏸ <i>Bot stopped — tap ▶️ to start.</i>"),
        _dashboard_keyboard(chat_id))


def _handle_watch(chat_id, args):
    """Basket scanner: watch up to 6 instruments — ANY the broker offers —
    and enter only the strongest setup per cycle, one position at a time."""
    raw = (args or "").strip()
    user = user_store.load(chat_id)
    if not raw:
        wl = user.get("watchlist") or []
        cur = " · ".join(wl) if wl else "— (single-symbol mode)"
        return send_to(chat_id,
            f"👁 <b>Watchlist:</b> {cur}\n\n"
            "Usage:\n"
            "<code>/watch XAUUSD EURUSD GBPUSD</code> — scan a basket (max 6, anything from /pairs)\n"
            "<code>/watch off</code> — back to single-symbol mode\n\n"
            "<i>The bot shops the whole basket every cycle and trades only the strongest "
            "setup — never more than one open position.</i>")
    if raw.lower() in ("off", "clear", "none"):
        user_store.update(chat_id, {"watchlist": []})
        running = _restart_user_loop(chat_id)
        return send_to(chat_id, "👁 Watchlist cleared — back to single-symbol mode (/symbol)."
                       + ("" if running or user_loop.is_running(chat_id) else "\n⏸ <i>Bot stopped — /start to run.</i>"))
    syms = [w.upper().replace("/", "_").replace("-", "_") for w in raw.split()][:6]
    # Forex + metals only — reject crypto CFDs / indices from the basket.
    non_fx = [s for s in syms if not forex.is_tradeable(s)]
    if non_fx:
        return send_to(chat_id, f"❌ This is a forex bot — not supported: <b>{', '.join(non_fx)}</b>. "
                                "Use forex pairs or metals (e.g. XAUUSD, EURUSD). Crypto has its own bot.")
    is_ct = bool(user.get("ctrader_access_token") and user.get("ctrader_account_id"))
    if is_ct:
        try:
            from apex import user_loop as _ul
            br, _ = _ul._make_broker(user)
            bad = []
            for sym in syms:
                try:
                    br._symbol_id(sym)
                except ValueError:
                    bad.append(sym)
            if bad:
                return send_to(chat_id, f"❌ Your broker doesn't offer: <b>{', '.join(bad)}</b>. "
                                        "Check /pairs and try again.")
        except Exception as e:
            return send_to(chat_id, f"⚠️ Couldn't verify the symbols right now: <i>{str(e)[:120]}</i>. Try again in a minute.")
    user_store.update(chat_id, {"watchlist": syms})
    running = _restart_user_loop(chat_id)
    send_to(chat_id,
            f"👁 <b>Watchlist set:</b> {' · '.join(syms)}\n\n"
            "Every cycle I scan all of them and take only the strongest setup — "
            "one open position at a time, risk rules unchanged."
            + ("" if running or user_loop.is_running(chat_id) else "\n⏸ <i>Bot stopped — send /start to begin.</i>"))


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


def send_photo(chat_id, png, caption="", filename="chart.png", content_type="image/png"):
    """Send an image to the chat (used for /chart, entry snapshots, and the
    static onboarding proof screenshots)."""
    try:
        requests.post(f"{_API}/sendPhoto",
                      data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                      files={"photo": (filename, png, content_type)}, timeout=25)
    except Exception as e:
        print(f"[TELEGRAM] send_photo failed: {e}")


def send_video(chat_id, mp4, caption="", filename="video.mp4", content_type="video/mp4"):
    """Send a video to the chat (used for the onboarding proof recording)."""
    try:
        requests.post(f"{_API}/sendVideo",
                      data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                      files={"video": (filename, mp4, content_type)}, timeout=60)
    except Exception as e:
        print(f"[TELEGRAM] send_video failed: {e}")


def send_media_group(chat_id, items):
    """Send photos/video together as one swipeable album instead of stacked
    separate messages. items: list of (bytes, filename, content_type,
    caption, kind) — kind is 'photo' or 'video'. Max 10 items (Telegram
    limit)."""
    media, files = [], {}
    for i, (data, filename, content_type, caption, kind) in enumerate(items):
        key = f"file{i}"
        entry = {"type": kind, "media": f"attach://{key}"}
        if caption:
            entry["caption"] = caption
            entry["parse_mode"] = "HTML"
        media.append(entry)
        files[key] = (filename, data, content_type)
    try:
        requests.post(f"{_API}/sendMediaGroup",
                      data={"chat_id": chat_id, "media": json.dumps(media)},
                      files=files, timeout=60)
    except Exception as e:
        print(f"[TELEGRAM] send_media_group failed: {e}")


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


def _handle_aiconfirm(chat_id, args):
    """Client choice: AI double-checks every entry (on) or pure rules (off)."""
    arg = (args or "").strip().lower()
    if arg in ("on", "1", "true", "yes"):
        user_store.update(chat_id, {"ai_confirm": True})
        _restart_user_loop(chat_id)
        return send_to(chat_id,
            "🧠 <b>AI confirmation ON.</b>\nEvery rule-based entry signal gets double-checked "
            "by the AI before executing — it can block weak setups (adds a few seconds per entry).")
    if arg in ("off", "0", "false", "no"):
        user_store.update(chat_id, {"ai_confirm": False})
        _restart_user_loop(chat_id)
        return send_to(chat_id,
            "⚡ <b>AI confirmation OFF.</b>\nEntries fire on the rule engine alone — instant, zero AI cost. "
            "All the risk guards (spread, news, HTF trend, cooldowns, circuit breakers) stay active.")
    cur = user_store.load(chat_id).get("ai_confirm", True)
    return send_to(chat_id,
        f"🧠 AI confirmation is <b>{'ON' if cur else 'OFF'}</b>.\n"
        "Use <code>/aiconfirm on</code> or <code>/aiconfirm off</code>.")


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


def _handle_resetstats(chat_id):
    """Wipe the trade journal + in-memory skip/streak counters for a clean run."""
    user_store.clear_trades(chat_id)
    dash = user_loop.get_dash(chat_id)
    if dash:
        dash["trades"] = []
        dash["skips"] = []
        dash["skipsToday"] = 0
        dash["startBalance"] = dash.get("balance", dash.get("startBalance", 0))
    # The persisted drawdown peak has to go too. It lives in strategy_session,
    # not dash, so it used to survive this "clean slate" — a stale peak (after
    # a withdrawal, say) then kept the drawdown breaker tripping on every tick
    # and the bot stayed halted straight through a reset the user believed had
    # cleared it, with no other way out.
    from apex import strategies as _st
    _bal = (dash or {}).get("balance")
    if _bal is None:
        _bal = user_store.load(chat_id).get("paper_balance") or 0
    _st.reset_peak(_bal, user_id=str(chat_id))
    send_to(chat_id,
        "🧹 <b>Journal reset — clean slate.</b>\n\n"
        "Performance stats now start fresh from this moment. Let the bot run "
        "undisturbed and check /stats in a week or two — that's the real,\n"
        "bug-free track record to judge it on.",
        _dashboard_keyboard(chat_id))


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


# ─── Performance ──────────────────────────────────────────
#
# Every figure on these screens comes from apex.performance, which in turn
# reuses ev.metrics. There is deliberately no arithmetic here: a second
# expectancy formula that drifts from the first is worse than no expectancy at
# all, and this file has already grown three private copies of one balance
# formatter once.

def _money(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"+${v:,.2f}" if v >= 0 else f"−${abs(v):,.2f}"


def _pf(v):
    if v == float("inf"):
        return "∞"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def _perf_body(s):
    """One summarize() dict, rendered. Returns None when there is nothing."""
    if not s or not s.get("trades"):
        return None
    lines = [
        f"📈 <b>{s['trades']}</b> trades · {s['wins']}W/{s['losses']}L · "
        f"Win rate <b>{s['win_rate']:g}%</b>",
        f"💰 Net: <b>{_money(s['net'])}</b>   ·   Expectancy: "
        f"<b>{_money(s['expectancy'])}</b>/trade",
        f"⚖️ Profit factor: <b>{_pf(s['profit_factor'])}</b>   ·   "
        f"Max drawdown: <b>{_money(-abs(s['max_drawdown']))}</b>",
        f"🏆 Best {_money(s['best'])} · 💥 Worst {_money(s['worst'])}",
    ]
    r = s.get("r")
    if r:
        # R answers a different question from dollars: whether the edge is
        # real. It carries its OWN trade count on purpose — rows written
        # before the stop distance was journalled cannot produce an R, and
        # borrowing the dollar count would overstate the sample.
        lines.append(
            f"\n📐 <b>In R</b> <i>(the {r['trades']} trades that recorded their "
            f"risk)</i>\nExpectancy <b>{r['expectancy_R']:+.2f}R</b> · "
            f"PF <b>{_pf(r['profit_factor_R'])}</b> · "
            f"Max DD <b>{abs(r['max_drawdown_R']):.2f}R</b>")
    return "\n".join(lines)


_PERF_TABS = [("Today", "pf:today"), ("Week", "pf:week"), ("Month", "pf:month"),
              ("All", "pf:all")]


def _perf_kb(chat_id):
    return _back_kb(chat_id, [
        [(lbl, cb) for lbl, cb in _PERF_TABS],
        [("🎯 By strategy", "pf:strat"), ("💱 By symbol", "pf:sym")],
    ])


def _screen_performance(chat_id, span="today"):
    from apex import performance
    from datetime import datetime, timedelta
    rows = user_store.load_trades(chat_id) or []
    titles = {"today": "Today", "week": "Last 7 days", "month": "Last 30 days",
              "all": "All time"}
    if span == "all":
        sel = rows
    else:
        days = {"today": 0, "week": 6, "month": 29}[span]
        day = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        sel = performance.since(rows, day)
    head = (f"📒 <b>Performance — {titles.get(span, span)}</b>\n"
            f"{_state_line(chat_id)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n")
    body = _perf_body(performance.summarize(sel))
    if body is None:
        return send_to(chat_id, head +
                       ("📭 No closed trades yet — this fills up as positions "
                        "close." if not rows else
                        "📭 No closed trades in this period. Try a wider one."),
                       _perf_kb(chat_id))
    send_to(chat_id, head + body +
            "\n\n<i>Closed trades only. An open position is not a result yet.</i>",
            _perf_kb(chat_id))


def _screen_perf_split(chat_id, by="strategy"):
    """Which method / which instrument is actually working on THIS account.

    Seventeen methods with no report saying which one works is a menu, not an
    advantage. Groups too thin to mean anything are shown last and labelled —
    ranking on three trades recommends whichever one got lucky.
    """
    from apex import performance
    rows = user_store.load_trades(chat_id) or []
    groups = (performance.by_strategy(rows) if by == "strategy"
              else performance.by_symbol(rows))
    title = "By strategy" if by == "strategy" else "By symbol"
    head = (f"📒 <b>Performance — {title}</b>\n{_state_line(chat_id)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n")
    if not groups:
        return send_to(chat_id, head + "📭 No closed trades yet.", _perf_kb(chat_id))
    out, thin_any = [], False
    for name, s in performance.ranked(groups):
        if by == "strategy":
            # The friendly label carries an explanation after an em-dash
            # ("Bounce Trader — buys dips, sells spikes"). That belongs on the
            # picker, not in a ranked list where it triples every row.
            label = (friendly_strategy(name)[0].split(" — ")[0]
                     if name != performance.UNLABELLED else "Unlabelled (older trades)")
        else:
            label = name
        thin = s.get("thin")
        thin_any = thin_any or thin
        out.append(f"{'⚪' if thin else ('✅' if s['net'] >= 0 else '❌')} "
                   f"<b>{_esc(label)}</b>\n"
                   f"   {s['trades']} trade{'s' if s['trades'] != 1 else ''} · "
                   f"{s['win_rate']:g}% won · "
                   f"net <b>{_money(s['net'])}</b> · "
                   f"expectancy {_money(s['expectancy'])}"
                   + ("  <i>— too few to judge</i>" if thin else ""))
    tail = ("\n\n<i>⚪ = fewer than 3 trades. Three trades is not evidence, so "
            "these are listed but not ranked.</i>" if thin_any else "")
    send_to(chat_id, head + "\n\n".join(out) + tail, _perf_kb(chat_id))


# ─── Emergency ────────────────────────────────────────────

def _screen_emergency(chat_id):
    n = user_loop.open_position_count(chat_id)
    count_line = ("<i>Open positions: not known yet — the bot has not reported "
                  "since it last started.</i>" if n is None else
                  f"<b>Open right now: {n} position{'s' if n != 1 else ''}</b>")
    running = user_loop.is_running(chat_id)
    send_to(chat_id,
            "🚨 <b>Emergency</b>\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{count_line}\n\n"
            "<b>⏸ Stop New Trades</b>\n"
            "The bot stops looking for setups. Anything already open stays "
            "open and keeps its stop-loss at the broker. Reversible — tap "
            "Resume whenever you want.\n\n"
            "<b>🔴 Close All Positions</b>\n"
            "Closes everything open, at the market price, immediately. "
            "<b>This cannot be undone:</b> a closed trade cannot be reopened "
            "at its entry, and whatever it is showing right now — profit or "
            "loss — becomes real.",
            _back_kb(chat_id, [
                [("⏸ Stop New Trades", "emg:pause")] if running
                else [("▶️ Resume Trading", "nav:resume")],
                [("🔴 Close All Positions", "emg:closeall")],
            ]))


def _screen_emergency_confirm(chat_id):
    n = user_loop.open_position_count(chat_id)
    if n == 0:
        return send_to(chat_id,
                       "📭 <b>Nothing is open</b> — there is nothing to close.",
                       _back_kb(chat_id, [[("🚨 Emergency", "nav:emg")]]))
    what = ("every open position" if n is None
            else f"{n} open position{'s' if n != 1 else ''}")
    unknown = ("\n\n⚠️ <i>The bot has not reported a position count since it "
               "last started, so it will close whatever it finds at the "
               "broker — which may be more than it is tracking.</i>"
               if n is None else "")
    send_to(chat_id,
            f"⚠️ <b>Close {what} now?</b>\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "This closes at the current market price, immediately, and "
            "<b>cannot be undone</b>. Any unrealised profit or loss becomes "
            "real the moment you tap.\n\n"
            "<b>The bot also stops opening new positions.</b> An emergency "
            "flatten that lets the next setup re-enter thirty seconds later is "
            "not an emergency stop — tap Resume when you want it watching "
            "again."
            + unknown,
            _back_kb(chat_id, [
                [(f"⚠️ Yes — close {'all' if n is None else n} now", "emg:go")],
                [("↩️ Cancel — leave them open", "emg:cancel")]]))


def _emergency_close_all(chat_id):
    send_to(chat_id, "🔴 Closing every open position…")
    # Hold FIRST, then flatten. In the other order the loop is still live
    # while positions are closing and can open a new one into the gap it just
    # made — which is the exact opposite of what the button says.
    try:
        user_loop.stop(chat_id)
    except Exception as e:
        print(f"[Telegram] emergency: could not stop the loop for {chat_id}: {e}")
    try:
        user_store.update(chat_id, {"emergency_stop": True})
    except Exception as e:
        print(f"[Telegram] emergency: could not record the hold for {chat_id}: {e}")
    try:
        res = user_loop.force_close_all(chat_id)
    except Exception as e:
        return send_to(chat_id,
                       "❌ <b>The close did not go through.</b>\n"
                       f"<i>{_esc(str(e)[:160])}</i>\n\n"
                       "<b>Your positions may still be open.</b> Check cTrader "
                       "and close them there.",
                       _back_kb(chat_id, [[("📈 Positions", "nav:pos")]]))
    try:
        from apex import control
        control._audit({"ts": int(time.time()), "actor": str(chat_id),
                        "action": "emergency_close_all",
                        "closed": res.get("closed"), "failed": res.get("failed")})
    except Exception as e:
        print(f"[Telegram] emergency close audit failed: {e}")
    closed = [c for c in (res.get("closed") or []) if c]
    failed = res.get("failed") or []
    parts = []
    if closed:
        parts.append(f"✅ Closed: <b>{_esc(', '.join(str(c) for c in closed))}</b>")
    if not closed and not failed:
        parts.append("📭 Nothing was open.")
    if failed:
        # The one outcome that must never be softened: still exposed.
        names = ", ".join(str(f.get("symbol") or "?") for f in failed)
        parts.append(f"\n🚨 <b>STILL OPEN: {_esc(names)}</b>\n"
                     "The broker did not confirm the close, so you are still "
                     "in these trades. <b>Open cTrader and close them "
                     "yourself.</b>")
    if res.get("sweepError"):
        parts.append(f"\n⚠️ <i>Could not read the full position list: "
                     f"{_esc(str(res['sweepError']))}. Check cTrader.</i>")
    parts.append("\n⏸ <b>The bot is now holding.</b> It will not open anything "
                 "new on this account until you resume it — that survives a "
                 "restart, so it stays held until you say otherwise.")
    send_to(chat_id, "🔴 <b>Emergency close</b>\n" + "\n".join(parts),
            _back_kb(chat_id, [[("▶️ Resume trading", "nav:resume")],
                               [("📈 Positions", "nav:pos"),
                                ("🏠 Home", "nav:home")]]))


# ─── Account ──────────────────────────────────────────────

def _screen_account(chat_id, refresh=False):
    """Which account, which environment, and what the bot may do on it."""
    from apex import screens
    st = _ui(chat_id, refresh=refresh, force=refresh)
    u = st.user or {}
    if not st.connected:
        return send_to(chat_id,
                       screens.account(st) + "\n\n"
                       "Connect a cTrader account and the bot can start. It "
                       "never holds your money — it places orders on your own "
                       "account, which stays yours.",
                       _kb([[("🔗 Connect my account", "go:connect")],
                            [("☰ Menu", "nav:menu")]]))
    dash = user_loop.get_dash(chat_id) or {}
    send_to(chat_id,
            screens.account(st,
                            account_id=u.get("ctrader_account_id"),
                            account_count=len(u.get("ctrader_accounts") or []),
                            balance=dash.get("balance")),
            _kb(screens.account_rows(st)))


def _screen_live_activation(chat_id):
    """The door to real money. It does not open it — /paper off still does.

    Deliberately a thin wrapper: the token, the TTL, the risk cap and the
    audit entry all live in _handle_paper, and a second activation path is
    exactly the kind of thing that ends up missing one of them.
    """
    # Before live activation the environment is re-established from the
    # broker, not read off the record. This is the single screen where being
    # wrong about demo-versus-live costs the client money.
    from apex import ui_state
    st = _ui(chat_id, refresh=True, force=True)
    if st.env != ui_state.LIVE:
        return send_to(chat_id,
                       f"{st.env_badge}\n\n"
                       "Real-money activation applies to a real broker "
                       "account. This one is not, or we could not confirm that "
                       "it is — either way we will not switch it to real "
                       "orders on a guess.\n\n"
                       f"<i>{st.env_detail.capitalize()}.</i>",
                       _kb([[("🔄 Switch account", "acct:switch")],
                            [("🔁 Re-check with my broker", "acct:refresh")],
                            [("☰ Menu", "nav:menu")]]))
    unverified = ("\n⚠️ <i>Your broker did not re-confirm this account just "
                  "now. The bot will still refuse a real order it cannot "
                  "authorise.</i>\n" if not st.proven else "")
    send_to(chat_id,
            "🔴 <b>Real-money trading</b>\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{unverified}\n"
            "The bot is connected to a LIVE account but is still simulating. "
            "Turning that off means the next setup places a real order.\n\n"
            + _protection_stack(chat_id) +
            "\n\nActivation needs a confirmation code you type back, and lands "
            f"with risk capped at <b>{_LIVE_INITIAL_RISK_CAP:.0%}</b> per trade "
            "whatever it was set to while simulating.",
            _back_kb(chat_id, [[("🔴 Start activation", "live:go")],
                               [("↩️ Stay in simulation", "nav:acct")]]))


def _handle_terminal(chat_id):
    """Open the Telegram Mini App — live interactive chart, position, news."""
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base:
        return send_to(chat_id, "⚠️ Terminal URL not configured (RENDER_EXTERNAL_URL).")
    # Show the symbol actually being traded RIGHT NOW in the message itself —
    # not just once the Mini App is opened — so this is never stale relative
    # to Auto-Pilot's live symbol rotation.
    dash = user_loop.get_dash(chat_id) or {}
    sym = dash.get("symbol")
    pos = dash.get("openPosition")
    if sym and pos:
        sym_line = f"📡 Currently trading: <b>{sym}</b> — {pos.get('side', '')} position open\n\n"
    elif sym:
        sym_line = f"📡 Currently watching: <b>{sym}</b> — no open position\n\n"
    else:
        sym_line = ""
    send_to(chat_id,
            "📈 <b>Apex Terminal</b>\n\n" + sym_line +
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


def _parse_trade_args(args):
    """Parse '/buy EURUSD 0.5' → (symbol_or_None, lots_or_None)."""
    parts = (args or "").strip().split()
    sym, lots = None, None
    for p in parts:
        try:
            lots = float(p)
        except ValueError:
            sym = p.upper().replace("/", "_").replace("-", "_")
    return sym, lots


_QUICK_SYMS_FX = ["EUR_USD", "GBP_USD", "USD_JPY", "XAU_USD", "GBP_JPY", "AUD_USD"]
_LOT_SIZES_FX = [0.01, 0.05, 0.1, 0.5, 1.0, 2.0]


def _trade_sym_kb(side):
    """Symbol picker buttons for /buy or /sell."""
    rows = []
    for i in range(0, len(_QUICK_SYMS_FX), 3):
        row = [{"text": s.replace("_", "/"), "callback_data": f"tr:{side}:{s}"}
               for s in _QUICK_SYMS_FX[i:i+3]]
        rows.append(row)
    return rows


def _size_word(n, label):
    """Pluralize a size label — 'oz' doesn't take a trailing 's'."""
    return label if label == "oz" else label + ("s" if n != 1 else "")


def _trade_lots_kb(side, sym):
    """Size picker buttons after symbol is chosen — 'lot' for FX, 'oz' for
    metals, 'unit' for anything else (crypto/indices), per forex.unit_label."""
    label = forex.unit_label(sym)
    rows = []
    for i in range(0, len(_LOT_SIZES_FX), 3):
        row = [{"text": f"{l} {_size_word(l, label)}", "callback_data": f"tr:{side}:{sym}:{l}"}
               for l in _LOT_SIZES_FX[i:i+3]]
        rows.append(row)
    rows.append([{"text": "🤖 Auto (risk-based)", "callback_data": f"tr:{side}:{sym}:auto"}])
    return rows


def _report_order_result(chat_id, result, side=None, sym=None):
    """One place that decides what a client is told about an order.

    Three outcomes, not two. The third — the broker did not answer — used to
    be reported as "❌ Could not open trade", which is a claim we cannot
    support: the order may be sitting open in the account. It gets its own
    screen, and that screen has no retry button.
    """
    from apex import screens
    if result.get("ok"):
        return True
    if result.get("ambiguous"):
        st = _ui(chat_id)
        send_to(chat_id,
                screens.order_unknown(st, side=side or result.get("side"),
                                      symbol=sym or result.get("symbol"),
                                      detail=_trade_err(result.get("error"))),
                _kb(screens.order_unknown_rows()))
        return False
    send_to(chat_id, f"❌ Could not open trade: {_trade_err(result.get('error'))}",
            _kb([[("📈 Positions", "nav:pos")], [("☰ Menu", "nav:menu")]]))
    return False


def _exec_trade(chat_id, side, sym, lots):
    lots_lbl = f" ({lots} {_size_word(lots, forex.unit_label(sym))})" if lots else ""
    send_to(chat_id, f"⚡ Opening <b>{side} {sym}</b>{lots_lbl}…")
    # Straight into the audited path. Telegram is a presentation layer: it does
    # not build a broker, it does not size a position and it does not decide
    # whether an order is allowed — force_trade enters gates.authorize_order
    # exactly as the automatic and control-plane origins do.
    result = user_loop.force_trade(str(chat_id), side, sym, lots=lots)
    if _report_order_result(chat_id, result, side, sym):
        send_to(chat_id,
                f"✅ <b>{side} {sym}</b> entered\n"
                f"Price: <b>{_fmt_px(result['price'])}</b> | Units: {result['units']}\n"
                f"SL: {_fmt_px(result['sl'])} | TP: {_fmt_px(result['tp'])}\n"
                f"Spread: {result.get('spread', '?')}p")


def _handle_buy(chat_id, args):
    sym, lots = _parse_trade_args(args)
    if sym and lots is not None:
        return _exec_trade(chat_id, "BUY", sym, lots)
    if sym:
        return send_to(chat_id, f"📊 <b>BUY {sym}</b> — choose size ({forex.unit_label(sym)}):",
                        extra={"reply_markup": {"inline_keyboard": _trade_lots_kb("BUY", sym)}})
    return send_to(chat_id, "📊 <b>BUY</b> — choose a pair:",
                    extra={"reply_markup": {"inline_keyboard": _trade_sym_kb("BUY")}})


def _handle_sell(chat_id, args):
    sym, lots = _parse_trade_args(args)
    if sym and lots is not None:
        return _exec_trade(chat_id, "SELL", sym, lots)
    if sym:
        return send_to(chat_id, f"📊 <b>SELL {sym}</b> — choose size ({forex.unit_label(sym)}):",
                        extra={"reply_markup": {"inline_keyboard": _trade_lots_kb("SELL", sym)}})
    return send_to(chat_id, "📊 <b>SELL</b> — choose a pair:",
                    extra={"reply_markup": {"inline_keyboard": _trade_sym_kb("SELL")}})


def _handle_close(chat_id):
    from apex import screens
    # Same rule as opening: the close goes through gates.authorize_close, and
    # a broker that did not answer is not a close that failed.
    result = user_loop.force_close(str(chat_id))
    if result.get("ok"):
        net = result.get("netPnl", 0)
        icon = "✅" if net >= 0 else "❌"
        return send_to(chat_id,
                f"🔒 <b>Position closed</b>\n"
                f"Price: <b>{result.get('price', '—')}</b>\n"
                f"{icon} Net P&amp;L: <b>{'+' if net >= 0 else ''}${net:.2f}</b> "
                f"<i>(gross ${result.get('grossPnl', 0):.2f} − cost ${result.get('costUsd', 0):.2f})</i>",
                _kb([[("📈 Positions", "nav:pos")], [("☰ Menu", "nav:menu")]]))
    if result.get("ambiguous"):
        return send_to(chat_id,
                       screens.close_unknown(_ui(chat_id),
                                             symbol=result.get("symbol"),
                                             detail=_trade_err(result.get("error"))),
                       _kb(screens.order_unknown_rows()))
    # A refusal from the close gate is a refusal, and it is named in words the
    # client can act on rather than in the gate's own vocabulary.
    reason = str(result.get("error") or "No open position")
    friendly = {
        "No open position to close": "There is nothing open to close.",
        "NOT_OWNER": "Another copy of the bot is managing this account right "
                     "now. It will close on its own — try again in a moment.",
        "DUPLICATE_CLOSE": "That close was already requested moments ago. "
                           "Check Positions before asking again.",
        "CLOSE_COORDINATION_UNAVAILABLE":
            "We cannot currently prove this close would not be sent twice, so "
            "it was not sent. If getting out now matters more than that risk, "
            "use Emergency → Close All.",
    }.get(reason, reason)
    send_to(chat_id, f"❌ {_esc(friendly)}",
            _kb([[("📈 Positions", "nav:pos"), ("🚨 Emergency", "nav:emg")],
                 [("☰ Menu", "nav:menu")]]))


# Stamped when the module loads, which is process start. Reading the clock on
# first CALL instead would report "running for 0m" on a process that had been
# up for days, which is precisely the fact this command exists to report.
_PROCESS_STARTED_AT = time.time()


def _handle_deploy(chat_id):
    """Report what is deployed. It no longer DEPLOYS anything.

    This used to shell out on the production host:

        fetch the branch, hard-reset the working tree onto it, reinstall
        requirements, then restart the service unit

    all of it as one string handed to a shell, behind nothing but an admin
    check. Three things are wrong with that in this architecture.

    (The literal commands are deliberately not written out here. A grep for
    them is how this class of thing gets found, and a docstring that contains
    the strings it is describing makes that grep useless — the same way a
    substring test can pass or fail on prose instead of code.)

    It cannot work. Production is Render, deploying from GitHub on every
    commit to the tracked branch. There is no checkout on disk to reset and no
    service unit to restart — the paths it drove belong to a host this service
    stopped running on.

    It was a second, competing way to change what code is live, inside a
    process that trades real money. Two deployment mechanisms mean the running
    code can disagree with the branch everyone reads.

    And it put arbitrary shell execution one compromised admin session away.
    `is_admin` is the only thing that stood between a Telegram message and a
    root shell on the trading host: no second factor, no confirmation, no
    audit beyond a log line.

    Deployment happens by pushing to the tracked branch. What an operator
    actually needs from Telegram is the answer to "is the thing I pushed the
    thing that is running", and that is a read.
    """
    import time as _t
    up = int(_t.time() - _PROCESS_STARTED_AT)
    h, rem = divmod(up, 3600)
    uptime = f"{h}h {rem // 60}m" if h else f"{rem // 60}m {rem % 60}s"

    # Render publishes these to every service it runs. Absent locally, which
    # is itself the honest answer to "what is deployed" on a laptop.
    svc = os.getenv("RENDER_SERVICE_NAME") or "—"
    branch = os.getenv("RENDER_GIT_BRANCH") or "—"
    commit = (os.getenv("RENDER_GIT_COMMIT") or "")[:8] or "—"
    on_render = bool(os.getenv("RENDER_SERVICE_NAME") or os.getenv("RENDER"))

    lines = [
        "🚀 <b>Deployment status</b>",
        f"Service: <b>{_esc(svc)}</b>",
        f"Branch: <code>{_esc(branch)}</code>",
        f"Commit: <code>{_esc(commit)}</code>",
        f"Running for: <b>{uptime}</b>",
        "",
    ]
    if on_render:
        lines.append("<i>Deploys are automatic: push to the branch above and "
                     "Render builds and restarts this service. There is "
                     "nothing to trigger from here.</i>")
    else:
        lines.append("<i>Not running on Render — these fields are only "
                     "populated by the deployment platform.</i>")
    lines.append("")
    lines.append("<i>This command is read-only. It reports what is deployed "
                 "and cannot change it.</i>")
    send_to(chat_id, "\n".join(lines), _back_kb(chat_id))


def _handle_grant(chat_id, args):
    target = (args or "").strip()
    if not target.lstrip("-").isdigit():
        return send_to(chat_id, "❌ Usage: <code>/grant 123456789</code>")
    if access.grant(target):
        send_to(chat_id, f"✅ Access granted to <code>{target}</code>.")
        send_to(target, f"✅ <b>You now have access to {cfg.BOT_NAME}!</b>\n"
                "The admin just gave you access. Tap below to connect your cTrader "
                "account and get set up.",
                extra={"reply_markup": {"inline_keyboard": [[
                    {"text": "🔗 Connect my cTrader account", "callback_data": "go:connect"}]]}})
    else:
        send_to(chat_id, f"ℹ️ <code>{target}</code> already has access.")


def _handle_revoke(chat_id, args):
    target = (args or "").strip()
    if not target.lstrip("-").isdigit():
        return send_to(chat_id, "❌ Usage: <code>/revoke 123456789</code>")
    if access.revoke(target):
        send_to(chat_id, f"✅ Access revoked for <code>{target}</code>.")
        send_to(target, f"⛔ Your access to {cfg.BOT_NAME} has been revoked.")
    else:
        send_to(chat_id, f"ℹ️ <code>{target}</code> not found or is an admin.")


_PURGE_THRESHOLD = 50000.0  # a real trade on these account sizes never gets near this


def _handle_purge_bad(chat_id, args):
    """Admin-only, mobile-friendly cleanup: find + (with confirmation) remove
    corrupted trade-journal records — no shell, no typing beyond the command
    itself. Defaults to the sender's own account if no user_id is given."""
    target = (args or "").strip() or str(chat_id)
    trades = user_store.load_trades(target)
    bad = [t for t in trades if abs(t.get("netPnl") or 0) > _PURGE_THRESHOLD
           or abs(t.get("grossPnl") or 0) > _PURGE_THRESHOLD]
    if not bad:
        return send_to(chat_id,
                f"✅ Journal for <code>{target}</code> looks clean — nothing above "
                f"${_PURGE_THRESHOLD:,.0f}.")
    lines = "\n".join(
        f"• {t.get('time', '?')} {t.get('symbol', '?')} netPnl={t.get('netPnl')}"
        for t in bad[:10])
    with _lock:
        _purge_pending[str(chat_id)] = target
    send_to(chat_id,
            f"⚠️ <b>Found {len(bad)} corrupted record(s)</b> for <code>{target}</code>:\n{lines}\n\n"
            "Remove just these? The rest of the journal stays untouched.",
            extra={"reply_markup": {"inline_keyboard": [[
                {"text": "🗑 Remove these", "callback_data": "purgebad:yes"},
                {"text": "✖️ Cancel", "callback_data": "purgebad:no"}]]}})


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
        parts.append(f"🧠 <i>{_esc(reasoning)}</i>")
    factors = result.get("keyFactors") or []
    if factors:
        parts.append("📊 " + " · ".join(_esc(f) for f in factors[:4]))
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


def daily_summary_text(user_id):
    """The end-of-day recap, or None when there is nothing to report.

    Built from the closed-trade journal, so it can only ever state what
    actually happened. Returns None on a day with no closed trades — a
    "0 trades today" message every evening is exactly the kind of noise this
    whole change is trying to remove.
    """
    from datetime import datetime
    try:
        rows = user_store.load_trades(user_id) or []
    except Exception:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    day = [r for r in rows if str(r.get("time", "")).startswith(today)]
    if not day:
        return None
    wins = [r for r in day if float(r.get("netPnl") or 0) > 0]
    losses = [r for r in day if float(r.get("netPnl") or 0) < 0]
    net = sum(float(r.get("netPnl") or 0) for r in day)
    bal = next((float(r["balance"]) for r in reversed(day)
                if r.get("balance") is not None), None)
    pct = (net / (bal - net) * 100) if bal and (bal - net) else 0
    icon = "✅" if net >= 0 else "❌"
    lines = [f"📊 <b>Today's summary</b>",
             f"Trades: <b>{len(day)}</b> ({len(wins)} won, {len(losses)} lost)",
             f"{icon} Net: <b>{'+' if net >= 0 else ''}${net:.2f}</b>"
             + (f" ({'+' if pct >= 0 else ''}{pct:.2f}%)" if pct else "")]
    if bal is not None:
        lines.append(f"💼 Balance: <b>${bal:.2f}</b>")
    # Name the strategies that traded — this is what §14 provenance is for.
    strats = [r.get("strategyId") for r in day if r.get("strategyId")]
    if strats:
        uniq = sorted(set(strats))
        lines.append("🎯 Strategy: <b>"
                     + ", ".join(friendly_strategy(x)[0] for x in uniq) + "</b>")
    lines.append("\n<i>Results vary day to day — past performance does not "
                 "guarantee future results. Adjust risk any time with "
                 "/risk.</i>")
    return "\n".join(lines)


def _strategy_choice_kb():
    """The one-tap "keep or change it" offer that rides the daily recap.

    Deliberately three buttons on an existing message rather than a new prompt
    of its own: the end of a trading day is the moment the question is worth
    asking, and asking it after every trade would put six keyboards a day in a
    channel the alert policy exists to keep readable.
    """
    return {"reply_markup": {"inline_keyboard": [
        [{"text": "✅ Keep this setup", "callback_data": "strat:keep"}],
        [{"text": "🔄 Change strategy", "callback_data": "nav:strat"},
         {"text": "⚙️ Rebuild it", "callback_data": "bld:open"}],
    ]}}


def send_daily_summary(user_id):
    text = daily_summary_text(user_id)
    if text:
        _user_alert(user_id, {"action": "DAILY_SUMMARY",
                              "text": text + "\n\n<b>Keep this setup for "
                                             "tomorrow, or change it?</b>",
                              "extra": _strategy_choice_kb()})
    return bool(text)


def _r_multiple_line(result):
    """" (+1.2R)" — the result in units of the risk that was taken.

    Dollars alone cannot be compared between trades: +$25 on a $10 risk and
    +$25 on a $200 risk are not the same outcome. R is the unit the whole
    exit logic already runs on (MIN_EXIT_R, RIDE_AT_R), and it was the one
    number the client could not see. Silent when the risk is unknown —
    inventing an R is worse than omitting it.
    """
    try:
        entry = float(result.get("entryPrice") or 0)
        stop = float(result.get("initialStop") or result.get("stopLoss") or 0)
        exit_px = float(result.get("price") or 0)
        if not (entry and stop and exit_px):
            return ""
        risk = abs(entry - stop)
        if risk <= 0:
            return ""
        side = (result.get("side") or "").upper()
        move = (exit_px - entry) if side == "BUY" else (entry - exit_px)
        r = move / risk
        return f" <b>({'+' if r >= 0 else ''}{r:.2f}R)</b>"
    except (TypeError, ValueError, ZeroDivisionError):
        return ""


def _user_alert(uid, result):
    """Per-user trade/heartbeat/error alert — module-level so setup auto-start,
    /start and auto-restore all share the same notification formatting."""
    try:
        from apex import control
        control.event_from_alert(uid, result)
    except Exception:
        pass
    action = result.get("action", "")
    sym = result.get("symbol", cfg.SYMBOL)
    # One gate for all 22 alert types. The bot used to send every diagnostic
    # it produced to every client; the volume is what made the channel
    # unreadable, not any single message.
    try:
        from apex import alert_policy
        if not alert_policy.allowed(action, user_store.load(uid)):
            return
    except Exception as e:
        print(f"[TELEGRAM] alert policy failed for {action}: {e}")
    if action == "DAILY_SUMMARY":
        send_to(uid, result.get("text", ""), result.get("extra"))
    elif action == "MARKET_CLOSE":
        send_to(uid,
                "🔴 <b>Market closed</b> — weekend.\n"
                + ("Your broker connection has been closed.\n"
                   if result.get("disconnected") else "")
                + "Nothing trades until Sunday. The bot reconnects to your "
                  "account by itself when the market reopens (~21:00 UTC) and "
                  "will message you then.")
    elif action == "MARKET_OPEN":
        if result.get("ok"):
            send_to(uid,
                    "🟢 <b>Market open</b> — the week has started.\n"
                    f"Account reconnected: <b>{result.get('detail', '')}</b>\n"
                    "The bot is scanning for setups again.")
        else:
            # This is the message the whole reconnect check exists to produce.
            # Saying "market open" without it would read as good news while the
            # account is unreachable and nothing can trade.
            send_to(uid,
                    "🟢 <b>Market open</b> — but the bot <b>cannot reach your "
                    "account</b>.\n"
                    f"<i>{str(result.get('detail', ''))[:200]}</i>\n\n"
                    "No trades will be placed until this is fixed. Send "
                    "/ctrader to reconnect your account.")
    elif action == "HEARTBEAT":
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
                f"<i>{_esc(result.get('reason', '')[:160])}</i>\n\n"
                "I retry every 30s automatically. If this keeps up, "
                "send /ctrader to re-connect your account.")
    elif action == "STOP":
        reasons = ", ".join(result.get("reasons", ["risk limit"]))
        send_to(uid, f"🛑 <b>Trading paused — risk limit hit</b>\n{reasons}")
    elif action == "SENTINEL_FLIP":
        _arrow = {"BUY": "🟢", "SELL": "🔴"}.get(result.get("to"), "⚪")
        _c = result.get("conf")
        _conf_txt = f"  ·  {_c:.0%} confidence" if isinstance(_c, (int, float)) else ""
        send_to(uid,
                f"{_arrow} <b>AI changed its read — {result.get('symbol', sym)}</b>\n"
                f"<b>{result.get('from', '?')}</b> → <b>{result.get('to', '?')}</b>"
                f"{_conf_txt}\n"
                f"Regime: <i>{_esc(str(result.get('regime', '—')))}</i>\n"
                f"{_esc(str(result.get('reasoning', ''))[:200])}\n\n"
                "<i>This is the Sentinel's view, not an order. "
                "The risk engine still decides.</i>")
    elif action == "SENTINEL_BLOCK":
        _why = {
            "NO_FRESH_AI_SIGNAL": "no fresh AI read — the last one expired",
            "AI_DISAGREES": "the AI wants the other direction",
            "LOW_CONFIDENCE": "the AI isn't confident enough",
            "LOW_EV": "expected value too low",
            "RISK_BLOCK": "the risk engine said no",
            "AI_SAYS_HOLD": "the AI says stay out",
        }.get(result.get("reason"), result.get("reason", "refused"))
        _mode = result.get("mode", "shadow")
        send_to(uid,
                f"🛑 <b>Sentinel {'blocked' if _mode == 'enforce' else 'would block'} "
                f"{result.get('wanted', '?')} {result.get('symbol', sym)}</b>\n"
                f"{_esc(_why)}\n"
                f"<code>{_esc(str(result.get('state', '')))}</code>"
                + ("" if _mode == "enforce" else
                   "\n\n<i>Shadow mode — the trade still went through. "
                   "This is what it WOULD have stopped.</i>"))
    elif action == "SHADOW_OPEN":
        send_to(uid,
                f"🔍 <b>Setup refused — {result.get('symbol', sym)}</b>\n"
                f"Would have been <b>{result.get('side')}</b> @ "
                f"<code>{result.get('entry')}</code>\n"
                f"SL <code>{result.get('sl')}</code> · TP <code>{result.get('tp')}</code>\n"
                f"Blocked by: <i>{_esc(result.get('blockedBy', 'filter'))}</i>\n"
                f"{_esc(result.get('reasoning', ''))}\n\n"
                "I'll follow it and tell you whether skipping was right.")
    elif action == "SHADOW_MOVE":
        r = result.get("r", 0)
        send_to(uid,
                f"📊 <b>Refused {result.get('symbol', sym)} — now {r:+.1f}R</b>\n"
                f"<i>{'Moving our way — skipping may have cost us.' if r > 0 else 'Moving against — skipping looks right so far.'}</i>")
    elif action == "SHADOW_RESULT":
        out, pips, r = result.get("outcome"), result.get("pips", 0), result.get("r", 0)
        if out == "TAKE_PROFIT":
            head = (f"❌ <b>Skipping that one cost us</b>\n"
                    f"{result.get('symbol', sym)} reached target: "
                    f"<b>+{abs(pips):.0f} pips ({r:+.1f}R)</b>")
        elif out == "STOP_LOSS":
            head = (f"✅ <b>Good call skipping that</b>\n"
                    f"{result.get('symbol', sym)} would have stopped out: "
                    f"<b>−{abs(pips):.0f} pips ({r:+.1f}R)</b>")
        else:
            head = (f"➖ <b>{result.get('symbol', sym)} went nowhere</b>\n"
                    f"Stopped watching at <b>{pips:+.0f} pips ({r:+.1f}R)</b> — "
                    "neither target nor stop reached")
        sc = result.get("scoreboard") or {}
        tail = ""
        if sc.get("n"):
            tail = (f"\n\n<b>Refused setups tracked:</b> {sc['n']} · "
                    f"{sc.get('wouldHaveWon', 0)} would have won · "
                    f"{sc.get('wouldHaveLost', 0)} would have lost\n"
                    f"<i>{_esc(sc.get('verdict', ''))}</i>")
        send_to(uid, head + tail)
    elif action == "SKIP_WARN":
        # One message per distinct refusal, then silence until it changes — so
        # this line has to carry the state the repeats used to imply. "3rd time
        # today" says the condition is persisting without another notification,
        # and naming the scan says the bot is working rather than stuck.
        n = result.get("countToday")
        nth = f" · {n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'} skip today" \
            if isinstance(n, int) and n > 0 else ""
        # Trade Blocked — a setup existed and a guard refused it. Naming the
        # guard is what turns "the bot isn't doing anything" into "the bot is
        # working and this is why".
        send_to(uid, f"⚠️ <b>Trade blocked — {result.get('symbol', sym)}</b>{nth}\n"
                     f"{_state_line(uid, guard=True)}\n"
                     "━━━━━━━━━━━━━━━━━━━━\n"
                     f"<i>{_esc(result.get('reason', 'market conditions are unfavourable right now'))}.</i>\n"
                     "Still scanning — I'll take the trade as soon as conditions "
                     "normalise, and I won't repeat this unless something changes.")
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
    elif action in ("NEWS_AHEAD", "NEWS_CLEAR"):
        # The calendar reaching out, rather than waiting to be looked up.
        # NEWS_WARN above is a different message: it fires only when a setup
        # was actually refused, so it says nothing at all on a day the bot
        # finds no trade to hold back. These two fire on the release itself.
        ev = result.get("event", {})
        ccy = _esc(str(ev.get("currency") or ""))
        title = _esc(str(ev.get("title") or "Economic release"))
        # Only claim the pause where the guard is actually switched on for
        # this client — the message must describe the bot they have.
        guarded = bool(result.get("guard"))
        if action == "NEWS_AHEAD":
            mins = max(0, int(ev.get("mins") or 0))
            figures = []
            if ev.get("forecast"):
                figures.append(f"expected <b>{_esc(str(ev['forecast']))}</b>")
            if ev.get("previous"):
                figures.append(f"previous {_esc(str(ev['previous']))}")
            fig = ("\n<i>" + " · ".join(figures) + "</i>") if figures else ""
            tail = ("\nI'm standing aside until it passes — spreads blow out "
                    "and price gaps straight through stops around releases."
                    if guarded else
                    # Do NOT point at /news on here: that switches these
                    # messages, not the guard. The guard is `news_filter`,
                    # which lives in Strategy Builder.
                    "\n<i>Your news guard is OFF, so I'll keep trading through "
                    "it — turn News guard on in /builder if you'd rather I "
                    "waited.</i>")
            send_to(uid, f"📰 <b>{ccy} · {title}</b>\n"
                         f"Lands in about <b>{mins} min</b>.{fig}{tail}")
        else:
            send_to(uid, f"✅ <b>{ccy} · {title} is out</b>\n"
                         + ("Back to trading normally."
                            if guarded else
                            "The release has passed and the market is settling."))
    elif action == "SUGGEST":
        # Trade Opportunity — the approval-required variant. The state banner
        # is not decoration: "is this my demo or my real account" is the first
        # thing anyone wants to know before tapping Approve.
        d = "🟢 BUY" if result.get("side") == "BUY" else "🔴 SELL"
        # Approving a trade is the moment "is this my real money" costs the
        # most to get wrong, so the demo and live variants of this alert say
        # different things about what Approve will do — and both of them read
        # the environment off the connected account.
        _st = _ui(uid)
        if _st.is_live and not _st.simulating:
            _what = ("<i>Approve places a <b>real order</b> on your live "
                     "account. Nothing opens until you tap it.</i>")
        elif _st.is_live:
            _what = ("<i>This is a real account, but the bot is still "
                     "simulating on it — Approve records the trade and places "
                     "nothing at your broker.</i>")
        elif _st.is_demo:
            _what = ("<i>Approve opens this on your demo account. Simulated "
                     "money — nothing here can cost you anything.</i>")
        else:
            _what = ("<i>We could not confirm which account this is. Approve "
                     "will be checked again before anything is placed.</i>")
        send_to(uid,
                f"⚡ <b>Trade opportunity</b>\n{_state_line(uid, guard=True)}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{d} <b>{sym}</b> @ {_fmt_px(result.get('price'))}"
                + _fx_why_block(result) +
                f"\n\n{_what}",
                extra={"reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Approve", "callback_data": "cp:y"},
                    {"text": "❌ Reject", "callback_data": "cp:n"}]]}})
    elif action == "SIGNAL":
        # Signals Only — there is deliberately no Approve button, because
        # there is nothing stored to approve. Saying so plainly is the whole
        # point: the client must never be left wondering whether the bot took
        # this one.
        d = "🟢 BUY" if result.get("side") == "BUY" else "🔴 SELL"
        # Same message, two audiences. On a demo account this is practice; on
        # a live one, acting on it by hand spends real money — and the client
        # should not have to work out which from a badge alone.
        _sst = _ui(uid)
        _where = (" on your <b>real-money</b> account" if _sst.is_live
                  else " on your <b>demo</b> account" if _sst.is_demo else "")
        send_to(uid,
                f"📣 <b>Signal</b> — no order placed\n{_state_line(uid)}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{d} <b>{sym}</b> @ {_fmt_px(result.get('price'))}"
                + _fx_why_block(result) +
                "\n\n<i>You're on Signals Only, so I placed nothing. If you "
                f"take this one yourself it is your own order{_where}, and "
                "none of the bot's limits apply to it.</i>",
                _back_kb(uid, [[("🤖 Automation", "nav:auto"),
                                ("📡 Market", "nav:mkt")]]))
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
        # Trade Executed. The state banner says whose money just moved.
        send_to(uid,
                f"{d} <b>{action}</b> — {sym}\n"
                f"{_state_line(uid, guard=True)}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"Price: <b>{_fmt_px(result.get('price'))}</b> | "
                f"Confidence: <b>{result.get('confidence', 0)}%</b>{spread_line}{rr_line}"
                + _fx_why_block(result))
        _send_chart_async(uid, symbol=sym, position={
            "side": action, "entryPrice": result.get("price"),
            "stopLoss": result.get("stopLoss"), "takeProfit": result.get("takeProfit")},
            caption=f"{d} {sym} — entry, SL &amp; TP on the chart")
        _handle_terminal(uid)  # one-tap live view right after every open — no digging for /terminal
    elif action == "CLOSE":
        net = result.get("netPnl")
        _reason_lbl = {"STOP_LOSS": "🛑 Stop loss hit",
                       "TAKE_PROFIT": "🎯 Take profit hit"}.get(result.get("reason"))
        why = (f"\n🧠 <i>{_esc(result['reasoning'])}</i>" if result.get("reasoning")
               else _fx_close_why(result.get("reason", "")))
        if net is not None:
            icon = "✅" if net >= 0 else "❌"
            head = f"🔒 <b>Position closed</b> — {sym}"
            if _reason_lbl:
                head = f"{_reason_lbl} — {sym}"
            send_to(uid,
                    f"{head}\n"
                    f"Exit: <b>{_fmt_px(result.get('price'))}</b>\n"
                    f"{icon} Net P&amp;L: <b>{'+' if net >= 0 else ''}${net:.2f}</b>"
                    f"{_r_multiple_line(result)} "
                    f"<i>(gross ${result.get('grossPnl', 0):.2f} − cost ${result.get('costUsd', 0):.2f})</i>\n"
                    f"💼 Balance: <b>${result.get('balance', 0):.2f}</b>"
                    + why)
        else:
            send_to(uid,
                    f"🔒 <b>Position closed</b> — {sym}\n"
                    f"Price: <b>{_fmt_px(result.get('price'))}</b>" + why)
    elif action == "BROKER_CLOSE_MULTI":
        send_to(uid,
                f"🔒 <b>Position closed</b> — {sym}\n"
                f"Hit its target or stop at the broker.\n"
                f"💼 Balance: <b>${result.get('balance', 0):.2f}</b>")
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
        # The exit price is absent when Auto-Pilot had already rotated to
        # another instrument by the time this close was noticed — the loop
        # refuses to pass the new focus pair's price off as this one's. Say
        # that, rather than printing an arrow pointing at an em-dash. The P&L
        # is the broker's own figure and is unaffected either way.
        _exit = result.get("price")
        move = (f"{result.get('side', '')} from <b>{_fmt_px(result.get('entryPrice'))}</b> → "
                f"≈ <b>{_fmt_px(_exit)}</b> (stop-loss or take-profit executed at cTrader)"
                if _exit is not None else
                f"{result.get('side', '')} from <b>{_fmt_px(result.get('entryPrice'))}</b> — "
                f"closed at cTrader (stop-loss or take-profit); exact exit price "
                f"not captured, P&amp;L below is the broker's own figure")
        send_to(uid,
                f"🎯 <b>Your broker closed the position</b> — {sym}\n"
                f"{move}\n"
                f"{pnl_line}"
                f"💼 Balance: <b>${result.get('balance', 0):.2f}</b>")
    elif action == "STOP_BREAKEVEN":
        # The one trail worth a sentence: past this point the trade cannot
        # lose. Every later trail is silent unless /verbose is on.
        sl = result.get("sl")
        side = "🟢 LONG" if result.get("side") == "BUY" else "🔴 SHORT"
        send_to(uid,
                f"🛡️ <b>This trade can no longer lose</b> — {sym} {side}\n"
                f"The stop is now past your entry (at <b>{_fmt_px(sl)}</b>), so "
                "the worst case is breaking even. It keeps trailing as price "
                "moves your way — I won't message you for each step.")
    elif action == "STOP_MOVED":
        sl = result.get("sl")
        side = "🟢 LONG" if result.get("side") == "BUY" else "🔴 SHORT"
        send_to(uid,
                f"🛡️ <b>Stop trailed</b> — {sym} {side} → <b>{_fmt_px(sl)}</b>")
    elif action == "UNPROTECTED":
        # The rarest and worst state: a live position with no stop-loss at the
        # broker, because the attach was rejected and the safety close failed
        # too. There is nothing to do remotely — say so plainly.
        send_to(uid,
                f"🚨 <b>{_esc(sym)} is open with NO stop-loss</b>\n"
                "The broker rejected the stop and my emergency close didn't go "
                "through either.\n\n"
                "<b>Open cTrader and close it, or set a stop yourself — now.</b> "
                "Until then this trade has no downside limit.\n"
                "<i>I've stopped opening anything new on it.</i>")
    elif action == "EXIT_FAILED":
        # The strategy wanted out and the broker refused the close. Silence
        # here is how a client ends up holding a trade the bot has already
        # decided against, believing it was exited.
        send_to(uid,
                f"⚠️ <b>Couldn't close {_esc(sym)}</b>\n"
                "The strategy called an exit and the broker didn't confirm it, "
                "so the position is <b>still open</b>. Your stop-loss is still "
                "with the broker and still protecting it.\n\n"
                "I'm retrying automatically. Close it yourself with /close if "
                "you'd rather not wait.")
    elif action == "WEEKEND_CLOSE":
        # Say what actually happened. This used to claim "any open position was
        # closed" unconditionally — and it was sent BEFORE the close was even
        # attempted, so a client could be told they were flat while the
        # position sat open at the broker over the weekend gap.
        _closed = int(result.get("closed") or 0)
        _failed = result.get("failed") or []
        if _failed:
            send_to(uid,
                    "⚠️ <b>Couldn't close before the weekend — please check</b>\n"
                    f"Still open: <b>{_esc(', '.join(_failed))}</b>\n\n"
                    "Close it yourself in cTrader. A position held through the "
                    "weekend gap can reopen Sunday well past its stop, which is "
                    "the exact risk this is meant to avoid.\n"
                    "<i>I'll keep retrying and tell you if it goes through.</i>")
        elif _closed:
            send_to(uid,
                    "🌙 <b>Market closed for the weekend</b>\n"
                    f"Closed {_closed} position{'s' if _closed != 1 else ''} to "
                    "avoid gap risk over Sat/Sun — no new trades until it "
                    "reopens. I'll message you the moment it's back.")
        else:
            send_to(uid,
                    "🌙 <b>Market closed for the weekend</b>\n"
                    "Nothing was open, so there was nothing to close. No new "
                    "trades until it reopens — I'll message you when it's back.")
    elif action == "WEEKEND_REOPEN":
        send_to(uid,
                "🔔 <b>Market's back open</b>\n"
                "Trading resumes automatically. As a precaution after the "
                "weekend break, send /ctrader now to reconnect your broker "
                "account — takes a second, and makes sure the connection "
                "is fresh before the first trade of the week.")
    else:
        send_to(uid, f"⚡ <b>{action}</b> — {sym}")


# Live Stripe Payment Link (plink_1Tge4jGpBbs5xtI52jgQQx7F) for the Apex Forex
# Bot one-time license, $497. Static, no backend required to serve it — but
# fulfillment (issuing the license key back to the buyer) still goes through
# the site's /stripe-webhook, so it only auto-activates while that service is
# up. If it's down, confirm manually via Stripe Dashboard + /grant <chat_id>.
_PURCHASE_LINK = "https://buy.stripe.com/4gMeVdcnn7AX5Xp5TU2Ji01"


_PROOF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "proof")
# (filename, caption) — real closed-trade screenshots from this bot's own
# Telegram output, shown before anything else to build trust with proof
# instead of claims.
_PROOF_SHOTS = [
    ("IMG_7107.jpeg", "📈 Real signal — NZDUSD, AI confidence 66%"),
    ("IMG_7108.jpeg", "✅ Same trade, closed: <b>+$199.23</b>"),
    ("IMG_7105.jpeg", "✅ XAUUSD (gold) — entry, chart, and result: <b>+$127.36</b>"),
]
# Full week of trading, wins AND losses — shown deliberately, not just the
# best individual trades above, because a real track record (including the
# losers) builds more trust than a highlight reel alone.
_PROOF_VIDEO = ("ScreenRecording_08-01-2026 17-15-50_1.mov",
                "🎥 A full week, unedited — wins <b>and</b> losses. "
                "This is what actually running the bot looks like.")


def send_proof_shots(chat_id):
    """Send the trade-result screenshots + full-week recording as ONE
    swipeable album, not stacked separate messages. Best-effort — a missing
    file or Telegram hiccup should never block onboarding.

    Shown at most ONCE per chat_id — a not-yet-licensed user hits the gate
    on every message they send (/start again, /help, whatever), and without
    this it resent the whole album each time, which is exactly the
    "repeats every time I hit start" spam this guards against.
    """
    cid = str(chat_id)
    try:
        if user_store.load(cid).get("proof_shown"):
            return
    except Exception:
        pass
    items = []
    for filename, caption in _PROOF_SHOTS:
        path = os.path.join(_PROOF_DIR, filename)
        try:
            with open(path, "rb") as f:
                items.append((f.read(), filename, "image/jpeg", caption, "photo"))
        except Exception as e:
            print(f"[TELEGRAM] proof shot {filename} failed: {e}")
    vid_filename, vid_caption = _PROOF_VIDEO
    vid_path = os.path.join(_PROOF_DIR, vid_filename)
    try:
        with open(vid_path, "rb") as f:
            items.append((f.read(), vid_filename, "video/quicktime", vid_caption, "video"))
    except Exception as e:
        print(f"[TELEGRAM] proof video failed: {e}")
    if items:
        send_media_group(chat_id, items)
    try:
        user_store.update(cid, {"proof_shown": True})
    except Exception:
        pass


def send_activation_sequence(chat_id, paid: bool):
    """Full onboarding in one shot: proof screenshots, welcome, FP Markets
    signup link, and the real cTrader authorize link — sent immediately, no
    extra taps needed to get to the link. Used both for free-growth-phase
    first contact and for instant post-payment activation (paid=True skips
    the free-access framing).
    """
    send_proof_shots(chat_id)
    welcome_head = ("🎉 <b>Payment received — you're in!</b>" if paid else
                     "🎉 <b>Welcome — you're in!</b>")
    risk_bullet = (f"• Free access requires a <b>live {_REQUIRED_BROKER_LABEL}</b> account\n"
                   if (_LIVE_BROKER_REQUIRED and not paid) else
                   "• Start on a <b>demo account</b> first to test risk-free\n")
    send_to(chat_id,
            f"{welcome_head}\n\n"
            "You now own a fully-hosted AI trading bot that runs on "
            "<b>your own</b> trading account, controlled entirely from "
            "this Telegram chat. No apps to install, no PC required.\n\n"
            "⚠️ <b>Important — please read:</b>\n"
            "• Trading involves risk — profits are not guaranteed\n"
            "• Losses are possible and they are <b>yours</b>\n"
            "• This is software, not financial advice\n"
            f"{risk_bullet}")
    broker_rows = _broker_signup_rows()
    if _LIVE_BROKER_REQUIRED:
        step1_body = (
            "📌 <b>Step 1 — Open a broker account</b>\n\n"
            f"You need a <b>live</b> cTrader account with <b>{_REQUIRED_BROKER_LABEL}</b> "
            "— that's who verifies and funds your bot. If you don't have one yet, "
            "open one below (takes 2 minutes).")
    else:
        step1_body = (
            "📌 <b>Step 1 — Create a broker account</b>\n\n"
            "You need a cTrader account with a supported broker. "
            "If you don't have one yet, create one below (takes 2 minutes).\n\n"
            "Supported brokers: IC Markets, Pepperstone, FxPro, "
            "RoboForex, and any broker that offers cTrader.")
    send_to(chat_id, step1_body,
            extra={"reply_markup": {"inline_keyboard": broker_rows}} if broker_rows else None)
    # Step 2 — send the REAL authorize link directly, not a button that makes
    # them tap again to get it. That's the whole point of "instant".
    send_to(chat_id, "📌 <b>Step 2 — Connect your account</b>")
    _handle_ctrader(chat_id)
    gurl = _guide_url()
    tips_kb = []
    if gurl:
        tips_kb.append([{"text": "📖 How it works — 2 min guide", "web_app": {"url": gurl}}])
    tips_kb.append([{"text": "🎛 See all controls", "callback_data": "go:controls"}])
    send_to(chat_id,
            "💡 <b>Helpful links</b>\n\n"
            "• /controls (or /settings) — see every command and what it does\n"
            "• /guide — how the bot works (visual guide)\n"
            "• /help — quick command list\n"
            "• /terminal — live trading dashboard",
            extra={"reply_markup": {"inline_keyboard": tips_kb}})
    label = "Paid client" if paid else "New client"
    send(f"🆕 <b>{label} activated!</b>\nID: <code>{chat_id}</code>")


def _handle_purchase(chat_id):
    # client_reference_id round-trips through Stripe Checkout and lands on the
    # session in the webhook payload — that's how stripe_license.handle_webhook
    # knows which Telegram chat to activate.
    link = f"{_PURCHASE_LINK}?client_reference_id={chat_id}"
    send_to(chat_id,
            f"💳 <b>Get {cfg.BOT_NAME}</b>\n\n"
            "One-time payment, $497 — lifetime access, no subscription.\n\n"
            "Tap below to pay securely via Stripe. Your access activates "
            "automatically the moment payment goes through — no key to copy, "
            "no waiting.",
            extra={"reply_markup": {"inline_keyboard": [[
                {"text": "💳 Buy now — $497", "url": link}]]}})


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
    (user_loop._loop), so config changes like ctrader_env only take effect on a
    fresh loop. No-op if the user isn't currently trading.
    """
    if not user_loop.is_running(chat_id):
        return False
    user_loop.stop(chat_id)
    return user_loop.start(chat_id, alert_fn=_user_alert)


def _handle_start(chat_id):
    # /start is one of the moments the account environment is re-established
    # from the broker. A client sending /start after switching accounts in
    # cTrader must not be shown the environment they had yesterday.
    from apex import ui_state
    user, _ok, _why = ui_state.refresh(chat_id, force=True)
    if user is None:
        user = user_store.load(chat_id)
    # Resuming is the one thing that lifts an emergency hold, and it is
    # deliberately explicit: the hold survives a restart, so it can only be
    # cleared by the client asking for it.
    if user.get("emergency_stop"):
        try:
            user_store.update(chat_id, {"emergency_stop": False})
        except Exception as e:
            print(f"[Telegram] could not clear the emergency hold for {chat_id}: {e}")
    # Check user has credentials set up
    if (not access.is_admin(str(chat_id)) and not user.get("paper")
            and not (user.get("ctrader_access_token") and user.get("ctrader_account_id"))):
        return send_to(chat_id,
            "🔗 <b>First, connect your trading account.</b>\n\n"
            "Tap below — it takes 30 seconds and then the bot sets itself up.",
            extra={"reply_markup": {"inline_keyboard": [[
                {"text": "🔗 Connect my account", "callback_data": "go:connect"}]]}})
    if user_loop.is_running(chat_id):
        return send_to(chat_id,
            "✅ <b>Bot is already ON</b> — watching the market. It trades automatically when a valid setup appears.",
            _dashboard_keyboard(chat_id))

    _auto_start_user(chat_id)
    send_to(chat_id,
        "✅ <b>Bot is ON — trading now active.</b>\nIt watches the market and trades automatically on valid setups.",
        _dashboard_keyboard(chat_id))


def _handle_stop(chat_id):
    """The Pause screen. Says what pausing does NOT do, which is the half
    people get wrong — an open position is still open and still exposed."""
    user_loop.stop(chat_id)
    # Also pause global bot for admin
    if access.is_admin(str(chat_id)) and _bot_control.get("set_paused"):
        _bot_control["set_paused"](True)
    n = None
    try:
        n = user_loop.open_position_count(chat_id)
    except Exception as e:
        print(f"[Telegram] pause: position count unreadable for {chat_id}: {e}")
    if n:
        still = (f"\n\n📈 <b>{n} position{'s' if n != 1 else ''} still open.</b> "
                 "Pausing does not close anything — each one keeps its stop at "
                 "your broker. Use Positions to close one, or Emergency to "
                 "close everything.")
    elif n == 0:
        still = "\n\n📭 Nothing is open."
    else:
        still = ("\n\n<i>How many positions are open has not been reported "
                 "since the bot last started — check Positions.</i>")
    send_to(chat_id,
            "⏸ <b>Trading paused</b>\n"
            f"{_state_line(chat_id, guard=True)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "The bot has stopped looking for setups. <b>No new position will "
            "be opened.</b>" + still,
            _back_kb(chat_id, [[("▶️ Resume trading", "nav:resume")],
                               [("📈 Positions", "nav:pos"),
                                ("🚨 Emergency", "nav:emg")]]))


def _handle_reset(chat_id):
    """Client self-service full reset: disconnects cTrader and wipes every bot
    setting back to defaults. Does NOT touch bot access —/grant'd or licensed
    users stay allowed, they just start the setup over from scratch."""
    send_to(chat_id,
        "⚠️ <b>Full reset — are you sure?</b>\n\n"
        "This disconnects your cTrader account from the bot and resets every "
        "setting (strategy, risk, pairs, symbol — everything) back to default. "
        "Your broker account itself is untouched — this only clears the bot's "
        "link to it.\n\n"
        "<i>This can't be undone.</i>",
        extra={"reply_markup": {"inline_keyboard": [[
            {"text": "⚠️ Yes, reset everything", "callback_data": "reset:yes"},
            {"text": "Cancel", "callback_data": "reset:no"}]]}})


def _handle_config(chat_id):
    keys = _BROKER_KEYS.get(cfg.BROKER, [])
    key_lines = "\n".join(
        f"  {k}: {_mask(getattr(cfg, k, '')) if getattr(cfg, k, '') else '—'}"
        for k in keys)
    paused = _bot_control.get("get_paused", lambda: False)()
    state_tag = "⏸️ PAUSED" if paused else "▶️ RUNNING"
    key_title = "MT bridge" if cfg.BROKER == "mt" else "cTrader"
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


# Growth-phase copy: while the live-broker gate is on, "start on demo" is
# actively wrong advice (demo never unlocks free access) — swap it for the
# real requirement instead of leaving stale text next to the working gate.
_SETUP_LINE_CLIENT = ("/setup — choose pair, risk, strategy\n" if _LIVE_BROKER_REQUIRED else
                      "/setup — choose demo/live, pair, risk\n")
_SETUP_LINE_CONTROLS = ("/setup — Guided setup: pick your pair, risk, strategy\n\n" if _LIVE_BROKER_REQUIRED else
                        "/setup — Guided setup: pick your pair, strategy, mode\n\n")
_DEMO_LIVE_HELP = ((
    "<b>🟢 Getting free access:</b>\n"
    f"Free access requires a <b>live {_REQUIRED_BROKER_LABEL}</b> account — "
    "run /setup, then /ctrader to connect it.\n\n"
) if _LIVE_BROKER_REQUIRED else (
    "<b>🔄 Demo ↔ Live:</b>\n"
    "Start on a demo account with /setup. When you're ready, "
    "send /ctrader and switch to your live account.\n\n"
))
_DEMO_LIVE_CONTROLS = ((
    "<b>🟢 Getting free access</b>\n"
    f"Free access requires a <b>live {_REQUIRED_BROKER_LABEL}</b> account. Connect it "
    "with /ctrader.\n\n"
) if _LIVE_BROKER_REQUIRED else (
    "<b>🔄 Demo ↔ Live</b>\n"
    "Start on a demo account. When you're confident, send /ctrader "
    "and connect your live broker account.\n\n"
))

_HELP_CLIENT = (f"📋 <b>{cfg.BOT_NAME.upper()}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{_SETUP_LINE_CLIENT}"
                "/status — live trading snapshot\n"
                "/ctrader — connect your cTrader account\n"
                "/start — resume trading\n"
                "/stop — pause your bot\n"
                "/controls or /settings — all controls explained\n"
                "/purchase — buy your license ($497)\n"
                "/help — this list\n\n"
                "/menu — every screen, as buttons\n\n"
                "<b>📊 Trading</b>\n"
                f"/buy — open a BUY · /sell — open a SELL\n"
                "/close — close current position\n"
                "/open — what's open right now\n"
                "/performance — results by period, method and pair\n"
                "/report — trade journal + P&amp;L\n"
                "/emergency — stop new trades, or close everything\n\n"
                "<b>⚙️ Settings</b>\n"
                "/automation — signals only, approval, or full\n"
                "/copilot on|off — approve trades yourself\n"
                "/builder — build your strategy\n"
                "/account — broker account and live activation\n"
                "/news — high-impact events\n\n"
                f"{_DEMO_LIVE_HELP}"
                "💬 <i>Or just ask me a question — write in any language, I answer in English.</i>")

_CONTROLS_TEXT = (
    f"🎛 <b>{cfg.BOT_NAME.upper()} — Controls Guide</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>🟢 Getting Started</b>\n"
    "/ctrader — Connect your cTrader broker account\n"
    f"{_SETUP_LINE_CONTROLS}"
    "<b>☰ Everything, as buttons</b>\n"
    "/menu — Overview, Positions, Strategy, Risk, Automation, Performance, "
    "Market, News, Settings, Help, Pause, Emergency\n\n"
    "<b>⏯ ON / OFF</b>\n"
    "/start — Turn the bot ON (it watches the market and trades automatically)\n"
    "/stop — Pause the bot (no new trades; open positions keep their safety stop)\n"
    "/emergency — Stop new trades, or close every open position at once\n\n"
    "<b>📊 Trading</b>\n"
    "/status — See your current position, balance, and bot state\n"
    "/open — Every position open right now, with live P&amp;L\n"
    "/performance — Results by day, week, month, method and instrument\n"
    "/report — Full trade journal with profit/loss breakdown\n"
    "/terminal — Open the live dashboard (chart, equity, stats)\n"
    "/buy — Manually open a BUY trade\n"
    "/sell — Manually open a SELL trade\n"
    "/close — Close your current open position\n\n"
    "<b>⚙️ Settings</b>\n"
    "/pairs — Browse available trading instruments\n"
    "/symbol EURUSD — Change what you trade\n"
    "/strategy — Pick a trading method (STRATCOUNT available, incl. Auto)\n"
    "/risk — Pick a risk tier, or /risk 2 for an exact % (0.5–50%)\n"
    "/sl 50 — Set stop loss in pips\n"
    "/tp 100 — Set take profit in pips\n"
    "/tptarget 5 — Or target a % of your balance per win instead (scales with the account)\n"
    "/atr on|off — Use dynamic ATR-based stops\n"
    "/aiconfirm on|off — AI double-checks each entry (on) or pure rules (off)\n"
    "/automation — How much the bot may do alone: Signals Only (it tells you "
    "and places nothing), Approval Required (it asks first), Full Automation\n"
    "/copilot on|off — Approve each trade before it opens (same setting, "
    "older name)\n"
    "/account — Which broker account you're on, and real-money activation\n"
    "/builder — Build a custom strategy step by step\n"
    "/autopilot on — Let the bot pick the best instruments too\n"
    "/maxpos 3 — Allow multiple positions at once\n\n"
    "<b>📰 Info</b>\n"
    "/news — Economic calendar · /news on|off for release alerts\n"
    "/voice — Control the bot from your phone through Siri Shortcuts\n"
    "/guide — How the bot works (visual guide)\n"
    "/purchase — Buy your license ($497 one-time)\n"
    "/help — Quick command list\n\n"
    f"{_DEMO_LIVE_CONTROLS}"
    "<b>♻️ Starting over</b>\n"
    "/reset — Disconnect cTrader and wipe all settings back to default\n\n"
    "💬 <i>You can also just ask me a question. Write in any language you like — I understand it and reply in English.</i>")

_HELP_ADMIN = (f"📋 <b>{cfg.BOT_NAME.upper()} COMMANDS</b>\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/status — live trading snapshot\n"
               "/market — session + market pulse\n"
               "/setup — guided setup wizard\n"
               "/config — show current settings\n"
               "/report — trade journal + net P&amp;L\n"
               "/summary — today's results in one message\n"
               "/controls or /settings — every control explained\n"
               "/guide — visual walkthrough\n"
               "/verbose — show or hide diagnostic alerts\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/buy &lt;PAIR&gt; — open BUY manually\n"
               "/sell &lt;PAIR&gt; — open SELL manually\n"
               "/close — close current position\n"
               "/ctrader — connect cTrader · /copilot on|off · /news\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/risk — risk tier menu · /risk &lt;0.5-50&gt; — exact % per trade\n"
               "/sl &lt;pips&gt; — stop loss · /tp &lt;pips&gt; — take profit\n"
               "/tptarget &lt;pct&gt; — TP as % of balance instead (scales with account)\n"
               "/symbol &lt;PAIR&gt; — set pair\n"
               "/pairs — available instruments\n"
               "/watch — scan a basket, trade the strongest setup\n"
               "/autopilot on — bot picks instruments too\n"
               "/maxpos 5 — hold several trades at once\n"
               "/strategy — pick from STRATCOUNT methods (send it to see them)\n"
               "/builder — build a full strategy or 1-tap preset\n"
               "/atr on|off — dynamic ATR stops\n"
               "/terminal — live trading terminal\n"
               "/stats — performance report\n"
               "/chart — quick chart snapshot\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/start — resume · /stop — pause · /reset — wipe cTrader link + all settings\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "/purchase — buy license link ($497)\n"
               "━━━━━━━━━━━━━━━━━━━━\n"
               "👑 <b>Admin</b>\n"
               "/grant &lt;id&gt; — give client access\n"
               "/revoke &lt;id&gt; — remove access\n"
               "/users — list clients\n"
               "/purgebad [id] — clean up corrupted journal records (defaults to your own)\n"
               "/help — this list\n\n"
               "💬 <i>Free text → AI assistant (any language)</i>")


def _with_counts(text):
    """Fill the STRATCOUNT placeholder from the registry, at send time.

    The help copy used to name the number itself — "10 available", "auto ·
    mean reversion · trend · breakout". Both went stale the moment §2 added
    the momentum/session/z-score/volatility families and grid/martingale: the
    guide promised ten while the picker listed sixteen. Asking the same source
    /strategy asks means the two can no longer disagree.
    """
    try:
        from apex import strategy_api
        strategy_api.load_builtins()
        n = len(strategy_api.available())
    except Exception:
        n = 0
    return text.replace("STRATCOUNT", str(n) if n else "several")


# ─── Poll loop ────────────────────────────────────────────

_VERIFY_URL = f"{cfg.LICENSE_SERVER}/api/verify-license"
_DEPLOY_URL = ""
# Open-access mode (free-for-everyone growth phase): set REQUIRE_LICENSE=true
# on Render to bring the license-key gate back on for new users. Existing
# already-granted users are unaffected either way — this only decides
# whether a brand-new chat_id needs a valid key to get past _license_ok.
_LICENSE_REQUIRED = (os.getenv("REQUIRE_LICENSE", "false").strip().lower() in ("1", "true", "yes"))


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
    cmd_l = cmd.lower().split("@")[0]
    key = karg.strip().upper()
    # /purchase (and aliases) must work for a not-yet-licensed user — that's
    # the whole point of the command. Without this it hit the generic
    # "activation required" branch below and just re-showed the proof shots,
    # never the actual payment link.
    if cmd_l in ("/purchase", "/buylicense", "/pay"):
        _handle_purchase(chat_id)
        return False
    if cmd_l != "/start" or not key:
        send_proof_shots(chat_id)
        send_to(chat_id,
            "🔒 <b>Activation required</b>\n\n"
            "Already bought? Open the activation link from your purchase email.\n\n"
            f"New here? Send /purchase — instant access, no waiting.")
        return False
    if not re.match(rf'^{cfg.LICENSE_KEY_PREFIX}-[A-Z2-9]{{4}}-[A-Z2-9]{{4}}-[A-Z2-9]{{4}}$', key):
        send_to(chat_id,
            "❌ <b>That doesn't look like a valid key.</b>\n\n"
            f"Use the <code>{cfg.LICENSE_KEY_PREFIX}-XXXX-XXXX-XXXX</code> key from your purchase email, "
            "or join https://t.me/Apex4Traders to get one")
        return False
    # FAIL CLOSED for a first-time chat. Everything above this point has
    # already let through the two populations that deserve grace: an admin, and
    # a returning customer whose stored key we still hold. Anything reaching
    # here has never been validated, so an unreachable verifier is not evidence
    # in their favour — and treating it as such made the outage itself the way
    # in. Whoever messaged during a verifier outage got the product.
    #
    # The cost is bounded and recoverable: a real buyer during an outage is
    # told to retry, and their key still works minutes later. The cost of the
    # other direction is unbounded — every key-shaped string is accepted for
    # as long as the verifier is down.
    try:
        r = requests.post(_VERIFY_URL, json={"key": key, "product": cfg.LICENSE_PRODUCT}, timeout=8)
        if r.status_code >= 500:
            raise RuntimeError(f"verifier returned HTTP {r.status_code}")
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("verifier returned a non-object body")
        if not data.get("valid"):
            send_to(chat_id,
                f"❌ <b>{data.get('message', 'License not found.')}</b>\n\n"
                "Need help? supportaicashsystem@gmail.com")
            return False
    except Exception as e:
        print(f"[TELEGRAM] ⛔ verify-license unavailable ({e}) — DENYING a "
              f"first-time activation. An unverifiable licence is not a licence.")
        send_to(chat_id,
            "⏳ <b>We can't check that key right now.</b>\n\n"
            "Our licence service isn't responding. Your key is fine — please "
            "try the activation link again in a few minutes.\n\n"
            "Still stuck after that? supportaicashsystem@gmail.com")
        return False
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
        r = requests.post(_VERIFY_URL, json={"key": key, "product": cfg.LICENSE_PRODUCT}, timeout=8)
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


# How long after start a 409 still counts as our own deploy handing over.
# Render overlaps the new instance with the draining old one; observed
# handovers on this service clear well inside a minute, and a second
# deployment never clears at all.
_CONFLICT_GRACE_S = float(os.getenv("TELEGRAM_CONFLICT_GRACE_S", "90"))


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
    _conflict_streak = 0
    _conflict_since = 0.0
    _started_at = time.time()
    while True:
        try:
            r = requests.get(f"{_API}/getUpdates",
                             params={"offset": _update_id, "timeout": 10,
                                     "allowed_updates": json.dumps(["message", "callback_query"])},
                             timeout=15)
            data = r.json()
            if not data.get("ok"):
                if data.get("error_code") == 409:
                    # Another process is polling this same token — Telegram
                    # only lets one getUpdates caller win at a time. Back off
                    # (capped at 2 min) rather than retrying flat forever.
                    #
                    # Nearly every one of these is our OWN deploy. Render
                    # starts the new instance before draining the old one, so
                    # for a few seconds both poll and one loses. The old copy
                    # exits on its own and the conflict clears with no action.
                    # The message used to send the operator hunting for "a
                    # leftover Railway deployment or a second Render service"
                    # every single deploy — an accusation of a misconfiguration
                    # that did not exist, which is how a real one would have
                    # been dismissed as the usual noise.
                    #
                    # So: quiet while a handover is plausible, loud only once
                    # it has outlived one. A second deployment does not drain.
                    _conflict_streak += 1
                    wait = min(120, 10 * _conflict_streak)
                    if _conflict_streak == 1:
                        _conflict_since = time.time()
                    # Grace is measured from the FIRST CONFLICT, not from this
                    # process's start, and the difference is not academic: the
                    # old instance is by definition old, so measuring from its
                    # start put it straight into the "this is no longer a
                    # handover" branch every single deploy. It then accused the
                    # operator of running a second deployment — with its own
                    # uptime quoted as how long the other process had been
                    # polling, which is not what that number is. Verified
                    # against the account: one service, numInstances=1, and the
                    # only other deployment suspended.
                    #
                    # A handover resolves within a minute whichever side you
                    # are on. A genuine second deployment does not resolve at
                    # all, so a conflict that outlives the grace window is the
                    # real signal.
                    _conflicted_for = time.time() - _conflict_since
                    _handover = _conflicted_for < _CONFLICT_GRACE_S
                    if _handover:
                        if _conflict_streak == 1:
                            print(f"[TELEGRAM] 409 Conflict — the other instance is still "
                                  f"draining. Normal during a deploy; waiting {wait}s.")
                    elif _conflict_streak == 1 or _conflict_streak % 6 == 0:
                        print(f"[TELEGRAM] 409 Conflict UNRESOLVED for "
                              f"{_conflicted_for:.0f}s (streak={_conflict_streak}). A "
                              f"deploy handover clears in under a minute, so something "
                              f"else is running the same TELEGRAM_BOT_TOKEN: a second "
                              f"Render service, a leftover deployment, or a local copy. "
                              f"Backing off {wait}s.")
                    time.sleep(wait)
                    continue
                print(f"[TELEGRAM] API error: {data.get('description')} (code {data.get('error_code')})")
                time.sleep(10)
                continue
            if _conflict_streak:
                print(f"[TELEGRAM] conflict cleared after {_conflict_streak} "
                      f"attempt(s) — this instance now owns the poll.")
            _conflict_streak = 0
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
                    # Growth phase: REQUIRE_LICENSE unset/false skips the gate
                    # entirely — anyone's first message grants access.
                    if _LICENSE_REQUIRED and not _license_ok(chat_id, raw):
                        continue
                    access.grant(chat_id_str)
                    send_activation_sequence(chat_id, paid=_LICENSE_REQUIRED)
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

                dispatch_command(chat_id, raw, msg_id, first_line, cmd_l, args)
        except Exception as e:
            print(f"[TELEGRAM] Poll error: {e}")
        time.sleep(2)


def dispatch_command(chat_id, raw, msg_id=None, first_line=None,
                     cmd_l=None, args=None):
    """Run one client command. The body of the Telegram poll loop.

    Extracted so the exact dispatch a real message goes through can also
    be driven from the control plane. Nothing here changed: the poll loop
    calls this with the same arguments it used to compute inline, and an
    injected message takes the identical path — same access checks, same
    handlers, same replies. A test that ran a private copy of this logic
    would prove nothing about what a client actually gets.
    """
    chat_id_str = str(chat_id)
    if first_line is None:
        first_line = (raw or "").splitlines()[0].strip() if raw else ""
    if cmd_l is None:
        _cmd, _, _args = first_line.partition(" ")
        cmd_l = _cmd.lower().split("@")[0]
        if args is None:
            args = _args.split("\n")[0].strip()
    if args is None:
        args = ""

    is_adm = access.is_admin(chat_id_str)

    # Log inbound Telegram commands to the control-plane feed so the
    # operator (via MCP) can see exactly what clients are sending.
    try:
        from apex import control
        control.event("tg_in", first_line[:120], user_id=chat_id_str)
    except Exception:
        pass

    if cmd_l == "/deploy" and is_adm:
        _handle_deploy(chat_id)
    elif cmd_l in ("/status", "/s"):
        _handle_status(chat_id)
    elif cmd_l == "/report":
        _handle_report(chat_id)
    elif cmd_l == "/help":
        _handle_quick_help(chat_id)
    elif cmd_l == "/allcommands":
        send_to(chat_id, _with_counts(_HELP_ADMIN if is_adm else _HELP_CLIENT))
    elif cmd_l == "/verbose":
        _u = user_store.load(chat_id)
        _on = not _u.get("verbose_alerts")
        user_store.update(chat_id, {"verbose_alerts": _on})
        send_to(chat_id,
                "🔊 <b>Detailed alerts ON</b> — you'll now also see "
                "every skipped setup, each stop trail and the "
                "bot's internal checks.\nSend /verbose again to go "
                "back to quiet."
                if _on else
                "🔇 <b>Quiet mode</b> — you'll get trades, the "
                "daily summary and anything that needs you. "
                "Diagnostics are hidden.\nSend /verbose to see "
                "everything.")
    elif cmd_l == "/summary":
        if not send_daily_summary(chat_id):
            send_to(chat_id, "📊 No closed trades today yet.")
    elif cmd_l in ("/controls", "/settings"):
        # /settings is an alias, not a nicety: it is the name
        # people reach for first, and the reconnect message told
        # clients to send it while no such command existed.
        send_to(chat_id, _with_counts(_CONTROLS_TEXT))
    elif cmd_l in ("/purchase", "/buylicense", "/pay"):
        _handle_purchase(chat_id)
    elif cmd_l == "/users" and is_adm:
        _handle_users(chat_id)
    elif cmd_l == "/grant" and is_adm:
        _handle_grant(chat_id, args)
    elif cmd_l == "/revoke" and is_adm:
        _handle_revoke(chat_id, args)
    elif cmd_l == "/purgebad" and is_adm:
        _handle_purge_bad(chat_id, args)
    elif cmd_l == "/setup":
        # Every paying client self-configures their OWN trading via the
        # wizard (writes only their user record); admin extras apply
        # globally inside _handle_wizard_reply.
        _handle_setup(chat_id)
    elif cmd_l == "/reset":
        _handle_reset(chat_id)
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
    elif cmd_l == "/switch":
        _handle_switch(chat_id)
    elif cmd_l == "/copilot":
        _handle_copilot(chat_id, args)
    elif cmd_l in ("/automation", "/mode"):
        _handle_automation(chat_id, args)
    elif cmd_l == "/menu":
        _handle_menu(chat_id)
    elif cmd_l == "/open":
        # NOT /positions — that has meant "how many at once" since /maxpos
        # shipped, and quietly repointing it would change what an existing
        # client's muscle memory does.
        _screen_positions(chat_id)
    elif cmd_l in ("/emergency", "/panic"):
        _screen_emergency(chat_id)
    elif cmd_l == "/account":
        _screen_account(chat_id)
    elif cmd_l == "/golive":
        _screen_live_activation(chat_id)
    elif cmd_l == "/news":
        _handle_news(chat_id, args)
    elif cmd_l in ("/voice", "/siri"):
        _handle_voice(chat_id, args)
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
    elif cmd_l == "/tptarget":
        _handle_tptarget(chat_id, args)
    elif cmd_l == "/symbol":
        _handle_symbol(chat_id, args)
    elif cmd_l in ("/pairs", "/symbols"):
        _handle_pairs(chat_id)
    elif cmd_l == "/watch":
        _handle_watch(chat_id, args)
    elif cmd_l in ("/autopilot", "/auto"):
        _handle_autopilot(chat_id, args)
    elif cmd_l in ("/maxpos", "/positions"):
        _handle_maxpos(chat_id, args)
    elif cmd_l in ("/builder", "/build", "/strategybuilder"):
        _handle_builder(chat_id)
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
    elif cmd_l in ("/guide", "/help2", "/manual", "/howto"):
        _handle_guide(chat_id)
    elif cmd_l == "/atr":
        _handle_atr(chat_id, args)
    elif cmd_l == "/aiconfirm":
        _handle_aiconfirm(chat_id, args)
    elif cmd_l == "/stats":
        _handle_stats(chat_id)
    elif cmd_l == "/performance":
        # Repointed off /stats deliberately. Both read the same journal, but
        # only this one can answer "which of my seventeen methods is actually
        # working" — and that is the question the number of methods creates.
        # /stats is untouched for anyone who has it in muscle memory.
        _screen_performance(chat_id, "today")
    elif cmd_l in ("/resetstats", "/resetjournal"):
        _handle_resetstats(chat_id)
    elif cmd_l == "/buy":
        _handle_buy(chat_id, args)
    elif cmd_l == "/sell":
        _handle_sell(chat_id, args)
    elif cmd_l == "/close":
        _handle_close(chat_id)
    elif cmd_l in ("/start", "/resume"):
        # /resume is what people type after /stop, and what the
        # onboarding copy promised. It did not exist.
        _handle_start(chat_id)
    elif cmd_l == "/stop":
        # Per-user: stops only this client's loop (admin also pauses global).
        _handle_stop(chat_id)
    elif cmd_l == "/ai":
        _handle_ai_setup(chat_id, args, msg_id)
    elif cmd_l in ("/groq", "/gemini", "/key"):
        # Explicit key command — the key is the argument.
        _handle_ai_key(chat_id, args, msg_id)
    elif not raw.startswith("/"):
        # A bare pasted AI key → connect it (and keep it out of chat history).
        if _detect_ai_key(raw.strip()):
            _handle_ai_key(chat_id, raw.strip(), msg_id)
            # Was `continue` when this lived in the poll loop; in a function
            # the same meaning is "this update is finished".
            return
        # Intent detection first (works with zero AI key)
        handled = _handle_trade_intent_fx(chat_id, raw)
        if not handled:
            handled = _handle_quick_answer(chat_id, raw)
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
               f"🛡 SL: {_fmt_px(stop_loss)} ({sl_pips:.0f} pips)\n"
               f"🎯 TP: {_fmt_px(take_profit)} ({tp_pips:.0f} pips){mult}{why}", _dashboard_keyboard())


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
    send(f"🚀 <b>{cfg.BOT_NAME.upper()} STARTED</b>\n{cfg.ASSET_EMOJI} {symbol} | {timeframe} | ${balance:.2f}\n⚙️ {mode}\n"
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
