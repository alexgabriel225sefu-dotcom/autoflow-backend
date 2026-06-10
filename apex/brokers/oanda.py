"""OANDA v20 REST connector (practice + live).

Docs: https://developer.oanda.com/rest-live-v20/introduction/
A free practice account provides full market data — paper mode uses it too.
"""
import time
import requests
from apex import config as cfg

UA = {"User-Agent": "ApexForexBot/1.0"}

_GRANULARITY = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
                "1h": "H1", "4h": "H4", "1d": "D"}


def _base():
    env = (cfg.OANDA_ENV or "practice").lower()
    return ("https://api-fxtrade.oanda.com/v3" if env == "live"
            else "https://api-fxpractice.oanda.com/v3")


def _headers():
    return {**UA, "Authorization": f"Bearer {cfg.OANDA_API_TOKEN}",
            "Content-Type": "application/json"}


def get_bid_ask(instrument=None):
    instrument = instrument or cfg.SYMBOL
    r = requests.get(f"{_base()}/accounts/{cfg.OANDA_ACCOUNT_ID}/pricing",
                     params={"instruments": instrument}, headers=_headers(), timeout=8)
    r.raise_for_status()
    p = r.json()["prices"][0]
    return float(p["bids"][0]["price"]), float(p["asks"][0]["price"])


def get_price(instrument=None):
    bid, ask = get_bid_ask(instrument)
    return round((bid + ask) / 2, 6)


def get_candles(instrument=None, interval=None, limit=None):
    instrument = instrument or cfg.SYMBOL
    gran = _GRANULARITY.get(interval or cfg.TIMEFRAME, "M5")
    limit = min(limit or cfg.CANDLES, 500)
    r = requests.get(f"{_base()}/instruments/{instrument}/candles",
                     params={"count": limit, "granularity": gran, "price": "M"},
                     headers=_headers(), timeout=10)
    r.raise_for_status()
    out = []
    for c in r.json()["candles"]:
        if not c.get("complete", True):
            continue
        mid = c["mid"]
        out.append({"time": c["time"], "open": float(mid["o"]), "high": float(mid["h"]),
                    "low": float(mid["l"]), "close": float(mid["c"]),
                    "volume": float(c.get("volume", 0))})
    return out


def get_balance():
    if cfg.PAPER_TRADING:
        return cfg.PAPER_BALANCE
    r = requests.get(f"{_base()}/accounts/{cfg.OANDA_ACCOUNT_ID}/summary",
                     headers=_headers(), timeout=10)
    r.raise_for_status()
    return float(r.json()["account"]["balance"])


def place_order(side, units, instrument=None):
    """Market order. OANDA uses signed units: positive = buy, negative = sell."""
    instrument = instrument or cfg.SYMBOL
    signed = int(units) if side == "BUY" else -int(units)
    if cfg.PAPER_TRADING:
        print(f"[PAPER][OANDA] {side} {units} {instrument}")
        return {"orderId": "PAPER_" + str(int(time.time() * 1000)), "status": "FILLED"}
    r = requests.post(f"{_base()}/accounts/{cfg.OANDA_ACCOUNT_ID}/orders",
                      json={"order": {"units": str(signed), "instrument": instrument,
                                      "type": "MARKET", "positionFill": "DEFAULT",
                                      "timeInForce": "FOK"}},
                      headers=_headers(), timeout=10)
    data = r.json()
    if "orderRejectTransaction" in data:
        reason = data["orderRejectTransaction"].get("rejectReason", "unknown")
        print(f"[LIVE][OANDA] ❌ Order rejected: {reason}")
        return {"status": "REJECTED", "reason": reason}
    tx = data.get("orderFillTransaction") or data.get("orderCreateTransaction") or {}
    print(f"[LIVE][OANDA] {side} {units} {instrument} -> {tx.get('id')}")
    return {"orderId": tx.get("id"), "status": "FILLED"}
