"""Binance Spot connector (API v3) with OKX public-data fallback."""
import os
import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests
from apex import config as cfg

# Default to testnet unless BINANCE_TESTNET is explicitly 'false'
_TESTNET = (os.getenv("BINANCE_TESTNET") or "").strip().lower() != "false"
BASE = "https://testnet.binance.vision/api/v3" if _TESTNET else "https://api.binance.com/api/v3"
UA = {"User-Agent": "ApexTradeBot/2.0"}


def _sign(params):
    qs = urlencode(params)
    sig = hmac.new(cfg.BINANCE_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return f"{qs}&signature={sig}"


def _okx_price(symbol):
    r = requests.get("https://www.okx.com/api/v5/market/ticker",
                     params={"instId": symbol.replace("USDT", "-USDT")}, headers=UA, timeout=6)
    return float(r.json()["data"][0]["last"])


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    try:
        r = requests.get(f"{BASE}/ticker/price", params={"symbol": symbol}, headers=UA, timeout=8)
        return float(r.json()["price"])
    except Exception as e:
        print(f"[DATA] Binance price blocked ({e}) -> OKX")
        return _okx_price(symbol)


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    try:
        r = requests.get(f"{BASE}/klines", params={"symbol": symbol, "interval": interval, "limit": limit},
                         headers=UA, timeout=8)
        return [{"time": k[0], "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in r.json()]
    except Exception as e:
        print(f"[DATA] Binance klines blocked ({e}) -> OKX")
        okx_sym = symbol.replace("USDT", "-USDT")
        r = requests.get("https://www.okx.com/api/v5/market/candles",
                         params={"instId": okx_sym, "bar": interval, "limit": limit}, headers=UA, timeout=8)
        data = r.json()
        return [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                for k in reversed(data["data"])]


def get_balance(asset=None):
    asset = asset or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    params = {"timestamp": int(time.time() * 1000)}
    r = requests.get(f"{BASE}/account?{_sign(params)}",
                     headers={**UA, "X-MBX-APIKEY": cfg.BINANCE_API_KEY}, timeout=10)
    bal = next((b for b in r.json().get("balances", []) if b["asset"] == asset), None)
    return float(bal["free"]) if bal else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][BINANCE] {side} {quantity} {symbol}")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000)), "status": "FILLED"}
    params = {"symbol": symbol, "side": side, "type": "MARKET",
              "quantity": f"{quantity:.0f}", "timestamp": int(time.time() * 1000)}
    r = requests.post(f"{BASE}/order?{_sign(params)}",
                      headers={**UA, "X-MBX-APIKEY": cfg.BINANCE_API_KEY}, timeout=10)
    data = r.json()
    print(f"[LIVE][BINANCE] {side} {quantity} {symbol} -> {data.get('orderId')}")
    return data
