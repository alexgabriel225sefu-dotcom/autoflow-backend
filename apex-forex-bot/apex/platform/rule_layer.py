"""Broker-agnostic, read-only rule calculations.

This module translates the same instrument/risk vocabulary across brokers.  It
does not create orders or call a broker; unknown metadata fails closed.
"""
from dataclasses import dataclass
from typing import Any

from apex import forex


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    pip_size: float
    unit_label: str
    min_units: float
    step_units: float


def normalise_instrument(symbol: Any, *, price: float | None = None) -> InstrumentSpec:
    name = str(symbol or "").strip().upper().replace("/", "_").replace("-", "_")
    compact = name.replace("_", "")
    if not name or not forex.is_tradeable(compact):
        raise ValueError("instrument metadata is unknown or not supported")
    return InstrumentSpec(name, forex.pip_size(compact, price),
                          forex.unit_label(compact), float(forex.min_units(compact)),
                          float(forex.min_units(compact)))


def round_volume(units: float, spec: InstrumentSpec) -> float:
    if units < 0:
        raise ValueError("volume must not be negative")
    if spec.step_units <= 0:
        raise ValueError("volume step is unknown")
    rounded = (units // spec.step_units) * spec.step_units
    return round(rounded, 8)


def stop_distance(entry: float, stop: float, symbol: str, *, price: float | None = None) -> float:
    if entry <= 0 or stop <= 0 or entry == stop:
        raise ValueError("entry and stop prices are required")
    normalise_instrument(symbol, price=price or entry)
    return abs(forex.to_pips(entry - stop, symbol, price or entry))


def risk_units(*, balance: float, risk_fraction: float, stop_pips: float,
               symbol: str, price: float, leverage: float = 30,
               quote_usd_rate: float | None = None) -> dict[str, Any]:
    spec = normalise_instrument(symbol, price=price)
    if balance <= 0 or not 0 < risk_fraction <= 1 or stop_pips <= 0 or price <= 0:
        raise ValueError("balance, risk, stop and price must be positive")
    raw = forex.calc_units(balance, risk_fraction, stop_pips, spec.symbol, price,
                           leverage=leverage, quote_usd_rate=quote_usd_rate)
    units = round_volume(raw, spec)
    return {"symbol": spec.symbol, "units": units, "unitLabel": spec.unit_label,
            "stopPips": stop_pips, "riskAmount": round(balance * risk_fraction, 8),
            "unknown": False}
