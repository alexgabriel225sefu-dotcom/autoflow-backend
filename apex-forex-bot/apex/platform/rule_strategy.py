"""The strategy module that decides nothing, and asks the rule instead.

WHAT WAS WRONG

A client built a rule — "RSI(14) below 30" to enter, "RSI(14) above 70" to
leave — activated it, pressed Start, and the engine chose entries with ITS OWN
strategies. `engine_config.translate` carried the stop, the target, the risk
percentage and the instrument across, and reported `entry` and `exit` to the
client as terms it would not act on. The conditions never reached the loop.

WHY IT IS THIS SHAPE

The loop already dispatches its decision through a registry:

    _strategy = strategy_api.get(active_mode)       # active_mode = cfg.STRATEGY
    ...
    return _strategy.signal(_frame)

`cfg.STRATEGY` is per-account, so `engine_config` can point one account's loop
at a strategy module that does nothing but ask the PLATFORM EVALUATOR about
that account's running rule. That is this file.

THE RULE THIS FILE FOLLOWS

**There is exactly one implementation of "does this rule fire".**

Not one for the preview screen and one for the loop. This module builds a
MarketSnapshot and calls `evaluator.evaluate` — the same function the rule
preview calls — and translates the verdict into the dict the loop reads. It
evaluates no condition itself, which is asserted directly: a test replaces
`evaluator.evaluate` and watches the verdict change with it, and a second
evaluation path anywhere in here would survive that substitution.

So the ONLY logic in this file is:

  * find the rule that is actually running for this account
  * drop the candle that has not closed yet
  * build the snapshot
  * translate the verdict

WHAT IT CANNOT DO

It cannot place, close or amend anything. It returns an opinion and the loop's
own risk engine decides what to do with it, exactly as for every other
strategy module. There is no import of the order bridge here and there must
never be one — `tests/test_rule_drives_loop.py` reads this file's AST and
fails if one appears.
"""

import time

from apex import sentinel as _sentinel
from apex import strategy_api
from apex.platform import automation as _automation
from apex.platform import conditions as _conditions
from apex.platform import decision as _decision
from apex.platform import engine_config as _engine_config
from apex.platform import evaluator as _evaluator
from apex.platform import snapshot as _snapshot
from apex.platform import store as _store

STRATEGY_ID = _engine_config.RULE_STRATEGY_ID
STRATEGY_VERSION = "1.0.0"

# The engine's sizing heuristic reads a confidence and a criteria count, and a
# score-less verdict landed on its 0.6x branch — so a client who set 1% risk
# was given 0.6% and nothing said so. A rule has no probability behind it: it
# fires or it does not. These two numbers are the fixed point of
# `strategies.druckenmiller_multiplier`, the pair that makes it return exactly
# 1.0x, and they mean "no size opinion", not "75% likely".
#
# They are passed to the loop's gates and are NOT evidence. The RuleDecision
# itself keeps `confidence=None`, because the evaluator refuses to invent a
# number that would read as evidence on a client's screen, and that refusal is
# right. `tests/test_rule_drives_loop.py` pins the 1.0x.
NEUTRAL_CONFIDENCE = 75
NEUTRAL_CRITERIA = 3


def _condition_ids():
    """The condition ids this release can evaluate.

    Activation validates a document against these, so it is the same registry
    the evaluator checks on every bar — a rule can never be activated with a
    condition the loop would then fail to understand.
    """
    return set(_conditions.available())


# ── finding the rule ────────────────────────────────────────────────────────
def _running_rule(user_id):
    """(doc, None) for the rule this account is running, else (None, why).

    `why` is written to be read by a human looking at a journal line asking
    why nothing happened, so it says which account and what was missing.
    """
    if not user_id:
        return None, ("this market frame carries no account id, so the rule "
                      "running on the account cannot be looked up — holding "
                      "rather than trading something nobody configured")
    # The stored record, not the screen's overlay. The chip says stopped when
    # the thread is gone; this function is how the thread, while it is alive,
    # finds the rule it was started with.
    try:
        rec = _automation._read(user_id)
    except Exception as e:                                   # noqa: BLE001
        return None, (f"the automation state for this account could not be "
                      f"read ({type(e).__name__}), so the running rule is "
                      f"unknown — holding")
    if rec.get("state") != _automation.RUNNING:
        return None, (f"automation is {rec.get('state')!r} for this "
                      f"account, not running, so there is no rule to act on")
    rule_doc_id = rec.get("ruleDocId")
    if not rule_doc_id:
        return None, ("automation is running but names no rule document, "
                      "which is a state nothing should be able to reach — "
                      "holding rather than guessing which rule was meant")
    try:
        return _store.get(user_id, rule_doc_id), None
    except _store.NotFound:
        return None, (f"rule {rule_doc_id} is named by this account's "
                      f"automation but no longer exists — holding")
    except Exception as e:                                   # noqa: BLE001
        return None, (f"rule {rule_doc_id} could not be read "
                      f"({type(e).__name__}) — holding")


# ── the bar that has closed ─────────────────────────────────────────────────
def _closed_candles(candles, bar_seconds, now):
    """`candles` with every bar that has not finished removed.

    `evaluateOn` is "bar_close". The loop's last candle is the bar in
    progress, whose close is not the close — a rule judged on it can fire on a
    price the bar never closes at, and a satisfied rule can be hidden by a
    single tick in the wrong direction. Both directions of that error are
    pinned by tests.

    Several bars are dropped rather than one, because a frame assembled after
    a gap (a weekend, a reconnect) can end with more than one unfinished bar,
    and "drop the last one" would then judge another unfinished bar instead.
    """
    out = list(candles or [])
    while out:
        opened = out[-1].get("time")
        if opened is None:
            # A bar with no timestamp cannot be shown to have closed, and
            # treating it as closed is the error this function exists to
            # prevent, so it goes.
            out.pop()
            continue
        if float(opened) + bar_seconds > now:
            out.pop()
            continue
        break
    return out


def _positions_from(market):
    """The open position as the evaluator needs to see it.

    `MarketSnapshot.positions_for` matches on symbol, and the loop's position
    dict does not always carry one — it belongs to the account's single
    instrument by construction. Without the symbol the evaluator would read
    "no position on this instrument" and look for a new entry while one is
    open, so the frame's symbol is filled in when the position lacks it.
    """
    pos = getattr(market, "open_position", None)
    if not pos:
        return []
    if not pos.get("symbol"):
        pos = dict(pos, symbol=market.symbol)
    return [pos]


def decide(market, now=None):
    """(RuleDecision, "") for this frame, or (None, why).

    `now` is a parameter rather than a clock read so the bar-close arithmetic
    is testable and a decision can be replayed. The snapshot refuses to stamp
    itself for the same reason.
    """
    now = time.time() if now is None else float(now)

    doc, why = _running_rule(getattr(market, "user_id", ""))
    if doc is None:
        return None, why

    bar_seconds = _sentinel.timeframe_seconds(market.timeframe, default=0)
    if not bar_seconds:
        # Defaulting here would judge the wrong bar: a frame labelled with a
        # timeframe nothing recognises would be measured in five-minute
        # candles and the verdict would look ordinary.
        return None, (f"{market.timeframe!r} is not a timeframe this release "
                      f"knows the length of, so which candle has closed "
                      f"cannot be established — holding")

    closed = _closed_candles(market.candles, bar_seconds, now)
    if not closed:
        return None, ("no candle on this frame has closed yet, and a rule is "
                      "judged on closed candles — holding until one does")

    last = closed[-1]
    try:
        snap = _snapshot.MarketSnapshot(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candles=closed,
            price=float(last["close"]),
            # The bar's CLOSE, not the time of this tick: the instant the
            # decision is about, which is what a journal entry has to point at.
            ts=float(last["time"]) + bar_seconds,
            spread_pips=getattr(market, "spread_pips", None),
            open_positions=_positions_from(market),
            balance=market.balance)
    except Exception as e:                                   # noqa: BLE001
        return None, (f"this market frame could not be read as a snapshot "
                      f"({type(e).__name__}: {str(e)[:120]}) — holding")

    # The one call that decides anything. Everything above finds the inputs;
    # everything below translates the answer.
    return _evaluator.evaluate(doc, snap), ""


# ── the loop's shape ────────────────────────────────────────────────────────
_ACTIONS = {
    _decision.BUY: "BUY",
    _decision.SELL: "SELL",
    _decision.CLOSE: "CLOSE",
    _decision.HOLD: "HOLD",
    # A rejected rule is not a trade. REJECT carries a code the client needs
    # to see, and the loop has no verb for it, so it becomes a HOLD whose
    # reason is the refusal.
    _decision.REJECT: "HOLD",
}


def _hold(reasoning, rule_doc_id=None):
    return {"action": "HOLD", "confidence": 0, "criteriaScore": 0,
            "riskLevel": "LOW", "reasoning": reasoning, "keyFactors": [],
            "ruleDocId": rule_doc_id}


class PlatformRuleStrategy(strategy_api.Strategy):
    """Asks the account's running rule. Holds whenever it cannot."""

    strategy_id = STRATEGY_ID
    strategy_version = STRATEGY_VERSION
    label = "Your rule"

    def analyze(self, market):
        """The read, not the decision — the market as the rule will see it."""
        return self.stamp({
            "indicators": market.indicators,
            "strat": market.strat,
            "regime": market.regime,
        })

    def signal(self, market):
        verdict, why = decide(market)
        if verdict is None:
            return self.stamp(_hold(why))

        action = _ACTIONS.get(verdict.verdict, "HOLD")
        entering = action in ("BUY", "SELL")
        out = _hold(verdict.reason, verdict.rule_doc_id)
        out.update({
            "action": action,
            "reasoning": verdict.reason,
            # See NEUTRAL_CONFIDENCE: "no size opinion", not a probability,
            # and only on a verdict that actually asks for a position.
            "confidence": NEUTRAL_CONFIDENCE if entering else 0,
            "criteriaScore": NEUTRAL_CRITERIA if entering else 0,
            "ruleDocId": verdict.rule_doc_id,
            "ruleDocVersion": verdict.rule_doc_version,
        })
        return self.stamp(out)

    def advise_risk(self, market):
        """No size opinion at all.

        The rule's own sizing is already carried onto the account by
        `engine_config.translate`, so a multiplier from here would scale a
        percentage the client chose by a number nothing on their screen
        mentions.
        """
        return {"multiplier": 1.0,
                "reason": "the rule's own risk percentage, unscaled"}

    def exit(self, market):
        """Whether the rule's exit conditions say to leave.

        The same evaluation as `signal`, so the two can never disagree about
        one bar — the loop calls whichever it needs and gets one answer.
        """
        verdict, why = decide(market)
        if verdict is None:
            return self.stamp({"exit": False, "reason": why})
        return self.stamp({
            "exit": verdict.verdict == _decision.CLOSE,
            "reason": verdict.reason,
            "ruleDocId": verdict.rule_doc_id,
        })


strategy_api.register(PlatformRuleStrategy)
