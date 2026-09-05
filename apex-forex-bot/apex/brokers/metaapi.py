"""MetaAPI broker connector — connect any MT4/MT5 account via cloud API.

Free tier: 2 MT accounts, real-time data, live + paper trading.
Sign up at metaapi.cloud, connect your MT5 account, get your token.

Set in Render env vars:
    BROKER=metaapi
    METAAPI_TOKEN=your_token_from_metaapi.cloud
    METAAPI_ACCOUNT_ID=your_account_id_from_metaapi.cloud
    PAPER_TRADING=true    (or false for real orders)
"""
import os
import time
import threading
import requests
from apex import config as cfg

# This module is NOT reachable in this build. config._resolve_broker() refuses
# BROKER=metaapi at import and apex.brokers._REGISTRY holds cTrader alone, so
# get_broker() cannot load it either. It is kept because it has tests.
#
# Its setting lives here rather than in apex/config.py: a credential declared
# in the production config reads like one the product still uses, and this one
# configures an execution path that cannot run.
AUTH_TOKEN = os.getenv("METAAPI_TOKEN", "")


# MetaAPI REST endpoints (London region — lowest latency for EU accounts)
_BASE = "https://mt-client-api-v1.london.agiliumtrade.ai"
_HEADERS = lambda: {
    "auth-token": AUTH_TOKEN,
    "Content-Type": "application/json",
}

_TIMEFRAME_MAP = {
    "1m": "1m", "1min": "1m",
    "5m": "5m", "5min": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

_lock = threading.Lock()
_price_cache: dict = {}   # symbol -> {bid, ask, ts}
_candle_cache: dict = {}  # (symbol, tf) -> {data, ts}
_PRICE_TTL = 5
_CANDLE_TTL = 30

# ── Helpers ──────────────────────────────────────────────────────────────────

def _account_id():
    aid = getattr(cfg, "METAAPI_ACCOUNT_ID", "") or ""
    if not aid:
        raise RuntimeError("METAAPI_ACCOUNT_ID not set. Get it from metaapi.cloud dashboard.")
    return aid


def _get(path, params=None, timeout=10):
    r = requests.get(f"{_BASE}{path}", headers=_HEADERS(), params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(path, body, timeout=10):
    r = requests.post(f"{_BASE}{path}", headers=_HEADERS(), json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _to_ma_symbol(symbol: str) -> str:
    """EUR_USD → EURUSD (MetaAPI uses no underscore)."""
    return symbol.replace("_", "").upper()


def _pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol.upper() else 0.0001


# ── Broker interface ─────────────────────────────────────────────────────────

def is_connected() -> bool:
    if not getattr(cfg, "METAAPI_TOKEN", "") or not getattr(cfg, "METAAPI_ACCOUNT_ID", ""):
        return False
    try:
        data = _get(f"/users/current/accounts/{_account_id()}")
        return data.get("state") in ("DEPLOYED", "DEPLOYING")
    except Exception:
        return False


def get_bid_ask(instrument=None):
    symbol = _to_ma_symbol(instrument or cfg.SYMBOL)
    now = time.time()
    with _lock:
        c = _price_cache.get(symbol)
    if c and now - c["ts"] < _PRICE_TTL:
        return c["bid"], c["ask"]

    data = _get(f"/users/current/accounts/{_account_id()}/symbols/{symbol}/current-price",
                params={"keepSubscription": "false"})
    bid = float(data.get("bid") or data.get("ask") or 0)
    ask = float(data.get("ask") or data.get("bid") or 0)
    if not bid:
        pip = _pip_size(symbol)
        mid = float(data.get("price") or 0)
        bid, ask = mid - pip / 2, mid + pip / 2

    with _lock:
        _price_cache[symbol] = {"bid": bid, "ask": ask, "ts": now}
    return bid, ask


def get_price(instrument=None):
    bid, ask = get_bid_ask(instrument)
    return round((bid + ask) / 2, 6)


def get_candles(instrument=None, interval=None, limit=None):
    symbol = _to_ma_symbol(instrument or cfg.SYMBOL)
    tf = _TIMEFRAME_MAP.get(interval or cfg.TIMEFRAME, "5m")
    count = limit or cfg.CANDLES
    key = (symbol, tf)
    now = time.time()

    with _lock:
        c = _candle_cache.get(key)
    if c and now - c["ts"] < _CANDLE_TTL:
        return c["data"][-count:]

    data = _get(
        f"/users/current/accounts/{_account_id()}/historical-market-data/symbols/{symbol}/timeframes/{tf}/candles",
        params={"limit": min(count + 10, 1000)},
    )
    candles = []
    for row in (data if isinstance(data, list) else data.get("candles", [])):
        try:
            candles.append({
                "time": int(row.get("time", 0)),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("tickVolume") or row.get("volume") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue

    candles.sort(key=lambda x: x["time"])
    with _lock:
        _candle_cache[key] = {"data": candles, "ts": now}
    return candles[-count:]


def get_balance() -> float:
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    data = _get(f"/users/current/accounts/{_account_id()}/account-information")
    return float(data.get("balance") or data.get("equity") or cfg.PAPER_BALANCE)


def place_order(side, units, instrument=None, sl=None, tp=None):
    symbol = _to_ma_symbol(instrument or cfg.SYMBOL)
    if cfg.PAPER_TRADING:
        print(f"[PAPER][MetaAPI] {side} {units} {symbol} sl={sl} tp={tp}")
        return {"orderId": f"MA_PAPER_{int(time.time()*1000)}", "status": "FILLED"}

    order_type = "ORDER_TYPE_BUY" if side == "BUY" else "ORDER_TYPE_SELL"
    body = {
        "symbol": symbol,
        "actionType": order_type,
        "volume": round(float(units) / 100000, 2),  # units → lots (1 lot = 100k units)
    }
    if sl:
        body["stopLoss"] = round(float(sl), 5)
    if tp:
        body["takeProfit"] = round(float(tp), 5)

    result = _post(f"/users/current/accounts/{_account_id()}/trade", body)
    return {"orderId": result.get("orderId", ""), "status": result.get("stringCode", "FILLED")}


def close_position(instrument=None):
    symbol = _to_ma_symbol(instrument or cfg.SYMBOL)
    if cfg.PAPER_TRADING:
        return {"status": "CLOSED"}
    data = _get(f"/users/current/accounts/{_account_id()}/positions")
    positions = data if isinstance(data, list) else []
    for pos in positions:
        if pos.get("symbol") == symbol:
            _post(f"/users/current/accounts/{_account_id()}/trade",
                  {"actionType": "POSITION_CLOSE_ID", "positionId": pos["id"]})
    return {"status": "CLOSED"}
