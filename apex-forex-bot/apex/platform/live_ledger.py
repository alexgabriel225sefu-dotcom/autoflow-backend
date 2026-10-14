"""The claim that stops one decision becoming two positions.

WHAT §6 OF THE LIVE-EXECUTION SPECIFICATION ASKS FOR, AND WHY THE OBVIOUS
VERSION OF IT DOES NOT WORK

Three ways a duplicate order happens, all three observed in this project
rather than imagined: a retry after a submit whose answer never came, a Render
deploy that overlaps two containers on one cTrader account, and a plain second
instance. One claim, taken before the broker is asked, catches all three — but
only if two independent processes computing the same decision arrive at the
same key.

That is the whole difficulty, and it is where the obvious implementation fails.
A key built from the current time, or from the snapshot's own timestamp, looks
right and passes any sequential test: the first claim wins, the retry a moment
later is refused. Then the deploy overlap arrives — in this repository's own
logs, instance 6n5hh was running at 18:21:07 while vvlq4 had started at
18:21:00 — and the two instances read the market seven seconds apart, compute
two different keys, and BOTH trade. The claim was taken, the test was green,
and the account has two positions.

So the key is derived from the BAR, not from a reading of the clock:

    SYMBOL:SIDE:strategy:bar

`bar` is the open time of the candle the decision was made on, which every
instance evaluating that candle computes identically however far apart they
read it. `strategy` is the frozen RuleDoc id and version, because in this
platform the frozen version IS the strategy — an active RuleDoc is written once
and never again (see store.py), so two instances referring to `rule-7v3` are
referring to exactly one set of terms. A timeframe this module cannot convert
to a bar is REFUSED rather than defaulted: a guessed bar length is a guessed
key, and a guessed key is no key at all.

RELEASED ONLY ON A CONFIRMED OUTCOME, WHICH IS THREE CASES AND NOT TWO

    confirmed filled      the position exists. The claim is NOT released.
                          Freeing it is how the next retry duplicates a
                          position that is already open.
    confirmed rejected     the broker said no, so nothing exists and the
                          decision may legitimately be taken again this bar.
                          Released.
    unknown                a timeout, an exception, a connection dropped
                          mid-submit. NOT released, and this is the case the
                          whole module exists for: a timed-out submit may have
                          filled, so releasing the claim turns one uncertain
                          order into two certain ones.

Collapsing the last two into one "it didn't work" boolean is the bug, because
the code that writes it is in an exception handler, where "it didn't work" is
exactly what it feels like.

A SHARED BACKEND IS MANDATORY, SO THIS MODULE REFUSES TO IMPORT WITHOUT ONE

§6 is explicit that for live execution the process must refuse to start, not
report itself degraded. A per-process claim is worse than none: it reports
success on every container independently, so the one failure it is built to
prevent is the one it cannot see. `user_store` already refuses to start in
production for the same reason; this is the same refusal moved to the place
where the local-JSON development fallback would otherwise still be permitted.
Importing this module is what a live-capable process does, so the refusal
belongs at import, and there is deliberately no flag that relaxes it.

Keys live under the platform's own namespace prefix, so `store.all_keys()`
sees them and the backup covers them. §12 of the specification requires a
restore to have been exercised before live execution, "because the ledger is
now the record of real money" — a ledger the backup does not scan is not
covered by that drill.

NOT AN EXECUTION PATH. This module cannot ask a broker for anything. It
imports neither `bridge` nor `execution`, and
tests/test_platform_live_invariants.py asserts that on the AST.
"""

import json
import os
import time
import uuid

from apex import user_store
from apex.platform import store as _store

# ── bar lengths ─────────────────────────────────────────────────────────────
# The same table as apex/candle_cache.py's `_PERIOD_SECONDS` and
# apex/miniapp_api.py's `_TF_SECONDS`, restated rather than imported: those
# live in the legacy engine, and the live claim must not acquire a dependency
# on a module the legacy Telegram bot also pulls in. A timeframe missing from
# here is refused, which is why it is safe for this copy to be narrower than
# theirs rather than more generous.
BAR_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}

# A claim must outlive the bar it guards, because the same decision can recur
# at any point inside that bar, and a claim that expires mid-bar reopens the
# duplicate it was taken to prevent. The margin covers a deploy that straddles
# a bar close. Beyond the bar there is nothing left to protect: the next bar is
# a different key, so letting the key expire is correct rather than merely
# tidy — Redis is not a place to leave keys that no longer decide anything.
CLAIM_MARGIN_S = 300

# How long the recorded outcome stays answerable. Longer than the claim on
# purpose: once the claim has gone, "what happened to that decision?" is still
# a question support and an incident review ask, and a week covers both.
OUTCOME_KEEP_S = 7 * 86400

# Outcomes. Three, not two — see the module docstring.
FILLED = "filled"
REJECTED = "rejected"
UNKNOWN = "unknown"
OUTCOMES = (FILLED, REJECTED, UNKNOWN)


class SharedBackendRequired(RuntimeError):
    """Live idempotency has no shared source of truth, so there is none."""


class CoordinationUnavailable(RuntimeError):
    """The shared store could not be asked, so nothing may be assumed.

    Distinct from `AlreadyClaimed` on purpose, and this is the distinction
    `user_store.claim_value`'s tri-state return exists to carry: False is
    "somebody else holds it", None is "I could not ask". Reading the second as
    the first halts a healthy account; reading it as "I won" places the
    duplicate. Neither is acceptable, so it is its own answer.
    """


class AlreadyClaimed(RuntimeError):
    """Another attempt holds this decision. `setup_key` names which.

    `outcome` carries what that attempt recorded, when it recorded anything,
    so a duplicate can be answered with the original result instead of a bare
    refusal.
    """

    def __init__(self, message, *, setup_key=None, key=None, outcome=None):
        self.setup_key = setup_key
        self.key = key
        self.outcome = outcome
        super().__init__(message)


class NotTheHolder(RuntimeError):
    """A confirmation came from something that does not hold this claim.

    Raised rather than ignored. A process confirming an outcome for a claim it
    does not own has lost track of its own bookkeeping, and the next thing it
    does with that misunderstanding involves a broker.
    """


def shared_backend():
    """True when claims are visible to every other instance."""
    return bool(getattr(user_store, "_USE_REDIS", False))


def assert_shared_backend():
    """Raise unless claims can be seen across processes.

    Called at import, below. The message names both halves of the remedy
    because the operator reading it is looking at a service that will not
    start.
    """
    if shared_backend():
        return True
    raise SharedBackendRequired(
        "live order idempotency requires a shared backend and this process "
        "has none, so it refuses to start.\n"
        "A local JSON store cannot be seen by another container: each one "
        "would grant itself every claim, so two instances driving the same "
        "broker account would each believe it was the only one. That is "
        "worse than having no claim at all, because it reports success.\n"
        "Configure REDIS_URL or the Upstash REST pair. There is no flag that "
        "relaxes this for live execution — see §6 of "
        "docs/LIVE_EXECUTION_SPECIFICATION.md."
    )


# ── reading a decision, in either of the two shapes it arrives in ───────────
def _field(obj, *names):
    """The first of `names` this object carries, by key or by attribute.

    A RuleDecision arrives either as the object (snake_case attributes) or as
    its `as_dict()` (camelCase keys), depending on whether the caller has
    already journalled it. Accepting one and silently reading None from the
    other is how a key loses a component without anything looking wrong.
    """
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            got = getattr(obj, name, None)
            if got is not None:
                return got
    return None


def _symbol(value):
    """EURUSD, from any of the spellings this product accepts.

    The same normalisation journal_store._matches uses. Without it EUR_USD and
    EURUSD are two keys for one instrument, and the second spelling trades
    again.
    """
    out = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if not out:
        raise ValueError("a claim needs a symbol to key on")
    return out


def _side(value):
    side = str(value or "").upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(
            f"a claim keys on a tradable side; got {value!r}. HOLD and REJECT "
            f"never reach a broker, so they have nothing to claim")
    return side


def bar_open(snapshot_ts, timeframe):
    """The open time of the candle `snapshot_ts` falls in.

    The one function in this module that makes the key work across processes.
    Every instance evaluating one candle lands on one integer, however far
    apart in wall time they read it.
    """
    if snapshot_ts is None:
        raise ValueError(
            "a claim needs the decision's snapshot time; without it the only "
            "thing left to key on is the clock, which is the duplicate")
    seconds = BAR_SECONDS.get(str(timeframe))
    if not seconds:
        raise ValueError(
            f"timeframe {timeframe!r} has no known bar length, so the bar "
            f"cannot be derived — refusing rather than guessing one")
    try:
        ts = float(snapshot_ts)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"snapshot time {snapshot_ts!r} is not a time") from e
    return int(ts // seconds) * seconds


def _component(value, what):
    """A key component that must not be able to move the key's boundaries.

    Refused rather than sanitised. Replacing the offending characters is the
    tempting fix and it silently maps two distinct identities onto one key —
    at which point one client's claim refuses another client's unrelated
    order, which is an outage that looks like idempotency working.
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"a claim needs {what}")
    if any(ch in text for ch in ":") or any(ch.isspace() for ch in text):
        raise ValueError(
            f"{what} {value!r} contains the key separator or whitespace; "
            f"refusing rather than rewriting it into a key that could "
            f"collide with another identity")
    return text


def setup_key(*, symbol, side, strategy, bar):
    """`SYMBOL:SIDE:strategy:bar` — the decision, as a string.

    Readable on purpose. This is what an operator greps for in Redis at the
    moment they are trying to work out whether an order went out twice, and a
    hash would make that moment harder for no gain.
    """
    return (f"{_symbol(symbol)}:{_side(side)}:"
            f"{_component(strategy, 'a strategy identity')}:{int(bar)}")


def setup_key_for(decision, *, timeframe, strategy=None):
    """The setup key for one RuleDecision.

    `strategy` defaults to the frozen RuleDoc id and version, which is this
    platform's strategy identity: the version is written once and never
    rewritten, so the component names an exact set of terms rather than
    whatever the rule happens to say now.
    """
    if strategy is None:
        rid = _field(decision, "rule_doc_id", "ruleDocId")
        ver = _field(decision, "rule_doc_version", "ruleDocVersion")
        if rid is None or ver is None:
            raise ValueError(
                "a claim needs the frozen rule id and version, or an explicit "
                "strategy identity — the key must name which terms traded")
        strategy = f"{_component(rid, 'a rule id')}v{int(ver)}"
    return setup_key(
        symbol=_field(decision, "symbol"),
        side=_field(decision, "side", "verdict"),
        strategy=strategy,
        bar=bar_open(_field(decision, "snapshot_ts", "snapshotTs"),
                     timeframe))


def claim_key(user_id, account_id, setup):
    """The shared-store key for one client's one account's one setup.

    Namespaced with the rest of the platform so the backup scans it. The
    client and account are part of the key rather than part of the setup
    string because two clients may legitimately take the same market setup at
    the same moment, and one of them must not refuse the other.
    """
    return (f"{_store.namespace_prefix()}liveclaim:"
            f"{_component(user_id, 'a user id')}:"
            f"{_component(account_id, 'an account id')}:{setup}")


def _outcome_key(key):
    return f"{key}:outcome"


class Claim:
    """A held claim, and the token that proves whose it is.

    `holder` is why this module uses `claim_value` rather than `claim`:
    `claim` writes a bare "1", which answers "is this taken" and cannot answer
    "is this still mine". Without the token a release is a bare DEL, and a
    bare DEL after a TTL expiry frees a claim another container has since
    taken — handing a third process a free key while two others believe they
    hold it.
    """

    __slots__ = ("key", "setup_key", "holder", "ttl_s", "claimed_at")

    def __init__(self, *, key, setup_key, holder, ttl_s, claimed_at=None):
        self.key = key
        self.setup_key = setup_key
        self.holder = holder
        self.ttl_s = int(ttl_s)
        self.claimed_at = float(time.time() if claimed_at is None
                                else claimed_at)

    @property
    def outcome_key(self):
        return _outcome_key(self.key)

    def __repr__(self):
        return f"<Claim {self.setup_key}>"


def _new_holder():
    """A token no other process can guess or collide with.

    The pid is in it so a human reading the Redis value can tell which process
    holds the claim; the uuid is what actually makes it unique, because pids
    are reused and two containers can share one.
    """
    return f"{uuid.uuid4().hex}:{os.getpid()}"


def claim(decision, *, user_id, account_id, timeframe, strategy=None):
    """Take the right to send this order. Returns a `Claim`, or raises.

    CALL THIS BEFORE THE BROKER IS ASKED FOR ANYTHING. Afterwards is not a
    claim, it is a log line: the duplicate has already been sent by the time
    the second caller finds out somebody else holds the key.

    Raises:
        AlreadyClaimed            another attempt holds this decision
        CoordinationUnavailable   the store could not be asked, so neither
                                  "free" nor "taken" may be assumed
    """
    assert_shared_backend()
    setup = setup_key_for(decision, timeframe=timeframe, strategy=strategy)
    key = claim_key(user_id, account_id, setup)
    seconds = BAR_SECONDS[str(timeframe)]
    ttl_s = seconds + CLAIM_MARGIN_S
    holder = _new_holder()

    # One call. There is deliberately no health probe before it: a probe adds
    # two round trips to the order path, cannot promise the claim will succeed,
    # and would still leave the None answer below to be handled — so it buys
    # latency and a false sense of a guarantee. The claim IS the probe.
    won = user_store.claim_value(key, holder, ttl_s=ttl_s)
    if won is True:
        return Claim(key=key, setup_key=setup, holder=holder, ttl_s=ttl_s)
    if won is False:
        raise AlreadyClaimed(
            f"a live order for {setup} is already claimed", setup_key=setup,
            key=key, outcome=_read_outcome(key, quiet=True))
    raise CoordinationUnavailable(
        f"the shared store could not confirm a claim on {setup}, so no order "
        f"may be sent — an unanswered claim is not a won one")


def _write_outcome(claim_obj, row):
    """Record what happened. True only when the store confirmed the write.

    Reported rather than raised. By the time this is called the claim's state
    is already correct — held or released as the outcome requires — and that
    is the part that stops a duplicate. The permanent record of a live order
    is the §7 audit trail, which refuses rather than reporting a failed
    append; this record exists so a duplicate can be answered with the
    original result, and losing it costs an explanation, not money.
    """
    raw = json.dumps(row, separators=(",", ":"), sort_keys=True)
    try:
        return bool(user_store.set_blob(claim_obj.outcome_key, raw,
                                        ttl_s=OUTCOME_KEEP_S))
    except Exception:                                   # noqa: BLE001
        return False


def _read_outcome(key, *, quiet=False):
    raw = None
    try:
        raw = user_store.get_blob_strict(_outcome_key(key))
    except Exception as e:                              # noqa: BLE001
        if quiet:
            # Reached from inside an AlreadyClaimed refusal, where the refusal
            # itself is the answer and is already correct. Failing to attach
            # the original outcome must not turn a correct refusal into an
            # error about the store.
            return None
        raise CoordinationUnavailable(
            f"the recorded outcome could not be read: {type(e).__name__} — "
            f"'no outcome recorded' and 'the store did not answer' are "
            f"different facts and this is the second one") from e
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        # A record that will not parse is not an absent one, for the same
        # reason store._decode refuses: reading it as absent lets a caller act
        # as though nothing happened.
        raise CoordinationUnavailable(
            f"the recorded outcome at {_outcome_key(key)} is unreadable")


def outcome_for(claim_obj):
    """What was recorded for this claim, or None if nothing was.

    Raises CoordinationUnavailable when the store could not answer, because a
    live order's outcome read as "nothing recorded" during an outage is how a
    retry decides it is safe to send again.
    """
    key = claim_obj.key if isinstance(claim_obj, Claim) else str(claim_obj)
    return _read_outcome(key)


def _row(claim_obj, outcome, **fields):
    row = {"outcome": outcome, "setupKey": claim_obj.setup_key,
           "at": time.time()}
    for name, value in fields.items():
        if value is not None:
            row[name] = value
    return row


def confirm_filled(claim_obj, *, broker_reply, position_id):
    """The broker confirmed a position. Record it and KEEP the claim.

    Not releasing is the point. The position exists; the next retry of this
    decision must be refused, and the claim is the only thing that refuses it.
    """
    row = _row(claim_obj, FILLED, positionId=str(position_id)
               if position_id is not None else None,
               brokerReply=broker_reply)
    row["recorded"] = _write_outcome(claim_obj, row)
    row["released"] = False
    return row


def confirm_rejected(claim_obj, *, broker_reply, code):
    """The broker confirmed there is no order. Release the claim.

    Safe to release precisely because the outcome is confirmed: nothing
    exists, so the decision may be taken again inside this bar — a price that
    moved back through the level is a legitimate second attempt, and holding
    the key for the rest of a daily bar would refuse it.

    The release happens FIRST, because release_claim is the atomic check of
    whether this process is the holder, and a confirmation from something that
    is not the holder must be refused before it writes anything.
    """
    if not code:
        raise ValueError(
            "a confirmed rejection needs the broker's code — a refusal "
            "nobody can read is a refusal nobody can debug")
    freed = user_store.release_claim(claim_obj.key, claim_obj.holder)
    if freed is None:
        raise CoordinationUnavailable(
            f"the store could not confirm the release of "
            f"{claim_obj.setup_key}; the claim is treated as still held")
    if freed is False:
        raise NotTheHolder(
            f"this process does not hold the claim on {claim_obj.setup_key}, "
            f"so it must not record an outcome for it")
    row = _row(claim_obj, REJECTED, code=str(code), brokerReply=broker_reply)
    row["recorded"] = _write_outcome(claim_obj, row)
    row["released"] = True
    return row


def abandon_unknown(claim_obj, *, detail):
    """The result is not known. Record that, and DO NOT release the claim.

    THE ONE FUNCTION IN THIS MODULE THAT MUST DO NOTHING. A submit that timed
    out may have filled. Releasing the claim here is what turns one uncertain
    order into two certain ones, and the code that would do it sits in an
    exception handler where releasing feels like cleaning up.

    So there is no call to release_claim in this function, and there must
    never be one. The claim expires with its own TTL, which outlives the bar
    it guards, and §8's wind-down is what stops the loop in the meantime.
    """
    if not str(detail or "").strip():
        raise ValueError(
            "an unknown outcome needs to say what was not known — this is "
            "the record somebody reads while deciding whether a real "
            "position exists")
    row = _row(claim_obj, UNKNOWN, detail=str(detail)[:1000])
    row["recorded"] = _write_outcome(claim_obj, row)
    row["released"] = False
    return row


# Refused at import, exactly as user_store refuses to start in production
# without a shared backend. Placed last so every name above is defined before
# the refusal fires — a traceback from a half-imported module is harder to read
# than it needs to be, and this one is read during an outage.
assert_shared_backend()
