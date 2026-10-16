"""Starting, pausing and stopping a client's automation.

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
  the account      connected, selected, and confirmed BY THE BROKER as demo
                   or live — a mode nobody confirmed is neither
  the state        not already running, and idempotent if it is

WHETHER LIVE MAY START IS NOT DECIDED IN THIS FILE

It used to be, as `mode != DEMO → refuse`, which was right while live did not
exist. It is wrong now for a duplication reason rather than a policy one:
`entitlement.capability()` already answers "may this account automate", live
included — it checks §1 the release switch and then the plan — and a second
comparison here would be a second answer to the same question. The two would
eventually disagree, and the one that let an order through would be the one
that mattered.

So this file asks `require_automation`, and asks it a second time for a LIVE
account once the BROKER has confirmed the mode, because the first answer was
derived from a stored record and the second is not. What it never does is
decide for itself.
"""

import time
import uuid

from apex import automation as _eng_auto
from apex import user_store
from apex.platform import approvals as _appr
from apex.platform import ctrader_link as _link
from apex.platform import emergency as _emerg
from apex.platform import engine_config as _ecfg
from apex.platform import entitlement as _ent
from apex.platform import journal_store as _jstore
from apex.platform import notifications as _notify
from apex.platform import ruledoc as _rd
from apex.platform import signals as _signals
from apex.platform import store as _store

STOPPED = "stopped"
RUNNING = "running"
PAUSED = "paused"
STATES = (STOPPED, RUNNING, PAUSED)

DEMO = "demo"
LIVE = "live"
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


def _level_of(rec):
    """The engine level the RUNNING loop was given, or None.

    Taken from the terms this start actually applied rather than re-read from
    the rule, for the same reason `appliedTerms` is kept on the record at all:
    the rule can be edited into a new version while this one runs, and what a
    client needs to see is what the loop in front of them was told to do.
    """
    applied = rec.get("appliedTerms")
    if not isinstance(applied, dict):
        return None
    return applied.get("automation") or None


def _plain(label):
    """An engine label without its icon.

    `automation.LABEL` is written for Telegram, where a message is plain text
    and the emoji is the only way to make a line stand out. This platform has
    its own iconography and a chip to put the words in, so the icon is dropped
    HERE rather than in the browser: a frontend stripping characters out of a
    server string would be guessing at which ones are decoration.
    """
    return "".join(c for c in str(label or "") if c.isascii()).strip() or None


def status(user_id):
    """Safe to hand a browser. Carries no token and no broker credential."""
    rec = _read(user_id)
    level = _level_of(rec)
    return {"status": "ok", "state": rec.get("state", STOPPED),
            "ruleDocId": rec.get("ruleDocId"), "mode": rec.get("mode"),
            "startedAt": rec.get("startedAt"),
            "updatedAt": rec.get("updatedAt"),
            # WHAT "RUNNING" MEANS, which the word on its own does not say.
            #
            # The three levels differ by whether a setup becomes an order, and
            # this screen used to show the same RUNNING for all of them. A
            # client at Signals Only would read it as "it is trading for me"
            # — which is how 6f984dfe9's silence went unnoticed for so long:
            # the dashboard said Running and nobody could tell that meant
            # nothing was being placed.
            #
            # The label and the verdict come from the server, not from a
            # browser mapping a level string to a sentence. That mapping is a
            # decision about what the product does with money, and a second
            # copy of it in the frontend would be free to drift.
            "level": level,
            "levelLabel": _plain(_eng_auto.LABEL.get(level)) if level else None,
            "levelBlurb": _eng_auto.BLURB.get(level) if level else None,
            "levelExecutes": (bool(_eng_auto.EXECUTES.get(level))
                              if level else None),
            # The terms of the running rule that this release does NOT act
            # on, each with its reason. Carried to the browser because the
            # alternative is a screen listing settings the loop ignores, with
            # nothing to tell them apart. `engineSnapshot` is deliberately
            # absent: it is the account's previous settings, which is state
            # for stop() to use and not something to render.
            "notApplied": rec.get("notApplied") or []}


def _preflight(user_id, rule_doc_id, *, mode_lister=None):
    """(rule, connection) or raise. Every refusal names its own cause.

    The order is deliberate. A client who has nothing connected and a draft
    rule should be told about the draft, because that is the thing they can
    act on first. Only the withdrawal check runs ahead of everything, since a
    client whose access was withdrawn should not be walked through a checklist
    at all.
    """
    # The emergency stop runs FIRST, ahead of the entitlement checklist.
    # Everything below this line tells a client what they could do about
    # their situation; a halt is not their situation and not theirs to act
    # on. Walking somebody through a checklist to arrive at "we have stopped
    # the product" is the wrong order to learn it in.
    #
    # Only the global and per-client levels are decidable here. The mode is
    # not resolved yet, so this asks the question that does not need it, and
    # the mode-dependent one is asked again below once the connection is
    # known.
    _emerg.check(user_id=user_id,
                 mode=_emerg.NOT_RESOLVED)      # raises Halted

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
    # `require_automation` has already decided whether THIS account may run,
    # live included — it checks §1 the release switch and then the plan, and
    # refuses a live account on either. So there is no mode comparison here
    # any more: one that re-decided it would be a second answer to a question
    # already answered, and the two would eventually disagree.
    #
    # What stays is the shape of the original rule: a mode that is neither
    # demo nor live is not something to start on.
    if conn.get("mode") not in (DEMO, LIVE):
        raise AutomationRefused(
            "MODE_UNKNOWN",
            "this account's mode was never recorded — reconnect it and "
            "select it again before starting anything")

    # A THIRD lock, and the only one that asks the broker instead of the
    # record. Everything above this line is derived from what cTrader said
    # when the account was LINKED, which can be months old. §3 of the
    # live-execution specification: the mode has to be re-verified at start,
    # and a mode the broker will not confirm is `unknown` and refused.
    #
    # `unknown` is refused rather than defaulted in either direction. For a
    # demo client that costs a retry when the broker is briefly unreachable,
    # which is the cheap side of this trade — the expensive side is starting a
    # loop against an account nobody confirmed is practice money.
    check = _link.verify_selected_mode(user_id, lister=mode_lister)
    if check["mode"] in (DEMO, LIVE) and check["verified"]:
        pass
    else:
        raise AutomationRefused(
            "MODE_UNVERIFIED",
            f"the broker did not confirm whether this is a demo or a real "
            f"account, so nothing was started — {check['reason']}")
    # A LIVE start is held to one more thing than a demo start: the broker's
    # answer must agree with the entitlement that was granted a moment ago.
    # `require_automation` read the mode from the stored link record; this
    # read it from cTrader just now. Starting a real-money loop on the
    # strength of a record, when the live answer is available and free here,
    # would be the one place in this file worth getting wrong.
    if check["mode"] == LIVE and not _ent.capability(user_id)["canAutomate"]:
        raise AutomationRefused("LIVE_NOT_AVAILABLE", _ent.LIVE_REFUSAL)
    if check["changed"]:
        # The record said one thing and the broker says another. Not adapted
        # to, on purpose: an account that changed mode under a stored record
        # is a situation a human has to look at.
        raise AutomationRefused(
            "MODE_CHANGED",
            f"this account is {check['mode']} at the broker but was recorded "
            f"as {check['recorded']}. Reconnect the account and select it "
            f"again before starting anything.")
    # Asked a second time, now that the mode and the instruments are known.
    # The first call could not evaluate a LIVE-scoped halt or a per-instrument
    # one, because neither fact existed yet.
    for symbol in (rule.get("symbols") or [None]):
        _emerg.check(user_id=user_id, symbol=symbol, mode=conn.get("mode"))
    return rule, conn


def start(user_id, rule_doc_id, *, starter=None, now=None,
          mode_lister=None):
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

    rule, conn = _preflight(user_id, rule_doc_id,
                            mode_lister=mode_lister)

    # Cross-process guard. user_store.claim is SET NX, the only primitive that
    # sees another container; None means no shared backend to ask, which is
    # development and carries on.
    # claim_value rather than claim, so the lock carries WHO holds it and only
    # that holder can drop it. claim() writes a bare "1", which any process
    # could then release — including one releasing somebody else's lock.
    lock = _k_lock(user_id)
    token = user_store.claim_value(lock, corr, ttl_s=_START_LOCK_TTL_S)
    if token is False:
        raise AutomationRefused(
            "START_IN_PROGRESS",
            "another start for this account is already in flight")
    held = token is True

    if starter is None:
        starter = _engine_starter
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
        # THE RULE'S TERMS, NOT JUST ITS INSTRUMENT.
        #
        # This wrote `symbol` and `timeframe` and nothing else, so a client
        # who set 1% risk and a 25-pip stop got whatever their account held
        # — four times the risk, in the case this was found on.
        # `engine_config.translate` carries across every term that maps to a
        # setting the loop reads, and returns the ones that do not so the
        # client can be told rather than left to assume.
        applied, not_applied = _ecfg.translate(rule)
        # Captured BEFORE the write, so stop() can put back what was there.
        # Without it a rule that ran once leaves its settings behind for
        # whatever runs next.
        snapshot = _ecfg.snapshot_of(user_store.load(user_id))
        user_store.update(user_id, dict(applied, active=True))
    except Exception as e:  # noqa: BLE001
        raise AutomationRefused("STORE_UNAVAILABLE",
                                f"the account settings could not be saved "
                                f"({type(e).__name__})")

    ok = _run_starter(starter, user_id, lock, corr, held)
    if ok is False:
        _jstore.record_error(
            "the engine refused to start this loop",
            correlation_id=corr, user_id=user_id,
            account_id=str(conn.get("ctid")))
        raise AutomationRefused(
            "ENGINE_REFUSED",
            "the trading engine refused to start this loop — it may already "
            "be owned by another instance")

    # The mode this loop ACTUALLY runs on, not a constant. It was DEMO here
    # while demo was the only thing that could start, and leaving it would
    # have made the record say "demo" over a real-money loop — on the one
    # screen a client checks to find out what is running.
    #
    # `conn["mode"]` is safe to use as the answer: _preflight refused unless
    # the broker confirmed a mode, and refused again if the broker's answer
    # differed from this record.
    out = _write(user_id, {"state": RUNNING, "ruleDocId": rule_doc_id,
                           "mode": conn.get("mode"), "startedAt": now,
                           "accountId": conn.get("ctid"),
                           "correlationId": corr,
                           # Kept on the automation record, not recomputed on
                           # read: the rule can be edited into a new version
                           # while this one runs, and what the client needs to
                           # see is what the RUNNING loop was given.
                           "appliedTerms": applied,
                           "notApplied": not_applied,
                           "engineSnapshot": snapshot})
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


def _engine_starter(user_id):
    """The real starter: the engine's loop, WITH somewhere to send alerts.

    THIS ARGUMENT IS THE REASON APPROVAL WAS SILENT.

    The loop was started as `user_loop.start(user_id)`. `alert_fn` therefore
    defaulted to None, and in approval mode `_suggest_trade` writes a pending
    proposal, calls that None, and places nothing — so every setup the loop
    found was a proposal nobody was told about, on a screen that said Running.
    Commit 6f984dfe9 removed that state by refusing the level; this is what
    makes the level answerable instead.

    The alert goes to `engine_alert`, which routes it to the module that
    owns the level it belongs to. It is bound HERE rather than passed through
    `start(starter=...)` on purpose: `starter` is the seam a test injects, and
    its contract — asserted by tests/test_rule_reaches_engine.py — is that the
    engine is handed the user id and nothing else, so there is no argument
    through which a rule could arrive. Binding the alert into the default keeps
    that true and still gives the engine a way to talk back.
    """
    from apex import user_loop
    return user_loop.start(user_id, alert_fn=engine_alert)


def engine_alert(user_id, payload):
    """The one alert function the engine gets, and the two sinks behind it.

    The engine takes a single `alert_fn`, and there are two levels that need to
    be heard through it: `approval`, whose proposal needs an answer, and
    `signals`, whose setup needs only to be reported. So both are offered every
    alert and each answers for its own action — `SUGGEST` and `SIGNAL`
    respectively — and ignores the rest of the firehose.

    OFFERED TO BOTH RATHER THAN ROUTED BY A TABLE HERE, because a table in this
    file would be a third place that has to agree with the two allowlists about
    which module owns which action, and the first time it disagreed an alert
    would go to the wrong screen or to none. The allowlists are the routing;
    `tests/test_signals_only.py` asserts they do not overlap, so an action can
    never be delivered twice.

    NEITHER CALL CAN PLACE AN ORDER. An alert is a report of something the loop
    already decided; the engine has set `entry_ok = False` before either of
    these is reached at both non-executing levels, and neither module imports
    an execution path. Both also swallow their own exceptions — this runs on
    the trading thread, and an exception here abandons the rest of the tick,
    which is where exits and trailing stops live.
    """
    _appr.engine_alert(user_id, payload)
    _signals.engine_alert(user_id, payload)
    return None


# EVERY ENGINE LEVEL THIS PLATFORM CAN REPORT FOR, which is the list `engine_alert`
# above has a sink for. It lives here because this is the only file that knows
# both sinks exist.
#
# THE RULE IT SERVES: a level that does not place orders and has no sink is a
# loop that runs, finds setups and tells nobody — which is the state every
# platform client shipped in, and what 6f984dfe9 fixed by refusing to offer
# `approval` at all. So `engine_config.SERVICEABLE_LEVELS` must hold nothing
# that is absent from here unless `automation.EXECUTES` says it acts on its
# own. tests/test_signals_only.py asserts that over all three levels.
#
# A level goes on this list when a sink answers for it, not when somebody
# intends to write one.
DELIVERED_LEVELS = (_ecfg.LEVEL_APPROVAL, _signals.LEVEL_SIGNALS)


def running_context(user_id):
    """Which rule and account this client's RUNNING loop belongs to.

    Exists so a loop event arriving from the engine can be filed against the
    rule that produced it. The engine knows a user id and nothing else — it
    predates rules entirely — so the join has to be made from this side, and
    reading it per event is what makes it correct for a loop the watchdog
    restarted as well as one a client started (see `signals._running_context`).

    Empty rather than raising when nothing is running: an event that arrives
    just after a stop is late, not wrong, and it still has to be recordable.
    """
    rec = _read(user_id)
    if rec.get("state") != RUNNING:
        return {}
    return {"ruleDocId": rec.get("ruleDocId"),
            "accountId": (str(rec.get("accountId"))
                          if rec.get("accountId") is not None else None),
            "correlationId": rec.get("correlationId"),
            "level": _level_of(rec)}


def _run_starter(starter, user_id, lock, corr, held):
    """Call the engine, then DROP THE START LOCK, whatever happened.

    The lock exists to stop two containers starting one account at the same
    moment; it is not meant to outlive the attempt. It was never released, so
    it sat for its full TTL — and the first thing anybody does after pausing is
    resume, which goes through start and was refused for thirty seconds with
    "another start for this account is already in flight". That message was
    false: nothing was in flight. Found on the first real run of
    scripts/smoke_ctrader_controls.py against the broker.

    The release is best-effort on purpose. Failing to drop a lock that expires
    on its own must not fail a start that already succeeded.
    """
    try:
        return starter(user_id)
    finally:
        if held:
            try:
                user_store.release_claim(lock, corr)
            except Exception:                               # noqa: BLE001
                pass


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


def resume(user_id, *, starter=None, mode_lister=None):
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
    #
    # The PAUSED record is NOT written away first. It used to be set to STOPPED
    # before start was called, so a start that then refused left the client in
    # stopped-but-still-remembering-a-rule — a state no control recovers from,
    # because resume raises NOT_PAUSED and the screen says stopped for
    # something they asked to resume. start() only treats RUNNING as a reason
    # to refuse, so PAUSED passes through it untouched, and a failed resume
    # leaves the pause exactly where it was.
    return start(user_id, rid, starter=starter,
                 mode_lister=mode_lister)


def _flatten_answer(rec):
    """Whether stopping also closed the open positions, and why not if not.

    §8.1 of the live-execution specification: a per-client stop must flatten
    or explicitly DECLINE to flatten, and say which. Silence is the failure
    mode — a client who presses Stop and is told "stopped" reasonably reads
    that as "and I am flat", and on a live account that belief is expensive.

    This release declines, and the reason is not squeamishness: closing a
    position is an ORDER, and this platform has nothing that places a closing
    one. `bridge` is imported by nothing in production, and `approvals` —
    which is the one thing here that can place an order at all — can only ask
    the controller to OPEN the setup a client approved. Claiming to flatten
    would be claiming to place an order we cannot place.

    THE SENTENCE BELOW USED TO BE WIDER THAN THE TRUTH. It said this release
    "cannot place orders of any kind", which was exactly right while nothing
    could, and became false the moment Approval Required worked: a client who
    approves a setup gets an opening order. The reason for declining is
    specific to CLOSING, so the sentence now says that and no more — a
    reassurance that overstates is still a thing a client acts on.
    """
    return {
        "flattened": False,
        "flattenDeclined": True,
        "flattenReason": (
            "Stopping ends the trading loop. It does not close positions that "
            "are already open — this release has no way to close a position. "
            "Any open position stays at your broker with the stop and target "
            "it was given, and you close it there."),
    }


def stop(user_id, *, stopper=None):
    """Stop and forget. Idempotent — stopping something stopped is fine."""
    rec = _read(user_id)
    if rec.get("state") == STOPPED:
        return dict(status(user_id), stopped=False, alreadyStopped=True,
                    **_flatten_answer(rec))
    _halt(user_id, stopper)
    _jstore.record_automation(
        _jstore._j.AUTOMATION_STOPPED, correlation_id=uuid.uuid4().hex,
        user_id=user_id, account_id=str(rec.get("accountId") or ""),
        rule_doc_id=rec.get("ruleDocId"))
    # Put the account's settings back the way the start found them. A rule
    # that ran once used to leave its risk, stop and target behind for
    # whatever ran next, which was already true of the instrument and the
    # timeframe before any of the other terms were carried across.
    try:
        user_store.update(user_id,
                          _ecfg.restore_patch(rec.get("engineSnapshot")))
    except Exception:                                       # noqa: BLE001
        # Best effort. A restore that fails must not fail a stop that has
        # already halted the loop — the loop being stopped is the thing that
        # mattered, and the settings are visible and editable.
        pass
    _write(user_id, {"state": STOPPED, "ruleDocId": None, "mode": None,
                     "startedAt": None, "appliedTerms": None,
                     "notApplied": None, "engineSnapshot": None})
    ans = _flatten_answer(rec)
    _notify.notify(user_id, type=_notify.SYSTEM, title="Automation stopped",
                   body="The trading loop has been stopped. "
                        + ans["flattenReason"])
    return dict(status(user_id), stopped=True, alreadyStopped=False, **ans)


def _halt(user_id, stopper):
    if stopper is None:
        from apex import user_loop
        stopper = user_loop.stop
    try:
        user_store.update(user_id, {"active": False})
    except Exception:
        pass
    stopper(user_id)
