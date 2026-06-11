"""Broker factory — selects the connector module for cfg.BROKER.

Every connector exposes the same interface:
    get_price(instrument) -> float                      (mid price)
    get_bid_ask(instrument) -> (bid, ask)
    get_candles(instrument, interval, limit) -> list[dict(time,open,high,low,close,volume)]
    get_balance() -> float
    place_order(side, units, instrument) -> dict
"""
import importlib
from apex import config as cfg

_REGISTRY = {
    "oanda": "apex.brokers.oanda",
    "mt": "apex.brokers.mtbridge",      # MetaTrader 5 via ApexBridge EA
    "td": "apex.brokers.twelvedata",    # Twelve Data — free forex data, paper only
}


def get_broker(name: str = None):
    name = (name or cfg.BROKER or "oanda").lower()
    if name not in _REGISTRY:
        raise ValueError(
            f'Unsupported BROKER="{name}". Supported: {", ".join(_REGISTRY)}'
        )
    module = importlib.import_module(_REGISTRY[name])
    module.__broker_name__ = name
    return module
