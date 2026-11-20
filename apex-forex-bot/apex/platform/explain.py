"""A decision, explained: what held, what did not, and who stopped it.

WHAT THIS IS

`RuleDecision.as_dict()` already carries the evidence: each condition with its
parameters and whether it passed, the reason, the refusal code, the rule
version and the snapshot time. What a reader still has to work out alone is the
question that matters when nothing happened: was it my STRATEGY (the setup was
not there), a RISK GUARD (the setup was there and a limit said no), the BROKER,
or the INFRASTRUCTURE? This module answers that, from the code the decision
already holds, and nothing else.

WHAT IT DOES NOT DO

It reads a decision dict. It does not evaluate anything, call a broker or touch
a store. A refusal code it does not know is reported as unknown, with the code
itself, rather than being filed under a category it was never given. The
sentences are templates over fields the decision carries; no field is guessed.
"""

STRATEGY = "strategy"            # the setup was not there, or the rule is wrong
RISK_GUARD = "risk_guard"        # the setup was there; a limit refused it
BROKER = "broker"                # the broker's state, mode or response
INFRASTRUCTURE = "infrastructure"  # our own systems could not do it safely
ACCOUNT = "account"              # licence, entitlement, release switch
UNKNOWN = "unknown"

# code -> (category, guard or area, plain sentence)
_CODES = {
    "RULE_INVALID": (STRATEGY, "rule validation", "The rule does not pass validation, so it cannot run."),
    "RULE_NOT_ACTIVE": (STRATEGY, "rule state", "The rule is not active."),
    "UNKNOWN_CONDITION": (STRATEGY, "rule validation", "The rule uses a condition this platform does not know."),
    "CONDITION_ERROR": (STRATEGY, "condition", "A condition could not be evaluated."),
    "SYMBOL_NOT_IN_RULE": (STRATEGY, "rule scope", "This instrument is not one the rule trades."),
    "TIMEFRAME_MISMATCH": (STRATEGY, "rule scope", "The data is not on the timeframe the rule uses."),
    "SIDE_NOT_ALLOWED": (STRATEGY, "rule scope", "The rule does not allow this direction."),
    "DIRECTION_AMBIGUOUS": (STRATEGY, "rule logic", "The conditions point both ways, so no direction was chosen."),
    "OUTSIDE_SCHEDULE": (RISK_GUARD, "session filter", "It is outside the hours the rule is allowed to trade."),
    "SPREAD_LIMIT_EXCEEDED": (RISK_GUARD, "spread limit", "The spread is wider than the maximum the rule allows."),
    "MAX_POSITIONS_REACHED": (RISK_GUARD, "maximum positions", "The maximum number of open positions is already reached."),
    "INSUFFICIENT_DATA": (INFRASTRUCTURE, "market data", "There was not enough price data to decide."),
    "PRESET_STRATEGY": (STRATEGY, "preset strategy", "This rule uses a ready-made strategy, which decides in the engine rather than by conditions."),
    "NOT_EXECUTABLE": (STRATEGY, "decision", "The decision was not an entry, so no order was built."),
    "CONSTRAINT_UNSUPPORTED": (STRATEGY, "rule validation", "The rule asks for a constraint the engine does not enforce."),
    "SIZING_FAILED": (RISK_GUARD, "position sizing", "A position size could not be worked out safely."),
    "NO_STOP": (RISK_GUARD, "stop loss", "No stop loss could be set, and an order without one is not sent."),
    "RISK_REFUSED": (RISK_GUARD, "risk limit", "A risk limit refused the order."),
    "HALTED": (ACCOUNT, "emergency stop", "An emergency stop is active."),
    "LIVE_NOT_ENABLED": (ACCOUNT, "release switch", "Live trading is not switched on."),
    "NOT_ENTITLED": (ACCOUNT, "licence", "The licence does not cover this."),
    "MODE_NOT_LIVE": (BROKER, "account mode", "The broker reports this account is not a live account."),
    "MODE_UNVERIFIED": (BROKER, "account mode", "The broker did not confirm whether this is a live or demo account."),
    "RATE_LIMITED": (RISK_GUARD, "order rate", "Too many orders in a short time."),
    "RATE_UNKNOWN": (INFRASTRUCTURE, "order rate", "The order counter could not be read, so the order was refused."),
    "LEDGER_UNAVAILABLE": (INFRASTRUCTURE, "order ledger", "The order record could not be written, so the order was refused."),
    "AUDIT_UNAVAILABLE": (INFRASTRUCTURE, "audit trail", "The audit record could not be written, so the order was refused."),
    "ALREADY_CLAIMED": (INFRASTRUCTURE, "duplicate protection", "This exact order was already sent."),
    "BUILD_REFUSED": (RISK_GUARD, "order build", "The order could not be built within the rules."),
    "NOT_A_TRADE": (STRATEGY, "decision", "The decision was not a trade."),
}


def _cond_line(c):
    cid = str(c.get("id") or "condition")
    params = c.get("params") or {}
    detail = (c.get("detail") or "").strip()
    return {"id": cid, "params": params, "detail": detail or None}


def explain(decision):
    """Structured explanation of one decision dict. Pure; never raises on a
    malformed input, it reports what it could read."""
    d = decision if isinstance(decision, dict) else {}
    verdict = d.get("verdict")
    conds = [c for c in (d.get("conditions") or []) if isinstance(c, dict)]
    met = [_cond_line(c) for c in conds if c.get("passed") is True]
    unmet = [_cond_line(c) for c in conds if c.get("passed") is False]
    unknown = [_cond_line(c) for c in conds if c.get("passed") is None]
    code = d.get("refusalCode")

    blocked = None
    if code:
        cat, guard, sentence = _CODES.get(code, (
            UNKNOWN, None,
            f"The platform refused this with code {code}, which has no "
            f"plain-language description yet."))
        blocked = {"category": cat, "code": code, "guard": guard,
                   "sentence": sentence}

    if verdict in ("BUY", "SELL"):
        outcome = "setup"
        headline = (f"All {len(met)} condition(s) held; the rule found a "
                    f"{verdict} setup.") if met and not unmet else \
            f"The rule found a {verdict} setup."
    elif verdict == "HOLD":
        outcome = "no_setup"
        if unmet:
            first = unmet[0]["id"]
            headline = (f"No setup: {len(unmet)} of {len(conds)} condition(s) "
                        f"did not hold, starting with {first}.")
        else:
            headline = d.get("reason") or "No setup: the conditions were not met."
    elif verdict == "REJECT":
        outcome = "refused"
        headline = (blocked["sentence"] if blocked else
                    d.get("reason") or "The rule could not run.")
        if met and blocked and blocked["category"] == RISK_GUARD:
            headline = (f"{len(met)} condition(s) held, but {blocked['guard']} "
                        f"refused it: {blocked['sentence']}")
    elif verdict == "CLOSE":
        outcome = "close"
        headline = "The rule decided to close the position."
    else:
        outcome = "unknown"
        headline = "This decision could not be read."

    if unknown:
        headline += f" {len(unknown)} condition(s) could not be evaluated."

    return {
        "outcome": outcome,
        "headline": headline,
        "met": met, "unmet": unmet, "unknown": unknown,
        "blockedBy": blocked,
        "dataUsed": {"symbol": d.get("symbol"),
                     "snapshotTs": d.get("snapshotTs"),
                     "ruleDocId": d.get("ruleDocId"),
                     "ruleDocVersion": d.get("ruleDocVersion")},
    }
