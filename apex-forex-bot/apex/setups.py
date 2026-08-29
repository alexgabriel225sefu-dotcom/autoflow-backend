"""A setup candidate — the thing the scanner produces and the engine judges.

WHY THIS EXISTS

Setup detection, ranking, the decision and the order were one straight line of
code inside `user_loop._loop`. That line works, but nothing in it can be
inspected: there is no object to rank, no object to explain, no object to
record when the setup is REJECTED, and no object a test can construct without
starting a trading loop.

The consequence a client sees is §61 — "why didn't APEX trade?" cannot be
answered for anything the scanner silently skipped, because the skip left no
trace. The scanner evaluated seven other instruments on every pass and threw
all seven readings away.

WHAT A CANDIDATE IS NOT

It is not permission to trade. A candidate carries no size, no order, and no
authority. `gates.authorize_order` remains the only thing that can permit an
order, and it never sees this object — the decision engine hands it a symbol,
a side and a size that deterministic code computed.

STATUS IS A MEASUREMENT, NOT A MOOD

    INVALID    the data itself is unusable — too few candles, no price,
               a broker read that failed. NOT "the setup looks weak".
    WATCH      a real structure is forming but its trigger has not fired.
    CANDIDATE  the trigger fired and the setup is complete.
    READY      it also passed the pre-risk feasibility checks.
    EXPIRED    it was one of the above and its own invalidation fired first.

The distinction between INVALID and WATCH matters more than it looks. Merging
them produces a screen that says "no setup" when the truth is "we could not
read the market", and a client cannot tell a quiet session from a broken feed.
"""

import time
import uuid

# ── Status vocabulary ────────────────────────────────────────────────────
INVALID = "INVALID"
WATCH = "WATCH"
CANDIDATE = "CANDIDATE"
READY = "READY"
EXPIRED = "EXPIRED"

STATUSES = (INVALID, WATCH, CANDIDATE, READY, EXPIRED)

# Only these transitions are legal (§55). A candidate cannot go back to WATCH
# once its trigger fired: the trigger is a fact about a moment, and rewinding
# it would let one setup fire twice.
_TRANSITIONS = {
    INVALID: {WATCH, CANDIDATE, EXPIRED},
    WATCH: {CANDIDATE, EXPIRED, INVALID},
    CANDIDATE: {READY, EXPIRED, INVALID},
    READY: {EXPIRED, INVALID},
    EXPIRED: set(),
}


def can_transition(old, new):
    """Whether `old -> new` is a legal status change."""
    if old == new:
        return True
    return new in _TRANSITIONS.get(old, set())


# ── Identity ─────────────────────────────────────────────────────────────
# A setup's identity is what makes it the SAME setup across ticks. Without it
# the scanner produces a fresh candidate every few seconds and §32's duplicate
# suppression has nothing to key on. Deliberately coarse: symbol, direction,
# strategy and the bar the trigger fired on. Two detections of the same
# structure on the same bar are one setup.
def setup_key(symbol, direction, strategy_id, bar_ts):
    return f"{str(symbol).upper()}:{direction}:{strategy_id}:{int(bar_ts or 0)}"


class SetupCandidate:
    """One detected setup, at one moment, on one instrument.

    Every field is either measured or explicitly absent. Nothing here is
    defaulted to a plausible value: a missing spread is None, not zero, because
    a zero spread reads as a perfect fill.
    """

    __slots__ = ("id", "key", "symbol", "direction", "detected_at", "timeframe",
                 "regime", "features", "trigger_state", "invalidation",
                 "strategy_id", "strategy_version", "config_version",
                 "evidence", "status", "status_reason", "rank_score",
                 "rank_reasons", "bar_ts")

    def __init__(self, *, symbol, direction, timeframe, strategy_id,
                 strategy_version, config_version=None, bar_ts=None,
                 regime=None, features=None, trigger_state=None,
                 invalidation=None, evidence=None, status=WATCH,
                 status_reason="", detected_at=None):
        if direction not in ("BUY", "SELL"):
            raise ValueError(f"direction must be BUY or SELL, got {direction!r}")
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        self.id = uuid.uuid4().hex[:16]
        self.symbol = str(symbol).upper()
        self.direction = direction
        self.timeframe = timeframe
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.config_version = config_version
        self.bar_ts = bar_ts
        self.key = setup_key(symbol, direction, strategy_id, bar_ts)
        self.detected_at = detected_at or time.time()
        self.regime = regime                      # a regime.Reading, or None
        self.features = dict(features or {})
        self.trigger_state = trigger_state or {}
        # What would make this setup wrong. Recorded at DETECTION, so the
        # position manager later compares against the reason the trade was
        # taken rather than against whatever looks reasonable now (§17).
        self.invalidation = list(invalidation or [])
        self.evidence = list(evidence or [])
        self.status = status
        self.status_reason = status_reason
        self.rank_score = None
        self.rank_reasons = []

    # ── status ───────────────────────────────────────────────────────────
    def set_status(self, new, reason=""):
        """Move to `new`, or raise. Illegal transitions are a bug, not a state."""
        if not can_transition(self.status, new):
            raise ValueError(
                f"illegal setup transition {self.status} -> {new} "
                f"({self.symbol} {self.direction})")
        self.status, self.status_reason = new, reason
        return self

    @property
    def tradeable(self):
        """Only READY is tradeable. CANDIDATE means complete, not approved."""
        return self.status == READY

    # ── evidence ─────────────────────────────────────────────────────────
    def add_evidence(self, name, value, *, passed=None, detail=""):
        """One observation that fed the decision.

        `passed` is tri-state on purpose. True/False are verdicts; None means
        the check could not be evaluated — an unread spread is not a passed
        spread check, and §61's screen has to be able to show that difference.
        """
        self.evidence.append({"name": name, "value": value,
                              "passed": passed, "detail": detail})
        return self

    def failed_checks(self):
        return [e["name"] for e in self.evidence if e.get("passed") is False]

    def unknown_checks(self):
        return [e["name"] for e in self.evidence if e.get("passed") is None]

    # ── serialisation ────────────────────────────────────────────────────
    def to_dict(self):
        """The wire form. Read models and the journal both use this.

        `regime` is flattened to its own dict so a stored candidate does not
        depend on the regime module still existing in the same shape when it
        is read back months later.
        """
        return {
            "id": self.id,
            "key": self.key,
            "symbol": self.symbol,
            "direction": self.direction,
            "detectedAt": round(self.detected_at, 3),
            "timeframe": self.timeframe,
            "barTs": self.bar_ts,
            "regime": (self.regime.to_dict()
                       if hasattr(self.regime, "to_dict") else self.regime),
            "features": self.features,
            "triggerState": self.trigger_state,
            "invalidation": self.invalidation,
            "strategyId": self.strategy_id,
            "strategyVersion": self.strategy_version,
            "configVersion": self.config_version,
            "evidence": self.evidence,
            "status": self.status,
            "statusReason": self.status_reason,
            "rankScore": self.rank_score,
            "rankReasons": self.rank_reasons,
        }

    def __repr__(self):
        return (f"<SetupCandidate {self.symbol} {self.direction} "
                f"{self.strategy_id} {self.status}"
                + (f" score={self.rank_score}" if self.rank_score is not None else "")
                + ">")


def invalid(symbol, reason, *, timeframe=None, direction="BUY",
            strategy_id="none", strategy_version="0"):
    """A candidate that records WHY the market could not be read.

    This is the object the scanner produces when a symbol fails, and it is the
    whole reason the scanner stops being a black box: an instrument that could
    not be evaluated is now visible as exactly that, instead of being
    indistinguishable from one that was evaluated and found uninteresting.
    """
    c = SetupCandidate(symbol=symbol, direction=direction, timeframe=timeframe,
                       strategy_id=strategy_id, strategy_version=strategy_version,
                       status=INVALID, status_reason=reason)
    c.add_evidence("market_data", None, passed=False, detail=reason)
    return c
