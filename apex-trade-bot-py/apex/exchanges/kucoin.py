"""KuCoin Spot connector (API v2 auth). HMAC-SHA256 base64 sign + hashed passphrase."""
import time
import json
import uuid
import hmac
import base64
import hashlib
import requests
from apex import config as cfg

BASE = "https://api.kucoin.com"
UA = {"User-Agent": "ApexTradeBot/2.0"}
_IV = {"1m": "1min", "3m": "5min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1hour", "4h": "4hour", "1d": "1day"}


def _sym(s):
    return s.replace("USDT", "-USDT")


def _headers(method, endpoint, body=""):
    ts = str(int(time.time() * 1000))
    str_to_sign = ts + method.upper() + endpoint + body
    sign = base64.b64encode(hmac.new(cfg.KUCOIN_API_SECRET.encode(), str_to_sign.encode(), hashlib.sha256).digest()).decode()
    passphrase = base64.b64encode(hmac.new(cfg.KUCOIN_API_SECRET.encode(), cfg.KUCOIN_API_PASSPHRASE.encode(), hashlib.sha256).digest()).decode()
    return {"KC-API-KEY": cfg.KUCOIN_API_KEY, "KC-API-SIGN": sign, "KC-API-TIMESTAMP": ts,
            "KC-API-PASSPHRASE": passphrase, "KC-API-KEY-VERSION": "2", "Content-Type": "application/json", **UA}


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    r = requests.get(f"{BASE}/api/v1/market/orderbook/level1", params={"symbol": _sym(symbol)}, headers=UA, timeout=8)
    return float(r.json()["data"]["price"])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    r = requests.get(f"{BASE}/api/v1/market/candles",
                     params={"type": _IV.get(interval, "5min"), "symbol": _sym(symbol)}, headers=UA, timeout=8)
    data = r.json()
    if data.get("code") != "200000":
        raise RuntimeError("KuCoin candles: " + str(data.get("msg")))
    # newest-first: [time, open, close, high, low, volume, turnover]
    rows = list(reversed(data["data"][:limit]))
    return [{"time": int(k[0]) * 1000, "open": float(k[1]), "close": float(k[2]),
             "high": float(k[3]), "low": float(k[4]), "volume": float(k[5])} for k in rows]


def get_balance(currency=None):
    currency = currency or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    endpoint = f"/api/v1/accounts?currency={currency}&type=trade"
    r = requests.get(BASE + endpoint, headers=_headers("GET", endpoint), timeout=8)
    data = r.json()
    if data.get("code") != "200000":
        raise RuntimeError("KuCoin balance: " + str(data.get("msg")))
    accounts = data.get("data") or []
    return float(accounts[0]["available"]) if accounts else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][KUCOIN] {side} {quantity} {symbol}")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000))}
    endpoint = "/api/v1/orders"
    body_obj = {"clientOid": str(uuid.uuid4()), "side": side.lower(), "symbol": _sym(symbol),
                "type": "market", "size": str(quantity)}
    body = json.dumps(body_obj, separators=(",", ":"))
    r = requests.post(BASE + endpoint, data=body, headers=_headers("POST", endpoint, body), timeout=10)
    data = r.json()
    if data.get("code") != "200000":
        raise RuntimeError("KuCoin order: " + str(data.get("msg")))
    print(f"[LIVE][KUCOIN] {side} {quantity} {symbol} -> {data.get('data', {}).get('orderId')}")
    return data["data"]
