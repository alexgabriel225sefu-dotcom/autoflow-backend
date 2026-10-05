"""The condition library — every question a rule is allowed to ask.

THE ONE RULE THIS FILE ENFORCES: a condition that cannot be answered is never
answered "false".

That distinction is the whole file. An EMA(200) over 50 bars is not "price is
below the EMA" — it is *unknown*, and the difference decides money. Under an
AND rule, a silent False looks exactly like an honest no-signal and the client
sees "conditions not met" forever without being told their history is too
short. Under an OR rule it is worse: the condition the client added to BLOCK
entries stops blocking, and other conditions carry the trade through. So
missing data raises ConditionUnavailable, bad parameters raise
ConditionMisconfigured, and the evaluator turns both into an explicit refusal.

SCOPE IS DELIBERATELY SMALL. Only concepts with one published formula and
named parameters live here. apex/indicators.py also offers fair value gaps,
liquidity sweeps and supply/demand zones; they are NOT exposed, because their
definitions vary between sources and a client choosing "liquidity sweep" in a
form would not know which one they bought. They can be added the day their
mathematics and parameters are written down.

PURITY. Nothing here reads the clock, the environment, the network or the
broker. Time-of-day conditions derive from `snapshot.ts`, which is a captured
field. That is what lets a decision be replayed years later.
"""

from apex import indicators

# ── failure modes, kept apart ───────────────────────────────────────────────


class ConditionUnavailable(Exception):
    """The data to answer this condition is not present. NOT a False."""


class ConditionMisconfigured(Exception):
    """The parameters are wrong. A configuration error, not a market state."""


# ── parameter checking ──────────────────────────────────────────────────────
class P:
    """One parameter's contract."""

    __slots__ = ("type", "default", "choices", "min", "max", "required")

    def __init__(self, type, default=None, choices=None, min=None, max=None,
                 required=False):
        self.type = type
        self.default = default
        self.choices = choices
        self.min = min
        self.max = max
        self.required = required


def _coerce(spec, raw, cid):
    """Clean parameters, or raise.

    An UNKNOWN key is an error rather than something to ignore. A client who
    typed "periods": 200 and had it dropped would be running period 20 and
    reading a form that says 200 — the rule and its description would disagree
    while both look fine.
    """
    raw = dict(raw or {})
    unknown = sorted(set(raw) - set(spec))
    if unknown:
        raise ConditionMisconfigured(
            f"{cid}: unknown parameter(s) {', '.join(unknown)} — "
            f"accepted: {', '.join(sorted(spec))}")
    out = {}
    for name, p in spec.items():
        if name not in raw or raw[name] is None:
            if p.required:
                raise ConditionMisconfigured(f"{cid}.{name} is required")
            out[name] = p.default
            continue
        v = raw[name]
        if p.type is int:
            if isinstance(v, bool) or not isinstance(v, int):
                raise ConditionMisconfigured(
                    f"{cid}.{name} must be a whole number, got {v!r}")
        elif p.type is float:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ConditionMisconfigured(
                    f"{cid}.{name} must be a number, got {v!r}")
            v = float(v)
        elif p.type is str:
            if not isinstance(v, str):
                raise ConditionMisconfigured(
                    f"{cid}.{name} must be text, got {v!r}")
            v = v.strip().lower()
        elif p.type is list:
            if not isinstance(v, (list, tuple)):
                raise ConditionMisconfigured(
                    f"{cid}.{name} must be a list, got {v!r}")
            v = list(v)
        if p.choices is not None and v not in p.choices:
            raise ConditionMisconfigured(
                f"{cid}.{name} must be one of "
                f"{', '.join(map(str, p.choices))}, got {v!r}")
        if p.min is not None and v < p.min:
            raise ConditionMisconfigured(
                f"{cid}.{name} must be >= {p.min}, got {v}")
        if p.max is not None and v > p.max:
            raise ConditionMisconfigured(
                f"{cid}.{name} must be <= {p.max}, got {v}")
        out[name] = v
    return out


# ── shared reads ────────────────────────────────────────────────────────────
# Every series read takes the LAST element. The RuleDoc's evaluateOn is
# "bar_close", so the final candle in a snapshot is the bar that just closed.

def _closes(snap, need, cid):
    if len(snap.candles) < need:
        raise ConditionUnavailable(
            f"{cid}: needs {need} candles, snapshot has {len(snap.candles)}")
    return [c["close"] for c in snap.candles]


def _last(series, cid, what):
    if not series or series[-1] is None:
        raise ConditionUnavailable(f"{cid}: {what} is undefined on this bar")
    return series[-1]


def _prev_last(series, cid, what):
    """The two most recent values — what a crossing is made of."""
    if len(series) < 2 or series[-1] is None or series[-2] is None:
        raise ConditionUnavailable(
            f"{cid}: {what} needs two consecutive defined values")
    return series[-2], series[-1]


def _ma(closes, kind, period):
    return indicators.ema(closes, period) if kind == "ema" \
        else indicators.sma(closes, period)


def _cmp(op, a, b):
    return a > b if op == "above" else a < b


def _utc(snap):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(snap.ts, timezone.utc)


def _minutes(hhmm, cid, field):
    parts = str(hhmm).split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ConditionMisconfigured(f"{cid}.{field} must be HH:MM, "
                                     f"got {hhmm!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ConditionMisconfigured(f"{cid}.{field} is not a real time: "
                                     f"{hhmm!r}")
    return h * 60 + m


# ── the conditions ──────────────────────────────────────────────────────────
# Each entry: params, check(params, snapshot) -> (bool, detail), and the
# direction it argues for. `bias` is what lets a two-sided rule know whether a
# satisfied set of conditions means buy or sell; None means the condition is a
# filter that argues for neither.

_LIB = {}


def _define(cid, *, params, check, bias=None, doc=""):
    _LIB[cid] = {"id": cid, "params": params, "check": check,
                 "bias": bias or (lambda p: None), "doc": doc}


# -- price against a moving average -----------------------------------------
def _c_price_vs_ma(p, snap):
    cid = "price_vs_ma"
    closes = _closes(snap, p["period"], cid)
    ma = _last(_ma(closes, p["indicator"], p["period"]), cid,
               f"{p['indicator'].upper()}({p['period']})")
    price = closes[-1]
    ok = _cmp(p["op"], price, ma)
    return ok, (f"price {price:.5f} is "
                f"{'above' if price > ma else 'below'} "
                f"{p['indicator'].upper()}({p['period']}) {ma:.5f}")


_define("price_vs_ma",
        params={"indicator": P(str, "ema", choices=("ema", "sma")),
                "period": P(int, 50, min=2, max=1000),
                "op": P(str, "above", choices=("above", "below"))},
        check=_c_price_vs_ma,
        bias=lambda p: "BUY" if p["op"] == "above" else "SELL",
        doc="Close of the last bar above/below an EMA or SMA.")


# -- one moving average crossing another ------------------------------------
def _c_ma_cross(p, snap):
    cid = "ma_cross"
    if p["fast_period"] >= p["slow_period"]:
        raise ConditionMisconfigured(
            f"{cid}: fast_period ({p['fast_period']}) must be shorter than "
            f"slow_period ({p['slow_period']}) — otherwise 'fast' is the "
            f"slower line and the crossing means the opposite of the label")
    closes = _closes(snap, p["slow_period"] + 1, cid)
    fp, fl = _prev_last(_ma(closes, p["fast"], p["fast_period"]), cid, "fast MA")
    sp, sl = _prev_last(_ma(closes, p["slow"], p["slow_period"]), cid, "slow MA")
    # A cross is a change of side between two consecutive bars. Testing only
    # the current bar ("fast > slow") would fire on every bar of a trend, not
    # on the event the client asked for.
    up = fp <= sp and fl > sl
    down = fp >= sp and fl < sl
    ok = up if p["direction"] == "up" else down
    return ok, (f"fast {fp:.5f}->{fl:.5f} vs slow {sp:.5f}->{sl:.5f}: "
                f"{'crossed up' if up else 'crossed down' if down else 'no cross'}")


_define("ma_cross",
        params={"fast": P(str, "ema", choices=("ema", "sma")),
                "fast_period": P(int, 20, min=2, max=1000),
                "slow": P(str, "ema", choices=("ema", "sma")),
                "slow_period": P(int, 50, min=2, max=1000),
                "direction": P(str, "up", choices=("up", "down"))},
        check=_c_ma_cross,
        bias=lambda p: "BUY" if p["direction"] == "up" else "SELL",
        doc="The fast MA crossing the slow MA on this bar.")


# -- RSI --------------------------------------------------------------------
def _c_rsi(p, snap):
    cid = "rsi"
    closes = _closes(snap, p["period"] + 2, cid)
    v = _last(indicators.rsi(closes, p["period"]), cid, "RSI")
    return _cmp(p["op"], v, p["value"]), f"RSI({p['period']}) = {v:.1f}"


_define("rsi",
        params={"period": P(int, 14, min=2, max=200),
                "op": P(str, "below", choices=("above", "below")),
                "value": P(float, 30.0, min=0, max=100)},
        check=_c_rsi,
        # Oversold argues for a buy, overbought for a sell.
        bias=lambda p: "BUY" if p["op"] == "below" else "SELL",
        doc="Wilder's RSI against a threshold.")


# -- MACD -------------------------------------------------------------------
def _c_macd(p, snap):
    cid = "macd"
    closes = _closes(snap, p["slow"] + p["signal"] + 2, cid)
    m = indicators.macd(closes, p["fast"], p["slow"], p["signal"])
    if p["state"] in ("bullish", "bearish"):
        line = _last(m["macd"], cid, "MACD line")
        sig = _last(m["signal"], cid, "MACD signal")
        ok = line > sig if p["state"] == "bullish" else line < sig
        return ok, f"MACD {line:.5f} vs signal {sig:.5f}"
    lp, ll = _prev_last(m["macd"], cid, "MACD line")
    sp, sl = _prev_last(m["signal"], cid, "MACD signal")
    up = lp <= sp and ll > sl
    down = lp >= sp and ll < sl
    ok = up if p["state"] == "cross_up" else down
    return ok, (f"MACD {lp:.5f}->{ll:.5f} vs signal {sp:.5f}->{sl:.5f}: "
                f"{'crossed up' if up else 'crossed down' if down else 'no cross'}")


_define("macd",
        params={"fast": P(int, 12, min=2, max=200),
                "slow": P(int, 26, min=3, max=400),
                "signal": P(int, 9, min=2, max=200),
                "state": P(str, "bullish",
                           choices=("bullish", "bearish", "cross_up",
                                    "cross_down"))},
        check=_c_macd,
        bias=lambda p: "BUY" if p["state"] in ("bullish", "cross_up") else "SELL",
        doc="MACD line against its signal line, as a state or a crossing.")


# -- ATR, as a volatility filter --------------------------------------------
def _c_atr(p, snap):
    cid = "atr"
    if len(snap.candles) < p["period"] + 2:
        raise ConditionUnavailable(
            f"{cid}: needs {p['period'] + 2} candles, "
            f"snapshot has {len(snap.candles)}")
    # indicators.atr() is built from true ranges, which start at candle 1, so
    # its series is one shorter than the candles. Its LAST element still lines
    # up with the last candle, which is the only element read here.
    a = _last(indicators.atr(snap.candles, p["period"]), cid, "ATR")
    from apex import forex
    pips = forex.to_pips(a, snap.symbol, snap.candles[-1]["close"])
    return _cmp(p["op"], pips, p["pips"]), \
        f"ATR({p['period']}) = {pips:.1f} pips"


_define("atr",
        params={"period": P(int, 14, min=2, max=200),
                "op": P(str, "above", choices=("above", "below")),
                "pips": P(float, 10.0, min=0)},
        check=_c_atr,
        # Volatility argues for neither direction; it gates, it does not point.
        bias=None,
        doc="ATR in pips against a threshold — a volatility filter.")


# -- Bollinger Bands --------------------------------------------------------
def _c_bollinger(p, snap):
    cid = "bollinger"
    closes = _closes(snap, p["period"], cid)
    band = indicators.bollinger_bands(closes, p["period"], p["multiplier"])[-1]
    if band["upper"] is None:
        raise ConditionUnavailable(f"{cid}: bands undefined on this bar")
    price = closes[-1]
    zone = p["zone"]
    if zone == "above_upper":
        ok = price > band["upper"]
    elif zone == "below_lower":
        ok = price < band["lower"]
    else:
        ok = band["lower"] <= price <= band["upper"]
    return ok, (f"price {price:.5f} vs bands "
                f"[{band['lower']:.5f}, {band['upper']:.5f}]")


_define("bollinger",
        params={"period": P(int, 20, min=2, max=500),
                "multiplier": P(float, 2.0, min=0.1, max=10),
                "zone": P(str, "below_lower",
                          choices=("above_upper", "below_lower", "inside"))},
        check=_c_bollinger,
        # Outside a band is a mean-reversion argument; inside is a filter.
        bias=lambda p: {"below_lower": "BUY", "above_upper": "SELL"}.get(
            p["zone"]),
        doc="Where the close sits relative to the Bollinger Bands.")


# -- Stochastic -------------------------------------------------------------
def _c_stochastic(p, snap):
    cid = "stochastic"
    need = p["k_period"] + p["smooth"] + p["d_period"]
    if len(snap.candles) < need:
        raise ConditionUnavailable(
            f"{cid}: needs {need} candles, snapshot has {len(snap.candles)}")
    st = indicators.stochastic(snap.candles, p["k_period"], p["d_period"],
                               p["smooth"])
    line = _last(st[p["line"]], cid, f"%{p['line'].upper()}")
    return _cmp(p["op"], line, p["value"]), \
        f"%{p['line'].upper()} = {line:.1f}"


_define("stochastic",
        params={"k_period": P(int, 14, min=2, max=200),
                "d_period": P(int, 3, min=1, max=100),
                "smooth": P(int, 3, min=1, max=100),
                "line": P(str, "k", choices=("k", "d")),
                "op": P(str, "below", choices=("above", "below")),
                "value": P(float, 20.0, min=0, max=100)},
        check=_c_stochastic,
        bias=lambda p: "BUY" if p["op"] == "below" else "SELL",
        doc="Classic Stochastic %K or %D against a threshold.")


# ── public surface ──────────────────────────────────────────────────────────
def available():
    return sorted(_LIB)


def get(cid):
    return _LIB.get(cid)


def describe():
    """What the UI renders a form from — ids, parameters and defaults."""
    out = {}
    for cid, d in _LIB.items():
        out[cid] = {
            "id": cid, "doc": d["doc"],
            "params": {n: {"type": p.type.__name__, "default": p.default,
                           "choices": list(p.choices) if p.choices else None,
                           "min": p.min, "max": p.max,
                           "required": p.required}
                       for n, p in d["params"].items()},
        }
    return out


def evaluate_one(cid, raw_params, snapshot):
    """(passed, detail, clean_params) or raise.

    Raises ConditionMisconfigured for an unknown id so a typo cannot quietly
    drop a condition the client is relying on.
    """
    d = _LIB.get(cid)
    if d is None:
        raise ConditionMisconfigured(
            f"unknown condition {cid!r} — available: {', '.join(available())}")
    clean = _coerce(d["params"], raw_params, cid)
    passed, detail = d["check"](clean, snapshot)
    return bool(passed), detail, clean


def bias_of(cid, raw_params):
    """Which side this condition argues for, or None. Never raises on a bad
    id — the caller is already refusing by then."""
    d = _LIB.get(cid)
    if d is None:
        return None
    try:
        return d["bias"](_coerce(d["params"], raw_params, cid))
    except ConditionMisconfigured:
        return None


# Registered last so that `available()` is complete the moment this module is
# imported. strategy_api's registry fills in only after a separate import and
# reads as empty until then; that surprise is not worth repeating here.
from apex.platform import conditions_context as _ctx  # noqa: E402,F401
