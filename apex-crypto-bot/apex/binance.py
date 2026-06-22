"""Binance market data + paper exchange.

Public market data (klines, price) needs NO API key — perfect for paper
trading with real prices. Live trading uses signed orders with the user's
own keys (testnet by default for safety).
"""
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

# api.binance.com is geo-blocked from most cloud servers (US/EU). The testnet
# host (testnet.binance.vision) is NOT geo-blocked and serves real-tracking
# market data — this is the same default the proven Node bot uses on Render.
# Override with BINANCE_TESTNET=false only if your region can reach mainnet.
_USE_TESTNET = (os.getenv("BINANCE_TESTNET") or "true").lower() != "false"
_PUBLIC = "https://testnet.binance.vision" if _USE_TESTNET else "https://api.binance.com"
_TESTNET = "https://testnet.binance.vision"

# Binance kline interval mapping (our timeframes → Binance codes)
_INTERVAL = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d",
}

# Small in-process cache so 100 users on BTCUSDT don't hammer the API.
_kline_cache = {}   # (symbol, tf) → {ts, candles}
_price_cache = {}   # symbol → {ts, price}
_KLINE_TTL = 20     # seconds
_PRICE_TTL = 5


def _base(testnet=False):
    return _TESTNET if testnet else _PUBLIC


def get_candles(symbol, timeframe="5m", limit=200):
    """Return list of {open,high,low,close,volume} dicts (oldest→newest)."""
    key = (symbol, timeframe)
    now = time.time()
    cached = _kline_cache.get(key)
    if cached and now - cached["ts"] < _KLINE_TTL:
        return cached["candles"]

    interval = _INTERVAL.get(timeframe, "5m")
    r = requests.get(f"{_PUBLIC}/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit},
                     timeout=10)
    r.raise_for_status()
    rows = r.json()
    candles = [{
        "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
        "close": float(k[4]), "volume": float(k[5]),
        "time": int(k[0]),
    } for k in rows]
    _kline_cache[key] = {"ts": now, "candles": candles}
    return candles


def get_price(symbol):
    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and now - cached["ts"] < _PRICE_TTL:
        return cached["price"]
    r = requests.get(f"{_PUBLIC}/api/v3/ticker/price",
                     params={"symbol": symbol}, timeout=8)
    r.raise_for_status()
    price = float(r.json()["price"])
    _price_cache[symbol] = {"ts": now, "price": price}
    return price


def valid_symbol(symbol):
    """Confirm a trading pair exists on Binance (cheap, cached by price call)."""
    try:
        get_price(symbol)
        return True
    except Exception:
        return False


# ─── Signed (live) trading — user's own keys, testnet by default ──
class LiveExchange:
    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base = _base(testnet)

    def _signed(self, method, path, params):
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.api_key}
        r = requests.request(method, url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_balance(self, asset="USDT"):
        data = self._signed("GET", "/api/v3/account", {})
        for b in data.get("balances", []):
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    def place_order(self, side, qty, symbol):
        data = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": side, "type": "MARKET", "quantity": qty,
        })
        fills = data.get("fills", [])
        avg = (sum(float(f["price"]) * float(f["qty"]) for f in fills) /
               sum(float(f["qty"]) for f in fills)) if fills else None
        return {"avgPrice": avg, "executedQty": float(data.get("executedQty", qty))}
