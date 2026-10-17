"""A setup the engine wants permission for, answerable BY THE PLATFORM.

WHAT WAS WRONG, AND IT WAS NOT SUBTLE

The engine has three automation levels — signals, approval, full. In
`approval` the loop finds a setup and calls `user_loop._suggest_trade`, which

  1. writes `pending_suggestion` onto the account record
  2. calls `alert_fn` with {"action": "SUGGEST", symbol, side, price, ...}
  3. and the caller then sets entry_ok = False, so nothing is placed

Both halves of that only ever had one implementation: the Telegram bot's
alert, and the ✅ Approve button it draws. `automation.start` started the loop
as `user_loop.start(user_id)` with NO alert function, and no platform client
has a Telegram chat to be asked in. So approval on the platform meant a loop
that found setups, wrote a proposal nobody could see, notified nobody, and
placed nothing — indefinitely, with the dashboard saying Running. Commit
6f984dfe9 removed that state by refusing to run at a level the platform could
not service; this module is the other half, the one that makes it serviceable.

THERE IS NO SECOND EXECUTION PATH HERE

`approve` hands the trade to `user_loop.force_trade`, the same controller the
Telegram ✅ button, /buy, the assistant and `bridge` all converge on. It is the
function that performs, in order: ownership.may_trade, gates.authorize_order,
gates.audit, ledger.claim/record, and only then broker.place_order. Writing
those five steps again here would mean two places that must both stay correct
forever, and the first time they disagreed one of them would be placing orders
the other believed were refused. See `apex/platform/bridge.py`, which refuses
to duplicate them for the same reason.

What this module adds is the part the engine does not have: a decision made by
somebody who is looking at a web page rather than a chat.

A DOUBLE TAP MUST NOT OPEN TWO POSITIONS, AND THREE THINGS ENSURE IT

  the claim     SET NX on a key naming THIS suggestion, so two requests in
                two containers cannot both get past it
  the clear     the suggestion is dropped BEFORE the order is attempted, so a
                second approve finds nothing to approve even where there is no
                shared backend to claim against (development)
  the gate      `gates.authorize_order` refuses an identical order whatever
                asked for it. The interface stops the ordinary double tap; the
                idempotency claim inside the controller is what actually
                prevents two positions

WHAT IS REFUSED, AND WHY EACH REFUSAL IS NOT A SILENT NO-OP

  NO_SUGGESTION   nothing is pending. Also what a second approve gets, and it
                  says so: the first one may have opened a position
  EXPIRED         older than the engine's own five-minute window. A setup
                  found five minutes ago is a price that has moved; it is
                  refused rather than placed at today's price under
                  yesterday's reasoning
  NOT_RUNNING     the loop is not running. `stop()` RESTORES the account's
                  previous risk, stop and target, so a suggestion approved
                  after a stop would be sized and stopped by terms other than
                  the ones that produced it — the silent substitution this
                  codebase exists to refuse. Pause promises "no new positions
                  until you resume" and is held to it
  ALREADY_HANDLED somebody else's request holds the claim for this suggestion
  ORDER_REFUSED   the controller or the broker said no, in its own words

WHERE THE PRICE AND THE REASONING COME FROM

The engine stores only {side, symbol, ts}. Everything a person needs to decide
— the price it was found at, the rule's own reason, the confidence — exists
only in the SUGGEST alert payload, which until now went nowhere. So the alert
writes those fields into a record of this module's own, STAMPED WITH THE
SUGGESTION'S TIMESTAMP, and the read joins the two on that stamp.

The stamp is the whole point. Without it a detail record left behind by a
suggestion the client already answered would be rendered as the price and
reasoning of the NEXT one — a screen describing one setup while the account
holds another. When the stamps do not match, the detail is dropped and the
fields read as unknown, because an unknown price shown as unknown is a
nuisance and an unknown price shown as a number is a lie.

The engine's record stays authoritative for WHETHER a suggestion exists. This
module never writes `pending_suggestion` and never restores one it cleared: a
resurrected suggestion is a second position waiting to happen.

TWO WAYS TO LEARN, NEITHER LOAD-BEARING ALONE

The notification is an interruption and the GET is a poll. A notification that
could not be written must not stop the engine's tick, so `engine_alert`
swallows everything — and the suggestion is still on the record for the next
poll to find. Equally, a client who never opens the app is not left with a
screen that would have told them if only they had looked.
"""

import time
import uuid

from apex import user_store
from apex.platform import journal_store as _jstore
from apex.platform import notifications as _notify
from apex.platform import store as _store

# The engine's window, not a number chosen here. `user_loop._suggest_trade`
# ignores a pending suggestion younger than this and overwrites an older one,
# so a suggestion past it is already one the loop considers replaceable. The
# platform must not act on what the engine has stopped waiting for.
EXPIRY_S = 300.0

# The alert action this module answers. Everything else the loop emits —
# STOP, CLOSE, BROKER_HEALTH, SIGNAL and a dozen more — is ignored on purpose:
# see `engine_alert`.
SUGGEST = "SUGGEST"

# The only two sides a suggestion can carry. Validated rather than trusted:
# a side this module does not recognise is never handed to the controller,
# whatever wrote it.
SIDES = ("BUY", "SELL")

# Why an order placed from here is recorded as coming from an approval, and
# not as "manual" (a client typing /buy) or "rule" (the loop acting alone).
# It appears in the audit line and the control event, where the question
# somebody is asking is who decided.
ORIGIN = "approval"

OK = "ok"
# The record came back with nothing in it. For a client who has never started
# anything that is simply true, and for a store that did not answer it is not
# — and `user_store.load` returns {} for both. Reported as its own state
# rather than as "no setup is waiting", which would be a claim neither case
# supports.
UNKNOWN = "unknown"

NO_SUGGESTION = "NO_SUGGESTION"
EXPIRED = "EXPIRED"
NOT_RUNNING = "NOT_RUNNING"
ALREADY_HANDLED = "ALREADY_HANDLED"
ORDER_REFUSED = "ORDER_REFUSED"

# Long enough that a slow broker call cannot let a retry through behind it,
# short enough that a container dying mid-approve does not strand the next
# suggestion — which it cannot anyway, because the claim key names the
# suggestion's own timestamp and the next one has a different stamp.
_CLAIM_TTL_S = 120


class ApprovalRefused(RuntimeError):
    """A refusal with a code the UI can branch on, never English to match."""

    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


# ── storage ─────────────────────────────────────────────────────────────────

def _k_detail(user_id):
    return f"{_store._ns()}:{_store._P}:suggestion:{user_id}"


def _k_claim(user_id, ts):
    # Keyed by the suggestion's own timestamp. A claim that named only the
    # client would still be held when the NEXT suggestion arrived, and the
    # client would be unable to approve a setup nobody had answered.
    return f"{_store._ns()}:{_store._P}:suggclaim:{user_id}:{float(ts):.3f}"


def _record(user_id):
    """The engine's account record, or {} when it could not be read.

    `user_store.load` collapses "no record" and "the store did not answer"
    into {}, which is why the read below reports UNKNOWN for an empty one
    instead of stating that nothing is pending.
    """
    rec = user_store.load(str(user_id))
    return rec if isinstance(rec, dict) else {}


def _parse(pend):
    """(symbol, side, ts) from a stored suggestion, or None if unusable.

    Validated at the boundary even though the engine wrote it. A record can be
    edited by hand, restored from a backup of a different shape, or written by
    a future version of the loop — and the one thing that must never happen is
    a side or a symbol this module does not understand reaching the order
    controller.
    """
    if not isinstance(pend, dict):
        return None
    symbol = pend.get("symbol")
    side = pend.get("side")
    ts = pend.get("ts")
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    if not isinstance(side, str) or side.strip().upper() not in SIDES:
        return None
    if not isinstance(ts, (int, float)) or isinstance(ts, bool) or ts <= 0:
        return None
    return symbol.strip(), side.strip().upper(), float(ts)


def _detail_for(user_id, ts):
    """The alert's own fields for THIS suggestion, or {}.

    Joined on the timestamp. A record belonging to a different suggestion is
    dropped rather than shown against this one — see the module docstring.
    """
    row = _store._read(_k_detail(str(user_id)))
    if not isinstance(row, dict):
        return {}
    row_ts = row.get("ts")
    if not isinstance(row_ts, (int, float)) or isinstance(row_ts, bool):
        return {}
    # Compared exactly, not within a tolerance. Both numbers come from the
    # same `time.time()` call in `_suggest_trade`; a tolerance would be a
    # window in which the wrong setup's price could be rendered.
    if abs(float(row_ts) - float(ts)) > 1e-6:
        return {}
    return row


def _clear(user_id):
    """Drop the suggestion and the detail that described it.

    Through `user_loop.clear_suggestion` rather than a `user_store.update` of
    our own, because that is the accessor the Telegram path already uses and
    two writers of one field is one more than this needs.
    """
    from apex import user_loop
    user_loop.clear_suggestion(str(user_id))
    try:
        _store._write(_k_detail(str(user_id)), None)
    except Exception as e:                                  # noqa: BLE001
        # The detail is a description, not a decision: a stale one can never
        # be joined to another suggestion (the stamps differ), so failing to
        # delete it must not fail the clear that stops a second approve.
        print(f"[Approvals] could not drop the detail record for {user_id} "
              f"({type(e).__name__})")


# ── what the engine tells us ────────────────────────────────────────────────

def engine_alert(user_id, payload):
    """The alert sink `automation.start` hands the engine. NEVER raises.

    This runs on the trading thread, inside the tick that found the setup. An
    exception here would propagate into the loop, so every failure is caught
    and printed: the suggestion is on the account record either way, and the
    dashboard's poll finds it on the next cycle.

    It answers ONE action. The loop's alert function is a firehose — STOP,
    CLOSE, WEEKEND_CLOSE, BROKER_HEALTH, SKIP_WARN, heartbeats and more — and
    notifying on all of them would bury the one that needs an answer under the
    ones that do not, which `notifications.py` explains at length and is the
    reason that store exists separately from the journal. SIGNAL is not
    handled here either: signals-only is a different level with a different
    screen, and a module that quietly took it over would be the second owner
    of a thing that needs exactly one.
    """
    try:
        if not isinstance(payload, dict):
            return None
        if str(payload.get("action") or "").strip().upper() != SUGGEST:
            return None
        return announce(user_id, payload)
    except Exception as e:                                  # noqa: BLE001
        print(f"[Approvals] the suggestion alert for {user_id} could not be "
              f"delivered ({type(e).__name__}: {e}) — it is still on the "
              f"account record and the next read will find it")
        return None


def announce(user_id, payload):
    """Record the alert's detail and tell the client, or do nothing.

    Returns the notification, or None when there was nothing to describe.

    The alert arrives immediately after `_suggest_trade` wrote the record, so
    the normal case is that the suggestion is there. When it is NOT there the
    client has already answered it, or it was never written, and the one thing
    this must not do is write anything that looks like a pending suggestion:
    the record is the engine's, and a proposal resurrected here is a position
    waiting to open after somebody said no.
    """
    user_id = str(user_id)
    from apex import user_loop
    parsed = _parse(user_loop.pending_suggestion(user_id))
    if not parsed:
        return None
    symbol, side, ts = parsed
    # The payload must describe the suggestion on the record. They are written
    # one line apart by the same tick, so a mismatch means this alert is about
    # some other setup and its price does not belong to this one.
    if (str(payload.get("symbol") or "").strip() != symbol
            or str(payload.get("side") or "").strip().upper() != side):
        return None

    price = payload.get("price")
    factors = payload.get("keyFactors")
    _store._write(_k_detail(user_id), {
        "ts": ts, "symbol": symbol, "side": side,
        # Absent rather than zero when the loop had no price: `_suggest_trade`
        # is called with whatever the tick held, and 0.0 rendered as a price
        # is a number nobody can tell apart from a real one.
        "price": (float(price) if isinstance(price, (int, float))
                  and not isinstance(price, bool) and price else None),
        "confidence": (payload.get("confidence")
                       if isinstance(payload.get("confidence"), (int, float))
                       and not isinstance(payload.get("confidence"), bool)
                       else None),
        "reasoning": (str(payload.get("reasoning"))[:500]
                      if payload.get("reasoning") else None),
        "keyFactors": ([str(f)[:120] for f in factors][:8]
                       if isinstance(factors, (list, tuple)) else []),
    })

    at = _price_words(price)
    # WARNING, not INFO. This one expires: in five minutes the setup is gone
    # whether anybody looked or not, so a notification that does not stand out
    # is the same as no notification. RULE rather than ORDER because no order
    # exists yet — the client decides whether one ever does.
    return _notify.notify(
        user_id, type=_notify.RULE, level=_notify.WARNING,
        title=f"Approve {side} {symbol}?",
        body=f"Your rule found a {side} setup on {symbol}{at}. "
             f"{str(payload.get('reasoning') or '').strip()} "
             f"Nothing opens until you approve it, and this setup expires "
             f"{int(EXPIRY_S // 60)} minutes after it was found.".strip(),
        link="/dashboard")


def _price_words(price):
    if (not isinstance(price, (int, float)) or isinstance(price, bool)
            or not price):
        return ""
    return f" at {price:g}"


# ── what the client sees ────────────────────────────────────────────────────

def pending(user_id, *, now=None):
    """The setup waiting for an answer, or that there is none.

    Shaped like the broker reads: a `status` first, and the data key only
    carries a claim when status is `ok`. An empty account record is UNKNOWN
    rather than "nothing pending", because `user_store.load` cannot tell a
    store that did not answer from a client who has never run anything.
    """
    now = time.time() if now is None else float(now)
    user_id = str(user_id)
    rec = _record(user_id)
    if not rec:
        return {"status": UNKNOWN,
                "reason": "this account has no engine state yet, or it could "
                          "not be read"}
    pend = rec.get("pending_suggestion")
    if not pend:
        return {"status": OK, "approval": None}

    parsed = _parse(pend)
    if not parsed:
        # Something is stored and it cannot be read. Reported rather than
        # treated as absent: it blocks the loop from proposing anything for
        # five minutes, and a client who is told can dismiss it. Nothing about
        # it is described, because nothing about it is known.
        return {"status": OK, "approval": None, "unreadable": True}

    symbol, side, ts = parsed
    detail = _detail_for(user_id, ts)
    age = max(0.0, now - ts)
    expired = age >= EXPIRY_S
    running = rec.get("active") is True
    refusal = (EXPIRED if expired else None) or (None if running
                                                 else NOT_RUNNING)
    return {"status": OK, "approval": {
        "symbol": symbol,
        "side": side,
        # None, never a stand-in. The card says the price was not recorded
        # rather than showing a zero somebody would read as a price.
        "price": detail.get("price"),
        "confidence": detail.get("confidence"),
        "reasoning": detail.get("reasoning"),
        "keyFactors": detail.get("keyFactors") or [],
        # Whether the alert's own fields were found for THIS suggestion. False
        # means the card has a symbol and a side and must say so, instead of
        # implying the rest is empty because there was nothing to say.
        "detailKnown": bool(detail),
        "proposedAt": ts,
        "ageSec": round(age, 1),
        "expiresAt": ts + EXPIRY_S,
        # The browser counts down from THIS rather than from `expiresAt`
        # against its own clock: a device whose clock is a minute out would
        # otherwise show a setup as expired that is not, or offer one that is.
        "expiresInSec": round(max(0.0, EXPIRY_S - age), 1),
        "expired": expired,
        # The server's verdict on whether approving would be accepted right
        # now, so the browser disables a button instead of deciding for
        # itself what the rules are.
        "actionable": refusal is None,
        "refusal": refusal,
    }}


def approve(user_id, *, now=None, executor=None):
    """Place the suggested trade through the engine's order controller.

    Idempotent in the only sense that matters: a second call cannot open a
    second position. The suggestion is claimed and cleared before the order is
    attempted, so the second caller is refused with NO_SUGGESTION or
    ALREADY_HANDLED rather than placing anything.

    `executor` is injectable so a test can assert exactly what would be sent
    with no broker anywhere near it. The default is the real controller.

    Returns {"status", "outcome", "order", "detail", "approval": None}.
    `outcome` is "placed" or "unknown" — never a quiet third thing. A refusal
    raises.
    """
    now = time.time() if now is None else float(now)
    user_id = str(user_id)
    corr = uuid.uuid4().hex

    rec = _record(user_id)
    parsed = _parse(rec.get("pending_suggestion"))
    if not parsed:
        raise ApprovalRefused(
            NO_SUGGESTION,
            "there is no setup waiting for approval on this account. If you "
            "have just approved one, check your open positions rather than "
            "approving again")
    symbol, side, ts = parsed
    if now - ts >= EXPIRY_S:
        # Refused, and deliberately NOT cleared. Clearing on a read that may
        # have raced the loop writing a fresh suggestion would delete the new
        # one; an expired suggestion is harmless where it is, because
        # `_suggest_trade` overwrites anything past this same window.
        raise ApprovalRefused(
            EXPIRED,
            f"this setup was found {int(now - ts)} seconds ago and is no "
            f"longer current — it is not placed at today's price under "
            f"reasoning from {int(EXPIRY_S // 60)} minutes ago. Your rule "
            f"proposes the next one it finds")
    if rec.get("active") is not True:
        raise ApprovalRefused(
            NOT_RUNNING,
            "automation is not running on this account, so this setup is not "
            "placed. Stopping restores the account's own risk, stop and "
            "target, and a trade opened now would be sized by those rather "
            "than by the rule that proposed it")

    # The claim is taken AFTER the cheap refusals, for the same reason the
    # live path runs its gates before `ledger.claim`: a refusal must not
    # consume the key that protects the next legitimate attempt.
    token = uuid.uuid4().hex
    claimed = user_store.claim_value(_k_claim(user_id, ts), token,
                                     ttl_s=_CLAIM_TTL_S)
    if claimed is False:
        raise ApprovalRefused(
            ALREADY_HANDLED,
            "this setup is already being answered — check your open "
            "positions before approving anything else")
    # `None` means there is no shared backend to ask, which is development.
    # The clear below is what stops a double tap there, and the idempotency
    # claim inside the order controller is what stops two positions anywhere.

    # BEFORE the order, exactly as the Telegram button does it: a second
    # Approve on the same setup then finds nothing to approve.
    _clear(user_id)

    if executor is None:
        # Imported here, not at module import, so this file can be loaded and
        # tested without pulling in the whole engine.
        from apex import user_loop
        executor = user_loop.force_trade

    # NO OVERRIDES, AND THAT IS THE CORRECT CALL.
    #
    # `force_trade` derives the stop, the target and the size from the
    # account's engine settings — which, for a platform client, ARE the rule's
    # terms: `engine_config.translate` wrote the risk percentage, the stop and
    # the target onto the record when the rule started, and `stop()` puts the
    # account's own settings back. Passing numbers of our own would be a
    # second sizing implementation reading the same document, and the two
    # would eventually disagree about one trade.
    try:
        result = executor(user_id, side, symbol=symbol, origin=ORIGIN)
    except Exception as e:                                  # noqa: BLE001
        # The controller did not answer at all. `force_trade` guards its own
        # broker call and returns a dict for every refusal, so an exception
        # here is most likely raised BEFORE anything was sent — and "most
        # likely" is not a thing to tell somebody about a position. Reported
        # as the unknown outcome, which is the only reading that cannot cause
        # a second order, and never allowed to escape as a 500: a traceback
        # reaching the API would leave the client with no answer at all about
        # a suggestion that has already been cleared.
        return _ambiguous(user_id, corr, symbol, side,
                          {"error": f"{type(e).__name__}: {e}"})
    result = result if isinstance(result, dict) else {}

    if result.get("ok") is True:
        return _placed(user_id, corr, symbol, side, result)
    if result.get("ambiguous") is True:
        # NOT a refusal. The broker did not say no; it did not answer, and
        # collapsing that into "refused" is how one uncertain order becomes
        # two certain ones — see `user_loop.broker_result_ambiguous`.
        return _ambiguous(user_id, corr, symbol, side, result)
    raise _refusal(user_id, corr, symbol, side, result)


def _placed(user_id, corr, symbol, side, result):
    detail = (f"{side} {symbol} opened at {result.get('price')} — "
              f"{result.get('units')} units, stop {result.get('sl')}, "
              f"target {result.get('tp')}.")
    # Guarded, and every one of these is after the order. Once a position is
    # open, nothing this module does may turn that into a failure the client
    # reads as "nothing happened" — the position exists either way, and a 500
    # here is how somebody ends up not knowing about it.
    _quietly(_notify.notify, user_id, type=_notify.ORDER, level=_notify.INFO,
             title=f"{side} {symbol} opened", body=detail,
             correlation_id=corr, link="/positions")
    return {"status": OK, "outcome": "placed",
            "order": {"symbol": symbol, "side": side,
                      "price": result.get("price"),
                      "units": result.get("units"),
                      "stopLoss": result.get("sl"),
                      "takeProfit": result.get("tp")},
            "detail": detail, "approval": None}


def _ambiguous(user_id, corr, symbol, side, result):
    # One sentence for two causes — a broker that did not answer, and a
    # controller that did not answer — because the client's situation is
    # identical in both: it may be open, and finding out means looking.
    detail = (f"The order for {side} {symbol} was sent for execution and the "
              f"result was not confirmed, so it may be open. Check your "
              f"positions at your broker before trying again — it is not "
              f"re-sent automatically, because a retry on an order that did "
              f"go through opens a second position.")
    _quietly(_jstore.record_error,
             f"approval {side} {symbol}: ambiguous broker outcome — "
             f"{result.get('error')}", correlation_id=corr, user_id=user_id,
             symbol=symbol)
    _quietly(_notify.notify, user_id, type=_notify.ORDER,
             level=_notify.CRITICAL,
             title=f"{side} {symbol} may have opened",
             body=detail, correlation_id=corr, link="/positions")
    return {"status": OK, "outcome": "unknown", "order": None,
            "detail": detail, "approval": None}


def _refusal(user_id, corr, symbol, side, result):
    """The refusal to raise, with the client told before it is raised.

    Returns the exception rather than raising it so the three outcomes stay
    side by side in `approve`, where the one thing a reader needs to check is
    that placed, unknown and refused are three different answers.
    """
    code = str(result.get("error") or "")
    # THE SENTENCE, NOT JUST THE CODE. `force_trade` returns a gate reason in
    # `error` and the explanation in `detail`, and this used to drop the
    # second — so the client read `ORDER_REFUSED: RISK_HALTED`, or
    # `ORDER_REFUSED: not the owning instance (...)`, for about fifteen
    # situations with fifteen different next steps.
    detail = str(result.get("detail") or "")
    why = f"{code} — {detail}" if code and detail else (
        detail or code or "the order was refused")

    # TWO OUTCOMES HERE ARE NOT "NOTHING HAPPENED", and the difference is the
    # client's money. `force_trade` refuses with these after the broker has
    # already opened something.
    if code == "OPEN_WITHOUT_STOP":
        title = f"{side} {symbol} is OPEN with no stop-loss"
        body = (f"You approved it, the broker opened it, and it would not "
                f"accept the stop-loss — and it could not be closed again "
                f"either. The position is live with no protection. Open "
                f"cTrader and either set a stop on it or close it.")
        level = _notify.CRITICAL
    elif code == "OPENED_AND_CLOSED":
        title = f"{side} {symbol} opened and was closed again"
        body = (f"You approved it and the broker opened it, then would not "
                f"accept the stop-loss, so it was closed again immediately "
                f"for safety. You are not holding this position. Nothing "
                f"needs doing, and the automation will look for the next "
                f"setup.")
        level = _notify.WARNING
    else:
        title = f"{side} {symbol} was not opened"
        body = f"You approved it and it was not placed: {why}"
        level = _notify.WARNING

    _quietly(_jstore.record_error, f"approval {side} {symbol}: {why}",
             correlation_id=corr, user_id=user_id, symbol=symbol)
    _quietly(_notify.notify, user_id, type=_notify.ORDER, level=level,
             title=title, body=body, correlation_id=corr,
             link="/positions" if code == "OPEN_WITHOUT_STOP" else None)
    return ApprovalRefused(ORDER_REFUSED, body if code in
                           ("OPEN_WITHOUT_STOP", "OPENED_AND_CLOSED") else why)


def reject(user_id, *, now=None):
    """Drop the suggestion. Idempotent — dismissing nothing is not a failure.

    The same claim as `approve`, so a Dismiss racing an Approve cannot both
    act on one setup.
    """
    user_id = str(user_id)
    rec = _record(user_id)
    pend = rec.get("pending_suggestion")
    if not pend:
        return {"status": OK, "rejected": False, "alreadyGone": True,
                "approval": None}

    parsed = _parse(pend)
    if parsed:
        token = uuid.uuid4().hex
        claimed = user_store.claim_value(_k_claim(user_id, parsed[2]), token,
                                         ttl_s=_CLAIM_TTL_S)
        if claimed is False:
            raise ApprovalRefused(
                ALREADY_HANDLED,
                "this setup is already being answered — check your open "
                "positions before dismissing it")
    # An unreadable suggestion has no timestamp to claim against and is
    # cleared anyway: it can never be approved, and leaving it there would
    # stop the loop proposing anything for five minutes.
    _clear(user_id)
    _quietly(_notify.notify, user_id, type=_notify.RULE, level=_notify.INFO,
             title="Setup dismissed",
             body="Nothing was opened. Your rule keeps watching and proposes "
                  "the next setup it finds.")
    return {"status": OK, "rejected": True, "alreadyGone": False,
            "approval": None}


def _quietly(fn, *a, **kw):
    """Run a bookkeeping write that must not change the outcome.

    Used only for notifications and journal lines written after the decision
    has already been made and, in `_placed`, after a real position exists.
    """
    try:
        return fn(*a, **kw)
    except Exception as e:                                  # noqa: BLE001
        print(f"[Approvals] {getattr(fn, '__name__', fn)} failed "
              f"({type(e).__name__}: {e})")
        return None
