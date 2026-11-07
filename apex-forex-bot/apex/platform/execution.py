"""ExecutionRequest — what we would ask the broker for, and what must hold.

A REQUEST, NOT AN ORDER. Building one places nothing. It still passes
`gates.authorize_order`, exactly like every other origin. This module creates
no second path to the broker and imports no broker.

THE RULE THAT GIVES THIS FILE ITS SHAPE: a constraint marked required is
refused when it cannot be met — never quietly dropped.

The failure this prevents is specific. A client sets "never fill worse than
2 points of slippage". The broker connector cannot express that for this
order type. The tempting behaviour is to send a plain market order and hope;
the client then believes a limit protected them that was never applied. So
`from_decision()` refuses, with the constraint named. A refused request is
visible. A silently dropped constraint is not.
"""

import uuid

# Constraint kinds. Required ones refuse; advisory ones degrade and say so.
REQUIRED = "required"
ADVISORY = "advisory"

# Refusal codes for the request itself, distinct from a rule's refusal codes.
NOT_EXECUTABLE = "NOT_EXECUTABLE"
CONSTRAINT_UNSUPPORTED = "CONSTRAINT_UNSUPPORTED"
SIZING_FAILED = "SIZING_FAILED"
NO_STOP = "NO_STOP"


class ExecutionRefused(RuntimeError):
    """Raised instead of building a degraded request."""

    def __init__(self, code, detail, constraint=None):
        self.code, self.detail, self.constraint = code, detail, constraint
        super().__init__(f"{code}: {detail}")


class Constraint:
    """Something that must (or should) hold for the fill to be acceptable."""

    __slots__ = ("name", "value", "kind")

    def __init__(self, name, value, kind=REQUIRED):
        if kind not in (REQUIRED, ADVISORY):
            raise ValueError(f"constraint kind must be {REQUIRED} or "
                             f"{ADVISORY}, got {kind!r}")
        self.name, self.value, self.kind = name, value, kind

    @property
    def required(self):
        return self.kind == REQUIRED

    def as_dict(self):
        return {"name": self.name, "value": self.value, "kind": self.kind}

    def __repr__(self):
        return f"<Constraint {self.name}={self.value!r} {self.kind}>"


class ExecutionRequest:
    """One intended order, traceable back to the rule that produced it."""

    __slots__ = ("request_id", "user_id", "account_id", "symbol", "side",
                 "order_type", "volume", "price", "stop_loss", "take_profit",
                 "max_slippage_points", "expires_after_sec", "rule_doc_id",
                 "rule_doc_version", "decision_id", "constraints", "mode",
                 "reason")

    def __init__(self, *, user_id, account_id, symbol, side, order_type,
                 volume, rule_doc_id, rule_doc_version, decision_id, mode,
                 reason, price=None, stop_loss=None, take_profit=None,
                 max_slippage_points=None, expires_after_sec=None,
                 constraints=None, request_id=None):
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        if mode not in ("demo", "live"):
            # Not defaulted. An order whose environment nobody stated is an
            # order that might be real money by accident.
            raise ValueError(f"mode must be 'demo' or 'live', got {mode!r}")
        if not volume or volume <= 0:
            raise ValueError("volume must be > 0")
        self.request_id = request_id or uuid.uuid4().hex
        self.user_id = str(user_id)
        self.account_id = str(account_id)
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.volume = volume
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.max_slippage_points = max_slippage_points
        self.expires_after_sec = expires_after_sec
        self.rule_doc_id = rule_doc_id
        self.rule_doc_version = rule_doc_version
        self.decision_id = decision_id
        self.constraints = list(constraints or [])
        self.mode = mode
        self.reason = reason

    @property
    def required_constraints(self):
        return [c for c in self.constraints if c.required]

    def as_dict(self):
        return {
            "requestId": self.request_id, "userId": self.user_id,
            "accountId": self.account_id, "symbol": self.symbol,
            "side": self.side, "orderType": self.order_type,
            "volume": self.volume, "price": self.price,
            "stopLoss": self.stop_loss, "takeProfit": self.take_profit,
            "maxSlippagePoints": self.max_slippage_points,
            "expiresAfterSec": self.expires_after_sec,
            "ruleDocId": self.rule_doc_id,
            "ruleDocVersion": self.rule_doc_version,
            "decisionId": self.decision_id,
            "constraints": [c.as_dict() for c in self.constraints],
            "mode": self.mode, "reason": self.reason,
        }

    def __repr__(self):
        return (f"<ExecutionRequest {self.side} {self.volume} {self.symbol} "
                f"{self.mode} rule={self.rule_doc_version}>")


def from_decision(decision, rule_doc, *, user_id, account_id, volume, mode,
                  decision_id, stop_loss=None, take_profit=None,
                  supported=None):
    """Build a request from a decision, or refuse.

    `supported` is the set of constraint names the execution path can actually
    honour. Passing it in — rather than asking a broker here — keeps this
    module free of I/O and lets a test state the capability exactly.

    Refuses when:
      * the decision is not executable (HOLD, REJECT, CLOSE);
      * a required constraint is not in `supported`;
      * no stop loss is given, since sizing and worst case both depend on it.
    """
    if not decision.executable:
        raise ExecutionRefused(
            NOT_EXECUTABLE,
            f"{decision.verdict} does not open a position"
            + (f" ({decision.refusal_code})" if decision.refusal_code else ""))

    if stop_loss is None:
        raise ExecutionRefused(
            NO_STOP, "a request without a stop has no defined worst case")

    order = (rule_doc or {}).get("order") or {}
    constraints = []
    slip = order.get("maxSlippagePoints")
    if slip is not None:
        # Required: the client asked for a ceiling on fill quality. Sending
        # the order without it would be a different order than the one
        # configured.
        constraints.append(Constraint("maxSlippagePoints", slip, REQUIRED))
    exp = order.get("expiresAfterSec")
    if exp is not None:
        constraints.append(Constraint("expiresAfterSec", exp, REQUIRED))

    if supported is not None:
        ok = set(supported)
        for c in constraints:
            if c.required and c.name not in ok:
                raise ExecutionRefused(
                    CONSTRAINT_UNSUPPORTED,
                    f"{c.name} is required by the rule but the execution path "
                    f"cannot honour it — refusing rather than sending a "
                    f"different order than the one configured",
                    constraint=c.name)

    return ExecutionRequest(
        user_id=user_id, account_id=account_id, symbol=decision.symbol,
        side=decision.side or decision.verdict,
        order_type=order.get("type", "MARKET"), volume=volume,
        stop_loss=stop_loss, take_profit=take_profit,
        max_slippage_points=slip, expires_after_sec=exp,
        rule_doc_id=decision.rule_doc_id,
        rule_doc_version=decision.rule_doc_version,
        decision_id=decision_id, constraints=constraints, mode=mode,
        reason=decision.reason)
