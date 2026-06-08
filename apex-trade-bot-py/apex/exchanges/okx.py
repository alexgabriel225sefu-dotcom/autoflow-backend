"""OKX Spot connector (API v5). HMAC-SHA256 base64 sign + ISO timestamp + passphrase."""
import time
import json
import hmac
import base64
import hashlib
from datetime import datetime, timezone
import requests
from apex import config as cfg

BASE = "https://www.okx.com"
UA = {"User-Agent": "ApexTradeBot/2.0"}
_IV = {"1m": "1m", "3m": "5m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}


def _inst(s):
    return s.replace("USDT", "-USDT")


def _headers(method, path, body=""):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}Z"
    prehash = ts + method.upper() + path + body
    sign = base64.b64encode(hmac.new(cfg.OKX_API_SECRET.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
    return {"OK-ACCESS-KEY": cfg.OKX_API_KEY, "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": cfg.OKX_API_PASSPHRASE, "Content-Type": "application/json"}


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    r = requests.get(f"{BASE}/api/v5/market/ticker", params={"instId": _inst(symbol)}, headers=UA, timeout=8)
    return float(r.json()["data"][0]["last"])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    r = requests.get(f"{BASE}/api/v5/market/candles",
                     params={"instId": _inst(symbol), "bar": _IV.get(interval, "5m"), "limit": limit},
                     headers=UA, timeout=8)
    data = r.json()
    if data.get("code") != "0":
        raise RuntimeError("OKX candles: " + str(data.get("msg")))
    return [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in reversed(data["data"])]


def get_balance(ccy=None):
    ccy = ccy or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    path = f"/api/v5/account/balance?ccy={ccy}"
    r = requests.get(BASE + path, headers=_headers("GET", path), timeout=8)
    data = r.json()
    if data.get("code") != "0":
        raise RuntimeError("OKX balance: " + str(data.get("msg")))
    details = (data["data"][0].get("details") if data.get("data") else None) or []
    det = next((d for d in details if d["ccy"] == ccy), None)
    return float(det["availBal"]) if det else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][OKX] {side} {quantity} {symbol}")
        return {"ordId": "PAPER_" + str(int(time.time() * 1000)), "state": "filled"}
    path = "/api/v5/trade/order"
    body_obj = {"instId": _inst(symbol), "tdMode": "cash", "side": side.lower(),
                "ordType": "market", "sz": str(quantity), "tgtCcy": "base_ccy"}
    body = json.dumps(body_obj, separators=(",", ":"))
    r = requests.post(BASE + path, data=body, headers=_headers("POST", path, body), timeout=10)
    data = r.json()
    if data.get("code") != "0":
        raise RuntimeError(f"OKX order: {data.get('msg')} {data.get('data')}")
    print(f"[LIVE][OKX] {side} {quantity} {symbol} -> {data['data'][0].get('ordId')}")
    return data["data"][0]
