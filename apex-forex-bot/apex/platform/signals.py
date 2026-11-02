"""Telling a platform client about a setup the engine found and did NOT place.

WHAT SIGNALS ONLY IS

`apex.automation` defines three levels. At `signals` the loop evaluates the
rule, finds the setup, reports it, and places nothing: `user_loop._signal_only`
posts it through `alert_fn` and the caller sets `entry_ok = False`. The refusal
is the feature. A client at this level has asked to be told, not traded for,
and they trade it themselves at their broker or not at all.

WHY THIS FILE EXISTS, AND WHAT WENT WRONG WITHOUT IT

On the platform that report went nowhere. `automation.start` started the loop
as `user_loop.start(user_id)` with no alert function, so `alert_fn` was None
and `_signal_only` wrote its throttle stamp and returned — every setup found,
nobody told. That is the same shape as the bug 6f984dfe9 fixed one level up,
where a platform client sat in `approval` for ever proposing trades through an
`alert_fn` that was None, while the dashboard said Running. A level whose
output has nowhere to go is not a level this platform can offer, and the fix
for `approval` was to refuse to offer it. The fix here is to give `signals`
somewhere to go.

THIS MODULE CANNOT PLACE AN ORDER, AND THAT IS CHECKED

It imports no broker, no gate, no ledger, no execution path and no
`user_loop`. The only two things it does are append to the journal and write a
notification. It reaches one other platform module, `automation`, and only to
ask `running_context` which rule a signal belongs to — a read. That module can
start and stop loops, so the test does not take the import on trust: it names
the only attribute this file may touch on it, and fails if a second one
appears.

`tests/test_signals_only.py` parses this file for all of that, because "a
signal never causes an order" is the whole promise of the level, and a promise
kept by habit is a promise waiting to be broken by a refactor.

WHERE A SIGNAL LANDS, AND WHY BOTH STORES

Neither store alone is enough, and they are the two that already exist.

  the journal        the durable record. 5000 entries per client, filterable
                     by symbol, time and rule, carrying the setup as data.
                     This is the client's signal history, and it is written
                     FIRST: a notification about a setup with no record behind
                     it is a claim we cannot show.

  notifications      the interruption. One unread row per signal, so a client
                     who was not watching the screen is told. The centre is
                     capped at 500 rows across every type, which is why the
                     history does not live here — a busy week of signals would
                     otherwise evict "your broker account was disconnected".

Nothing here reaches Telegram, deliberately: see notifications.py.
"""

import math

from apex.platform import journal as _j
from apex.platform import journal_store as _jstore
from apex.platform import notifications as _notify

# The engine level this module delivers for, by name rather than by literal at
# the call site. `apex.automation` owns the name; it is repeated here rather
# than imported to keep this module's import list down to the two stores it
# writes to, which is the list the purity test reads. A test asserts this
# string is still one of `automation.MODES`, so the copy cannot drift.
LEVEL_SIGNALS = "signals"

# The engine `alert_fn` payload actions THIS module answers for. An ALLOWLIST,
# not a filter on the ones we do not want: `alert_fn` is called for heartbeats,
# broker health, skip warnings, shadow fills, weekend closes and a dozen other
# things, and a notification centre that received all of them would bury the
# two rows that mattered under the ones that did not. Anything not named here
# is dropped — see `engine_alert` for why dropping is the safe direction.
#
# This is also the routing. `automation.engine_alert` offers every alert to
# both sinks and lets each answer for its own actions, so these allowlists
# must not overlap; a test asserts they do not. The roster of LEVELS the
# platform can report for lives with that fan-out, in
# `automation.DELIVERED_LEVELS`, because that is the only place that knows
# which sinks exist.
DELIVERED_ACTIONS = ("SIGNAL",)

# A setup is described to a person, so every text field is bounded before it
# reaches a store or a screen.
_MAX_SYMBOL = 32
_MAX_REASON = 600
_MAX_FACTORS = 8
_MAX_FACTOR = 120

_SIDES = ("BUY", "SELL")


def _text(value, limit):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _finite(value):
    """`value` as a float, or None. NaN and infinity are not numbers here.

    A price of nan renders as "nan" and reads to a client as a broken screen,
    so it is treated as absent rather than passed on. Absent is sayable;
    nonsense is not.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def parse(payload):
    """The engine's SIGNAL payload as something describable, or None.

    VALIDATED AT THE BOUNDARY, BECAUSE THIS IS ONE. The engine hands over a
    plain dict assembled a long way from here, and everything below renders it
    to a client.

    REQUIRED: the instrument and the side. A signal missing either cannot be
    acted on by the person reading it, and telling somebody "a setup happened"
    without saying what to buy is worse than silence — it looks like news.
    Those two missing is a refusal, and the caller journals it rather than
    dropping it quietly.

    OPTIONAL: price, confidence, reasoning, key factors. These are reported as
    unknown when they do not arrive, and NOT a reason to withhold the signal:
    the promise of this level is that the client hears about every setup, so an
    unreadable confidence must not be allowed to cancel one.
    """
    if not isinstance(payload, dict):
        return None
    symbol = _text(payload.get("symbol"), _MAX_SYMBOL).upper()
    side = _text(payload.get("side") or payload.get("action"), 8).upper()
    if not symbol or side not in _SIDES:
        return None
    price = _finite(payload.get("price"))
    if price is not None and price <= 0:
        price = None
    # Confidence is the engine's 0–100 integer scale (cfg.MIN_CONFIDENCE
    # defaults to 68), not a 0–1 probability. Anything outside the scale is a
    # number we cannot label with a % sign, so it is unknown.
    conf = _finite(payload.get("confidence"))
    if conf is not None and not (0 <= conf <= 100):
        conf = None
    factors = payload.get("keyFactors")
    if not isinstance(factors, (list, tuple)):
        factors = []
    return {
        "symbol": symbol,
        "side": side,
        "price": price,
        "confidence": conf,
        "reasoning": _text(payload.get("reasoning"), _MAX_REASON),
        "keyFactors": [f for f in
                       (_text(x, _MAX_FACTOR) for x in factors[:_MAX_FACTORS])
                       if f],
    }


def headline(sig):
    """What the alerts list shows as the row's title."""
    return f"{sig['side'].capitalize()} setup: {sig['symbol']}"


def summary(sig):
    """The setup in prose, for a person reading a notification row.

    Written out in full rather than left to the UI to assemble, so the same
    sentence reaches every channel this notification is ever read through and
    there is only one place where "nothing was placed" can be forgotten.
    """
    parts = [f"{sig['side'].capitalize()} {sig['symbol']}"]
    parts.append(f"around {sig['price']:g}" if sig["price"] is not None
                 else "entry price unavailable")
    if sig["confidence"] is not None:
        parts.append(f"confidence {sig['confidence']:g}%")
    lead = " · ".join(parts) + "."
    tail = []
    if sig["reasoning"]:
        tail.append(sig["reasoning"])
    if sig["keyFactors"]:
        tail.append("Key factors: " + ", ".join(sig["keyFactors"]) + ".")
    # Last, and never omitted. This is the one sentence that distinguishes a
    # signal from a trade, and a client scanning a list of alerts has to be
    # able to tell which they are looking at without opening anything.
    tail.append("Nothing was placed — this rule runs at Signals Only. "
                "Place it yourself at your broker, or not at all.")
    return " ".join([lead] + tail)


def deliver(user_id, payload, *, correlation_id=None, account_id=None,
            rule_doc_id=None, now=None):
    """Record one signal and tell its owner. Returns the parsed signal or None.

    The journal entry goes first. It is the evidence, it is the thing a client
    can still find next week, and a notification pointing at a record that was
    never written would be the one failure mode worse than no notification.
    """
    sig = parse(payload)
    corr = correlation_id or _j.new_correlation_id()
    if sig is None:
        # NOT dropped in silence. An unreadable signal means the client was
        # not told about a setup the engine found, which is exactly the
        # failure this whole file exists to end, so it leaves a trace that
        # somebody can search for instead of a gap nobody can.
        _jstore.record_error(
            "the engine reported a setup this platform could not read, so "
            "nothing was delivered for it",
            correlation_id=corr, user_id=user_id, account_id=account_id)
        return None
    _jstore.record_signal(
        sig, correlation_id=corr, user_id=user_id, account_id=account_id,
        rule_doc_id=rule_doc_id, ts=now)
    _notify.notify(user_id, type=_notify.SIGNAL, level=_notify.INFO,
                   title=headline(sig), body=summary(sig),
                   # The journal is where the setup keeps its detail once the
                   # notification centre has rotated past it.
                   link="/journal", correlation_id=corr, ts=now)
    return sig


def _running_context(user_id):
    """Which rule and account the loop that produced this signal is running.

    Read at DELIVERY time rather than bound into the alert function when the
    loop starts, because one of the two ways a loop starts has nothing to bind:
    the engine's watchdog restarts a dead loop itself, 180 seconds at a time,
    with no knowledge of this platform's records. A closure captured in
    `automation.start` would carry the rule for loops started by a client and
    None for every loop the watchdog brought back — the sort of difference that
    shows up as a journal that is complete until the night something restarts.

    Imported here rather than at module scope because `automation` reaches this
    module, and best-effort because a signal whose rule we cannot name is still
    a signal the client must be told about.
    """
    try:
        from apex.platform import automation as _am
        return _am.running_context(user_id)
    except Exception:                                       # noqa: BLE001
        return {}


def engine_alert(user_id, payload):
    """The engine's alert sink for signals. Delivers, never trades, never raises.

    Shaped to match `approvals.engine_alert`, because `automation` hands the
    engine ONE alert function and both are reached through it.

    IT ALLOWLISTS. `alert_fn` is a firehose — STOP, CLOSE, BROKER_HEALTH,
    SKIP_WARN, WEEKEND_CLOSE, SHADOW_OPEN, heartbeats — and only the actions in
    `DELIVERED_ACTIONS` are delivered. Anything else is dropped rather than
    guessed at, `SUGGEST` included: that is the approval level's proposal, it
    needs an answer, and announcing it from here would make this module the
    second owner of something that needs exactly one.

    IT NEVER RAISES. This runs on the trading thread inside the tick that found
    the setup. The whole tick body sits in one try/except in `user_loop._loop`,
    so an exception here cannot place an order — but it does abandon the rest of
    the tick, and the rest of the tick is where trailing stops, exits and
    position management live. A notification store having a bad moment must not
    cost a client their stop management.
    """
    try:
        if not isinstance(payload, dict):
            return None
        if _text(payload.get("action"), 32).upper() not in DELIVERED_ACTIONS:
            return None
        ctx = _running_context(user_id)
        return deliver(user_id, payload,
                       correlation_id=ctx.get("correlationId"),
                       account_id=ctx.get("accountId"),
                       rule_doc_id=ctx.get("ruleDocId"))
    except Exception as e:                                  # noqa: BLE001
        print(f"[Signals] the setup alert for {user_id} could not be "
              f"delivered ({type(e).__name__}: {e}) — the loop carries on")
        return None
