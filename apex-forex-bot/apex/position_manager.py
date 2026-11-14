"""What to do with an open position, and why — as a proposal, never an order.

THE PROBLEM THIS REPLACES

`_manage_trailing` manages a trade by a schedule: stop to entry at +1R, then a
1R trail. It is correctly implemented and it is losing money. On the live
account it produces a 60% win rate at a profit factor of 1.10, because a target
at 2.4R behind a 1R trail is a target that is rarely reached — winners get
closed near 1R while losers run the full stop. The journal shows the
fingerprints: USDJPY +0.26, NZDUSD -0.56, EURUSD -1.98.

The alternative is not a looser trail. It is managing by the REASON: hold while
the thesis holds, act when it stops holding. A pullback that does not break
structure invalidates nothing, so the winner survives it.

WHAT THIS MODULE IS ALLOWED TO DO

Propose. Nothing here calls a broker, and `gates.authorize_close` remains the
only thing that can permit a close. A proposal carries a reason code that was
computed from a measured condition — §18 forbids choosing the exit reason after
the fact from the outcome.

WHY IT DOES NOT CHURN

§16 says not to churn positions and not to exit on a bare timer. Two rules do
that work here: a proposal must clear a minimum improvement before it is worth
an amend, and the manager will not re-propose the same action for the same
position inside a cooldown.
"""

import time

from apex import thesis as _thesis

# ── Proposed actions ─────────────────────────────────────────────────────
HOLD = "HOLD"
TIGHTEN_STOP_PROPOSED = "TIGHTEN_STOP_PROPOSED"
REDUCE_PROPOSED = "REDUCE_PROPOSED"
EXIT_PROPOSED = "EXIT_PROPOSED"

ACTIONS = (HOLD, TIGHTEN_STOP_PROPOSED, REDUCE_PROPOSED, EXIT_PROPOSED)

# ── Exit reason codes (§18) ──────────────────────────────────────────────
# The reason is the condition that FIRED. Never derived from the P&L: a
# profitable manual close is not a target hit, and labelling it one turns the
# journal into a story about how well the strategy worked.
THESIS_INVALIDATED = "THESIS_INVALIDATED"
TARGET_REACHED = "TARGET_REACHED"
STOP_LEVEL_BROKEN = "STOP_LEVEL_BROKEN"
RISK_VIOLATION = "RISK_VIOLATION"
PORTFOLIO_RISK = "PORTFOLIO_RISK"
SPREAD_UNTRADEABLE = "SPREAD_UNTRADEABLE"
THESIS_WEAKENING = "THESIS_WEAKENING"
PROTECT_PROFIT = "PROTECT_PROFIT"
NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
THESIS_UNREADABLE = "THESIS_UNREADABLE"
COOLDOWN = "MANAGEMENT_COOLDOWN"

REASON_TEXT = {
    THESIS_INVALIDATED: "the reason for this trade no longer holds",
    TARGET_REACHED: "the recorded target was reached",
    STOP_LEVEL_BROKEN: "price traded through the level the trade was built on",
    RISK_VIOLATION: "an account risk limit was breached",
    PORTFOLIO_RISK: "total exposure needs reducing",
    SPREAD_UNTRADEABLE: "the spread is too wide to manage this position now",
    THESIS_WEAKENING: "part of the reason for this trade has stopped holding",
    PROTECT_PROFIT: "enough of the move is banked to protect it",
    NO_ACTION_NEEDED: "the trade is doing what it was opened to do",
    THESIS_UNREADABLE: "the market could not be read this pass",
    COOLDOWN: "the same action was proposed moments ago",
}

MANAGER_VERSION = "1.0.0"

# Defaults. Every one is overridable through `policy` so §71 holds — nothing
# here is a magic financial constant.
DEFAULTS = {
    # Below this the position is not touched at all: there is no profit to
    # protect and the stop is where the strategy put it.
    "protect_from_r": 1.0,
    # How far behind price a protective stop sits, in R. Wider than the old
    # 1R trail on purpose — the old one sat inside ordinary noise for a
    # ranging instrument, which is what cut the winners.
    "protect_trail_r": 1.5,
    # A proposal must move the stop at least this much of one R to be worth an
    # amend. Stops churn otherwise.
    "min_improvement_r": 0.15,
    # Do not repeat the same proposal for the same position this often.
    "cooldown_s": 120,
    # A weakening thesis proposes tightening, not exiting. Only invalidation
    # exits. This is the whole difference from the schedule-based policy.
    "exit_on_weakening": False,
}


class Proposal:
    """One proposed action on one position. Carries its own justification."""

    __slots__ = ("action", "reason", "symbol", "position_id", "new_stop",
                 "reduce_fraction", "at", "thesis_state", "findings", "r_now",
                 "detail")

    def __init__(self, action, reason, *, symbol, position_id=None,
                 new_stop=None, reduce_fraction=None, thesis_state=None,
                 findings=None, r_now=None, detail="", at=None):
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        self.action = action
        self.reason = reason
        self.symbol = str(symbol).upper()
        self.position_id = position_id
        self.new_stop = new_stop
        self.reduce_fraction = reduce_fraction
        self.thesis_state = thesis_state
        self.findings = list(findings or [])
        self.r_now = r_now
        self.detail = detail
        self.at = at or time.time()

    @property
    def acts(self):
        return self.action != HOLD

    def to_dict(self):
        return {"action": self.action, "reason": self.reason,
                "reasonText": REASON_TEXT.get(self.reason, self.reason),
                "symbol": self.symbol, "positionId": self.position_id,
                "newStop": self.new_stop,
                "reduceFraction": self.reduce_fraction,
                "thesisState": self.thesis_state, "findings": self.findings,
                "rNow": self.r_now, "detail": self.detail,
                "managerVersion": MANAGER_VERSION, "at": round(self.at, 3)}

    def __repr__(self):
        return f"<Proposal {self.symbol} {self.action} {self.reason}>"


# Per-position memory of the last proposal, so the same one is not repeated
# every tick. Process-local by design: this is churn control, not a financial
# control, and a restart proposing once more is harmless.
_last = {}


def _cooled(position_key, action, cooldown_s, now):
    prev = _last.get(position_key)
    if prev and prev[0] == action and (now - prev[1]) < cooldown_s:
        return True
    return False


def _remember(position_key, action, now):
    _last[position_key] = (action, now)
    if len(_last) > 500:                       # bounded; oldest first
        for k in list(_last)[:200]:
            _last.pop(k, None)


def reset_memory():
    """For tests, and for a deliberate restart of management state."""
    _last.clear()


def evaluate(position, th, observation, *, policy=None, risk_context=None,
             now=None):
    """(Proposal) for one open position. Deterministic. Never raises.

    `position`  — the broker's own row: symbol, side, positionId, stopLoss…
    `th`        — the frozen Thesis, or None when the trade predates it
    `observation` — what the platform measures now (see thesis.evaluate)

    A position with no recorded thesis is HELD and reported as such. Inventing
    a thesis for it after the fact would be exactly the retrospective
    reconstruction §24 forbids, and acting on an invented one would be worse.
    """
    p = dict(DEFAULTS)
    p.update(policy or {})
    rc = dict(risk_context or {})
    now = now or time.time()
    sym = position.get("symbol")
    pid = position.get("positionId")
    key = str(pid or sym)

    def out(action, reason, **kw):
        if action != HOLD and _cooled(key, action, p["cooldown_s"], now):
            return Proposal(HOLD, COOLDOWN, symbol=sym, position_id=pid,
                            detail=f"{action} proposed within "
                                   f"{p['cooldown_s']}s", at=now)
        if action != HOLD:
            _remember(key, action, now)
        return Proposal(action, reason, symbol=sym, position_id=pid, at=now, **kw)

    # 1. Account-level conditions come first: they are true regardless of what
    #    this particular trade is doing.
    if rc.get("riskViolation"):
        return out(EXIT_PROPOSED, RISK_VIOLATION,
                   detail=str(rc.get("riskDetail") or "")[:160])
    if rc.get("portfolioReduce"):
        return out(REDUCE_PROPOSED, PORTFOLIO_RISK,
                   reduce_fraction=rc.get("reduceFraction") or 0.5)

    if th is None:
        return Proposal(HOLD, NO_ACTION_NEEDED, symbol=sym, position_id=pid,
                        detail="no thesis recorded for this position; it is "
                               "managed by its broker stop", at=now)

    price = observation.get("price")
    r_now = th.r_multiple(price)
    state, findings = _thesis.evaluate(th, observation)

    # 2. An unreadable market is not a reason to act. Closing a position
    #    because a feed hiccuped is worse than holding one a pass too long.
    if state == _thesis.UNREADABLE:
        return Proposal(HOLD, THESIS_UNREADABLE, symbol=sym, position_id=pid,
                        thesis_state=state, findings=findings, r_now=r_now,
                        at=now)

    # 3. The target, when one was recorded and price actually reached it. This
    #    is the ONLY path that may report TARGET_REACHED (§18).
    if th.initial_target is not None and price is not None:
        try:
            hit = (float(price) >= float(th.initial_target)
                   if th.direction == "BUY"
                   else float(price) <= float(th.initial_target))
        except (TypeError, ValueError):
            hit = False
        if hit:
            return out(EXIT_PROPOSED, TARGET_REACHED, thesis_state=state,
                       findings=findings, r_now=r_now)

    # 4. The reason is gone.
    if state == _thesis.INVALIDATED:
        broke = [f["kind"] for f in findings if f["state"] == "BROKEN"]
        reason = (STOP_LEVEL_BROKEN if _thesis.LEVEL in broke
                  else THESIS_INVALIDATED)
        return out(EXIT_PROPOSED, reason, thesis_state=state,
                   findings=findings, r_now=r_now,
                   detail="broken: " + ", ".join(broke))

    # 5. Weakening tightens; it does not exit. This is the single change that
    #    separates this from the policy it replaces — a partial loss of
    #    conviction protects the trade instead of ending it.
    if state == _thesis.WEAKENING and p["exit_on_weakening"]:
        return out(EXIT_PROPOSED, THESIS_WEAKENING, thesis_state=state,
                   findings=findings, r_now=r_now)

    # 6. Protect a move that is genuinely in profit. Nothing is touched below
    #    protect_from_r: there is no profit to protect and the stop belongs
    #    where the strategy put it.
    risk = th.initial_risk
    if (risk and r_now is not None and price is not None
            and r_now >= p["protect_from_r"]):
        trail = (float(price) - p["protect_trail_r"] * risk
                 if th.direction == "BUY"
                 else float(price) + p["protect_trail_r"] * risk)
        cur = position.get("stopLoss") or position.get("sl")
        tighter = p["exit_on_weakening"] or state != _thesis.WEAKENING
        if cur is not None and tighter:
            try:
                improved = ((trail - float(cur)) if th.direction == "BUY"
                            else (float(cur) - trail))
                if improved > risk * p["min_improvement_r"]:
                    return out(TIGHTEN_STOP_PROPOSED, PROTECT_PROFIT,
                               new_stop=round(trail, 6), thesis_state=state,
                               findings=findings, r_now=r_now,
                               detail=f"at {r_now:.2f}R, trailing "
                                      f"{p['protect_trail_r']}R behind price")
            except (TypeError, ValueError):
                pass

    return Proposal(HOLD, NO_ACTION_NEEDED, symbol=sym, position_id=pid,
                    thesis_state=state, findings=findings, r_now=r_now, at=now)


def describe(proposal):
    """The proposal as the position screen and the copilot read it."""
    head = (f"{proposal.symbol}: {proposal.action} — "
            f"{REASON_TEXT.get(proposal.reason, proposal.reason)}")
    lines = [head]
    if proposal.r_now is not None:
        lines.append(f"  currently {proposal.r_now:+.2f}R")
    for f in proposal.findings:
        mark = {"HOLDS": "+", "BROKEN": "x", "UNKNOWN": "?"}.get(f["state"], "?")
        lines.append(f"  [{mark}] {f['kind']}: expected {f['expected']}, "
                     f"now {f['actual']}")
    if proposal.detail:
        lines.append(f"  {proposal.detail}")
    return "\n".join(lines)
