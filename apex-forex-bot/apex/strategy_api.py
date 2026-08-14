"""Standardized strategy-module interface + registry (blueprint V1 §3/§14/§16).

The pipeline this sits inside:

    MARKET DATA -> STRATEGY -> AI CONTEXT -> RISK ENGINE -> EXECUTION
                   ^^^^^^^^
    this file defines that one box — not what runs before or after it

A strategy module answers four questions about a single market frame:

    analyze(market) -> what do I see?              (read-only market read)
    signal(market)  -> what would I do?            (BUY/SELL/HOLD/CLOSE)
    risk(market)    -> how big, IF the engine runs it?   (ADVISORY ONLY)
    exit(market)    -> should the open position come out?

`risk()` is advisory and nothing else (blueprint §6/§16). It returns a
multiplier the Risk Engine *may* apply to a size the Risk Engine itself
computed. It cannot raise a limit, skip a circuit breaker, or authorise a
trade. A strategy module is untrusted input to the Risk Engine — it may be
written by someone else later, or be steered by an AI context that has every
incentive to ask for more size — so this module clamps whatever it is handed
into the band the existing sizing code already enforces, and strips any key
that reads like an instruction to override or bypass a check. Both the base
class and `advisory_multiplier()` do that, so neither an honest module nor a
module that overrides `risk()` outright can inflate risk.

NOT WIRED TO THE LIVE LOOP. `apex/user_loop.py` still makes its decisions
exactly as it does today; this is the shape those decisions will move into
later, and `apex/strategy_modules.py` is the first set of modules poured into
it. Registering a strategy never changes what the running bot trades.
"""

# The sizing multiplier band the live code already enforces
# (strategies.druckenmiller_multiplier clamps to exactly this). An advisory
# from a strategy module can never leave it.
ADVISORY_MIN = 0.4
ADVISORY_MAX = 1.2

_REQUIRED_OHLC = ("open", "high", "low", "close")

# Anything that reads like "ignore the risk engine" is dropped from an
# advisory rather than passed along for a future consumer to honour.
_AUTHORITY_WORDS = ("override", "bypass", "force", "skip", "allow", "disable",
                    "unlock", "ignore")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _validate_candles(candles):
    """Candles arrive from a broker feed — validate at the boundary."""
    if not isinstance(candles, (list, tuple)):
        raise TypeError(f"candles must be a list, got {type(candles).__name__}")
    if not candles:
        raise ValueError("market frame needs at least one candle")
    for i, c in enumerate(candles):
        if not isinstance(c, dict):
            raise TypeError(f"candle {i} is {type(c).__name__}, expected dict")
        for k in _REQUIRED_OHLC:
            if not _is_num(c.get(k)):
                raise ValueError(f"candle {i} has non-numeric {k!r}: {c.get(k)!r}")
    return list(candles)


def _validate_position(pos):
    if pos is None:
        return None
    if not isinstance(pos, dict):
        raise TypeError(f"open_position must be a dict or None, got {type(pos).__name__}")
    side = pos.get("side")
    if side not in ("BUY", "SELL"):
        raise ValueError(f"open_position side must be BUY or SELL, got {side!r}")
    return pos


class Market:
    """One validated market frame handed to a strategy module.

    Indicators and the legacy strategy bundle are computed lazily and cached,
    so a caller that already has them (the live loop does) passes them in and
    nothing is recomputed, while a caller that only has candles (tests, the
    backtester) still gets a complete frame.
    """

    def __init__(self, candles, symbol="", indicators=None, strat=None,
                 open_position=None, price=None, balance=None, timeframe="",
                 confidence=None, criteria_score=None):
        self.candles = _validate_candles(candles)
        self.symbol = str(symbol or "")
        self.timeframe = str(timeframe or "")
        self.open_position = _validate_position(open_position)
        self.balance = float(balance) if _is_num(balance) else None
        self.confidence = float(confidence) if _is_num(confidence) else None
        self.criteria_score = (float(criteria_score)
                               if _is_num(criteria_score) else None)
        self.price = float(price) if _is_num(price) else float(self.candles[-1]["close"])
        if indicators is not None and not isinstance(indicators, dict):
            raise TypeError("indicators must be a dict or None")
        if strat is not None and not isinstance(strat, dict):
            raise TypeError("strat must be a dict or None")
        self._ind = indicators
        self._strat = strat
        self._regime = None

    @property
    def indicators(self):
        if self._ind is None:
            from apex import indicators as _ind
            self._ind = _ind.analyze(self.candles)
        return self._ind

    @property
    def strat(self):
        """The apex.strategies analysis bundle (turtle/livermore/soros/…)."""
        if self._strat is None:
            from apex import strategies as _st
            self._strat = _st.analyze(self.candles)
        return self._strat

    @property
    def regime(self):
        if self._regime is None:
            from apex import strategies as _st
            self._regime = _st.detect_regime(self.candles)
        return self._regime


def _sanitize_advice(advice, strategy=None):
    """Force a risk advisory back inside the band, whoever produced it."""
    out = {}
    if isinstance(advice, dict):
        for k, v in advice.items():
            key = str(k).lower()
            if any(w in key for w in _AUTHORITY_WORDS):
                continue  # a strategy does not get to instruct the risk engine
            out[k] = v
    raw = out.get("multiplier", 1.0)
    try:
        mult = float(raw)
    except (TypeError, ValueError):
        mult = 1.0
    if mult != mult:  # NaN
        mult = 1.0
    clamped = min(ADVISORY_MAX, max(ADVISORY_MIN, mult))
    if clamped != mult:
        out["clamped_from"] = raw
    out["multiplier"] = clamped
    out["advisory"] = True
    if strategy is not None:
        out.setdefault("strategy_id", getattr(strategy, "strategy_id", ""))
        out.setdefault("strategy_version", getattr(strategy, "strategy_version", ""))
    return out


class Strategy:
    """Base class for every strategy module.

    Subclasses implement `analyze`, `signal`, `exit` and — for risk — the
    `advise_risk` hook rather than `risk` itself. `risk()` is deliberately not
    the extension point: it is the sanitising wrapper that keeps an advisory
    inside the band no matter what a module returns.
    """

    strategy_id = ""        # stable machine name, recorded per trade (§14)
    strategy_version = ""   # bump when the decision logic changes (§14)
    label = ""              # human-facing name

    def provenance(self):
        """What §14 requires be recorded on every trade for reproducibility."""
        return {"strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version}

    def stamp(self, verdict):
        out = dict(verdict) if isinstance(verdict, dict) else {"verdict": verdict}
        out.update(self.provenance())
        return out

    def analyze(self, market):
        raise NotImplementedError

    def signal(self, market):
        raise NotImplementedError

    def advise_risk(self, market):
        """Override this. Return {"multiplier": float, ...} — advisory only."""
        return {}

    def risk(self, market):
        return _sanitize_advice(self.advise_risk(market), self)

    def exit(self, market):
        raise NotImplementedError


def advisory_multiplier(strategy, market, default=1.0):
    """The Risk Engine's read of a strategy's advice.

    Clamps a second time, on purpose: `Strategy.risk()` guards modules that
    extend the base properly, and this guards the Risk Engine against one that
    overrode `risk()` to return whatever it liked. A module that raises is
    worth no size opinion at all, not a trade-blocking exception.
    """
    try:
        advice = strategy.risk(market)
    except Exception as e:
        print(f"[STRATEGY_API] {getattr(strategy, 'strategy_id', '?')} "
              f"risk() failed: {e}")
        advice = {"multiplier": default, "error": str(e)}
    return _sanitize_advice(advice, strategy)["multiplier"]


# ── Registry: name -> class, so strategies are added without touching the
#    engine above. Nothing here imports a strategy module; content depends on
#    the engine, never the other way round. ──
_REGISTRY = {}

_INTERFACE = ("analyze", "signal", "risk", "exit")


def register(cls):
    """Class decorator. Rejects anything that isn't a usable strategy."""
    if not isinstance(cls, type) or not issubclass(cls, Strategy):
        raise TypeError(f"{cls!r} is not a Strategy subclass")
    sid = getattr(cls, "strategy_id", "")
    ver = getattr(cls, "strategy_version", "")
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError(f"{cls.__name__} needs a non-empty strategy_id (§14)")
    if not isinstance(ver, str) or not ver.strip():
        raise ValueError(f"{cls.__name__} needs a non-empty strategy_version (§14)")
    for name in _INTERFACE:
        if not callable(getattr(cls, name, None)):
            raise TypeError(f"{cls.__name__} does not implement {name}()")
    existing = _REGISTRY.get(sid)
    if existing is not None and existing is not cls:
        raise ValueError(f"strategy_id {sid!r} already registered "
                         f"by {existing.__name__}")
    _REGISTRY[sid] = cls
    return cls


def unregister(strategy_id):
    """Remove a strategy. Exists for tests; the live path only ever adds."""
    return _REGISTRY.pop(strategy_id, None)


def get(strategy_id):
    """A fresh instance of the named strategy, or None. Modules are stateless
    — all mutable session state stays in apex.strategies, where the circuit
    breakers can see it."""
    cls = _REGISTRY.get(strategy_id)
    return cls() if cls else None


def available():
    return sorted(_REGISTRY)


def describe():
    return [{"strategy_id": c.strategy_id, "strategy_version": c.strategy_version,
             "label": c.label} for _, c in sorted(_REGISTRY.items())]


def provenance_for(strategy_id):
    """The §14 record for a strategy, without instantiating anything."""
    cls = _REGISTRY.get(strategy_id)
    if not cls:
        return None
    return {"strategy_id": cls.strategy_id,
            "strategy_version": cls.strategy_version}


def load_builtins():
    """Import the shipped modules so they register themselves.

    strategy_modules  — the ten engines the bot already traded
    strategy_extra    — momentum, session breakout, quant/statistical
    strategy_specialized — grid and martingale, capped (blueprint §2 keeps
                        these separate on purpose)
    """
    from apex import strategy_modules      # noqa: F401
    from apex import strategy_extra        # noqa: F401
    from apex import strategy_specialized  # noqa: F401
    return available()
