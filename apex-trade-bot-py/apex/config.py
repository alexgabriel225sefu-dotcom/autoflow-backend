"""Configuration loaded from environment (.env supported). Mirrors the JS config."""
import os
from dotenv import load_dotenv

load_dotenv()


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("true", "1", "yes", "on")


# ─── Exchange ────────────────────────────────────────────
EXCHANGE = (os.getenv("EXCHANGE") or "binance").lower()
SUPPORTED_EXCHANGES = ["binance", "bybit", "okx", "kraken", "kucoin", "coinbase", "bitget", "mexc"]

# ─── Bybit ──────────────────────────────────────────────
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET = _truthy(os.getenv("BYBIT_TESTNET"))

# ─── Binance ────────────────────────────────────────────
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = _truthy(os.getenv("BINANCE_TESTNET"))

# ─── OKX ────────────────────────────────────────────────
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_API_SECRET = os.getenv("OKX_API_SECRET", "")
OKX_API_PASSPHRASE = os.getenv("OKX_API_PASSPHRASE", "")

# ─── Kraken ─────────────────────────────────────────────
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

# ─── KuCoin ─────────────────────────────────────────────
KUCOIN_API_KEY = os.getenv("KUCOIN_API_KEY", "")
KUCOIN_API_SECRET = os.getenv("KUCOIN_API_SECRET", "")
KUCOIN_API_PASSPHRASE = os.getenv("KUCOIN_API_PASSPHRASE", "")

# ─── Coinbase (Advanced Trade, JWT key) ─────────────────
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY", "")        # key name: organizations/.../apiKeys/...
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET", "")  # EC private key PEM

# ─── Bitget ─────────────────────────────────────────────
BITGET_API_KEY = os.getenv("BITGET_API_KEY", "")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET", "")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE", "")

# ─── MEXC ───────────────────────────────────────────────
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

# ─── AI providers ───────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ─── Telegram ───────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

# ─── Trading ────────────────────────────────────────────
SYMBOL = os.getenv("TRADE_SYMBOL", "SOLUSDT")
QUOTE_ASSET = os.getenv("QUOTE_ASSET", "USDT")
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
CANDLES = 200

# ─── Scanner ────────────────────────────────────────────
SCAN_SYMBOLS = (os.getenv("SCAN_SYMBOLS") or "SOLUSDT,XRPUSDT,DOGEUSDT,TRXUSDT,ADAUSDT").split(",")
MULTI_SYMBOL = os.getenv("MULTI_SYMBOL") != "false"

# ─── Risk ───────────────────────────────────────────────
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE") or 0.20)
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT") or 0.008)
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT") or 0.016)
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 62)

# ─── Trailing stop ──────────────────────────────────────
TRAILING_STOP = os.getenv("TRAILING_STOP") != "false"
TRAILING_STOP_DIST = float(os.getenv("TRAILING_STOP_DIST") or 0.01)

# ─── ATR-based SL/TP ────────────────────────────────────
ATR_BASED_SL = os.getenv("ATR_BASED_SL") == "true"
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT") or 1.5)
ATR_TP_MULT = float(os.getenv("ATR_TP_MULT") or 3.0)

# ─── Misc ───────────────────────────────────────────────
COMPOUND = os.getenv("COMPOUND") != "false"
LOOP_INTERVAL_MS = int(os.getenv("LOOP_INTERVAL_MS") or 5 * 60 * 1000)

# ─── Paper trading ──────────────────────────────────────
PAPER_TRADING = _truthy(os.getenv("PAPER_TRADING"))
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE") or 100)

# Legacy testnet flag
TESTNET = BYBIT_TESTNET

# ─── License ────────────────────────────────────────────
LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SERVER = os.getenv("LICENSE_SERVER") or "https://aicashsystem.space"
