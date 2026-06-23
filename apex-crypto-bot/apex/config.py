"""Configuration loaded from environment (.env supported) — crypto edition."""
import os
from dotenv import load_dotenv

load_dotenv()


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("true", "1", "yes", "on")


# ─── AI providers (OWNER sets one shared key — clients never need their own) ──
# Priority for the assistant: Anthropic (executes trades) > Gemini (free 1500/day)
# > Groq (free, fast). Set ONE of these in Render and every client uses it.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Smartest free brain by default. Free tier (1500/day):
#   gemini-2.5-flash → smart + fast (recommended)
#   gemini-2.5-pro   → smartest, lower free daily limit
#   gemini-2.0-flash → older, fastest
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()

# ─── Telegram ───────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")
SITE_URL = os.getenv("SITE_URL", "https://aicashsystem.space")

# ─── Exchange (market data + optional live) ─────────────
# Binance public market data needs no API key (paper trading default).
# Testnet by default so any "live" experiment can't touch real funds.
EXCHANGE = (os.getenv("EXCHANGE") or "binance").lower()
BINANCE_TESTNET = (os.getenv("BINANCE_TESTNET") or "true").lower() != "false"

# ─── Trading defaults ───────────────────────────────────
SYMBOL = (os.getenv("TRADE_SYMBOL") or "BTCUSDT").upper()
TIMEFRAME = os.getenv("TIMEFRAME") or "5m"
CANDLES = 200
STRATEGY_MODE = (os.getenv("STRATEGY_MODE") or "auto").lower()

# ─── Risk (percent-based for crypto) ────────────────────
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE") or 0.05)     # 5% of balance per trade
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT") or 0.016)      # 1.6%
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT") or 0.032)  # 3.2% (R:R 2)
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 58)
MIN_CRITERIA = int(os.getenv("MIN_CRITERIA") or 2)
FEE_PCT = float(os.getenv("FEE_PCT") or 0.001)                  # 0.1% taker

# ─── Risk pause (self-healing, never latches) ───────────
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES") or 3)
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT") or 3.0)
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT") or 20.0)
MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES") or 10)
RISK_PAUSE_MIN = int(os.getenv("RISK_PAUSE_MIN") or 60)         # auto-resume after N min
COOLDOWN_AFTER_LOSS_MIN = int(os.getenv("COOLDOWN_AFTER_LOSS_MIN") or 15)

# ─── Loop ───────────────────────────────────────────────
LOOP_INTERVAL_SEC = int(os.getenv("LOOP_INTERVAL_SEC") or 60)  # analyze every minute

# ─── Paper trading ──────────────────────────────────────
PAPER_TRADING = _truthy(os.getenv("PAPER_TRADING") or "true")
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE") or 100)

# ─── License (kept for support/tracking; never shown to clients) ──
LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SERVER = os.getenv("LICENSE_SERVER") or "https://aicashsystem.space"
