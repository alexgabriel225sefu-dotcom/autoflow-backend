"""JournalEntry — the record that answers "why was this order opened, or not?"

Every evaluation and every execution produces one. The entry links the
configuration, the reading, the verdict, the request and the broker's answer,
so the question can be answered from stored data rather than reconstructed
from logs.

THE CORRELATION ID IS THE POINT. One evaluation may produce a decision, a
request, a broker call and an error. All of them carry the same
`correlation_id`, so the chain can be pulled back out in one query. Without it
the pieces exist but cannot be joined, which is the same as not having them.

NO SECRETS. `redact()` is applied on the way in, not on the way out: an entry
that never held a token cannot leak one later through a log, an export or a
support screenshot.
"""

import time
import uuid

# What produced the entry.
EVALUATION = "evaluation"
EXECUTION = "execution"
BROKER_RESULT = "broker_result"
ERROR = "error"
POSITION = "position"
AUTOMATION = "automation"
KINDS = (EVALUATION, EXECUTION, BROKER_RESULT, ERROR, POSITION, AUTOMATION)

# ── status ──────────────────────────────────────────────────────────────────
# `kind` says which STAGE an entry belongs to. `status` says which of the nine
# things that can actually happen it IS, and it is the field a client filters
# on, because "show me the rejected orders" is a question about outcome, not
# about stage. Deriving it here rather than leaving callers to invent strings
# is what keeps "order_rejected" from being spelled three ways.
EVALUATED = "evaluated"            # the rule ran
HOLD = "hold"                      # it ran and chose not to act
REJECT = "reject"                  # it could not run
EXECUTION_REQUESTED = "execution_requested"   # a request was built
ORDER_SENT = "order_sent"          # handed to the execution controller
ORDER_CONFIRMED = "order_confirmed"           # the broker took it
ORDER_REJECTED = "order_rejected"  # the broker or a gate refused it
POSITION_CLOSED = "position_closed"
BROKER_ERROR = "broker_error"

# Turning automation on and off is evidence too — "who started this, and
# when" is a question an account owner asks. It is NOT filed under
# BROKER_ERROR, which is what recording a successful start through
# for_error() would have done: a journal whose errors include every ordinary
# success is a journal nobody can search for real errors in.
AUTOMATION_STARTED = "automation_started"
AUTOMATION_PAUSED = "automation_paused"
AUTOMATION_STOPPED = "automation_stopped"

STATUSES = (EVALUATED, HOLD, REJECT, EXECUTION_REQUESTED, ORDER_SENT,
            ORDER_CONFIRMED, ORDER_REJECTED, POSITION_CLOSED, BROKER_ERROR,
            AUTOMATION_STARTED, AUTOMATION_PAUSED, AUTOMATION_STOPPED)

# Anything whose name looks like a credential is dropped, whatever its value.
_SECRET_HINTS = ("token", "secret", "password", "apikey", "api_key",
                 "client_secret", "access", "refresh", "authorization",
                 "cookie", "session")


def new_correlation_id():
    return uuid.uuid4().hex


def redact(obj, *, _depth=0):
    """A copy with credential-looking keys removed.

    Matches on the KEY, not the value: a token is still a token when it looks
    like an ordinary string, and guessing from values would both miss real
    secrets and mangle innocent data.
    """
    if _depth > 8:
        return "<too deep>"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            low = str(k).lower()
            if any(h in low for h in _SECRET_HINTS):
                out[k] = "<redacted>"
            else:
                out[k] = redact(v, _depth=_depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth=_depth + 1) for v in obj]
    return obj


class JournalEntry:
    """One link in the chain, already redacted."""

    __slots__ = ("entry_id", "kind", "status", "ts", "correlation_id",
                 "user_id", "account_id", "rule_doc_id", "rule_doc_version",
                 "symbol", "snapshot", "decision", "execution_request",
                 "broker_result", "position", "error")

    def __init__(self, *, kind, correlation_id, user_id, status=None,
                 account_id=None, rule_doc_id=None, rule_doc_version=None,
                 symbol=None, snapshot=None, decision=None,
                 execution_request=None, broker_result=None, position=None,
                 error=None, ts=None, entry_id=None):
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        if status is not None and status not in STATUSES:
            # Refused rather than stored. A status nobody can filter on is
            # worse than none: it looks like a category and is invisible to
            # every query that matters.
            raise ValueError(f"status must be one of {STATUSES}, "
                             f"got {status!r}")
        self.status = status
        if not correlation_id:
            raise ValueError("a journal entry without a correlation id cannot "
                             "be joined to the rest of its chain")
        self.entry_id = entry_id or uuid.uuid4().hex
        self.kind = kind
        self.ts = float(ts if ts is not None else time.time())
        self.correlation_id = correlation_id
        self.user_id = str(user_id)
        self.account_id = account_id
        self.rule_doc_id = rule_doc_id
        self.rule_doc_version = rule_doc_version
        self.symbol = symbol
        self.snapshot = redact(snapshot) if snapshot else None
        self.decision = redact(decision) if decision else None
        self.execution_request = (redact(execution_request)
                                  if execution_request else None)
        self.broker_result = redact(broker_result) if broker_result else None
        self.position = redact(position) if position else None
        self.error = error

    def as_dict(self):
        return {
            "entryId": self.entry_id, "kind": self.kind, "ts": self.ts,
            "correlationId": self.correlation_id, "userId": self.user_id,
            "status": self.status,
            "accountId": self.account_id, "ruleDocId": self.rule_doc_id,
            "ruleDocVersion": self.rule_doc_version, "symbol": self.symbol,
            "snapshot": self.snapshot, "decision": self.decision,
            "executionRequest": self.execution_request,
            "brokerResult": self.broker_result, "position": self.position,
            "error": self.error,
        }

    def __repr__(self):
        return (f"<JournalEntry {self.kind} {self.symbol or '-'} "
                f"corr={self.correlation_id[:8]}>")


def for_evaluation(decision, snapshot, *, correlation_id, user_id,
                   account_id=None, ts=None):
    """The entry every evaluation writes — including the ones that do nothing.

    A HOLD is journalled too. "Why did nothing happen today?" is a question
    clients ask, and it is unanswerable if only trades are recorded.
    """
    return JournalEntry(
        kind=EVALUATION, correlation_id=correlation_id, user_id=user_id,
        status={"HOLD": HOLD, "REJECT": REJECT}.get(decision.verdict,
                                                    EVALUATED),
        account_id=account_id, rule_doc_id=decision.rule_doc_id,
        rule_doc_version=decision.rule_doc_version, symbol=decision.symbol,
        snapshot=snapshot.as_dict() if snapshot else None,
        decision=decision.as_dict(), ts=ts)


def for_execution(request, *, correlation_id, result=None, ts=None):
    """The request, and what came back.

    `result` is recorded even when it is a refusal. An execution entry that
    only ever appears on success would make the journal answer "why was this
    order opened?" while staying silent on "why was this one not?", which is
    the question a client asks far more often.
    """
    # A result that is present and not an error means the controller accepted
    # it; a result carrying an error means it was refused. No result at all
    # means the request was built but not yet handed over.
    if result is None:
        _status = EXECUTION_REQUESTED
    elif isinstance(result, dict) and (result.get("error")
                                       or result.get("ok") is False):
        _status = ORDER_REJECTED
    else:
        _status = ORDER_CONFIRMED
    return JournalEntry(
        kind=EXECUTION, correlation_id=correlation_id, status=_status,
        user_id=request.user_id, account_id=request.account_id,
        rule_doc_id=request.rule_doc_id,
        rule_doc_version=request.rule_doc_version, symbol=request.symbol,
        execution_request=request.as_dict(), broker_result=result, ts=ts)


def for_error(message, *, correlation_id, user_id, account_id=None,
              symbol=None, ts=None):
    return JournalEntry(
        kind=ERROR, correlation_id=correlation_id, user_id=user_id,
        status=BROKER_ERROR, account_id=account_id, symbol=symbol,
        error=str(message)[:500], ts=ts)


def for_order_sent(request, *, correlation_id, ts=None):
    """Handed to the execution controller; the broker has not answered yet.

    Separate from for_execution because the gap between "sent" and "confirmed"
    is exactly where an ambiguous broker failure lives, and a journal that
    cannot show that gap cannot explain one.
    """
    return JournalEntry(
        kind=EXECUTION, correlation_id=correlation_id, status=ORDER_SENT,
        user_id=request.user_id, account_id=request.account_id,
        rule_doc_id=request.rule_doc_id,
        rule_doc_version=request.rule_doc_version, symbol=request.symbol,
        execution_request=request.as_dict(), ts=ts)


def for_automation(status, *, correlation_id, user_id, account_id=None,
                   rule_doc_id=None, rule_doc_version=None, detail=None,
                   ts=None):
    if status not in (AUTOMATION_STARTED, AUTOMATION_PAUSED,
                      AUTOMATION_STOPPED):
        raise ValueError(f"not an automation status: {status!r}")
    return JournalEntry(
        kind=AUTOMATION, correlation_id=correlation_id, status=status,
        user_id=user_id, account_id=account_id, rule_doc_id=rule_doc_id,
        rule_doc_version=rule_doc_version, error=None,
        position={"detail": detail} if detail else None, ts=ts)


def for_position_closed(position, *, correlation_id, user_id,
                        account_id=None, symbol=None, rule_doc_id=None,
                        rule_doc_version=None, ts=None):
    return JournalEntry(
        kind=POSITION, correlation_id=correlation_id, status=POSITION_CLOSED,
        user_id=user_id, account_id=account_id,
        symbol=symbol or (position or {}).get("symbol"),
        rule_doc_id=rule_doc_id, rule_doc_version=rule_doc_version,
        position=position, ts=ts)
