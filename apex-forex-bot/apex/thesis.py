"""Why this trade was taken — frozen at entry, never rewritten.

WHY THIS EXISTS, IN THIS REPOSITORY

The measured problem is not entry selection. On the live account the entry
engine wins 60% of the time. The profit factor is 1.10 because the average loss
is 36% larger than the average win, and the mechanism is the exit policy:
`BREAKEVEN_AT_R = 1.0` moves the stop to entry at +1R, a 1R trail then follows,
and the target sits at 2.4R. A winner has to travel 2.4R without a 1R pullback
after 2R. In a ranging market — which is what most of these trades are tagged —
it almost never does. Winners get closed near 1R; losers run the full stop.

That policy manages a trade by a schedule. A thesis manages it by a reason.
The trade was taken because certain things were true; it should be held while
they stay true and closed when they stop being true. That is the only version
that can hold a winner through a pullback, because a pullback that does not
break the structure does not invalidate anything.

TWO RULES THAT MAKE IT HONEST

§17: the thesis is written at entry and NEVER rewritten afterwards. A thesis
edited to match how the trade turned out is a story, not a record — and it
would make the replay lie about a trade the platform already closed.

§18: the exit reason is the condition that actually fired. It is never chosen
after the fact from the outcome. "Target hit" is claimed only when the target
was hit; a profitable manual close is a profitable manual close.

THIS MODULE PROPOSES. IT DOES NOT EXECUTE.

Nothing here touches a broker. `gates.authorize_close` remains the only thing
that can permit a close.
"""

import time
import uuid

# ── Thesis state ─────────────────────────────────────────────────────────
VALID = "VALID"
STRENGTHENED = "STRENGTHENED"
WEAKENING = "WEAKENING"
INVALIDATED = "INVALIDATED"
UNREADABLE = "UNREADABLE"          # the market could not be read this pass

STATES = (VALID, STRENGTHENED, WEAKENING, INVALIDATED, UNREADABLE)

# ── Condition kinds a thesis can rest on ─────────────────────────────────
# Each is something the platform already measures. A thesis may not rest on a
# condition nothing evaluates, because it could then never be checked and would
# read as permanently valid.
STRUCTURE = "STRUCTURE"            # livermore structure trend
HTF_ALIGNMENT = "HTF_ALIGNMENT"    # higher-timeframe agreement
REGIME = "REGIME"                  # market regime the setup was built for
MOMENTUM = "MOMENTUM"              # RSI / momentum reading
LEVEL = "LEVEL"                    # a price level that must hold

KINDS = (STRUCTURE, HTF_ALIGNMENT, REGIME, MOMENTUM, LEVEL)

THESIS_VERSION = "1.0.0"


class Condition:
    """One thing that had to be true for the trade to make sense."""

    __slots__ = ("kind", "expected", "detail", "weight")

    def __init__(self, kind, expected, *, detail="", weight=1.0):
        if kind not in KINDS:
            raise ValueError(f"unknown condition kind {kind!r}")
        self.kind = kind
        self.expected = expected
        self.detail = detail
        self.weight = float(weight)

    def to_dict(self):
        return {"kind": self.kind, "expected": self.expected,
                "detail": self.detail, "weight": self.weight}

    @classmethod
    def from_dict(cls, d):
        return cls(d["kind"], d.get("expected"), detail=d.get("detail", ""),
                   weight=d.get("weight", 1.0))


class Thesis:
    """The reason a position exists. Immutable after entry."""

    __slots__ = ("id", "symbol", "direction", "created_at", "conditions",
                 "target_logic", "strategy_id", "strategy_version",
                 "entry_price", "initial_stop", "initial_target",
                 "setup_key", "decision_id", "_frozen")

    def __init__(self, *, symbol, direction, conditions, strategy_id,
                 strategy_version, entry_price=None, initial_stop=None,
                 initial_target=None, target_logic="", setup_key=None,
                 decision_id=None, created_at=None, thesis_id=None):
        self.id = thesis_id or uuid.uuid4().hex[:16]
        self.symbol = str(symbol).upper()
        self.direction = direction
        self.created_at = created_at or time.time()
        self.conditions = list(conditions or [])
        self.target_logic = target_logic
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        # The trade's ORIGINAL levels. These are what R is measured against for
        # the position's whole life — deriving R from the CURRENT stop stops
        # measuring risk the moment the stop ratchets past entry.
        self.entry_price = entry_price
        self.initial_stop = initial_stop
        self.initial_target = initial_target
        self.setup_key = setup_key
        self.decision_id = decision_id
        self._frozen = True

    def __setattr__(self, name, value):
        # §17 in code rather than in a comment. A thesis edited after entry
        # would make the replay describe a trade that never happened.
        if name != "_frozen" and getattr(self, "_frozen", False):
            raise AttributeError(
                f"a thesis is frozen at entry; {name!r} cannot be changed "
                f"(record a new event instead)")
        object.__setattr__(self, name, value)

    @property
    def initial_risk(self):
        """Entry-to-stop distance, as recorded. None when either is absent."""
        if self.entry_price is None or self.initial_stop is None:
            return None
        try:
            d = abs(float(self.entry_price) - float(self.initial_stop))
        except (TypeError, ValueError):
            return None
        return d or None

    def r_multiple(self, price):
        """How many R this trade is worth at `price`. None when unmeasurable."""
        risk = self.initial_risk
        if risk is None or price is None or self.entry_price is None:
            return None
        try:
            move = float(price) - float(self.entry_price)
        except (TypeError, ValueError):
            return None
        if self.direction == "SELL":
            move = -move
        return round(move / risk, 3)

    def to_dict(self):
        return {"thesisId": self.id, "symbol": self.symbol,
                "direction": self.direction,
                "createdAt": round(self.created_at, 3),
                "conditions": [c.to_dict() for c in self.conditions],
                "targetLogic": self.target_logic,
                "strategyId": self.strategy_id,
                "strategyVersion": self.strategy_version,
                "thesisVersion": THESIS_VERSION,
                "entryPrice": self.entry_price,
                "initialStop": self.initial_stop,
                "initialTarget": self.initial_target,
                "setupKey": self.setup_key, "decisionId": self.decision_id}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or not d.get("symbol"):
            return None
        return cls(symbol=d["symbol"], direction=d.get("direction"),
                   conditions=[Condition.from_dict(c)
                               for c in (d.get("conditions") or [])
                               if isinstance(c, dict) and c.get("kind") in KINDS],
                   strategy_id=d.get("strategyId"),
                   strategy_version=d.get("strategyVersion"),
                   entry_price=d.get("entryPrice"),
                   initial_stop=d.get("initialStop"),
                   initial_target=d.get("initialTarget"),
                   target_logic=d.get("targetLogic", ""),
                   setup_key=d.get("setupKey"), decision_id=d.get("decisionId"),
                   created_at=d.get("createdAt"), thesis_id=d.get("thesisId"))

    def __repr__(self):
        return (f"<Thesis {self.symbol} {self.direction} "
                f"{len(self.conditions)} conditions>")


def from_candidate(candidate, *, entry_price, initial_stop, initial_target=None,
                   decision_id=None):
    """Build the thesis from the setup that justified the trade.

    Only conditions the candidate actually MEASURED become part of the thesis.
    A condition built from an unread feature would be unfalsifiable: nothing
    could ever make it false, so it would report VALID for the life of the
    trade and quietly weaken the whole mechanism.
    """
    conds = []
    f = candidate.features or {}

    htf = f.get("htfTrend")
    if htf in ("BULLISH", "BEARISH"):
        conds.append(Condition(
            HTF_ALIGNMENT, htf,
            detail="the higher timeframe agreed with the entry", weight=1.0))

    struct = f.get("structureTrend") or (
        (candidate.regime.evidence or {}).get("structureTrend")
        if candidate.regime is not None else None)
    if struct in ("BULLISH", "BEARISH"):
        conds.append(Condition(STRUCTURE, struct,
                               detail="market structure at entry", weight=1.0))

    r = candidate.regime
    if r is not None and getattr(r, "valid", False) and r.regime != "UNKNOWN":
        conds.append(Condition(REGIME, r.regime,
                               detail=f"{candidate.strategy_id} was taken in "
                                      f"a {r.regime} market", weight=0.7))

    if initial_stop is not None:
        conds.append(Condition(
            LEVEL, initial_stop,
            detail="the level whose break invalidates the trade", weight=1.5))

    return Thesis(symbol=candidate.symbol, direction=candidate.direction,
                  conditions=conds, strategy_id=candidate.strategy_id,
                  strategy_version=candidate.strategy_version,
                  entry_price=entry_price, initial_stop=initial_stop,
                  initial_target=initial_target,
                  target_logic=(f"target at {initial_target}"
                                if initial_target is not None else ""),
                  setup_key=candidate.key, decision_id=decision_id)


def evaluate(thesis, observation):
    """(state, findings) — is the reason for this trade still true?

    `observation` is what the platform measures NOW, in the same vocabulary the
    conditions were written in:

        {"htfTrend": "BULLISH", "structureTrend": "BULLISH",
         "regime": "TRENDING", "price": 1.1042, "momentum": "neutral"}

    A condition whose current value could not be read is UNKNOWN, and unknown
    never counts as broken. Closing a position because a data feed hiccuped is
    the one failure mode worse than holding one too long.
    """
    findings, broken, held, unknown = [], 0.0, 0.0, 0.0

    for c in thesis.conditions:
        now = None
        if c.kind == HTF_ALIGNMENT:
            now = observation.get("htfTrend")
        elif c.kind == STRUCTURE:
            now = observation.get("structureTrend")
        elif c.kind == REGIME:
            now = observation.get("regime")
        elif c.kind == MOMENTUM:
            now = observation.get("momentum")
        elif c.kind == LEVEL:
            now = observation.get("price")

        if now is None:
            findings.append({"kind": c.kind, "expected": c.expected,
                             "actual": None, "state": "UNKNOWN",
                             "detail": "not readable now"})
            unknown += c.weight
            continue

        if c.kind == LEVEL:
            # The stop level. Broken means price traded through it — which the
            # broker's own stop handles; this is here so the thesis reports the
            # same fact rather than a different one.
            try:
                through = (float(now) <= float(c.expected)
                           if thesis.direction == "BUY"
                           else float(now) >= float(c.expected))
            except (TypeError, ValueError):
                findings.append({"kind": c.kind, "expected": c.expected,
                                 "actual": now, "state": "UNKNOWN",
                                 "detail": "level not comparable"})
                unknown += c.weight
                continue
            ok = not through
        else:
            ok = (str(now).upper() == str(c.expected).upper())

        findings.append({"kind": c.kind, "expected": c.expected, "actual": now,
                         "state": "HOLDS" if ok else "BROKEN",
                         "detail": c.detail})
        # LEVEL is a backstop, not a reason. When it breaks it is decisive on
        # its own (below). When it HOLDS it must not count as evidence the
        # thesis is intact, because it holds for every trade that has simply
        # not stopped out yet — counting it would tilt every evaluation toward
        # "still valid" and make the engine reluctant to ever call an
        # invalidation, which is the exact bias this module exists to remove.
        if c.kind == LEVEL:
            continue
        if ok:
            held += c.weight
        else:
            broken += c.weight

    # The stop level breaking ends the trade on its own terms, whatever else
    # still holds — checked before the tally so it cannot be outvoted.
    if any(f["kind"] == LEVEL and f["state"] == "BROKEN" for f in findings):
        return INVALIDATED, findings

    total = held + broken + unknown
    if total <= 0:
        return UNREADABLE, findings
    if unknown >= total:
        return UNREADABLE, findings

    known = held + broken
    if known <= 0:
        return UNREADABLE, findings
    if broken == 0:
        return VALID, findings
    if broken >= known * 0.5:
        return INVALIDATED, findings
    return WEAKENING, findings


def describe(thesis, state, findings):
    """The thesis as the trade screen and the copilot read it."""
    lines = [f"{thesis.symbol} {thesis.direction} — thesis {state}"]
    for f in findings:
        mark = {"HOLDS": "+", "BROKEN": "x", "UNKNOWN": "?"}.get(f["state"], "?")
        lines.append(f"  [{mark}] {f['kind']}: expected {f['expected']}, "
                     f"now {f['actual']}")
    return "\n".join(lines)
