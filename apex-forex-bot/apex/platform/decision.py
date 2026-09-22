"""RuleDecision — what a rule concluded, and why.

NAMED RuleDecision, NOT Decision, DELIBERATELY.

`apex/gates.py` already defines `class Decision`: the AUTHORISATION verdict,
`(allowed, reason, detail)`, answering "may this order proceed?". This one
answers a different question — "what does the rule say?" — and the two meet on
the same code path. Two classes called Decision there would be a trap: reading
`.allowed` on the wrong one raises AttributeError on a good day and silently
confuses a reviewer on a bad one.

tests/test_platform_contracts.py asserts the two stay distinguishable.

WHY EVERY CONDITION RESULT IS KEPT

A verdict that says only "HOLD" cannot answer the product's core question:
"why did nothing happen?" So each evaluated condition is recorded with its id,
its parameters, whether it passed, and a human-readable detail. The reason
string is assembled FROM those results rather than written separately, so it
cannot drift from what was actually evaluated.
"""

# ── verdicts ────────────────────────────────────────────────────────────────
BUY = "BUY"
SELL = "SELL"
CLOSE = "CLOSE"
HOLD = "HOLD"
REJECT = "REJECT"
VERDICTS = (BUY, SELL, CLOSE, HOLD, REJECT)

# The only two that may ever become an ExecutionRequest for a NEW position.
ENTRY_VERDICTS = (BUY, SELL)

# ── refusal codes ───────────────────────────────────────────────────────────
# REJECT is not HOLD. HOLD means "the rule ran and its conditions were not
# met". REJECT means "the rule could not be run at all". Collapsing them would
# hide configuration errors behind a quiet no-trade.
RULE_INVALID = "RULE_INVALID"
RULE_NOT_ACTIVE = "RULE_NOT_ACTIVE"
UNKNOWN_CONDITION = "UNKNOWN_CONDITION"
CONDITION_ERROR = "CONDITION_ERROR"
SYMBOL_NOT_IN_RULE = "SYMBOL_NOT_IN_RULE"
TIMEFRAME_MISMATCH = "TIMEFRAME_MISMATCH"
SPREAD_LIMIT_EXCEEDED = "SPREAD_LIMIT_EXCEEDED"
MAX_POSITIONS_REACHED = "MAX_POSITIONS_REACHED"
OUTSIDE_SCHEDULE = "OUTSIDE_SCHEDULE"
SIDE_NOT_ALLOWED = "SIDE_NOT_ALLOWED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConditionResult:
    """One condition, evaluated."""

    __slots__ = ("condition_id", "params", "passed", "detail")

    def __init__(self, condition_id, passed, detail="", params=None):
        self.condition_id = condition_id
        self.passed = None if passed is None else bool(passed)
        self.detail = detail or ""
        self.params = dict(params or {})

    def as_dict(self):
        return {"id": self.condition_id, "params": self.params,
                "passed": self.passed, "detail": self.detail}

    def __repr__(self):
        mark = {True: "✓", False: "✗", None: "?"}[self.passed]
        return f"<{mark} {self.condition_id}>"


class RuleDecision:
    """The verdict, plus the evidence it was reached from."""

    __slots__ = ("verdict", "rule_doc_id", "rule_doc_version", "symbol",
                 "snapshot_ts", "conditions", "reason", "risk_level",
                 "confidence", "refusal_code", "side")

    def __init__(self, *, verdict, rule_doc_id, rule_doc_version, symbol,
                 snapshot_ts, conditions=None, reason="", risk_level=None,
                 confidence=None, refusal_code=None, side=None):
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}, "
                             f"got {verdict!r}")
        if verdict == REJECT and not refusal_code:
            # A refusal without a code cannot be acted on or explained.
            raise ValueError("a REJECT decision needs a refusal_code")
        self.verdict = verdict
        self.rule_doc_id = rule_doc_id
        self.rule_doc_version = rule_doc_version
        self.symbol = symbol
        self.snapshot_ts = snapshot_ts
        self.conditions = list(conditions or [])
        self.reason = reason
        self.risk_level = risk_level
        # Left None unless a real definition backs it. A number invented to
        # fill a field is worse than an absent one: it looks like evidence.
        self.confidence = confidence
        self.refusal_code = refusal_code
        self.side = side

    @property
    def executable(self):
        """Only an entry verdict may become an order for a NEW position.

        HOLD and REJECT are not executable, and neither is CLOSE here — a
        close goes through gates.authorize_close on its own path, not through
        an ExecutionRequest for a new position.
        """
        return self.verdict in ENTRY_VERDICTS

    @property
    def passed_conditions(self):
        return [c for c in self.conditions if c.passed is True]

    @property
    def failed_conditions(self):
        return [c for c in self.conditions if c.passed is False]

    def as_dict(self):
        return {
            "verdict": self.verdict,
            "ruleDocId": self.rule_doc_id,
            "ruleDocVersion": self.rule_doc_version,
            "symbol": self.symbol,
            "snapshotTs": self.snapshot_ts,
            "side": self.side,
            "conditions": [c.as_dict() for c in self.conditions],
            "reason": self.reason,
            "riskLevel": self.risk_level,
            "confidence": self.confidence,
            "executable": self.executable,
            "refusalCode": self.refusal_code,
        }

    def __repr__(self):
        tail = f" {self.refusal_code}" if self.refusal_code else ""
        return (f"<RuleDecision {self.verdict}{tail} {self.symbol} "
                f"v{self.rule_doc_version}>")


# ── constructors for the common shapes ──────────────────────────────────────
def hold(*, rule_doc_id, rule_doc_version, symbol, snapshot_ts,
         conditions=None, reason=""):
    """The rule ran; its conditions were not met."""
    return RuleDecision(verdict=HOLD, rule_doc_id=rule_doc_id,
                        rule_doc_version=rule_doc_version, symbol=symbol,
                        snapshot_ts=snapshot_ts, conditions=conditions,
                        reason=reason or "conditions not met")


def reject(*, rule_doc_id, rule_doc_version, symbol, snapshot_ts, code,
           reason, conditions=None):
    """The rule could not be run. Always carries a code."""
    return RuleDecision(verdict=REJECT, rule_doc_id=rule_doc_id,
                        rule_doc_version=rule_doc_version, symbol=symbol,
                        snapshot_ts=snapshot_ts, conditions=conditions,
                        reason=reason, refusal_code=code)
