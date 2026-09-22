"""evaluate(rule_doc, snapshot) -> RuleDecision. A pure function.

No clock, no network, no broker, no environment, no randomness. The same
RuleDoc and the same MarketSnapshot must give the same RuleDecision forever,
because that is the only way the journal can answer "why did this happen?"
with something a client can check rather than trust.

THREE-VALUED LOGIC, ON PURPOSE.

A condition is true, false, or UNKNOWN - the data to answer it was not there.
Most systems quietly fold unknown into false, and the result looks identical
to an honest no-signal, so nobody finds out. This evaluator keeps the third
value and combines with Kleene's rules:

    AND   any false  -> not met (a false makes the rest irrelevant)
          else any unknown -> refuse: the remaining trues do not carry it
    OR    any true   -> met (a true makes the rest irrelevant)
          else any unknown -> refuse

That is not pedantry. Under OR, a condition the client added to BLOCK entries
stops blocking the moment its indicator goes undefined; under AND, an
indicator with too little history makes a rule that silently never fires and
never says why. Both are answered here instead.

A MISCONFIGURED condition is different from an unknown one and always refuses,
even on a bar where the logic would have short-circuited past it. A typo in a
parameter does not stop being a typo because this bar happened to resolve
early - the client's rule does not mean what their screen says it means, and
they need to know now rather than on the bar where it matters.

NO SHORT-CIRCUIT EVALUATION. Every condition is evaluated even once the
outcome is decided, because "why did nothing happen today?" is the question
this product exists to answer, and a short-circuit leaves half the conditions
with no recorded result. The cost is a few indicator passes per bar.
"""

from apex.platform import conditions as cond
from apex.platform import decision as dec
from apex.platform import ruledoc

UNKNOWN = None


def _eval_block(block, snap):
    """(results, satisfied, problem) for one AND/OR group.

    `satisfied` is True, False or UNKNOWN. `problem` is (code, reason) when
    the block cannot be judged at all.
    """
    combine = (block or {}).get("combine", "AND")
    results, states = [], []
    misconfigured = None
    unavailable = None

    for raw in (block or {}).get("conditions") or []:
        cid = (raw or {}).get("id")
        params = (raw or {}).get("params") or {}
        try:
            passed, detail, clean = cond.evaluate_one(cid, params, snap)
            results.append(dec.ConditionResult(cid, passed, detail, clean))
            states.append(passed)
        except cond.ConditionMisconfigured as e:
            results.append(dec.ConditionResult(cid, UNKNOWN, str(e), params))
            states.append(UNKNOWN)
            misconfigured = misconfigured or str(e)
        except cond.ConditionUnavailable as e:
            results.append(dec.ConditionResult(cid, UNKNOWN, str(e), params))
            states.append(UNKNOWN)
            unavailable = unavailable or str(e)
        except Exception as e:  # noqa: BLE001 - an indicator blew up
            # Never let this become a False. An exception inside an indicator
            # is the least understood state there is; treating it as "the
            # condition was not met" would trade around a bug in silence.
            results.append(dec.ConditionResult(
                cid, UNKNOWN, f"{type(e).__name__}: {e}", params))
            states.append(UNKNOWN)
            misconfigured = misconfigured or f"{cid}: {type(e).__name__}: {e}"

    # A broken parameter refuses regardless of how the logic would resolve.
    if misconfigured:
        return results, UNKNOWN, (dec.CONDITION_ERROR, misconfigured)

    if combine == "OR":
        if any(s is True for s in states):
            return results, True, None
        if any(s is UNKNOWN for s in states):
            return results, UNKNOWN, (dec.INSUFFICIENT_DATA, unavailable)
        return results, False, None

    if any(s is False for s in states):
        return results, False, None
    if any(s is UNKNOWN for s in states):
        return results, UNKNOWN, (dec.INSUFFICIENT_DATA, unavailable)
    return results, True, None


def _side_for(doc, results):
    """(side, problem). Which way a satisfied entry block points.

    `sides` is the client's choice and wins outright - a one-sided rule is
    taken at its word even when its conditions argue the other way, because
    "only buy, and only when momentum is stretched" is a strategy, not a
    mistake. The condition biases are consulted only for BOTH, where nothing
    else can say which direction a set of booleans means.
    """
    want = doc.get("sides", "BOTH")
    if want in (dec.BUY, dec.SELL):
        return want, None

    votes = set()
    for r in results:
        if r.passed is True:
            b = cond.bias_of(r.condition_id, r.params)
            if b:
                votes.add(b)
    if len(votes) == 1:
        return votes.pop(), None
    if not votes:
        return None, (dec.DIRECTION_AMBIGUOUS,
                      "sides is BOTH and none of the satisfied conditions "
                      "implies a direction — set sides to BUY or SELL, or "
                      "add a directional condition")
    return None, (dec.DIRECTION_AMBIGUOUS,
                  f"sides is BOTH and the satisfied conditions disagree on "
                  f"direction ({', '.join(sorted(votes))}) — split this into "
                  f"one rule per side")


def _schedule_problem(doc, snap):
    """(code, reason) when the bar is outside the rule's schedule."""
    sched = doc.get("schedule") or {}
    days = sched.get("days") or []
    windows = sched.get("windows") or []
    if not days and not windows:
        return None
    from datetime import datetime, timezone
    t = datetime.fromtimestamp(snap.ts, timezone.utc)
    if days and t.weekday() not in days:
        return (dec.OUTSIDE_SCHEDULE,
                f"{t.strftime('%a')} is not one of the rule's trading days")
    if windows:
        now = t.hour * 60 + t.minute
        for w in windows:
            try:
                start = cond._minutes(w.get("from"), "schedule", "from")
                end = cond._minutes(w.get("to"), "schedule", "to")
            except cond.ConditionMisconfigured as e:
                return (dec.RULE_INVALID, str(e))
            inside = start <= now < end if start < end \
                else (now >= start or now < end)
            if inside:
                return None
        return (dec.OUTSIDE_SCHEDULE,
                f"{t.strftime('%H:%M')} UTC is outside every trading window")
    return None


def _limit_problem(doc, snap):
    """(code, reason) when a doc-level limit blocks a NEW position.

    Only new positions. An open trade stays manageable while these block, which
    is what `onLimit: "block"` means — a spread spike must not be able to
    strand a position by making its exit unreachable.
    """
    limits = doc.get("limits") or {}
    max_open = limits.get("maxOpenPositions")
    if isinstance(max_open, int) and not isinstance(max_open, bool):
        n = len(snap.positions_for())
        if n >= max_open:
            return (dec.MAX_POSITIONS_REACHED,
                    f"{n} position(s) already open on {snap.symbol}, "
                    f"limit is {max_open}")
    cap = limits.get("maxSpreadPips")
    if isinstance(cap, (int, float)) and not isinstance(cap, bool):
        if snap.spread_pips is None:
            return (dec.INSUFFICIENT_DATA,
                    "the rule caps spread but the snapshot carries none, so "
                    "the cap cannot be honoured")
        if snap.spread_pips > cap:
            return (dec.SPREAD_LIMIT_EXCEEDED,
                    f"spread {snap.spread_pips:.1f} pips is over the "
                    f"{cap:.1f} pip cap")
    return None


def _same(a, b):
    n = lambda s: str(s or "").replace("_", "").replace("/", "").upper()
    return n(a) == n(b)


def evaluate(doc, snap):
    """The rule's verdict on this bar."""
    doc = doc or {}
    rid = doc.get("ruleDocId")
    ver = doc.get("version")

    def _reject(code, reason, results=None):
        return dec.reject(rule_doc_id=rid, rule_doc_version=ver,
                          symbol=snap.symbol, snapshot_ts=snap.ts, code=code,
                          reason=reason, conditions=results)

    def _hold(reason, results=None):
        return dec.hold(rule_doc_id=rid, rule_doc_version=ver,
                        symbol=snap.symbol, snapshot_ts=snap.ts,
                        reason=reason, conditions=results)

    # 1. The document itself. Checked on every bar rather than trusted from
    #    activation, because a stored document can be edited by something
    #    other than this code path.
    problems = ruledoc.validate(doc, known_condition_ids=cond.available())
    if problems:
        return _reject(dec.RULE_INVALID,
                       f"rule is not valid: {'; '.join(problems[:5])}")
    if doc.get("state") != ruledoc.ACTIVE:
        return _reject(dec.RULE_NOT_ACTIVE,
                       f"rule is {doc.get('state')!r}, not active")

    # 2. Is this snapshot even addressed to this rule?
    if not any(_same(s, snap.symbol) for s in doc.get("symbols") or []):
        return _reject(dec.SYMBOL_NOT_IN_RULE,
                       f"{snap.symbol} is not one of this rule's instruments")
    if str(doc.get("timeframe")) != str(snap.timeframe):
        return _reject(dec.TIMEFRAME_MISMATCH,
                       f"rule runs on {doc.get('timeframe')}, snapshot is "
                       f"{snap.timeframe} — evaluating it would answer a "
                       f"different question than the client configured")

    # 3. Managing an open position comes FIRST, and is not gated by the
    #    entry limits. An exit that could be blocked by a spread spike or a
    #    schedule window is not an exit.
    if snap.positions_for():
        results, satisfied, problem = _eval_block(doc.get("exit"), snap)
        if problem:
            return _reject(problem[0], problem[1], results)
        if satisfied is True:
            return dec.RuleDecision(
                verdict=dec.CLOSE, rule_doc_id=rid, rule_doc_version=ver,
                symbol=snap.symbol, snapshot_ts=snap.ts, conditions=results,
                reason=_describe(results, "exit conditions met"))
        return _hold(_describe(results, "holding the open position"), results)

    # 4. New entries.
    sched = _schedule_problem(doc, snap)
    if sched:
        return _reject(sched[0], sched[1])
    lim = _limit_problem(doc, snap)
    if lim:
        return _reject(lim[0], lim[1])

    results, satisfied, problem = _eval_block(doc.get("entry"), snap)
    if problem:
        return _reject(problem[0], problem[1], results)
    if satisfied is not True:
        return _hold(_describe(results, "entry conditions not met"), results)

    side, side_problem = _side_for(doc, results)
    if side_problem:
        return _reject(side_problem[0], side_problem[1], results)

    return dec.RuleDecision(
        verdict=side, rule_doc_id=rid, rule_doc_version=ver,
        symbol=snap.symbol, snapshot_ts=snap.ts, conditions=results, side=side,
        reason=_describe(results, f"{side} — entry conditions met"),
        # confidence stays None. There is no definition behind a number here,
        # and an invented one would read as evidence on a client's screen.
        risk_level=None, confidence=None)


def _describe(results, headline):
    """The reason, assembled from the results rather than written beside them,
    so it cannot drift from what was actually evaluated."""
    if not results:
        return headline
    parts = []
    for r in results:
        mark = {True: "+", False: "-", None: "?"}[r.passed]
        parts.append(f"{mark} {r.condition_id} ({r.detail})")
    return f"{headline}: " + "; ".join(parts)
