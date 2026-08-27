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

# cTrader only.
#
# The registry listed five brokers, and get_broker() resolves whatever name it
# is given — so get_broker("mt") loaded the MetaTrader bridge regardless of
# what config.py had decided about BROKER. An allowlist with a second door is
# not an allowlist.
#
# The mtbridge, twelvedata, metaapi and yahoo modules remain on disk: two of
# them have tests that import them directly, and deleting a test to tidy a
# registry is the wrong trade. They are simply no longer reachable through the
# factory, which is the only way the engine obtains a broker.
_REGISTRY = {
    "ctrader":   "apex.brokers.ctrader",    # cTrader Open API — the only path
}


def get_broker(name: str = None):
    name = (name or cfg.BROKER or "ctrader").lower()
    if name not in _REGISTRY:
        raise ValueError(
            f'Unsupported BROKER="{name}". Supported: {", ".join(_REGISTRY)}'
        )
    module = importlib.import_module(_REGISTRY[name])
    module.__broker_name__ = name
    return module
