"""Configuration loaded from environment (.env supported)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("true", "1", "yes", "on")


# ─── Broker ─────────────────────────────────────────────
BROKER = (os.getenv("BROKER") or "ctrader").lower()
SUPPORTED_BROKERS = ["ctrader"]

# ─── cTrader Open API (BROKER=ctrader) ──────────────────
# App credentials (per business, once) from openapi.ctrader.com/apps:
CTRADER_CLIENT_ID     = os.getenv("CTRADER_CLIENT_ID", "")
CTRADER_CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET", "")
# Per-client (set via OAuth onboarding / configurator):
CTRADER_ACCESS_TOKEN  = os.getenv("CTRADER_ACCESS_TOKEN", "")
CTRADER_REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN", "")
CTRADER_ACCOUNT_ID    = os.getenv("CTRADER_ACCOUNT_ID", "")   # ctidTraderAccountId
CTRADER_ENV           = (os.getenv("CTRADER_ENV") or "demo").lower()  # demo | live
# OAuth scope: "accounts" (read-only — works before KYC, enough for paper mode)
# or "trading" (real orders — requires the app to be "Active" after KYC review).
CTRADER_SCOPE         = (os.getenv("CTRADER_SCOPE") or "trading").lower()
# Where cTrader redirects after the client authorizes (OAuth callback):
CTRADER_REDIRECT_URI  = os.getenv("CTRADER_REDIRECT_URI", "")

# ─── MetaTrader bridge (BROKER=mt) ──────────────────────
MT_BRIDGE_SECRET = os.getenv("MT_BRIDGE_SECRET", "")

# ─── Twelve Data (BROKER=td) ────────────────────────────
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY", "")

# ─── MetaAPI (BROKER=metaapi) ───────────────────────────
METAAPI_TOKEN      = os.getenv("METAAPI_TOKEN", "")
METAAPI_ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID", "")

# ─── AI providers ───────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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


# ─── Product / branding (one engine serves Forex and Crypto builds) ──
# PRODUCT flips the asset-class defaults: "forex" (24/5, FX universe) or
# "crypto" (24/7, crypto-CFD universe). Each is overridable individually below,
# so a deployment can fine-tune without changing code.
PRODUCT = (os.getenv("PRODUCT") or "forex").lower()
_IS_CRYPTO = PRODUCT == "crypto"
BOT_NAME = os.getenv("BOT_NAME") or ("Apex Crypto Bot" if _IS_CRYPTO else "Apex Forex Bot")
ASSET_EMOJI = os.getenv("ASSET_EMOJI") or ("₿" if _IS_CRYPTO else "💱")
ASSET_NOUN = os.getenv("ASSET_NOUN") or ("crypto" if _IS_CRYPTO else "forex")
# Market hours: crypto trades 24/7, forex 24/5 (closed weekends).
MARKET_24_7 = _truthy(os.getenv("MARKET_24_7") or ("true" if _IS_CRYPTO else "false"))
LICENSE_PRODUCT = os.getenv("LICENSE_PRODUCT") or ("apex-crypto" if _IS_CRYPTO else "apex-forex")
LICENSE_KEY_PREFIX = (os.getenv("LICENSE_KEY_PREFIX") or ("CRPT" if _IS_CRYPTO else "FORX")).upper()

# ─── Trading ────────────────────────────────────────────
SYMBOL = os.getenv("TRADE_SYMBOL") or ("BTCUSD" if _IS_CRYPTO else "EUR_USD")
TIMEFRAME = _scalp("TIMEFRAME", "1m", "5m")
CANDLES = 200

# ─── Scanner ────────────────────────────────────────────
_DEFAULT_SCAN = "BTCUSD,ETHUSD,SOLUSD" if _IS_CRYPTO else "NZD_USD"
SCAN_SYMBOLS = (os.getenv("SCAN_SYMBOLS") or _DEFAULT_SCAN).split(",")  # tuning r9: NZD-only (EUR/AUD/JPY/CAD all negative; NZD edge is signal-specific)
MULTI_SYMBOL = os.getenv("MULTI_SYMBOL") != "false"

# Curated liquid universe the Auto-Pilot scans (comma-separated env override).
# FX majors + gold are on every cTrader broker; crypto CFDs are the liquid
# majors. Non-FX candidates are validated per account before use.
_DEFAULT_UNIVERSE = ("BTCUSD,ETHUSD,SOLUSD,XRPUSD,LTCUSD,ADAUSD,DOGEUSD,DOTUSD,"
                     "LINKUSD,BCHUSD" if _IS_CRYPTO else
                     "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,"
                     "XAUUSD,US30,NAS100,US500,GER40")
AUTOPILOT_UNIVERSE = [s.strip().upper() for s in
                      (os.getenv("AUTOPILOT_UNIVERSE") or _DEFAULT_UNIVERSE).split(",") if s.strip()]

# Symbols that belong to the OTHER product. Used to self-heal a user record that
# picked up cross-product symbols back when crypto & forex shared one Redis
# namespace (e.g. a forex account trading SOLUSD). Gold (XAUUSD) is shared and
# never blocked. Compared normalised (no separators, upper-case).
_CRYPTO_ONLY = {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "LTCUSD", "ADAUSD",
                "DOGEUSD", "DOTUSD", "LINKUSD", "BCHUSD"}
_FOREX_ONLY = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
               "NZDUSD", "US30", "NAS100", "US500", "GER40", "XAUUSD"}
CROSS_PRODUCT_BLOCK = _FOREX_ONLY if _IS_CRYPTO else _CRYPTO_ONLY

# ─── Risk ───────────────────────────────────────────────
RISK_PER_TRADE = float(_scalp("RISK_PER_TRADE", 0.01, 0.005))  # scalp: 1% (controlled, not aggressive) · swing: 0.5%
STOP_LOSS_PIPS = float(_scalp("STOP_LOSS_PIPS", 15, 25))        # scalp: 15p · swing: 25p — room to breathe past spread+noise
TAKE_PROFIT_PIPS = float(_scalp("TAKE_PROFIT_PIPS", 30, 50))   # scalp: 30p (RR 1:2) · swing: 50p (RR 2:1)
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 68)
LEVERAGE = float(os.getenv("LEVERAGE") or 30)
MARGIN_CAP = float(os.getenv("MARGIN_CAP") or 0.5)             # use ≤50% of available margin
MAX_SPREAD_PIPS = float(_scalp("MAX_SPREAD_PIPS", 1.2, 3.0))   # scalp: strict 1.2p — wide spread kills tight targets
# Crypto's pip conventions make spreads huge in pip terms (SOL pip=$0.01 → a
# $0.30 spread = 30 pips), so a fixed pip limit blocks every crypto trade. For
# crypto use a %-of-price spread limit instead: normal crypto CFD spread is
# ~0.05-0.3%, and brokers blow it out to 1-3% on weekends (correctly skipped).
# 0 = disabled (forex keeps the pip limit).
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT") or (0.35 if _IS_CRYPTO else 0))
# Flash-crash guard: an FX major moving >1.2% in one M5 candle is a violent
# spike; crypto routinely moves that much normally, so raise the bar for crypto.
FLASH_SPIKE_PCT = float(os.getenv("FLASH_SPIKE_PCT") or (0.05 if _IS_CRYPTO else 0.012))

# ─── Trailing stop ──────────────────────────────────────
TRAILING_STOP = os.getenv("TRAILING_STOP") != "false"  # ON by default — let winners run, exit on reversal
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
PAPER_TRADING = _truthy(os.getenv("PAPER_TRADING") or "false")
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE") or 1000)

# ─── License ────────────────────────────────────────────
LICENSE_KEY = os.getenv("LICENSE_KEY", "")
LICENSE_SERVER = os.getenv("LICENSE_SERVER") or "https://aicashsystem.space"
