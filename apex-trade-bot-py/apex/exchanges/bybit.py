"""Bybit Spot connector (API v5) with public-data fallback to Binance/OKX."""
import time
import json
import hmac
import hashlib
import requests
from apex import config as cfg

BASE = "https://api-testnet.bybit.com" if cfg.BYBIT_TESTNET else "https://api.bybit.com"
RECV = "5000"
UA = {"User-Agent": "ApexTradeBot/2.0"}
_IV = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}


def _sign(payload):
    return hmac.new(cfg.BYBIT_API_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _headers_get(params):
    ts = str(int(time.time() * 1000))
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sig = _sign(ts + cfg.BYBIT_API_KEY + RECV + query)
    return {"X-BAPI-API-KEY": cfg.BYBIT_API_KEY, "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-SIGN": sig, "X-BAPI-RECV-WINDOW": RECV}


def _headers_post(body_str):
    ts = str(int(time.time() * 1000))
    sig = _sign(ts + cfg.BYBIT_API_KEY + RECV + body_str)
    return {"X-BAPI-API-KEY": cfg.BYBIT_API_KEY, "X-BAPI-TIMESTAMP": ts, "X-BAPI-SIGN": sig,
            "X-BAPI-RECV-WINDOW": RECV, "Content-Type": "application/json"}


def get_price(symbol=None):
    symbol = symbol or cfg.SYMBOL
    try:
        r = requests.get(f"{BASE}/v5/market/tickers", params={"category": "spot", "symbol": symbol},
                         headers=UA, timeout=6)
        p = r.json().get("result", {}).get("list", [{}])[0].get("lastPrice")
        if p:
            return float(p)
    except Exception:
        pass
    r = requests.get("https://www.okx.com/api/v5/market/ticker",
                     params={"instId": symbol.replace("USDT", "-USDT")}, headers=UA, timeout=6)
    return float(r.json()["data"][0]["last"])


def get_candles(symbol=None, interval=None, limit=None):
    symbol = symbol or cfg.SYMBOL
    interval = interval or cfg.TIMEFRAME
    limit = limit or cfg.CANDLES
    r = requests.get(f"{BASE}/v5/market/kline",
                     params={"category": "spot", "symbol": symbol, "interval": _IV.get(interval, "5"), "limit": limit},
                     headers=UA, timeout=8)
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError("Bybit: " + str(data.get("retMsg")))
    return [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in reversed(data["result"]["list"])]


def get_balance(coin=None):
    coin = coin or cfg.QUOTE_ASSET
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    params = {"accountType": "UNIFIED", "coin": coin}
    r = requests.get(f"{BASE}/v5/account/wallet-balance", params=params,
                     headers=_headers_get(params), timeout=8)
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError("Bybit balance: " + str(data.get("retMsg")))
    lst = data["result"]["list"][0].get("coin", [])
    bal = next((c for c in lst if c["coin"] == coin), None)
    return float(bal["availableToWithdraw"]) if bal and bal.get("availableToWithdraw") else 0.0


def place_order(side, quantity, symbol=None):
    symbol = symbol or cfg.SYMBOL
    if cfg.PAPER_TRADING:
        print(f"[PAPER][BYBIT] {side} {quantity} {symbol}")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000)), "orderStatus": "Filled"}
    body = {"category": "spot", "symbol": symbol, "side": "Buy" if side == "BUY" else "Sell",
            "orderType": "Market", "qty": str(quantity)}
    body_str = json.dumps(body, separators=(",", ":"))
    r = requests.post(f"{BASE}/v5/order/create", data=body_str, headers=_headers_post(body_str), timeout=10)
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit order failed ({data.get('retCode')}): {data.get('retMsg')}")
    print(f"[LIVE][BYBIT] {side} {quantity} {symbol} -> {data.get('result', {}).get('orderId')}")
    return data["result"]
