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
    contract_size: float | None
    digits: int | None
    min_stop_distance_pips: float | None
    sources: dict[str, str]


def normalise_instrument(symbol: Any, *, price: float | None = None) -> InstrumentSpec:
    name = str(symbol or "").strip().upper().replace("/", "_").replace("-", "_")
    compact = name.replace("_", "")
    if not name or not forex.is_tradeable(compact):
        raise ValueError("instrument metadata is unknown or not supported")
    pip = float(forex.pip_size(compact, price))
    units = float(forex.min_units(compact))
    label = forex.unit_label(compact)
    contract = 100000.0 if label == "lot" else 1.0 if label == "oz" else None
    digits = max(0, len(str(pip).rstrip("0").split(".")[-1])) if pip < 1 else 0
    return InstrumentSpec(
        name, pip, label, units, units, contract, digits, None,
        {"pipSize": "apex.forex.pip_size", "unit": "apex.forex.unit_label",
         "minimum": "apex.forex.min_units", "step": "broker metadata unavailable",
         "contractSize": "instrument convention", "digits": "pip-size convention",
         "minimumStopDistance": "broker metadata unavailable"})


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
            "unknown": False,
            "metadata": {"minLot": spec.min_units, "lotStep": spec.step_units,
                          "contractSize": spec.contract_size, "digits": spec.digits,
                          "minimumStopDistancePips": spec.min_stop_distance_pips,
                          "sources": spec.sources}}


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def inputs_from_rule(rule, payload=None):
    """Stop distance (pips) and risk fraction for a saved rule.

    Returns ``(stop_pips, risk_fraction, missing)``. ``missing`` names, in
    plain words, what the rule does not carry; it is empty when both values
    were read.

    A rule keeps its stop under ``stopLoss`` and its risk under ``sizing``.
    The route used to look for ``limits.stopPips`` and
    ``limits.riskFraction``, which no rule has, so every real rule was
    refused as unreadable. A value in the request still wins, and nothing is
    guessed: an ATR stop or a fixed-volume rule has no pips or percentage to
    convert.
    """
    payload = payload if isinstance(payload, dict) else {}
    rule = rule if isinstance(rule, dict) else {}
    limits = rule.get("limits") if isinstance(rule.get("limits"), dict) else {}
    stop = rule.get("stopLoss") if isinstance(rule.get("stopLoss"), dict) else {}
    sizing = rule.get("sizing") if isinstance(rule.get("sizing"), dict) else {}

    stop_pips = _num(payload.get("stopPips")) or _num(limits.get("stopPips"))
    if stop_pips is None and stop.get("mode") == "pips":
        stop_pips = _num(stop.get("pips"))
    risk_fraction = (_num(payload.get("riskFraction"))
                     or _num(limits.get("riskFraction")))
    if risk_fraction is None and sizing.get("mode") == "risk_percent":
        percent = _num(sizing.get("riskPercent"))
        risk_fraction = percent / 100.0 if percent is not None else None

    missing = []
    if stop_pips is None or stop_pips <= 0:
        stop_pips = None
        missing.append("a fixed stop distance in pips")
    if risk_fraction is None or risk_fraction <= 0:
        risk_fraction = None
        missing.append("a risk percentage per trade")
    return stop_pips, risk_fraction, missing
