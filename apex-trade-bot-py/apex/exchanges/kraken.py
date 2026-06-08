"""Kraken Spot connector (REST). HMAC-SHA512 sign with nonce; BTC->XBT pair mapping."""
import time
import hmac
import base64
import hashlib
import urllib.parse
import requests
from apex import config as cfg

BASE = "https://api.kraken.com"
UA = {"User-Agent": "ApexTradeBot/2.0"}
_IV = {"1m": 1, "3m": 5, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def _pair(s):
    return ("XBT" + s[3:]) if s.startswith("BTC") else s


def _sign(path, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _private(method, params=None):
    params = params or {}
    path = f"/0/private/{method}"
    nonce = int(time.time() * 1000000)
    body = {"nonce": nonce, **params}
    headers = {"API-Key": cfg.KRAKEN_API_KEY, "API-Sign": _sign(path, body, cfg.KRAKEN_API_SECRET),
               "Content-Type": "application/x-www-form-urlencoded", **UA}
    r = requests.post(BASE + path, data=body, headers=headers, timeout=10)
    data = r.json()
    if data.get("error"):
        raise RuntimeError("Kraken: " + ", ".join(data["error"]))
    return data["result"]


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    r = requests.get(f"{BASE}/0/public/Ticker", params={"pair": _pair(symbol)}, headers=UA, timeout=8)
    data = r.json()
    if data.get("error"):
        raise RuntimeError("Kraken price: " + ", ".join(data["error"]))
    rec = next(iter(data["result"].values()))
    return float(rec["c"][0])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    r = requests.get(f"{BASE}/0/public/OHLC", params={"pair": _pair(symbol), "interval": _IV.get(interval, 5)},
                     headers=UA, timeout=8)
    data = r.json()
    if data.get("error"):
        raise RuntimeError("Kraken candles: " + ", ".join(data["error"]))
    rows = next(iter(data["result"].values()))
    # [time, open, high, low, close, vwap, volume, count]
    return [{"time": int(k[0]) * 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[6])} for k in rows[-limit:]]


def get_balance(asset=None):
    asset = asset or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    res = _private("Balance")
    key = asset if asset in res else ("ZUSD" if asset == "USD" else asset)
    return float(res[key]) if res.get(key) else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][KRAKEN] {side} {quantity} {symbol}")
        return {"txid": ["PAPER_" + str(int(time.time() * 1000))]}
    res = _private("AddOrder", {"pair": _pair(symbol), "type": side.lower(),
                                "ordertype": "market", "volume": str(quantity)})
    print(f"[LIVE][KRAKEN] {side} {quantity} {symbol} -> {res.get('txid')}")
    return res
