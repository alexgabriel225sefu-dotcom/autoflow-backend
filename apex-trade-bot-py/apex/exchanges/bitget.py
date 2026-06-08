"""Bitget Spot connector (API v2). HMAC-SHA256 base64 sign + ms timestamp + passphrase."""
import time
import json
import hmac
import base64
import hashlib
import requests
from apex import config as cfg

BASE = "https://api.bitget.com"
UA = {"User-Agent": "ApexTradeBot/2.0", "locale": "en-US"}
_IV = {"1m": "1min", "3m": "5min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day"}


def _headers(method, request_path, body=""):
    ts = str(int(time.time() * 1000))
    prehash = ts + method.upper() + request_path + body
    sign = base64.b64encode(hmac.new(cfg.BITGET_API_SECRET.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
    return {"ACCESS-KEY": cfg.BITGET_API_KEY, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": cfg.BITGET_API_PASSPHRASE, "Content-Type": "application/json", **UA}


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    r = requests.get(f"{BASE}/api/v2/spot/market/tickers", params={"symbol": symbol}, headers=UA, timeout=8)
    return float(r.json()["data"][0]["lastPr"])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    r = requests.get(f"{BASE}/api/v2/spot/market/candles",
                     params={"symbol": symbol, "granularity": _IV.get(interval, "5min"), "limit": limit},
                     headers=UA, timeout=8)
    data = r.json()
    if data.get("code") != "00000":
        raise RuntimeError("Bitget candles: " + str(data.get("msg")))
    return [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in data["data"]]


def get_balance(coin=None):
    coin = coin or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    path = f"/api/v2/spot/account/assets?coin={coin}"
    r = requests.get(BASE + path, headers=_headers("GET", path), timeout=8)
    data = r.json()
    if data.get("code") != "00000":
        raise RuntimeError("Bitget balance: " + str(data.get("msg")))
    a = data["data"][0] if data.get("data") else None
    return float(a["available"]) if a else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][BITGET] {side} {quantity} {symbol}")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000))}
    path = "/api/v2/spot/trade/place-order"
    body_obj = {"symbol": symbol, "side": side.lower(), "orderType": "market", "force": "gtc", "size": str(quantity)}
    body = json.dumps(body_obj, separators=(",", ":"))
    r = requests.post(BASE + path, data=body, headers=_headers("POST", path, body), timeout=10)
    data = r.json()
    if data.get("code") != "00000":
        raise RuntimeError("Bitget order: " + str(data.get("msg")))
    print(f"[LIVE][BITGET] {side} {quantity} {symbol} -> {data.get('data', {}).get('orderId')}")
    return data["data"]
