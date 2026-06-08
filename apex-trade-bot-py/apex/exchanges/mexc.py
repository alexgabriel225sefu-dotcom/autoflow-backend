"""MEXC Spot connector (API v3 — Binance-compatible signing)."""
import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests
from apex import config as cfg

BASE = "https://api.mexc.com"
UA = {"User-Agent": "ApexTradeBot/2.0"}
_IV = {"1m": "1m", "3m": "5m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "4h": "4h", "1d": "1d"}


def _sign(params):
    qs = urlencode(params)
    sig = hmac.new(cfg.MEXC_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return f"{qs}&signature={sig}"


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    r = requests.get(f"{BASE}/api/v3/ticker/price", params={"symbol": symbol}, headers=UA, timeout=8)
    return float(r.json()["price"])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    r = requests.get(f"{BASE}/api/v3/klines",
                     params={"symbol": symbol, "interval": _IV.get(interval, "5m"), "limit": limit},
                     headers=UA, timeout=8)
    return [{"time": k[0], "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in r.json()]


def get_balance(asset=None):
    asset = asset or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    r = requests.get(f"{BASE}/api/v3/account?{_sign(params)}",
                     headers={**UA, "X-MEXC-APIKEY": cfg.MEXC_API_KEY}, timeout=10)
    bal = next((b for b in r.json().get("balances", []) if b["asset"] == asset), None)
    return float(bal["free"]) if bal else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][MEXC] {side} {quantity} {symbol}")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000)), "status": "FILLED"}
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": str(quantity),
              "timestamp": int(time.time() * 1000), "recvWindow": 5000}
    r = requests.post(f"{BASE}/api/v3/order?{_sign(params)}",
                      headers={**UA, "X-MEXC-APIKEY": cfg.MEXC_API_KEY}, timeout=10)
    data = r.json()
    print(f"[LIVE][MEXC] {side} {quantity} {symbol} -> {data.get('orderId')}")
    return data
