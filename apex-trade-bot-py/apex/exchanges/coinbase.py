"""Coinbase Advanced Trade connector. ES256 JWT auth (PyJWT).

COINBASE_API_KEY    = key name (organizations/.../apiKeys/...)
COINBASE_API_SECRET = EC private key PEM
Market-data endpoints are public; balance/orders require the JWT key.
"""
import time
import uuid
import secrets
import requests
from apex import config as cfg

HOST = "api.coinbase.com"
BASE = f"https://{HOST}"
UA = {"User-Agent": "ApexTradeBot/2.0"}
_GRAN = {"1m": "ONE_MINUTE", "3m": "FIVE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
         "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "4h": "SIX_HOUR", "1d": "ONE_DAY"}
_GRAN_SEC = {"ONE_MINUTE": 60, "FIVE_MINUTE": 300, "FIFTEEN_MINUTE": 900, "THIRTY_MINUTE": 1800,
             "ONE_HOUR": 3600, "SIX_HOUR": 21600, "ONE_DAY": 86400}


def _product(s):
    return s.replace("USDT", "-USDT")


def _jwt(method, path):
    import jwt  # PyJWT — imported lazily (only needed for live/authed Coinbase calls)
    key = (cfg.COINBASE_API_SECRET or "").replace("\\n", "\n")
    now = int(time.time())
    payload = {"sub": cfg.COINBASE_API_KEY, "iss": "cdp", "nbf": now, "exp": now + 120,
               "uri": f"{method} {HOST}{path}"}
    headers = {"kid": cfg.COINBASE_API_KEY, "nonce": secrets.token_hex(16)}
    return jwt.encode(payload, key, algorithm="ES256", headers=headers)


def _auth(method, path):
    return {"Authorization": f"Bearer {_jwt(method, path)}", **UA}


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    path = f"/api/v3/brokerage/market/products/{_product(symbol)}"
    r = requests.get(BASE + path, headers=UA, timeout=8)
    return float(r.json()["price"])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    g = _GRAN.get(interval, "FIVE_MINUTE")
    n = min(limit, 300)
    end = int(time.time())
    start = end - _GRAN_SEC[g] * n
    path = f"/api/v3/brokerage/market/products/{_product(symbol)}/candles"
    r = requests.get(BASE + path, params={"start": start, "end": end, "granularity": g, "limit": n},
                     headers=UA, timeout=8)
    candles = r.json().get("candles", [])
    return [{"time": int(c["start"]) * 1000, "open": float(c["open"]), "high": float(c["high"]),
             "low": float(c["low"]), "close": float(c["close"]), "volume": float(c["volume"])}
            for c in reversed(candles)]


def get_balance(asset=None):
    asset = asset or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    path = "/api/v3/brokerage/accounts"
    r = requests.get(BASE + path, headers=_auth("GET", path), timeout=8)
    accounts = r.json().get("accounts", [])
    acc = next((a for a in accounts if a["currency"] in (asset, "USD")), None)
    return float(acc["available_balance"]["value"]) if acc else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][COINBASE] {side} {quantity} {symbol}")
        return {"success": True, "order_id": "PAPER_" + str(int(time.time() * 1000))}
    path = "/api/v3/brokerage/orders"
    body = {"client_order_id": str(uuid.uuid4()), "product_id": _product(symbol),
            "side": side.upper(), "order_configuration": {"market_market_ioc": {"base_size": str(quantity)}}}
    headers = {**_auth("POST", path), "Content-Type": "application/json"}
    r = requests.post(BASE + path, json=body, headers=headers, timeout=10)
    data = r.json()
    if data.get("success") is False:
        raise RuntimeError("Coinbase order: " + str(data.get("error_response") or data))
    print(f"[LIVE][COINBASE] {side} {quantity} {symbol} -> {data.get('order_id') or data.get('success_response', {}).get('order_id')}")
    return data
