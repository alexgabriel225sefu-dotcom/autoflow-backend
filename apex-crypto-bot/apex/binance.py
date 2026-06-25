"""Binance market data + paper exchange.

Public market data (klines, price) needs NO API key — perfect for paper
trading with real prices. Live trading uses signed orders with the user's
own keys (testnet by default for safety).
"""
import os
import time
import math
import hmac
import hashlib
import requests
from decimal import Decimal
from urllib.parse import urlencode

# Try mainnet first (works from Render US), fall back to public mirror, then testnet.
_USE_TESTNET = (os.getenv("BINANCE_TESTNET") or "true").lower() != "false"
_TESTNET = "https://testnet.binance.vision"
_PUBLIC = "https://testnet.binance.vision" if _USE_TESTNET else "https://api.binance.com"

# Ordered list of public data hosts to try on each call (most reliable first).
_DATA_HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
    "https://testnet.binance.vision",
]

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


def _get_json(path, params, timeout=10, hosts=None):
    """Try each data host in order; return parsed JSON or raise last error."""
    last_err = None
    for host in (hosts or _DATA_HOSTS):
        try:
            r = requests.get(f"{host}{path}", params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            print(f"[Binance] {host} failed: {e}")
    raise last_err


def get_candles(symbol, timeframe="5m", limit=200, exchange="binance"):
    """Return list of {open,high,low,close,volume} dicts (oldest→newest), or []."""
    key = (symbol, timeframe, exchange)
    now = time.time()
    cached = _kline_cache.get(key)
    if cached and now - cached["ts"] < _KLINE_TTL:
        return cached["candles"]
    try:
        interval = _INTERVAL.get(timeframe, "5m")
        rows = _get_json("/api/v3/klines",
                         {"symbol": symbol, "interval": interval, "limit": limit},
                         hosts=data_hosts_for(exchange))
        candles = [{
            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5]),
            "time": int(k[0]),
        } for k in rows]
        _kline_cache[key] = {"ts": now, "candles": candles}
        return candles
    except Exception as e:
        print(f"[Binance] get_candles({symbol}) failed all hosts: {e}")
        return []


def get_price(symbol, exchange="binance"):
    key = (symbol, exchange)
    now = time.time()
    cached = _price_cache.get(key)
    if cached and now - cached["ts"] < _PRICE_TTL:
        return cached["price"]
    try:
        data = _get_json("/api/v3/ticker/price", {"symbol": symbol}, timeout=8,
                         hosts=data_hosts_for(exchange))
        price = float(data["price"])
        _price_cache[key] = {"ts": now, "price": price}
        return price
    except Exception as e:
        print(f"[Binance] get_price({symbol}) failed all hosts: {e}")
        return cached["price"] if cached else 0.0


def valid_symbol(symbol):
    """Confirm a trading pair exists on Binance (cheap, cached by price call)."""
    try:
        get_price(symbol)
        return True
    except Exception:
        return False


# ─── Symbol trading filters (LOT_SIZE / MIN_NOTIONAL) ─────────────
# Binance rejects orders whose quantity isn't a multiple of the symbol's
# stepSize, is below minQty, or whose value is below minNotional. We MUST round
# to these before sending a live order or it comes back -1013 LOT_SIZE and the
# entry is silently skipped. Cached 1h — filters change very rarely.
_filters_cache = {}   # (exchange, symbol) → {stepSize, minQty, minNotional, ts}
_FILTERS_TTL = 3600


def get_symbol_filters(symbol, exchange="binance"):
    """Return {'stepSize','minQty','minNotional'} for a symbol, or None on failure."""
    key = (exchange, symbol)
    now = time.time()
    cached = _filters_cache.get(key)
    if cached and now - cached["ts"] < _FILTERS_TTL:
        return cached
    try:
        data = _get_json("/api/v3/exchangeInfo", {"symbol": symbol},
                         hosts=data_hosts_for(exchange))
        syms = data.get("symbols") or []
        if not syms:
            return None
        step = min_qty = min_notional = 0.0
        for f in syms[0].get("filters", []):
            t = f.get("filterType")
            if t == "LOT_SIZE":
                step = float(f.get("stepSize", 0) or 0)
                min_qty = float(f.get("minQty", 0) or 0)
            elif t in ("NOTIONAL", "MIN_NOTIONAL"):
                min_notional = float(f.get("minNotional", 0) or 0)
        result = {"stepSize": step, "minQty": min_qty,
                  "minNotional": min_notional, "ts": now}
        _filters_cache[key] = result
        return result
    except Exception as e:
        print(f"[Binance] exchangeInfo({symbol}) failed: {e}")
        return None


def _step_precision(step):
    """Decimal places implied by a stepSize like 0.00001 → 5, 1 → 0."""
    if step <= 0:
        return 6
    exp = Decimal(str(step)).normalize().as_tuple().exponent
    return max(0, -exp)


def round_qty(symbol, qty, price=0.0, exchange="binance"):
    """Round qty DOWN to the symbol's stepSize and validate against minQty /
    minNotional. Returns (rounded_qty, error_or_None). error is a human-readable
    string when the order would be rejected (caller should skip + tell the user).
    """
    filt = get_symbol_filters(symbol, exchange)
    if not filt:
        # Couldn't fetch filters — fall back to a conservative 6-dp round so we
        # at least don't send absurd precision. Better than guessing a step.
        return round(qty, 6), None
    step = filt["stepSize"]
    if step > 0:
        rq = math.floor(qty / step) * step
        rq = round(rq, _step_precision(step))
    else:
        rq = round(qty, 6)
    if filt["minQty"] and rq < filt["minQty"]:
        return 0.0, (f"quantity {rq:g} is below Binance's minimum "
                     f"{filt['minQty']:g} for {symbol}")
    if filt["minNotional"] and price > 0 and rq * price < filt["minNotional"]:
        return 0.0, (f"order value ${rq * price:.2f} is below Binance's minimum "
                     f"${filt['minNotional']:.2f} for {symbol} — increase the amount")
    return rq, None


# Per-exchange API hosts. binance.us is a separate entity for US clients.
_EXCHANGE_HOSTS = {
    "binance":   "https://api.binance.com",   # global (blocked in US)
    "binanceus": "https://api.binance.us",     # US only
}


def data_hosts_for(exchange="binance"):
    """Market-data hosts to try, ordered, for a given exchange."""
    if exchange == "binanceus":
        return ["https://api.binance.us"]
    return _DATA_HOSTS


# ─── Signed (live) trading — user's own keys, testnet by default ──
class LiveExchange:
    def __init__(self, api_key, api_secret, testnet=True, exchange="binance"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = exchange
        if testnet:
            self.base = _TESTNET
        else:
            self.base = _EXCHANGE_HOSTS.get(exchange, _EXCHANGE_HOSTS["binance"])

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

    def verify(self):
        """Validate keys + permissions. Returns (ok, message, usdt_balance)."""
        try:
            data = self._signed("GET", "/api/v3/account", {})
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            body = ""
            try:
                body = e.response.json().get("msg", "")
            except Exception:
                pass
            if code in (401, 403) or "Invalid API-key" in body or "signature" in body.lower():
                return False, "Keys rejected — check they're copied correctly and not IP-restricted.", 0.0
            return False, f"Binance error: {body or code}", 0.0
        except Exception as e:
            return False, f"Could not reach Binance ({e}).", 0.0
        if not data.get("canTrade", False):
            return False, "Keys valid but TRADING is not enabled — enable Spot Trading on the API key.", 0.0
        usdt = 0.0
        for b in data.get("balances", []):
            if b["asset"] == "USDT":
                usdt = float(b["free"])
                break
        return True, "Connected", usdt

    def place_order(self, side, qty, symbol):
        # Round to the symbol's LOT_SIZE/minQty so Binance accepts the order.
        # Raises ValueError when below the minimum so callers fail loud, not silent.
        rq, err = round_qty(symbol, qty, exchange=self.exchange)
        if err:
            raise ValueError(err)
        qty = rq
        data = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": side, "type": "MARKET", "quantity": qty,
        })
        fills = data.get("fills", [])
        avg = (sum(float(f["price"]) * float(f["qty"]) for f in fills) /
               sum(float(f["qty"]) for f in fills)) if fills else None
        return {"avgPrice": avg, "executedQty": float(data.get("executedQty", qty))}
