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

# ─── Trading ────────────────────────────────────────────
SYMBOL = os.getenv("TRADE_SYMBOL", "EUR_USD")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
CANDLES = 200

# ─── Scanner ────────────────────────────────────────────
SCAN_SYMBOLS = (os.getenv("SCAN_SYMBOLS") or "EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD").split(",")
MULTI_SYMBOL = os.getenv("MULTI_SYMBOL") != "false"

# ─── Risk ───────────────────────────────────────────────
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE") or 0.02)   # 2% — forex standard
STOP_LOSS_PIPS = float(os.getenv("STOP_LOSS_PIPS") or 15)
TAKE_PROFIT_PIPS = float(os.getenv("TAKE_PROFIT_PIPS") or 30)  # 1:2 R:R
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 65)
LEVERAGE = float(os.getenv("LEVERAGE") or 30)
MARGIN_CAP = float(os.getenv("MARGIN_CAP") or 0.5)             # use ≤50% of available margin
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS") or 3.0)   # skip entries on wide spreads

# ─── Trailing stop ──────────────────────────────────────
TRAILING_STOP = os.getenv("TRAILING_STOP") != "false"
TRAILING_STOP_PIPS = float(os.getenv("TRAILING_STOP_PIPS") or 10)

# ─── ATR-based SL/TP (overrides pip-based when on) ──────
ATR_BASED_SL = os.getenv("ATR_BASED_SL") == "true"
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT") or 1.5)
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT") or 3.0)

# ─── Misc ───────────────────────────────────────────────
LOOP_INTERVAL_MS = int(os.getenv("LOOP_INTERVAL_MS") or 5 * 60 * 1000)

# ─── Paper trading ──────────────────────────────────────
PAPER_TRADING = _truthy(os.getenv("PAPER_TRADING") or "true")
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE") or 1000)

# ─── License ────────────────────────────────────────────
LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SERVER = os.getenv("LICENSE_SERVER") or "https://aicashsystem.space"
