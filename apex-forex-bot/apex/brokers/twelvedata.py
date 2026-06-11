"""Twelve Data broker connector — free forex API, paper trading only.

No broker account required. Sign up at twelvedata.com for a free key.
Free tier: 800 calls/day, 8 calls/minute — plenty for 5-min intervals.

Set in .env:
    BROKER=td
    TWELVE_DATA_KEY=your_api_key
    PAPER_TRADING=true   (required — TD does not execute real orders)
"""
import time
import threading
import requests
from apex import config as cfg

BASE_URL = "https://api.twelvedata.com"
SPREAD_PIPS = 1.0      # simulated bid/ask spread
PRICE_TTL = 10         # seconds before re-fetching price
CANDLE_TTL = 60        # seconds before re-fetching candles

_lock = threading.Lock()
_price_cache: dict = {}   # symbol -> {bid, ask, time}
_candle_cache: dict = {}  # symbol -> {data, time}

_INTERVAL_MAP = {
    "1m": "1min",  "1min": "1min",
    "5m": "5min",  "5min": "5min",
    "15m": "15min", "15min": "15min",
    "30m": "30min", "30min": "30min",
    "1h": "1h",    "4h": "4h",
    "1d": "1day",  "D": "1day",
}


def _to_td_symbol(symbol: str) -> str:
    return symbol.replace("_", "/").upper()


def _pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def _fetch_price(symbol: str) -> dict:
    """Return cached or freshly fetched {bid, ask, time}."""
    now = time.time()
    with _lock:
        c = _price_cache.get(symbol)
    if c and now - c["time"] < PRICE_TTL:
        return c

    params = {"symbol": _to_td_symbol(symbol), "apikey": cfg.TWELVE_DATA_KEY}
    r = requests.get(f"{BASE_URL}/price", params=params, timeout=10)
    data = r.json()
    if "price" not in data:
        with _lock:
            c = _price_cache.get(symbol)
        if c:
            return c
        raise RuntimeError(f"Twelve Data: {data.get('message', data)}")

    mid = float(data["price"])
    spread = _pip_size(symbol) * SPREAD_PIPS
    result = {"bid": round(mid - spread / 2, 6),
              "ask": round(mid + spread / 2, 6),
              "time": now}
    with _lock:
        _price_cache[symbol] = result
    return result


# ─── Broker interface ─────────────────────────────────────

def is_connected() -> bool:
    if not cfg.TWELVE_DATA_KEY:
        return False
    try:
        r = requests.get(f"{BASE_URL}/price",
                         params={"symbol": "EUR/USD", "apikey": cfg.TWELVE_DATA_KEY},
                         timeout=5)
        return r.status_code == 200 and "price" in r.json()
    except Exception:
        return False


def get_bid_ask(instrument=None):
    data = _fetch_price(instrument or cfg.SYMBOL)
    return data["bid"], data["ask"]


def get_price(instrument=None):
    bid, ask = get_bid_ask(instrument)
    return round((bid + ask) / 2, 6)


def get_candles(instrument=None, interval=None, limit=None):
    symbol = instrument or cfg.SYMBOL
    td_sym = _to_td_symbol(symbol)
    td_interval = _INTERVAL_MAP.get(interval or cfg.TIMEFRAME, "5min")
    count = limit or cfg.CANDLES

    now = time.time()
    with _lock:
        c = _candle_cache.get(symbol)
    if c and now - c["time"] < CANDLE_TTL:
        return c["data"][-count:]

    params = {
        "symbol": td_sym,
        "interval": td_interval,
        "outputsize": min(count + 10, 500),
        "apikey": cfg.TWELVE_DATA_KEY,
        "order": "ASC",
    }
    r = requests.get(f"{BASE_URL}/time_series", params=params, timeout=15)
    data = r.json()
    if "values" not in data:
        with _lock:
            c = _candle_cache.get(symbol)
        if c:
            return c["data"][-count:]
        raise RuntimeError(f"Twelve Data candles: {data.get('message', data)}")

    candles = []
    for row in data["values"]:
        try:
            ts = int(time.mktime(time.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")))
            candles.append({
                "time": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0),
            })
        except (KeyError, ValueError):
            continue

    with _lock:
        _candle_cache[symbol] = {"data": candles, "time": now}
    return candles[-count:]


def get_balance():
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    raise RuntimeError("Twelve Data broker only supports paper trading (PAPER_TRADING=true).")


def place_order(side, units, instrument=None, sl=None, tp=None):
    if not cfg.PAPER_TRADING:
        raise RuntimeError("Twelve Data broker only supports paper trading (PAPER_TRADING=true).")
    order_id = f"TD_PAPER_{int(time.time() * 1000)}"
    print(f"[PAPER][TD] {side} {units} {instrument or cfg.SYMBOL} (simulated)")
    return {"orderId": order_id, "status": "FILLED"}


def close_position(instrument=None):
    return place_order("CLOSE", 0, instrument)
