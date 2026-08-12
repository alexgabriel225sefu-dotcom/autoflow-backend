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
               "NZDUSD", "US30", "NAS100", "US500", "GER40"}
CROSS_PRODUCT_BLOCK = _FOREX_ONLY if _IS_CRYPTO else _CRYPTO_ONLY

# ─── Risk ───────────────────────────────────────────────
RISK_PER_TRADE = float(_scalp("RISK_PER_TRADE", 0.025, 0.0125))  # scalp: 2.5% · swing: 1.25% (was 1%/0.5%)
STOP_LOSS_PIPS = float(_scalp("STOP_LOSS_PIPS", 15, 25))        # scalp: 15p · swing: 25p — room to breathe past spread+noise
TAKE_PROFIT_PIPS = float(_scalp("TAKE_PROFIT_PIPS", 30, 50))   # scalp: 30p (RR 1:2) · swing: 50p (RR 2:1)
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE") or 68)

# ─── EV gate (V2 decision core — see apex/ev.py) ─────────
# The signal engine's "confidence" is an indicator count (52 + 8×score), not a
# probability, and at the default MIN_CONFIDENCE=68 it gates nothing: the
# lowest confidence any firing signal can carry is 71. The EV engine replaces
# that with a probability measured from the account's own closed trades, and
# refuses entries whose expected value is negative after real costs.
#
#   off     — engine never runs (pre-V2 behaviour)
#   shadow  — engine runs and logs its verdict, but never blocks a trade.
#             Use this first: it shows what WOULD have been filtered, with no
#             risk to a live account.
#   enforce — engine can veto entries.
EV_GATE_MODE = (os.getenv("EV_GATE_MODE") or "shadow").strip().lower()
# The win-rate dial. Higher = fewer trades, a higher share of them winners.
# Set too high the bot simply stops trading, so raise it in small steps and
# read the shadow log before enforcing.
EV_MIN_PROBABILITY = float(os.getenv("EV_MIN_PROBABILITY") or 0.55)
# Minimum labelled closed trades before calibration is trusted at all. Below
# this the engine reports NO_PROBABILITY and (in enforce mode) stands aside.
EV_MIN_SAMPLES = int(os.getenv("EV_MIN_SAMPLES") or 30)

# Smallest profit, as a multiple of the trade's own risk, that a strategy is
# allowed to take voluntarily. Measured on the live account: winners were being
# closed at ~1 pip by mean_reversion's midline rule while losers ran the full
# 15-pip stop — a realised 1:5 that needs an 83% win rate to break even. This
# is the floor that stops it. Only ever blocks exits that are IN PROFIT; a
# strategy bailing out of a losing trade is never held. 0 disables.
MIN_EXIT_R = float(os.getenv("MIN_EXIT_R") or 1.0)

# The other half of the same problem: MIN_EXIT_R stops winners being cut short,
# these let them RUN. Once a trade is this many R in profit and the trend still
# agrees with it, a strategy's discretionary exit is converted into a stop
# ratchet instead of a close — the bot keeps RIDE_LOCK of the open profit and
# lets the market end the trade. Requires TRAILING_STOP; if the stop cannot be
# moved the trade is closed as before, never held unprotected.
RIDE_AT_R = float(os.getenv("RIDE_AT_R") or 2.0)
RIDE_LOCK = float(os.getenv("RIDE_LOCK") or 0.6)

# ─── Permanent Market Sentinel (see apex/sentinel.py) ────
# A persistent, EXPIRING view of each symbol, so "what the AI thinks about
# EURUSD" outlives the single function call that produced it — and so a stale
# opinion is never acted on. Same three modes as the EV gate, same reason:
#   off     — no sentinel state is kept
#   shadow  — state is published and the gate's verdict logged, never blocking
#   enforce — an entry the Sentinel refuses does not go through
SENTINEL_MODE = (os.getenv("SENTINEL_MODE") or "shadow").strip().lower()
# Confidence is 0-1 here, not the engine's 0-100 score. None = not enforced.
SENTINEL_MIN_CONFIDENCE = float(os.getenv("SENTINEL_MIN_CONFIDENCE") or 0.0) or None
# Signal lifetime. 0 = derive it from the timeframe (one candle), which is what
# you want: a fixed 60s TTL on a 15m chart leaves every signal stale on arrival
# and the bot stops trading entirely.
SENTINEL_TTL_S = int(os.getenv("SENTINEL_TTL_S") or 0)

# Show the AI the actual chart, not just indicator values. Structure — where
# price keeps failing, whether a level was tested once or five times, whether
# the approach looks impulsive or exhausted — does not survive being flattened
# into a list of numbers. Costs image tokens on every candidate entry (never on
# an idle tick, the AI is only consulted on a BUY/SELL candidate), so it is
# opt-in. Falls back to text-only if rendering fails or the fallback provider
# is used.
AI_VISION = _truthy(os.getenv("AI_VISION"))

# Derive the stop and target from the structure the signal was built on,
# instead of a fixed pip count that has nothing to do with it. On M1 the
# fibonacci swing is a median ~17 pips wide, so a flat 15-pip stop is 0.9x the
# entire swing and a 30-pip target is 1.8x it — while the setup's own objective
# (price returning to the swing extreme) sits a median 6 pips away. The trade
# is asked to do something the signal never predicted.
#
# On: stop goes a buffer beyond the swing origin, target to the swing extreme,
# and the RR that comes out is whatever the structure actually offers. Off: the
# fixed sl_pips/tp_pips behaviour. Reversible, because it changes both trade
# frequency and average R.
STRUCTURAL_STOPS = _truthy(os.getenv("STRUCTURAL_STOPS"))
# Never accept a structural trade worse than this — a level sitting right next
# to its target offers no room and should simply be skipped.
STRUCTURAL_MIN_RR = float(os.getenv("STRUCTURAL_MIN_RR") or 1.3)

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
# Signing secret for the Stripe webhook endpoint registered against THIS bot's
# own /api/stripe/webhook (separate from the main site's /stripe-webhook —
# each registered endpoint in the Stripe Dashboard gets its own secret).
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# ─── Storage encryption ─────────────────────────────────
# Fernet key (Fernet.generate_key()) used to encrypt broker tokens and
# user-supplied AI keys at rest in Redis/Upstash. If unset, those fields are
# stored in plaintext (logged loudly at startup) — set this in production.
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
