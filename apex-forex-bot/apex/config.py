"""Configuration loaded from environment (.env supported)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("true", "1", "yes", "on")


# ─── Broker ─────────────────────────────────────────────
BROKER = (os.getenv("BROKER") or "oanda").lower()
SUPPORTED_BROKERS = ["oanda", "mt", "td"]

# ─── MetaTrader bridge (BROKER=mt) ──────────────────────
MT_BRIDGE_SECRET = os.getenv("MT_BRIDGE_SECRET", "")

# ─── Twelve Data (BROKER=td) ────────────────────────────
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY", "")

# ─── OANDA ──────────────────────────────────────────────
OANDA_API_TOKEN = os.getenv("OANDA_API_TOKEN", "")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")
OANDA_ENV = (os.getenv("OANDA_ENV") or "practice").lower()  # practice | live

# ─── AI providers ───────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ─── Telegram ───────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

# ─── Scalping mode ──────────────────────────────────────
# One switch that flips the bot to a fast, tight-target profile for small
# accounts. Explicit env vars below still override these, so you can fine-tune.
# Critical for scalping: a STRICT spread filter — on 9-pip targets a wide
# spread silently eats the edge, so we skip entries when the spread is too big.
SCALP_MODE = _truthy(os.getenv("SCALP_MODE"))


def _scalp(name, scalp_default, normal_default):
    """Env var wins; otherwise scalp default in SCALP_MODE, else normal default."""
    v = os.getenv(name)
    return v if v is not None else (scalp_default if SCALP_MODE else normal_default)


# ─── Trading ────────────────────────────────────────────
SYMBOL = os.getenv("TRADE_SYMBOL", "EUR_USD")
TIMEFRAME = _scalp("TIMEFRAME", "1m", "5m")
CANDLES = 200

# ─── Scanner ────────────────────────────────────────────
SCAN_SYMBOLS = (os.getenv("SCAN_SYMBOLS") or "NZD_USD").split(",")  # tuning r9: NZD-only (EUR/AUD/JPY/CAD all negative; NZD edge is signal-specific)
MULTI_SYMBOL = os.getenv("MULTI_SYMBOL") != "false"

# ─── Risk ───────────────────────────────────────────────
RISK_PER_TRADE = float(_scalp("RISK_PER_TRADE", 0.01, 0.005))  # scalp: 1% (controlled, not aggressive) · swing: 0.5%
STOP_LOSS_PIPS = float(_scalp("STOP_LOSS_PIPS", 6, 20))        # scalp: tight 6p · swing: 20p
TAKE_PROFIT_PIPS = float(_scalp("TAKE_PROFIT_PIPS", 9, 40))    # scalp: 9p (R:R 1.5) · swing: 40p (R:R 2)
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 62)
LEVERAGE = float(os.getenv("LEVERAGE") or 30)
MARGIN_CAP = float(os.getenv("MARGIN_CAP") or 0.5)             # use ≤50% of available margin
MAX_SPREAD_PIPS = float(_scalp("MAX_SPREAD_PIPS", 1.2, 3.0))   # scalp: strict 1.2p — wide spread kills tight targets

# ─── Trailing stop ──────────────────────────────────────
TRAILING_STOP = os.getenv("TRAILING_STOP") == "true"  # off implicit — tuning: pure-TP bate trailing în chop
TRAILING_STOP_PIPS = float(os.getenv("TRAILING_STOP_PIPS") or 10)

# ─── Exit management (cut losses, let profits run) ──────
BREAKEVEN_AT_R = float(os.getenv("BREAKEVEN_AT_R") or 0)           # 0 = off; tuning: BE+trail taie câștiguri în chop
LET_WINNERS_RUN = os.getenv("LET_WINNERS_RUN") != "false"          # la TP nu închide — trailing strâns (doar paper)
RUNNER_TRAIL_PIPS = float(os.getenv("RUNNER_TRAIL_PIPS") or 6)     # trail în runner mode

# ─── Entry filters (anti-chop) ──────────────────────────
HTF_FILTER = os.getenv("HTF_FILTER") != "false"                    # nu intra contra trendului mare
HTF_STRICT = os.getenv("HTF_STRICT") != "false"                    # tuning r4: ON by default — filtrul cel mai bun; R4 EUR +0.33%, AUD +1.46%
HTF_TIMEFRAME = os.getenv("HTF_TIMEFRAME") or "1h"
COOLDOWN_AFTER_LOSS_MIN = int(_scalp("COOLDOWN_AFTER_LOSS_MIN", 3, 15))  # scalp: shorter pause

# ─── ATR-based SL/TP (overrides pip-based when on) ──────
ATR_BASED_SL = os.getenv("ATR_BASED_SL") == "true"
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT") or 1.5)
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT") or 3.0)

# ─── Misc ───────────────────────────────────────────────
LOOP_INTERVAL_MS = int(_scalp("LOOP_INTERVAL_MS", 60 * 1000, 5 * 60 * 1000))  # scalp: analyze every 1 min

# ─── Paper trading ──────────────────────────────────────
PAPER_TRADING = _truthy(os.getenv("PAPER_TRADING") or "true")
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE") or 1000)

# ─── License ────────────────────────────────────────────
LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SERVER = os.getenv("LICENSE_SERVER") or "https://aicashsystem.space"
