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
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE") or 0.005)  # 0.5% — tuning r3: scales linearly; 1% → -9.7%/10d in chop
STOP_LOSS_PIPS = float(os.getenv("STOP_LOSS_PIPS") or 15)
TAKE_PROFIT_PIPS = float(os.getenv("TAKE_PROFIT_PIPS") or 30)  # 1:2 R:R
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 62)
LEVERAGE = float(os.getenv("LEVERAGE") or 30)
MARGIN_CAP = float(os.getenv("MARGIN_CAP") or 0.5)             # use ≤50% of available margin
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS") or 3.0)   # skip entries on wide spreads

# ─── Trailing stop ──────────────────────────────────────
TRAILING_STOP = os.getenv("TRAILING_STOP") == "true"  # off implicit — tuning: pure-TP bate trailing în chop
TRAILING_STOP_PIPS = float(os.getenv("TRAILING_STOP_PIPS") or 10)

# ─── Exit management (cut losses, let profits run) ──────
BREAKEVEN_AT_R = float(os.getenv("BREAKEVEN_AT_R") or 0)           # 0 = off; tuning: BE+trail taie câștiguri în chop
LET_WINNERS_RUN = os.getenv("LET_WINNERS_RUN") != "false"          # la TP nu închide — trailing strâns (doar paper)
RUNNER_TRAIL_PIPS = float(os.getenv("RUNNER_TRAIL_PIPS") or 6)     # trail în runner mode

# ─── Entry filters (anti-chop) ──────────────────────────
HTF_FILTER = os.getenv("HTF_FILTER") != "false"                    # nu intra contra trendului mare
HTF_STRICT = os.getenv("HTF_STRICT") == "true"                     # intră DOAR pe direcția HTF (tuning: best forex config)
HTF_TIMEFRAME = os.getenv("HTF_TIMEFRAME") or "1h"
COOLDOWN_AFTER_LOSS_MIN = int(os.getenv("COOLDOWN_AFTER_LOSS_MIN") or 15)

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
