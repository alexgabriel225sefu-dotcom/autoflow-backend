"""The APEX decision engine — what the platform decided, and on what grounds.

WHAT THIS IS FOR

Two screens depend entirely on this module existing:

    WHY DID APEX ENTER?          §26
    WHY DIDN'T APEX TRADE?       §61

Neither can be answered by asking a model afterwards. §24 is explicit that
replay must not call the current AI and ask why a past trade happened, because
the answer would be a plausible reconstruction rather than the reason. So the
reason has to be RECORDED at the moment of the decision, in a form that does
not change when the strategy changes.

That is what a Decision is: the conditions that were checked, which of them
passed, which failed, which could not be evaluated, and the action that
followed — stamped with the versions that were live at the time.

WHAT THIS IS NOT

It is not permission to trade, and it never touches a broker. ENTER_PROPOSED
is a proposal. `gates.authorize_order` is still the only thing that can permit
an order, it runs after this, and it can refuse a proposal this engine made.
§13's path is:

    decision proposal -> deterministic validation -> risk engine -> execution

This module is the first box. It does not import a broker, and it must not.
"""

import time
import uuid

from apex import ranking as _ranking
from apex import regime as _regime
from apex import setups as _setups

# ── Actions ──────────────────────────────────────────────────────────────
NO_TRADE = "NO_TRADE"
WATCH = "WATCH"
CANDIDATE = "CANDIDATE"
ENTER_PROPOSED = "ENTER_PROPOSED"

ACTIONS = (NO_TRADE, WATCH, CANDIDATE, ENTER_PROPOSED)

DECISION_VERSION = "1.0.0"

# ── Reason codes ─────────────────────────────────────────────────────────
# Stable identifiers. The wording on screen may be rewritten; these may not,
# because they are what a stored decision is read back by. §61 shows the code
# beside the sentence for exactly that reason.
NO_MARKET_DATA = "NO_MARKET_DATA"
DATA_STALE = "DATA_STALE"
SETUP_INCOMPLETE = "SETUP_INCOMPLETE"
SETUP_EXPIRED = "SETUP_EXPIRED"
SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
REGIME_MISMATCH = "REGIME_MISMATCH"
REGIME_UNKNOWN = "REGIME_UNKNOWN"
HTF_CONFLICT = "HTF_CONFLICT"
CONFIDENCE_BELOW_MIN = "CONFIDENCE_BELOW_MIN"
EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
SYMBOL_ALREADY_OPEN = "SYMBOL_ALREADY_OPEN"
CORRELATED_EXPOSURE = "CORRELATED_EXPOSURE"
RISK_HALTED = "RISK_HALTED"
COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
OUTRANKED = "OUTRANKED"
AI_BLOCKED = "AI_BLOCKED"
AI_UNAVAILABLE = "AI_UNAVAILABLE"
NOT_RANKABLE = "NOT_RANKABLE"
ALL_CONDITIONS_MET = "ALL_CONDITIONS_MET"

# Sentences for the screen. A code with no sentence still renders — as the code
# — because a missing translation must never hide a recorded reason.
REASON_TEXT = {
    NO_MARKET_DATA: "market data could not be read for this instrument",
    DATA_STALE: "the market data was older than the freshness limit",
    SETUP_INCOMPLETE: "the setup's trigger has not fired yet",
    SETUP_EXPIRED: "the setup invalidated before it could be taken",
    SPREAD_TOO_HIGH: "the spread was too large for the stop this trade needs",
    REGIME_MISMATCH: "this strategy is not built for the current market",
    REGIME_UNKNOWN: "the market regime could not be read",
    HTF_CONFLICT: "the higher timeframe is going the other way",
    CONFIDENCE_BELOW_MIN: "the setup scored below the configured minimum",
    EXPOSURE_LIMIT: "the account is already at its position limit",
    SYMBOL_ALREADY_OPEN: "there is already a position on this instrument",
    CORRELATED_EXPOSURE: "this would add to an exposure already held elsewhere",
    RISK_HALTED: "the risk engine has paused trading",
    COOLDOWN_ACTIVE: "this instrument is in a cooldown after a recent trade",
    OUTRANKED: "another candidate ranked higher for the free slot",
    AI_BLOCKED: "the analysis layer disagreed with the rule signal",
    AI_UNAVAILABLE: "the analysis layer could not be reached",
    NOT_RANKABLE: "too little could be measured to rank this setup",
    ALL_CONDITIONS_MET: "every checked condition was satisfied",
}

# Codes that mean "do not trade this, at all, now" as opposed to "not this
# one, this pass". The difference matters to the scanner: an OUTRANKED
# candidate is worth re-evaluating next tick, a RISK_HALTED one is not.
HARD_BLOCKS = frozenset({
    NO_MARKET_DATA, DATA_STALE, SETUP_EXPIRED, SPREAD_TOO_HIGH,
    EXPOSURE_LIMIT, SYMBOL_ALREADY_OPEN, CORRELATED_EXPOSURE, RISK_HALTED,
    COOLDOWN_ACTIVE, AI_BLOCKED,
})


def reason_text(code):
    return REASON_TEXT.get(code, code)


class Decision:
    """One decision, with everything needed to explain it later."""

    __slots__ = ("id", "at", "symbol", "direction", "action", "reason_codes",
                 "evidence", "regime", "strategy_id", "strategy_version",
                 "config_version", "risk_context", "invalidation", "source",
                 "model_version", "data_version", "setup_id", "setup_key",
                 "rank_score", "account_env")

    def __init__(self, *, symbol, action, direction=None, reason_codes=None,
                 evidence=None, regime=None, strategy_id=None,
                 strategy_version=None, config_version=None, risk_context=None,
                 invalidation=None, source="scanner", model_version=None,
                 data_version=None, setup_id=None, setup_key=None,
                 rank_score=None, account_env=None, at=None):
        if action not in ACTIONS:
            raise ValueError(f"unknown decision action {action!r}")
        self.id = uuid.uuid4().hex[:16]
        self.at = at or time.time()
        self.symbol = str(symbol).upper()
        self.direction = direction
        self.action = action
        self.reason_codes = list(reason_codes or [])
        self.evidence = list(evidence or [])
        self.regime = regime
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.config_version = config_version
        self.risk_context = dict(risk_context or {})
        self.invalidation = list(invalidation or [])
        self.source = source
        self.model_version = model_version
        self.data_version = data_version
        self.setup_id = setup_id
        self.setup_key = setup_key
        self.rank_score = rank_score
        self.account_env = account_env

    @property
    def proposes_entry(self):
        return self.action == ENTER_PROPOSED

    def to_dict(self):
        return {
            "decisionId": self.id,
            "at": round(self.at, 3),
            "symbol": self.symbol,
            "direction": self.direction,
            "action": self.action,
            "reasonCodes": self.reason_codes,
            "reasons": [{"code": c, "text": reason_text(c)}
                        for c in self.reason_codes],
            "evidence": self.evidence,
            "regime": (self.regime.to_dict()
                       if hasattr(self.regime, "to_dict") else self.regime),
            "strategyId": self.strategy_id,
            "strategyVersion": self.strategy_version,
            "configVersion": self.config_version,
            "decisionVersion": DECISION_VERSION,
            "rankingVersion": _ranking.RANKING_VERSION,
            "riskContext": self.risk_context,
            "invalidation": self.invalidation,
            "source": self.source,
            "modelVersion": self.model_version,
            "dataVersion": self.data_version,
            "setupId": self.setup_id,
            "setupKey": self.setup_key,
            "rankScore": self.rank_score,
            "environment": self.account_env,
        }

    def __repr__(self):
        return (f"<Decision {self.symbol} {self.action} "
                f"{','.join(self.reason_codes) or '-'}>")


def _from_candidate(c, action, codes, *, risk_context=None, source="scanner",
                    account_env=None, model_version=None):
    return Decision(
        symbol=c.symbol, direction=c.direction, action=action,
        reason_codes=codes, evidence=list(c.evidence), regime=c.regime,
        strategy_id=c.strategy_id, strategy_version=c.strategy_version,
        config_version=c.config_version, invalidation=list(c.invalidation),
        setup_id=c.id, setup_key=c.key, rank_score=c.rank_score,
        risk_context=risk_context, source=source, account_env=account_env,
        model_version=model_version)


def evaluate(candidate, *, policy, risk_context=None, account_env=None,
             slots_free=1, model_version=None, source="scanner"):
    """One candidate -> one Decision. Deterministic. Never raises.

    `policy` carries the operator's configured limits, so nothing here is a
    magic constant (§71):

        min_confidence      int
        max_spread_ratio    float, spread / stop distance
        require_htf         bool
        allow_unknown_regime bool

    The order of checks is deliberate and mirrors `gates.authorize_order`:
    cheapest and most decisive first, so the recorded reason is the FIRST
    thing that was actually wrong rather than whichever check happened to run
    last. A client reading "spread too high" on a setup that was also outside
    its regime learns less than one reading the earliest true cause.
    """
    codes = []

    # 0. Could the market be read at all? Nothing below means anything if not.
    if candidate.status == _setups.INVALID:
        return _from_candidate(candidate, NO_TRADE, [NO_MARKET_DATA],
                               risk_context=risk_context, source=source,
                               account_env=account_env)
    if candidate.status == _setups.EXPIRED:
        return _from_candidate(candidate, NO_TRADE, [SETUP_EXPIRED],
                               risk_context=risk_context, source=source,
                               account_env=account_env)

    rc = dict(risk_context or {})

    # 1. Account-level blocks. These are true regardless of the setup, so they
    #    are checked before anything about the setup is considered.
    if rc.get("halted"):
        return _from_candidate(candidate, NO_TRADE, [RISK_HALTED],
                               risk_context=rc, source=source,
                               account_env=account_env)
    if rc.get("dataStale"):
        return _from_candidate(candidate, NO_TRADE, [DATA_STALE],
                               risk_context=rc, source=source,
                               account_env=account_env)
    if rc.get("sameSymbolOpen"):
        return _from_candidate(candidate, NO_TRADE, [SYMBOL_ALREADY_OPEN],
                               risk_context=rc, source=source,
                               account_env=account_env)
    if rc.get("cooldownUntil", 0) > time.time():
        return _from_candidate(candidate, NO_TRADE, [COOLDOWN_ACTIVE],
                               risk_context=rc, source=source,
                               account_env=account_env)
    if rc.get("correlatedExposure"):
        return _from_candidate(candidate, NO_TRADE, [CORRELATED_EXPOSURE],
                               risk_context=rc, source=source,
                               account_env=account_env)

    # 2. Is the setup even finished? An unfired trigger is WATCH, not a
    #    rejection — the difference is what makes a watchlist possible.
    if candidate.status == _setups.WATCH:
        return _from_candidate(candidate, WATCH, [SETUP_INCOMPLETE],
                               risk_context=rc, source=source,
                               account_env=account_env)

    # 3. Cost. Checked early because it is objective and, past the limit, no
    #    amount of setup quality compensates for it.
    spread = candidate.features.get("spreadPips")
    sl = candidate.features.get("slPips")
    max_ratio = policy.get("max_spread_ratio")
    if spread is not None and sl and max_ratio:
        try:
            if float(spread) / float(sl) > float(max_ratio):
                codes.append(SPREAD_TOO_HIGH)
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    # 4. Regime. UNKNOWN is its own answer and the operator decides whether it
    #    blocks — §8 says not to force a classification, and forcing a DECISION
    #    on an unforced classification would be the same mistake one step later.
    r = candidate.regime
    if r is None or not getattr(r, "valid", False) or r.regime == _regime.UNKNOWN:
        if not policy.get("allow_unknown_regime", True):
            codes.append(REGIME_UNKNOWN)
    elif r.fits(candidate.strategy_id) is False:
        codes.append(REGIME_MISMATCH)

    # 5. Higher timeframe, when the operator requires agreement.
    if policy.get("require_htf"):
        htf = candidate.features.get("htfTrend")
        want = "BULLISH" if candidate.direction == "BUY" else "BEARISH"
        if htf in ("BULLISH", "BEARISH") and htf != want:
            codes.append(HTF_CONFLICT)

    # 6. The strategy's own bar.
    conf = candidate.features.get("confidence")
    min_conf = policy.get("min_confidence")
    if conf is not None and min_conf is not None and float(conf) < float(min_conf):
        codes.append(CONFIDENCE_BELOW_MIN)

    # 7. Room on the account.
    if slots_free is not None and slots_free <= 0:
        codes.append(EXPOSURE_LIMIT)

    if codes:
        return _from_candidate(candidate, NO_TRADE, codes, risk_context=rc,
                               source=source, account_env=account_env,
                               model_version=model_version)

    # 8. Nothing objected. A candidate that cannot be ranked still does not get
    #    proposed: the ranking is what decides which of several setups takes
    #    the free slot, and an unrankable one cannot take part in that.
    if candidate.rank_score is None:
        return _from_candidate(candidate, CANDIDATE, [NOT_RANKABLE],
                               risk_context=rc, source=source,
                               account_env=account_env,
                               model_version=model_version)

    return _from_candidate(candidate, ENTER_PROPOSED, [ALL_CONDITIONS_MET],
                           risk_context=rc, source=source,
                           account_env=account_env, model_version=model_version)


def evaluate_all(candidates, *, policy, risk_context=None, account_env=None,
                 slots_free=1, model_version=None, source="scanner"):
    """Rank, then decide — and record a decision for EVERY candidate.

    The losers are the point. Only the highest-ranked eligible candidates fill
    the free slots; the rest are recorded as OUTRANKED rather than discarded,
    which is what lets §61 answer for an instrument the scanner passed over.

    Returns (decisions, proposals) — proposals is the subset that reached
    ENTER_PROPOSED, best first, already truncated to the free slots.
    """
    ordered = _ranking.rank(candidates)
    decisions, proposals = [], []
    for c in ordered:
        remaining = slots_free - len(proposals) if slots_free is not None else None
        d = evaluate(c, policy=policy, risk_context=risk_context,
                     account_env=account_env, slots_free=remaining,
                     model_version=model_version, source=source)
        # A proposal that only failed because the slots are gone is reported as
        # OUTRANKED, not EXPOSURE_LIMIT: the account has room, this candidate
        # simply lost the queue. Those are different facts to a reader.
        if (d.action == NO_TRADE and d.reason_codes == [EXPOSURE_LIMIT]
                and proposals):
            d.reason_codes = [OUTRANKED]
        decisions.append(d)
        if d.proposes_entry:
            proposals.append(d)
    return decisions, proposals


def explain(decision):
    """A decision as the §26 / §61 screen reads it."""
    lines = [f"{decision.symbol} {decision.direction or ''} — {decision.action}"]
    for e in decision.evidence:
        mark = "?" if e.get("passed") is None else ("+" if e["passed"] else "x")
        lines.append(f"  [{mark}] {e.get('name')}: {e.get('value')}")
    for c in decision.reason_codes:
        lines.append(f"  reason: {c} — {reason_text(c)}")
    if not decision.evidence and not decision.reason_codes:
        lines.append("  No recorded APEX decision is available for this period.")
    return "\n".join(lines)
