"""Yahoo Finance broker connector — completely free, no API key needed.

Uses yfinance to fetch real OHLCV forex data. Paper trading only.

Set in Render env vars:
    BROKER=yahoo
    PAPER_TRADING=true
"""
import time
import threading

try:
    import yfinance as yf
except ImportError:
    yf = None

from apex import config as cfg

_lock = threading.Lock()
_price_cache: dict = {}
_candle_cache: dict = {}
_PRICE_TTL = 10
_CANDLE_TTL = 60

_INTERVAL_MAP = {
    "1m": "1m", "1min": "1m",
    "5m": "5m", "5min": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",   # Yahoo doesn't have 4h — use 1h
    "1d": "1d",
}

# How many days of history to fetch per interval
_PERIOD_MAP = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "1d": "730d",
}


def _to_yahoo_symbol(symbol: str) -> str:
    """EUR_USD → EURUSD=X"""
    return symbol.replace("_", "") + "=X"


def _pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def _ensure_yfinance():
    if yf is None:
        raise RuntimeError("yfinance not installed. Add 'yfinance' to requirements.txt.")


def _fetch_price(symbol: str) -> float:
    _ensure_yfinance()
    now = time.time()
    with _lock:
        c = _price_cache.get(symbol)
    if c and now - c["ts"] < _PRICE_TTL:
        return c["price"]

    ticker = yf.Ticker(_to_yahoo_symbol(symbol))
    info = ticker.fast_info
    price = float(getattr(info, "last_price", 0) or getattr(info, "regularMarketPrice", 0) or 0)
    if not price:
        # fallback: latest close from 1-day history
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])

    with _lock:
        _price_cache[symbol] = {"price": price, "ts": now}
    return price


# ── Broker interface ─────────────────────────────────────────────────────────

def is_connected() -> bool:
    try:
        _ensure_yfinance()
        p = _fetch_price(cfg.SYMBOL)
        return p > 0
    except Exception:
        return False


def get_price(instrument=None) -> float:
    return _fetch_price(instrument or cfg.SYMBOL)


def get_bid_ask(instrument=None):
    price = get_price(instrument)
    pip = _pip_size(instrument or cfg.SYMBOL)
    spread = pip * 1.0  # simulate 1-pip spread
    return round(price - spread / 2, 6), round(price + spread / 2, 6)


def get_candles(instrument=None, interval=None, limit=None):
    _ensure_yfinance()
    symbol = instrument or cfg.SYMBOL
    tf = interval or cfg.TIMEFRAME
    yf_interval = _INTERVAL_MAP.get(tf, "5m")
    period = _PERIOD_MAP.get(yf_interval, "60d")
    count = limit or cfg.CANDLES
    key = (symbol, yf_interval)

    now = time.time()
    with _lock:
        c = _candle_cache.get(key)
    if c and now - c["ts"] < _CANDLE_TTL:
        return c["data"][-count:]

    ticker = yf.Ticker(_to_yahoo_symbol(symbol))
    hist = ticker.history(period=period, interval=yf_interval)
    if hist.empty:
        with _lock:
            c = _candle_cache.get(key)
        return (c["data"][-count:] if c else [])

    candles = []
    for ts, row in hist.iterrows():
        try:
            candles.append({
                "time": int(ts.timestamp()),
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  float(row["Close"]),
                "volume": float(row.get("Volume") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue

    with _lock:
        _candle_cache[key] = {"data": candles, "ts": now}
    return candles[-count:]


def get_balance() -> float:
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    raise RuntimeError("Yahoo Finance broker supports paper trading only.")


def place_order(side, units, instrument=None, sl=None, tp=None):
    if not cfg.PAPER_TRADING:
        raise RuntimeError("Yahoo Finance broker supports paper trading only.")
    print(f"[PAPER][Yahoo] {side} {units} {instrument or cfg.SYMBOL}")
    return {"orderId": f"YF_PAPER_{int(time.time()*1000)}", "status": "FILLED"}


def close_position(instrument=None):
    return place_order("CLOSE", 0, instrument)
