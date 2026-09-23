"""Starting, pausing and stopping a client's automation. Demo only, for now.

CONNECTING A BROKER ACCOUNT DOES NOT START ANYTHING

That is the whole reason this is a separate, explicit act with its own
endpoint and its own state. A client who links cTrader to look at their
balance has not asked to be traded for, and a platform that reads a
connection as consent is a platform that surprises people with positions.

WHAT MUST BE TRUE BEFORE A LOOP RUNS, CHECKED IN THIS ORDER

  the session      re-verified against Supabase, not read from cache
  the licence      ACTIVE; unknown is not active (see licence.py)
  the rule         exists, belongs to this client, and is ACTIVE — a draft
                   has never been validated-and-frozen, so it has no terms
  the account      connected, selected, and DEMO. Live is refused here and
                   again in the connection accessor
  the state        not already running, and idempotent if it is

LIVE IS NOT IMPLEMENTED, NOT MERELY BLOCKED

There is no branch in this module that starts a live loop, and no flag that
would enable one. `mode` is compared against DEMO and anything else refuses.
When live is built it will be a deliberate piece of work with its own review,
not a boolean somebody flips.
"""

import time
import uuid

from apex import user_store
from apex.platform import ctrader_link as _link
from apex.platform import entitlement as _ent
from apex.platform import journal_store as _jstore
from apex.platform import notifications as _notify
from apex.platform import ruledoc as _rd
from apex.platform import store as _store

STOPPED = "stopped"
RUNNING = "running"
PAUSED = "paused"
STATES = (STOPPED, RUNNING, PAUSED)

DEMO = "demo"
_START_LOCK_TTL_S = 30


class AutomationRefused(RuntimeError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _k(user_id):
    return f"{_store._ns()}:{_store._P}:automation:{user_id}"


def _k_lock(user_id):
    return f"{_store._ns()}:{_store._P}:autolock:{user_id}"


def _read(user_id):
    rec = _store._read(_k(str(user_id)))
    if not isinstance(rec, dict) or str(rec.get("userId")) != str(user_id):
        return {"userId": str(user_id), "state": STOPPED, "ruleDocId": None,
                "mode": None, "startedAt": None, "updatedAt": None}
    return rec


def _write(user_id, rec):
    rec["userId"] = str(user_id)
    rec["updatedAt"] = time.time()
    _store._write(_k(str(user_id)), rec)
    return rec


def status(user_id):
    """Safe to hand a browser. Carries no token and no broker credential."""
    rec = _read(user_id)
    return {"status": "ok", "state": rec.get("state", STOPPED),
            "ruleDocId": rec.get("ruleDocId"), "mode": rec.get("mode"),
            "startedAt": rec.get("startedAt"),
            "updatedAt": rec.get("updatedAt")}


def _preflight(user_id, rule_doc_id):
    """(rule, connection) or raise. Every refusal names its own cause.

    The order is deliberate. A client who has nothing connected and a draft
    rule should be told about the draft, because that is the thing they can
    act on first. Only the withdrawal check runs ahead of everything, since a
    client whose access was withdrawn should not be walked through a checklist
    at all.
    """
    # Demo automation is free. This checks only that access has not been
    # WITHDRAWN — see apex/platform/entitlement.py for why an absent licence
    # is the free tier rather than a refusal.
    _ent.require_activation(user_id)            # raises NotEntitled

    rule = _store.get(user_id, rule_doc_id)     # raises NotFound — ownership
    if rule.get("state") != _rd.ACTIVE:
        raise AutomationRefused(
            "RULE_NOT_ACTIVE",
            f"this rule is {rule.get('state')!r}. Activate it first — a draft "
            f"has never been validated and frozen, so there are no terms to "
            f"trade")

    conn = _link.get_ctrader_connection(user_id)
    if not conn:
        raise AutomationRefused(
            "NO_ACCOUNT",
            "connect a cTrader account and select one before starting")
    # Two independent locks on the same door, on purpose. The entitlement
    # module decides from the stored link record; this line decides from the
    # connection actually resolved for this start. They agree today, and if a
    # future change makes them disagree, the start is refused rather than
    # taking whichever answer came first.
    _ent.require_automation(user_id)            # raises NotEntitled
    if conn.get("mode") != DEMO:
        raise AutomationRefused("LIVE_NOT_AVAILABLE", _ent.LIVE_REFUSAL)
    return rule, conn


def start(user_id, rule_doc_id, *, starter=None, now=None):
    """Begin automation for one rule, on a demo account. Idempotent."""
    now = time.time() if now is None else now
    user_id = str(user_id)
    corr = uuid.uuid4().hex

    rec = _read(user_id)
    if rec.get("state") == RUNNING and rec.get("ruleDocId") == rule_doc_id:
        # Idempotent on purpose: a double-tapped button, a retried request or
        # a second browser tab must not produce a second loop against one
        # account. Answering "already running" is the truth, not a failure.
        return dict(status(user_id), started=False, alreadyRunning=True)
    if rec.get("state") == RUNNING:
        raise AutomationRefused(
            "ALREADY_RUNNING",
            f"automation is already running for rule {rec.get('ruleDocId')}. "
            f"Stop it before starting another")

    rule, conn = _preflight(user_id, rule_doc_id)

    # Cross-process guard. user_store.claim is SET NX, the only primitive that
    # sees another container; None means no shared backend to ask, which is
    # development and carries on.
    token = user_store.claim(_k_lock(user_id), ttl_s=_START_LOCK_TTL_S)
    if token is False:
        raise AutomationRefused(
            "START_IN_PROGRESS",
            "another start for this account is already in flight")

    if starter is None:
        from apex import user_loop
        starter = user_loop.start
    # NOTE WHAT IS ABSENT: `paper`. Exactly one place writes the live/demo
    # flag — telegram._handle_paper, the writer that applies every activation
    # gate — and test_live_path_invariants.py enforces that there is only one.
    # Writing it here would have made this a second one, in the file with the
    # fewest of those gates.
    #
    # It is not needed. _preflight above has already established that the
    # selected account is DEMO, and _make_broker derives the mode from that
    # same connection rather than from a stored boolean that could drift.
    try:
        user_store.update(user_id, {
            "active": True,
            "symbol": (rule.get("symbols") or [None])[0],
            "timeframe": rule.get("timeframe"),
        })
    except Exception as e:  # noqa: BLE001
        raise AutomationRefused("STORE_UNAVAILABLE",
                                f"the account settings could not be saved "
                                f"({type(e).__name__})")

    ok = starter(user_id)
    if ok is False:
        _jstore.record_error(
            "the engine refused to start this loop",
            correlation_id=corr, user_id=user_id,
            account_id=str(conn.get("ctid")))
        raise AutomationRefused(
            "ENGINE_REFUSED",
            "the trading engine refused to start this loop — it may already "
            "be owned by another instance")

    out = _write(user_id, {"state": RUNNING, "ruleDocId": rule_doc_id,
                           "mode": DEMO, "startedAt": now,
                           "accountId": conn.get("ctid"),
                           "correlationId": corr})
    _jstore.record_automation(
        _jstore._j.AUTOMATION_STARTED, correlation_id=corr, user_id=user_id,
        account_id=str(conn.get("ctid")), rule_doc_id=rule_doc_id,
        rule_doc_version=rule.get("version"),
        detail=f"demo account {conn.get('ctid')}")
    _notify.notify(user_id, type=_notify.SYSTEM,
                   title="Automation started",
                   body=f"Running {rule.get('name') or rule_doc_id} on demo "
                        f"account {conn.get('ctid')}.",
                   correlation_id=corr)
    return dict(status(user_id), started=True, alreadyRunning=False)


def pause(user_id, *, stopper=None):
    """Stop the loop but remember which rule was running.

    Pausing stops the engine rather than merely flagging it. A 'paused' state
    that left a loop ticking would be the most dangerous word on the screen.
    """
    rec = _read(user_id)
    if rec.get("state") != RUNNING:
        raise AutomationRefused(
            "NOT_RUNNING", f"automation is {rec.get('state')}, not running")
    _halt(user_id, stopper)
    _write(user_id, dict(rec, state=PAUSED))
    _jstore.record_automation(
        _jstore._j.AUTOMATION_PAUSED, correlation_id=uuid.uuid4().hex,
        user_id=user_id, account_id=str(rec.get("accountId") or ""),
        rule_doc_id=rec.get("ruleDocId"))
    _notify.notify(user_id, type=_notify.SYSTEM, title="Automation paused",
                   body="No new positions will be opened until you resume.")
    return dict(status(user_id), paused=True)


def resume(user_id, *, starter=None):
    rec = _read(user_id)
    if rec.get("state") != PAUSED:
        raise AutomationRefused(
            "NOT_PAUSED", f"automation is {rec.get('state')}, not paused")
    rid = rec.get("ruleDocId")
    if not rid:
        raise AutomationRefused("NO_RULE",
                                "this paused automation has no rule recorded")
    # Everything is re-checked. A licence can lapse and a rule can be archived
    # while automation sits paused, and resuming is a fresh start, not the
    # undoing of a pause.
    _write(user_id, dict(rec, state=STOPPED))
    return start(user_id, rid, starter=starter)


def stop(user_id, *, stopper=None):
    """Stop and forget. Idempotent — stopping something stopped is fine."""
    rec = _read(user_id)
    if rec.get("state") == STOPPED:
        return dict(status(user_id), stopped=False, alreadyStopped=True)
    _halt(user_id, stopper)
    _jstore.record_automation(
        _jstore._j.AUTOMATION_STOPPED, correlation_id=uuid.uuid4().hex,
        user_id=user_id, account_id=str(rec.get("accountId") or ""),
        rule_doc_id=rec.get("ruleDocId"))
    _write(user_id, {"state": STOPPED, "ruleDocId": None, "mode": None,
                     "startedAt": None})
    _notify.notify(user_id, type=_notify.SYSTEM, title="Automation stopped",
                   body="The trading loop has been stopped.")
    return dict(status(user_id), stopped=True, alreadyStopped=False)


def _halt(user_id, stopper):
    if stopper is None:
        from apex import user_loop
        stopper = user_loop.stop
    try:
        user_store.update(user_id, {"active": False})
    except Exception:
        pass
    stopper(user_id)
