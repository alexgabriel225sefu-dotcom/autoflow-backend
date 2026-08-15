"""One definition of "safe financial action", for every origin.

Before this module there were two definitions. The automatic strategy path
checked entitlement, risk guard, ownership and idempotency; the manual paths —
/buy, the AI assistant, the control plane — reached the broker with fewer
checks, and `force_close` reached it with none of them. An order is an order
whoever asked for it, so the checks belong here rather than at each caller.

WHAT THIS IS NOT. It does not decide whether a trade is a good idea. Strategy
selection, sizing and signal quality stay where they are; forcing a manual
trade to invent a signal would be worse than the duplication it replaced. This
is the financial safety layer underneath that decision:

    AUTOMATIC SIGNAL ┐
    MANUAL TELEGRAM  ├─→ authorize_order() ─→ broker
    AI REQUEST       │
    MCP CONTROLLED   ┘

THE UNKNOWN RULE, stated once because it is the whole design:

    A fact we could not establish is not a fact in our favour.

Entitlement that cannot be read, ownership that cannot be verified, a
coordination backend that cannot be reached — each of those is UNKNOWN, and for
a LIVE account every UNKNOWN denies the order. Demo keeps the permissive
reading, because halting a simulation on a Redis blip protects nobody and
costs the client the product they are evaluating.

Closing is treated differently from opening on purpose. A close reduces
exposure, so blocking one on an unverifiable check can be the more dangerous
choice — but it is still a financial action with a duplicate-execution problem,
so it keeps idempotency and audit while the ownership rule is explicit rather
than accidental.
"""
import time

from apex import access, ledger, ownership, user_store

# Verdicts. Strings rather than an enum so they survive the JSON round trip
# through the control plane unchanged.
ALLOW = "ALLOW"
DENY = "DENY"


class Decision:
    """(allowed, reason, detail) with a stable shape for auditing."""

    __slots__ = ("allowed", "reason", "detail")

    def __init__(self, allowed, reason, detail=""):
        self.allowed, self.reason, self.detail = bool(allowed), reason, detail

    def __bool__(self):
        return self.allowed

    def as_dict(self):
        return {"allowed": self.allowed, "reason": self.reason,
                "detail": self.detail}

    def __repr__(self):
        return f"<Decision {'ALLOW' if self.allowed else 'DENY'} {self.reason}>"


def _live(user):
    return not (user or {}).get("paper", True)


def live_entitlement(user_id, user=None):
    """May this account open NEW live positions? allowed / denied / unknown.

    Deliberately NOT the same question as `access.allowed_state`, which governs
    whether a chat may use the bot at all. That one treats UNKNOWN as
    allow-and-log, and it is right to: a store hiccup must not black out a
    paying client's interface. This one governs money, so UNKNOWN is a refusal.

    A stored licence key still counts as entitlement. The access index is wiped
    on every redeploy when it falls back to local JSON, and a paying client
    must not lose live trading to that.
    """
    user_id = str(user_id)
    try:
        u = user if user is not None else user_store.load(user_id)
    except Exception as e:
        return "unknown", f"user store unreachable: {str(e)[:80]}"
    if (u or {}).get("license_key"):
        return "allowed", "licence on file"
    try:
        state = access.allowed_state(user_id)
    except Exception as e:
        return "unknown", f"access store unreachable: {str(e)[:80]}"
    if state == "allowed":
        return "allowed", "granted"
    if state == "denied":
        return "denied", "no grant and no licence"
    return "unknown", "access store degraded"


def authorize_order(user_id, *, symbol, side, units, sl=None, tp=None,
                    origin="unknown", user=None, dash=None):
    """The one gate every new position passes, whatever asked for it.

    Order matters: the cheapest and most decisive checks first, so a denied
    request never reaches the broker and never burns an idempotency claim.
    """
    user_id = str(user_id)
    try:
        u = user if user is not None else user_store.load(user_id)
    except Exception as e:
        return Decision(False, "STORE_UNREACHABLE", str(e)[:120]), None
    live = _live(u)

    # 1. Entitlement. UNKNOWN denies for live money, allows for a simulation.
    ent, why = live_entitlement(user_id, u)
    if ent == "denied":
        return Decision(False, "NOT_ENTITLED", why), None
    if ent == "unknown" and live:
        return Decision(False, "ENTITLEMENT_UNKNOWN", why), None

    # 2. Risk guard, as the LOOP published it. Recomputing here would advance
    #    the peak-balance and daily-reset state — a check must not move the
    #    thing it is checking.
    d = dash if dash is not None else _dash(user_id)
    guard = (d or {}).get("riskGuard")
    if isinstance(guard, dict) and guard.get("halted"):
        reasons = "; ".join(str(r) for r in (guard.get("reasons") or [])) or "risk limit"
        return Decision(False, "RISK_HALTED", reasons), None

    # 3. Ownership. Another container managing the same account is worse than
    #    a missed entry, and an unverifiable lease is not ownership.
    own_ok, own_why = ownership.may_trade(user_id, live=live)
    if not own_ok:
        return Decision(False, "NOT_OWNER", own_why), None

    # 4. Idempotency, last — so the claim is only taken for a request that has
    #    already cleared everything else.
    ok, why, rid = ledger.claim(user_id, symbol, side, units, sl, tp,
                                fail_closed=live)
    if not ok:
        return Decision(False, why, f"origin={origin}"), None
    return Decision(True, "AUTHORIZED", f"origin={origin} entitlement={ent}"), rid


def authorize_close(user_id, *, position_id=None, symbol=None, origin="unknown",
                    user=None, emergency=False):
    """The one gate every close passes. Returns (Decision, close_intent_id).

    A close is not an order and is not gated like one:

      * no entitlement check. Refusing to let a client out of a position
        because their licence lookup timed out is the wrong failure — the
        position is already open and already risking their money.
      * no risk-guard check, for the same reason. The guard exists to stop new
        exposure; a close reduces it.
      * ownership IS checked, because two containers closing the same position
        is a real double-execution. `emergency=True` documents an intentional
        override for the operator's emergency path — it does not remove the
        check, it records that a human overrode it.
      * idempotency ALWAYS. A close request that times out may have succeeded;
        retrying it can close a position that was reopened in between.
    """
    user_id = str(user_id)
    try:
        u = user if user is not None else user_store.load(user_id)
    except Exception as e:
        return Decision(False, "STORE_UNREACHABLE", str(e)[:120]), None
    live = _live(u)

    if not emergency:
        own_ok, own_why = ownership.may_trade(user_id, live=live)
        if not own_ok:
            return Decision(False, "NOT_OWNER", own_why), None

    # Keyed on the position, not on a generated id, so two processes asking to
    # close the same position agree on the key without talking to each other.
    intent = position_id or symbol or "flat"
    #
    # TWO POLICIES, because one rule cannot serve both cases.
    #
    # NORMAL CLOSE — fails CLOSED when shared idempotency is unavailable. The
    # in-process ledger cannot see another container, so during a backend
    # outage two instances would each believe they were the first to close the
    # same position. The second close lands on whatever was reopened after the
    # first, which is a new position closed without anyone asking.
    #
    # EMERGENCY OPERATOR CLOSE — may proceed, because the situation it exists
    # for is "get me out of this position now" and a coordination outage is
    # not a reason to refuse that. It is never silent: ownership was already
    # waived above, the decision records `emergency`, and gates.audit writes it
    # whether it succeeded or not. The residual risk is a duplicate close
    # request, which the broker answers with "no such position" — bounded, and
    # smaller than being unable to exit.
    ok, why, rid = ledger.claim(user_id, f"CLOSE:{intent}", "CLOSE", 0,
                                None, None, fail_closed=not emergency)
    if not ok:
        if why == "COORDINATION_UNAVAILABLE":
            return Decision(False, "CLOSE_COORDINATION_UNAVAILABLE",
                            "shared idempotency is unreachable; a normal close "
                            "cannot be proven unique. Use the emergency path if "
                            "exiting now matters more than the duplicate risk."), rid
        prior = ledger.result_for(rid)
        return Decision(False, "DUPLICATE_CLOSE",
                        f"already requested; prior result: {prior!r}"), rid
    return Decision(True, "AUTHORIZED",
                    f"origin={origin}{' emergency' if emergency else ''}"), rid


def _dash(user_id):
    try:
        from apex import user_loop
        return user_loop.get_dash(user_id) or {}
    except Exception:
        return {}


def audit(user_id, action, decision, *, origin, rid=None, extra=None):
    """Record a financial decision — allowed or refused.

    Refusals are the half people forget, and they are the half that matters
    when working out whether a control fired.
    """
    try:
        from apex import control
        control.event(
            "order" if decision.allowed else "warn",
            f"{action} {decision.reason} origin={origin} "
            f"{decision.detail}"[:380],
            user_id=str(user_id),
            extra={"rid": rid, "allowed": decision.allowed, **(extra or {})},
        )
    except Exception as e:
        print(f"[Gates] audit failed for {user_id}/{action}: {e}")
