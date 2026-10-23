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

import hashlib
import re
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


def risk_guard(user_id, *, reader=None):
    """What the Risk Guard last reported, as the LOOP published it.

    `{"state": "ok" | "holding" | "unknown", "reasons": [...]}`. Never raises
    and never recomputes: asking the guard to evaluate would advance the very
    state the badge describes (see `apex.ui_state`). "unknown" is a guard that
    has not reported — it is NOT "ok" and is never worded as the guard having
    said yes, which is the one line this badge must not get wrong.
    """
    try:
        if reader is None:
            from apex import ui_state
            reader = ui_state.risk_state
        state, reasons = reader(str(user_id))
        if state not in ("ok", "holding", "unknown"):
            state = "unknown"
        return {"state": state,
                "reasons": [str(r)[:160] for r in (reasons or [])][:5]}
    except Exception:                                        # noqa: BLE001
        return {"state": "unknown", "reasons": []}


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
            "notApplied": rec.get("notApplied") or [],
            # The Risk Guard's last report, so every screen can show it. Only
            # meaningful while a loop runs; the browser shows it then.
            "riskGuard": risk_guard(user_id)}


def why(user_id, *, loop_reader=None, declines_reader=None,
        market_open=None, risk_reader=None):
    """"Why isn't it trading?" — the answer the Telegram `/why` gave, for the web.

    A waiting client reads silence as breakage. This says which of the real
    reasons applies, in order of how much each one explains:

      stopped / paused      the loop is not looking at all
      halted                an emergency stop is in force
      loop not active here  the platform says Running, this process is not
                            running a loop for the client (a restart: the
                            supervisor revives it, which takes minutes)
      not an executing level  Signals only / Ask me first — a setup is not an
                            order by design
      position already open   the position limit is the reason
      market closed         nothing to act on
      otherwise             on and watching; most candidates are refused

    THE TWO LISTS OF REFUSALS ARE DIFFERENT THINGS and are not merged.
    `skips` is the loop's in-memory list for the current process: newest
    first, last thirty, empty after a restart. `recorded` is the persistent
    decision log: it has the instrument and survives a restart. A client whose
    list is empty must not be told "there was no reason" — `recordedCount` is
    0 only when the log holds nothing, and the screen words that as "nothing
    recorded yet", never as proof the loop chose nothing.

    The three readers are parameters so a test drives every branch without a
    live loop. Never raises: an unreadable source is reported as unreadable,
    since an explanation page that errors is the page nobody can use when
    something is already wrong.
    """
    rec = _read(user_id)
    state = rec.get("state", STOPPED)
    level = _level_of(rec)
    executes = (bool(_eng_auto.EXECUTES.get(level)) if level else None)

    out = {"status": "ok", "state": state, "level": level,
           "levelLabel": _plain(_eng_auto.LABEL.get(level)) if level else None,
           "loopActive": None, "marketOpen": None, "halted": False,
           "openPosition": None, "maxPositions": None,
           "riskGuard": risk_guard(user_id, reader=risk_reader),
           "skipsToday": None, "skips": [], "recorded": [],
           "recordedCount": 0, "recordedReadable": True}

    # ── the engine's own view, read defensively ─────────────────────────────
    try:
        if loop_reader is None:
            from apex import user_loop
            alive = bool(user_loop.is_running(str(user_id)))
            dash = user_loop.get_dash(str(user_id)) or {}
        else:
            alive, dash = loop_reader(str(user_id))
        out["loopActive"] = alive
        op = dash.get("openPosition")
        if isinstance(op, dict):
            out["openPosition"] = {"symbol": op.get("symbol")}
        out["maxPositions"] = dash.get("maxpos")
        out["skipsToday"] = dash.get("skipsToday")
        out["skips"] = [{"time": str(s.get("time", "")),
                         "reason": str(s.get("reason", ""))[:120]}
                        for s in (dash.get("skips") or [])[:10]
                        if isinstance(s, dict)]
    except Exception as e:                                   # noqa: BLE001
        print(f"[Automation:why] loop state unreadable "
              f"({type(e).__name__})")

    try:
        if declines_reader is None:
            from apex import trade_events
            rows = trade_events.declines(str(user_id), limit=10)
        else:
            rows = declines_reader(str(user_id))
        for r in rows or []:
            payload = r.get("payload") if isinstance(r, dict) else None
            out["recorded"].append({
                "at": r.get("ts") or r.get("time"),
                "symbol": r.get("symbol"),
                "reason": str((payload or {}).get("reason", ""))[:200]})
        out["recordedCount"] = len(out["recorded"])
    except Exception as e:                                   # noqa: BLE001
        out["recordedReadable"] = False
        print(f"[Automation:why] decision log unreadable "
              f"({type(e).__name__})")

    try:
        if market_open is None:
            from apex import forex as _fx
            out["marketOpen"] = bool(_fx.is_market_open())
        else:
            out["marketOpen"] = bool(market_open())
    except Exception:                                        # noqa: BLE001
        pass

    try:
        _emerg.check(user_id=user_id, mode=_emerg.NOT_RESOLVED)
    except _emerg.Halted:
        out["halted"] = True
    except Exception:                                        # noqa: BLE001
        pass

    # ── the verdict: ONE reason, the most explanatory that is true ──────────
    if out["halted"]:
        code, text = "halted", ("An emergency stop is in force, so nothing "
                                "will be placed until it is lifted.")
    elif state == PAUSED:
        code, text = "paused", ("Automation is paused. It is not looking for "
                                "setups until you resume it.")
    elif state != RUNNING:
        code, text = "stopped", ("Automation is stopped, which is why "
                                 "nothing is happening. Start it from a "
                                 "rule to switch it on.")
    elif out["loopActive"] is False:
        code, text = "loop_inactive", (
            "Automation is marked as running, but its loop is not active on "
            "the server right now. After a restart it is picked up again "
            "automatically; that can take up to about fifteen minutes.")
    elif out["riskGuard"]["state"] == "holding":
        why_txt = "; ".join(out["riskGuard"]["reasons"]) or "a risk limit was hit"
        code, text = "risk_holding", (
            f"The Risk Guard is holding new trades: {why_txt}. This protects "
            f"your account; it lifts when the limit no longer applies.")
    elif executes is False:
        code, text = "level_no_orders", (
            f"This rule runs at “{out['levelLabel']}”, so a setup is shown to "
            f"you and is not placed as a trade by itself.")
    elif out["openPosition"]:
        sym = out["openPosition"].get("symbol") or "an instrument"
        lim = out["maxPositions"] or 1
        code, text = "position_open", (
            f"You already have a position open on {sym}, and the limit is "
            f"{lim} at a time. It looks for the next setup once this one "
            f"closes.")
    elif out["marketOpen"] is False:
        code, text = "market_closed", ("The forex market is closed, so "
                                       "there is nothing to act on.")
    else:
        code, text = "watching", (
            "It is on and watching. It only enters when a setup passes every "
            "check, and most candidates are refused.")
    out["reason"] = code
    out["summary"] = text
    return out


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


def _note_engine_refused(user_id, corr, ctid, *, revive):
    """File the engine's refusal to start a loop — unless the supervisor asked.

    The supervisor retries a dead loop every few minutes and, right after a
    deploy, the previous instance still holds the lease for up to ten minutes,
    so the engine refuses each retry ("owned by another instance"). That is the
    EXPECTED shape of a restart, not a fault — and it was being written to the
    client's journal as "Broker error", once per retry (four entries after one
    deploy), none of them about the broker. A journal whose errors include
    every ordinary handover is one nobody can search for a real error in.

    An interactive Start the client pressed is different: they asked, so the
    refusal is theirs to see. It is filed as an ENGINE error, not a broker
    error: the engine said no, and the provider was never asked.
    """
    if revive:
        return
    _jstore.record_engine_error(
        "the engine refused to start this loop — it may already be owned by "
        "another instance",
        correlation_id=corr, user_id=user_id, account_id=str(ctid))


# What the cTrader connector says when the PROVIDER answered with a refusal.
# Only these count as "the broker rejected it". A timeout, a dropped socket, a
# KeyError or any other exception from our own code is the engine's or the
# network's, and is filed as such.
_PROVIDER_REJECTION_PREFIXES = (
    "ctrader error:", "ctrader order error:", "ctrader token error:",
    "app auth failed", "account auth failed",
)
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9_\-\.=+/]{24,}")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+\S+")
_KEYED = re.compile(
    r"(?i)\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"authorization|api[_-]?key|password|secret|token)\b\s*[=:]\s*\S+")


def _safe_cause(exc, *secrets):
    """`TypeName: message`, bounded and with anything credential-shaped removed.

    The text of an exception from a provider call can carry what was sent or
    what came back. It is cut to a sentence, every known secret is replaced,
    and so is anything that merely LOOKS like a token (a long unbroken run of
    token characters) or is named like one. Provider payloads are never
    attached — only this string.
    """
    text = str(exc)
    for sec in secrets:
        if sec and isinstance(sec, str) and len(sec) >= 8:
            text = text.replace(sec, "[redacted]")
    text = _BEARER.sub(r"\1 [redacted]", text)
    text = _KEYED.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    text = _TOKEN_LIKE.sub("[redacted]", text)
    text = " ".join(text.split())[:160]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _is_provider_rejection(exc):
    return str(exc).strip().lower().startswith(_PROVIDER_REJECTION_PREFIXES)


def _record_starter_failure(user_id, corr, conn, exc, *, revive):
    """Journal why the engine could not start, honestly labelled; return the cause.

    A provider's refusal is a BROKER error. Anything else — our own exception,
    a timeout, a dropped socket — is an ENGINE error: filing it as the broker's
    sends the client looking for a fault at a provider that did nothing.

    The supervisor's retries are deduplicated per cause for an hour: a fault
    that persists would otherwise fill the journal at one entry every three
    minutes, and the entry nobody has read yet is already enough.
    """
    cause = _safe_cause(exc, (conn or {}).get("accessToken"),
                        (conn or {}).get("refreshToken"))
    print(f"[Automation] starter failed for {user_id}: {cause}")
    if revive:
        try:
            first = user_store.claim(
                f"revive-err:{user_id}:{hashlib.sha1(cause.encode()).hexdigest()[:12]}",
                ttl_s=3600)
        except Exception:                                    # noqa: BLE001
            first = None
        if first is False:
            return cause
    ctid = str((conn or {}).get("ctid"))
    if _is_provider_rejection(exc):
        _jstore.record_error(
            f"the broker rejected the request: {cause}",
            correlation_id=corr, user_id=user_id, account_id=ctid)
    else:
        _jstore.record_engine_error(
            f"the engine failed to start the loop: {cause}",
            correlation_id=corr, user_id=user_id, account_id=ctid)
    return cause


def start(user_id, rule_doc_id, *, starter=None, now=None,
          mode_lister=None, revive=False):
    """Begin automation for one rule. Idempotent unless `revive`.

    `revive` is for `supervise` alone — see the guard below and the note on
    that function. It skips ONE early return and nothing else: the licence,
    the rule, the account, the broker-confirmed mode and the emergency stop
    are all re-checked exactly as they are for a client pressing Start.
    """
    now = time.time() if now is None else now
    user_id = str(user_id)
    corr = uuid.uuid4().hex

    rec = _read(user_id)
    if (rec.get("state") == RUNNING and rec.get("ruleDocId") == rule_doc_id
            and not revive):
        # Idempotent on purpose: a double-tapped button, a retried request or
        # a second browser tab must not produce a second loop against one
        # account. Answering "already running" is the truth, not a failure.
        #
        # `revive` is the one caller for whom it is NOT the truth. The record
        # says RUNNING and the engine's thread is gone — the process that held
        # it was restarted — so `supervise` has already established that this
        # record is lying, and answering "already running" would leave the
        # client exactly as stuck as the bug it is there to fix. Only this
        # guard is skipped; every check below still runs.
        return dict(status(user_id), started=False, alreadyRunning=True)
    if rec.get("state") == RUNNING and not revive:
        # The SECOND idempotency guard, and it needs the same exemption as the
        # first. It catches starting a DIFFERENT rule while one runs, which is
        # a real refusal for a client — and it caught `supervise` too, so the
        # first version of the revival refused every account it was built to
        # rescue. Found in production logs two minutes after deploying it:
        # "0 alive, 0 revived" with ALREADY_RUNNING beside it.
        #
        # The test did not catch it because it mocked `start` and asserted
        # only that supervise CALLED it with revive=True. Asserting the call
        # and not the behaviour is how a guard that refuses everything looks
        # exactly like a guard that works.
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
        #
        # BUT ONLY THE FIRST TIME. `start` also runs on REVIVE (the supervisor
        # restarting a loop after a deploy) and on RESUME (after a pause). By
        # then the account record already carries the RULE's terms, so
        # reading it again captured the rule's own settings as though they
        # were the client's, and overwrote the original snapshot on the
        # automation record. A Stop after any redeploy or pause then
        # "restored" the rule's settings and the client's real ones were
        # gone: a rule that ran once left its risk, stop and target behind.
        #
        # An existing snapshot on a RUNNING or PAUSED record is therefore
        # kept as it is. `{}` is a legitimate snapshot (the account held none
        # of the keys), so presence is tested, not truthiness.
        if (rec.get("state") in (RUNNING, PAUSED)
                and rec.get("engineSnapshot") is not None):
            snapshot = rec["engineSnapshot"]
        else:
            snapshot = _ecfg.snapshot_of(user_store.load(user_id))
        user_store.update(user_id, dict(applied, active=True))
    except Exception as e:  # noqa: BLE001
        raise AutomationRefused("STORE_UNAVAILABLE",
                                f"the account settings could not be saved "
                                f"({type(e).__name__})")

    try:
        ok = _run_starter(starter, user_id, lock, corr, held)
    except Exception as e:                                   # noqa: BLE001
        cause = _record_starter_failure(user_id, corr, conn, e, revive=revive)
        raise AutomationRefused(
            "ENGINE_START_FAILED",
            f"the trading engine could not start this loop ({cause})") from None
    if ok is False:
        _note_engine_refused(user_id, corr, conn.get("ctid"), revive=revive)
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
    _safety_alert(user_id, payload)
    return None


# THE THIRD SINK, AND WITHOUT IT A CLIENT NEVER LEARNED THEIR MONEY WAS
# EXPOSED.
#
# The two sinks above allowlist for good reasons and neither should widen:
# burying the one alert that needs an answer under heartbeats is exactly what
# `notifications.py` exists to prevent. But between them they deliver SUGGEST
# and SIGNAL and nothing else, so every alert the engine raises about a
# POSITION went nowhere for a platform client.
#
# Two of them are not reports. They are the engine saying it has lost control
# of real exposure and only the client can act:
#
#   UNPROTECTED  the position is open at the broker with no stop-loss, and
#                the safety close did not go through either. `user_loop`'s own
#                comment on raising it reads: "Nothing here can fix it
#                remotely — the client has to be told, now, and told exactly
#                what to do." For a platform client, nobody was told.
#   EXIT_FAILED  the rule asked to close and the broker refused. The position
#                stays open. The loop retries, and if it never clears, the
#                client is holding a trade their rule tried to exit.
#
# Deliberately a THIRD allowlist rather than a route table here. The design
# note above is right that a table in this file would be a third thing that
# has to agree with the allowlists; three allowlists that do not overlap is
# the same pattern, not a new one, and `tests/test_safety_alerts.py` asserts
# the non-overlap in all three directions.
#
# Not in the journal. The journal is where a client goes to read what
# happened; this is something they must act on before the next bar.
SAFETY_ACTIONS = ("UNPROTECTED", "EXIT_FAILED")

# Deliberately NOT included: OWNERSHIP_LOST and BROKER_HEALTH are platform
# faults with no client action, and WEEKEND_CLOSE and STOP/CLOSE are the
# engine doing what it was asked. Alerting on those trains a client to
# dismiss the two above, which is worse than not alerting at all.


def _safety_alert(user_id, payload):
    """Tell the client when the engine has lost control of real exposure.

    NEVER RAISES, for the same reason the other two sinks do not: this runs
    on the trading thread inside the tick, and an exception here abandons the
    rest of that tick — which is where trailing stops, exits and position
    management live. A notification store having a bad moment must not cost a
    client their stop management.
    """
    try:
        if not isinstance(payload, dict):
            return None
        action = str(payload.get("action") or "").strip().upper()
        if action not in SAFETY_ACTIONS:
            return None
        sym = str(payload.get("symbol") or "your position").strip()
        if action == "UNPROTECTED":
            title = f"{sym}: open with NO stop-loss"
            body = (f"A {sym} position is open at your broker and we could "
                    f"not attach a stop-loss to it. The attempt to close it "
                    f"again also failed, so it is live with no protection "
                    f"and nothing here can fix that remotely. Open cTrader "
                    f"and either set a stop on it or close it.")
        else:
            title = f"{sym}: the broker would not close it"
            body = (f"Your rule asked to close {sym} and the broker did not "
                    f"accept it, so the position is still open. Any "
                    f"stop-loss already set on it is still in force at the "
                    f"broker. The automation retries on every bar — if it "
                    f"stays open, close it in cTrader.")
        return _notify.notify(user_id, type=_notify.ORDER,
                              level=_notify.CRITICAL, title=title, body=body)
    except Exception as e:                                   # noqa: BLE001
        print(f"[Automation] the safety alert for {user_id} could not be "
              f"delivered ({type(e).__name__}: {e}) — the engine's own log "
              f"line is the only remaining record")
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
    # SAYS WHAT A PAUSE ALSO STOPS, which the old sentence did not.
    #
    # "No new positions will be opened until you resume" is true and is less
    # than half the truth. `pause` calls `user_loop.stop`, which ENDS THE
    # THREAD — so while paused there is no trailing stop, no break-even, no
    # rule exit condition, no news exit and no weekend flatten. An open
    # position keeps only what the broker already holds: the stop and target
    # attached when it was opened.
    #
    # This module's own docstring argues that a paused-but-ticking loop would
    # be the most dangerous word on the screen. The inverse was equally
    # unsaid, and it is the one a client acts on: they pause with a position
    # open, believing it is still being managed to its target.
    #
    # Telegram's equivalent screen has always said this plainly.
    _notify.notify(
        user_id, type=_notify.SYSTEM, title="Automation paused",
        body="No new positions will be opened until you resume. Anything "
             "already open is also no longer being managed — the trailing "
             "stop, break-even and exit conditions all stop with the "
             "automation. It keeps the stop-loss and target your broker "
             "already holds for it.")
    return dict(status(user_id), paused=True)


def supervise(*, starter=None, mode_lister=None):
    """Restart platform loops whose thread died. Returns (alive, revived).

    THE BUG THIS EXISTS TO FIX, AND IT WAS LIVE

    `start` runs the engine loop as a DAEMON THREAD inside the API process.
    The process dies, the thread dies — and the automation record still says
    RUNNING, so the dashboard goes on reporting RUNNING over a loop that no
    longer exists. A client pressed Start, saw RUNNING, and stopped trading at
    the next deploy or instance recycle without being told.

    The engine has always had `start_all` and `start_watchdog` for this, and
    both are called only from `apex/bot.py` — the Telegram entry point, which
    is not deployed. Nothing in production revived a platform loop.

    WHY THE REVIVAL IS HERE AND NOT IN THE SERVER

    The first version of this fix had `platform_server.py` call
    `user_loop.start` directly in a supervisor thread, and
    `tests/test_platform_server.py` refused it — correctly, and for a better
    reason than style. Going straight to the engine skips `_preflight`, which
    is where the licence, the rule's state, the connection and the mode the
    BROKER confirms are checked. A weekend is long enough for a trial to
    lapse, a rule to be archived or an account to change hands; reviving a
    loop without re-asking would be the one place in this product where a
    trading loop starts on nobody's authority.

    So the revival runs the same preflight a client pressing Start runs, and
    refuses for the same reasons. A refusal is recorded and the next cycle
    tries again — a lapsed licence simply never revives, which is right.

    `user_loop.is_running` is read from the engine's in-process registry, so
    after a restart it is empty and reports every loop as dead, which is the
    truth this function needs. A healthy loop is left untouched.
    """
    from apex import user_loop, user_store
    alive = revived = 0
    for uid in (user_store.all_active() or []):
        uid = str(uid)
        try:
            if not _link.is_platform_account(uid):
                # The bot's account, not ours. This process has no Telegram
                # alert sink and no business starting loops for chats.
                continue
        except Exception as e:                               # noqa: BLE001
            print(f"[Automation] could not classify {uid} "
                  f"({type(e).__name__}) — leaving it alone")
            continue
        rec = _read(uid)
        if rec.get("state") != RUNNING:
            continue                    # stopped or paused on purpose
        if user_loop.is_running(uid):
            alive += 1
            continue
        rid = rec.get("ruleDocId")
        if not rid:
            print(f"[Automation] {uid} is RUNNING with no rule recorded — "
                  f"not revived, a human should look at it")
            continue
        try:
            start(uid, rid, starter=starter, mode_lister=mode_lister,
                  revive=True)
            revived += 1
            print(f"[Automation] revived the loop for {uid} on rule {rid}")
        except AutomationRefused as e:
            # Expected and useful: the licence lapsed, the rule was archived,
            # the broker cannot confirm the mode. Say which, and leave the
            # record alone so the client still sees what they asked for.
            print(f"[Automation] not reviving {uid}: {e.code} — {e.detail}")
        except Exception as e:                               # noqa: BLE001
            print(f"[Automation] reviving {uid} failed: "
                  f"{type(e).__name__}: {e}")
    return alive, revived


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

    Stop still declines to flatten, on purpose: it ends the LOOP, and closing a
    position is an order the client should decide per position, with the
    position in front of them. Stop must not become a hidden "close
    everything".

    THIS SENTENCE HAS BEEN WRONG TWICE, in opposite directions, and both times
    a client would have acted on it:

      1. It said this release "cannot place orders of any kind". True while
         nothing could; false once Approval Required worked.
      2. It then said "this release has no way to close a position". True
         until the demo Close arrived (position_close.close_demo, reached from
         the Positions page). After that it told a client there was no way to
         do something they could do in one click.

    So it now says what Stop does NOT do and where closing IS available. The
    pairing test (tests/test_stop_sentence_truthful.py) ties the sentence to
    the capability, so it cannot drift a third time.
    """
    return {
        "flattened": False,
        "flattenDeclined": True,
        "flattenReason": (
            "Stopping ends the trading loop. It does not close positions that "
            "are already open. Any open position stays at your broker with "
            "the stop and target it was given. You can close it from the "
            "Positions page on a demo account, or in cTrader."),
    }


def stop(user_id, *, stopper=None):
    """Stop and forget. Idempotent — stopping something stopped is fine."""
    rec = _read(user_id)
    if rec.get("state") == STOPPED:
        return dict(status(user_id), stopped=False, alreadyStopped=True,
                    **_flatten_answer(rec))
    stopped_here = _halt(user_id, stopper)
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
    out = dict(status(user_id), stopped=True, alreadyStopped=False,
               loopStoppedHere=stopped_here, **ans)
    if not stopped_here:
        # NOT "stopped" on the strength of a record alone. No loop was running
        # in the process that took this request. If one runs in another
        # container (a deploy overlap) it honours the recorded stop at its next
        # tick; saying so is the difference between a sentence that is true and
        # one that is only hopeful.
        out["stopNote"] = (
            "No trading loop was running on this server instance. If one is "
            "running on another instance — possible for a few minutes after an "
            "update — it will notice this stop at its next check, within about "
            "five minutes.")
    return out


def _halt(user_id, stopper):
    """Record the stop and stop the loop in THIS process. Returns whether a loop
    here was actually stopped (False: none was running in this process)."""
    if stopper is None:
        from apex import user_loop
        stopper = user_loop.stop
    try:
        user_store.update(user_id, {"active": False})
    except Exception:
        pass
    return bool(stopper(user_id))
