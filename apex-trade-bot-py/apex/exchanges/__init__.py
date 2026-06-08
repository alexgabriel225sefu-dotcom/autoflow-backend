"""Exchange factory — selects the connector module for cfg.EXCHANGE.

Every connector exposes the same interface:
    get_price(symbol) -> float
    get_candles(symbol, interval, limit) -> list[dict(time,open,high,low,close,volume)]
    get_balance(asset) -> float
    place_order(side, quantity, symbol) -> dict
"""
import importlib
from apex import config as cfg

_REGISTRY = {
    "binance": "apex.exchanges.binance",
    "bybit": "apex.exchanges.bybit",
    "okx": "apex.exchanges.okx",
    "kraken": "apex.exchanges.kraken",
    "kucoin": "apex.exchanges.kucoin",
    "coinbase": "apex.exchanges.coinbase",
    "bitget": "apex.exchanges.bitget",
    "mexc": "apex.exchanges.mexc",
}


def get_exchange(name: str = None):
    name = (name or cfg.EXCHANGE or "binance").lower()
    if name not in _REGISTRY:
        raise ValueError(
            f'Unsupported EXCHANGE="{name}". Supported: {", ".join(_REGISTRY)}'
        )
    module = importlib.import_module(_REGISTRY[name])
    module.__exchange_name__ = name
    return module
