"""The live order path, assembled — every gate, in the order §§2-9 require.

WHAT WAS MISSING, AND WHY IT MATTERED

The gates were all built and none of them were wired. `risk_gates`,
`live_ledger`, `audit`, `order_rate` and `emergency` each existed, each with
its own tests, and `bridge.submit` — the only function that can reach a broker
— called none of them. Every piece of the safety machinery was present and
nothing was holding the door.

This module is the door. It is the one path an order may take, and it refuses
at the first gate that says no.

THE ORDER OF THE GATES IS THE DESIGN

  1  §8   emergency stop            before anything else is even read
  2  §1   the live switch           off in this release, for everyone
  3  §2   entitlement               the plan pays for live
  4  §3   mode, from the BROKER     never from a stored flag
  5  §9   order rate                per client, shared, refuses when unsure
  6       build the request         stop, target, size
  7  §5   risk gates                thirteen checks, fail closed
  8  §6   ledger claim              TAKEN BEFORE THE BROKER CALL
  9  §7   audit the order           written before the order is sent
  10      the broker call
  11 §6   confirm filled / rejected / abandon UNKNOWN
  12 §7   audit the outcome

Numbers 8 and 11 are the pair that matters most. The claim is taken before the
call and released only on a CONFIRMED outcome; a submit that timed out may
have filled, so an unknown result keeps the claim and the key stays held. That
is the difference between one uncertain order and two certain ones.

EVERY REFUSAL IS AUDITED

§7 wants every refusal with its gate and its code, not only the ones that got
far enough to be interesting. So `_refuse` is the only way out of this
function that is not a placed order, and it writes the record before it
returns. A refusal nobody recorded is a refusal nobody can review.

WHAT THIS MODULE STILL CANNOT DO

`entitlement.live_execution_enabled()` returns False and this checks it
second, so every call refuses at step 2 today. That is not a placeholder — it
is the switch, and it stays off until the manual walk-through on a real demo
account, the legal rewrite and the security review in §12 are done. Nothing in
production imports this module; `tests/test_platform_live_invariants.py`
asserts that, and will keep asserting it in the shape §12 describes: reachable
only through these gates.
"""

import time
import uuid

from apex.platform import audit as _audit
from apex.platform import bridge as _bridge
from apex.platform import decision as _dec
from apex.platform import emergency as _emerg
from apex.platform import entitlement as _ent
from apex.platform import live_ledger as _ledger
from apex.platform import order_rate as _rate
from apex.platform import risk_gates as _gates

LIVE = "live"

# Every refusal this path can produce, named so a review can count them and a
# screen can branch on them without matching English.
HALTED = "HALTED"
LIVE_NOT_ENABLED = "LIVE_NOT_ENABLED"
NOT_ENTITLED = "NOT_ENTITLED"
MODE_NOT_LIVE = "MODE_NOT_LIVE"
MODE_UNVERIFIED = "MODE_UNVERIFIED"
RATE_LIMITED = "RATE_LIMITED"
RATE_UNKNOWN = "RATE_UNKNOWN"
BUILD_REFUSED = "BUILD_REFUSED"
RISK_REFUSED = "RISK_REFUSED"
ALREADY_CLAIMED = "ALREADY_CLAIMED"
LEDGER_UNAVAILABLE = "LEDGER_UNAVAILABLE"
AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
NOT_A_TRADE = "NOT_A_TRADE"


class LiveExecutionRefused(RuntimeError):
    """Raised only where a caller asked for something structurally wrong.

    An ordinary refusal is a RETURN VALUE, not an exception: refusing is the
    normal outcome of this function and a caller must handle it on the happy
    path rather than in an `except`.
    """

    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _audit_refusal(*, user_id, actor, account_id, gate, code, detail,
                   rule_doc=None, decision=None):
    """Record a refusal, and never let recording it become the failure.

    §7 is non-negotiable, and so is not turning an audit outage into a second
    fault on a path that has already refused. The refusal stands either way;
    what is lost is the record, and that is printed where an operator sees it.
    """
    try:
        _audit.record_refusal(
            user_id=user_id, actor=actor, account_id=account_id,
            gate=gate, code=code, reason=detail,
            rule_doc_id=(rule_doc or {}).get("ruleDocId"),
            rule_doc_version=(rule_doc or {}).get("version"),
            decision_id=getattr(decision, "decision_id", None))
    except Exception as e:                                   # noqa: BLE001
        print(f"[LiveExec] the refusal {code} for {user_id} could not be "
              f"audited ({type(e).__name__}) — the order was still refused")


def _refused(code, detail, *, gate, **audit_kw):
    _audit_refusal(gate=gate, code=code, detail=detail, **audit_kw)
    return {"placed": False, "code": code, "gate": gate, "detail": detail,
            "order": None, "outcome": None}


def place(rule_doc, decision, snapshot, *, user_id, account_id,
          balance_reader, mode_reader, actor="system:loop", state=None,
          timeframe=None, strategy=None, broker=None, now=None,
          correlation_id=None):
    """Take one rule decision all the way to a broker, or refuse.

    `mode_reader` is a callable returning the account mode as the BROKER
    reports it, read now. There is no parameter that accepts the mode as a
    value: §3 requires the fact to come from the broker, and a signature that
    allowed a caller to assert it would be the place somebody eventually did.

    `balance_reader` is likewise a callable — §5 requires a live, uncached
    balance, so there is no number to pass instead.

    Returns a dict. `placed` is True only when a broker confirmed an order.
    """
    now = time.time() if now is None else float(now)
    correlation_id = correlation_id or uuid.uuid4().hex
    aud = {"user_id": user_id, "actor": actor, "account_id": account_id,
           "rule_doc": rule_doc, "decision": decision}

    # ── 1. §8 the emergency stop, before anything is read ──────────────────
    try:
        _emerg.check(user_id=user_id,
                     symbol=getattr(decision, "symbol", None),
                     mode=LIVE)
    except _emerg.Halted as e:
        return _refused(HALTED, str(e), gate="emergency_stop", **aud)

    # ── 2. §1 the switch. Off in this release, for everyone. ───────────────
    if not _ent.live_execution_enabled():
        return _refused(
            LIVE_NOT_ENABLED,
            "live execution is not enabled in this release — see §12 of "
            "docs/LIVE_EXECUTION_SPECIFICATION.md for what closes it",
            gate="release_switch", **aud)

    # ── 3. §2 entitlement ──────────────────────────────────────────────────
    if _ent.entitlement_of(user_id) != _ent.PAID_LIVE:
        return _refused(
            NOT_ENTITLED,
            "this account does not hold the plan that covers real-money "
            "trading", gate="entitlement", **aud)

    # ── 4. §3 the mode, from the broker, read now ──────────────────────────
    try:
        mode = mode_reader()
    except Exception as e:                                   # noqa: BLE001
        return _refused(
            MODE_UNVERIFIED,
            f"the account mode could not be verified with the broker "
            f"({type(e).__name__}) — an unverified mode is not a live mode",
            gate="mode_verification", **aud)
    if str(mode) != LIVE:
        return _refused(
            MODE_NOT_LIVE,
            f"the broker reports this account as {mode!r}, so the live path "
            f"does not apply to it", gate="mode_verification", **aud)

    # ── 5. the decision has to be a trade at all ───────────────────────────
    verdict = getattr(decision, "verdict", None)
    if verdict not in _dec.ENTRY_VERDICTS:
        return _refused(
            NOT_A_TRADE,
            f"the rule decided {verdict!r}, which is not an entry",
            gate="decision", **aud)

    # ── 6. §9 the per-client order rate ────────────────────────────────────
    try:
        _rate.authorize(user_id, now=now)
    except _rate.OrderRateExceeded as e:
        return _refused(RATE_LIMITED, str(e), gate="order_rate", **aud)
    except _rate.OrderRateUnavailable as e:
        return _refused(RATE_UNKNOWN, str(e), gate="order_rate", **aud)

    # ── 7. build the request: stop, target, size ───────────────────────────
    try:
        req = _bridge.build(rule_doc, decision, snapshot, user_id=user_id,
                            account_id=account_id, mode=mode,
                            balance=balance_reader(),
                            decision_id=getattr(decision, "decision_id", None))
    except _bridge.BUILD_REFUSALS as e:
        return _refused(BUILD_REFUSED,
                        f"{e.code}: {getattr(e, 'detail', str(e))}",
                        gate="build", **aud)
    except Exception as e:                                   # noqa: BLE001
        return _refused(BUILD_REFUSED,
                        f"the order could not be built ({type(e).__name__})",
                        gate="build", **aud)

    # ── 8. §5 the thirteen risk gates ──────────────────────────────────────
    # `req.price` is None for a MARKET order — there is no limit price to
    # state — and §5's stop gate measures the stop against the price the
    # order will fill near. That is the snapshot's price, the same reading
    # every other gate on this decision used. Passing None instead refuses
    # every market order with NO_ENTRY_PRICE, which is how this was found.
    intent = _gates.OrderIntent(symbol=req.symbol, side=req.side,
                                entry_price=(req.price
                                             if req.price is not None
                                             else getattr(snapshot, "price",
                                                          None)),
                                stop_price=req.stop_loss,
                                volume=req.volume)
    v = _gates.authorize(rule_doc, intent, mode=mode,
                         balance_reader=balance_reader, state=state)
    if not v.allowed:
        return _refused(RISK_REFUSED, f"{v.code}: {v.detail}",
                        gate=f"risk:{v.gate}", **aud)

    # ── 9. §6 the claim, TAKEN BEFORE THE BROKER CALL ──────────────────────
    try:
        claim = _ledger.claim(decision, user_id=user_id,
                              account_id=account_id,
                              timeframe=timeframe, strategy=strategy)
    except _ledger.AlreadyClaimed as e:
        return _refused(
            ALREADY_CLAIMED,
            f"{e} — this decision has already been acted on, and acting on "
            f"it again is how one signal becomes two positions",
            gate="ledger", **aud)
    except Exception as e:                                   # noqa: BLE001
        return _refused(
            LEDGER_UNAVAILABLE,
            f"the duplicate-order ledger could not answer "
            f"({type(e).__name__}) — an order placed without it may be a "
            f"second copy of one already working", gate="ledger", **aud)

    # ── 10. §7 the order is audited BEFORE it is sent ──────────────────────
    # If this cannot be written the order does not go. An order nobody can
    # attribute afterwards is the one case where refusing is cheaper than
    # proceeding, and the claim is abandoned as unknown-free: nothing was
    # sent, so releasing it is correct and the next attempt may proceed.
    try:
        _audit.record_live_order(
            user_id=user_id, actor=actor, account_id=account_id,
            rule_doc_id=(rule_doc or {}).get("ruleDocId"),
            rule_doc_version=(rule_doc or {}).get("version"),
            decision_id=getattr(decision, "decision_id", None),
            request=req.as_dict(), broker_reply={"status": "about_to_send"},
            position_id=None)
    except Exception as e:                                   # noqa: BLE001
        try:
            _ledger.confirm_rejected(
                claim, broker_reply={"sent": False},
                code="AUDIT_UNAVAILABLE")
        except Exception:                                    # noqa: BLE001
            pass
        return _refused(
            AUDIT_UNAVAILABLE,
            f"the order could not be recorded in the audit trail "
            f"({type(e).__name__}) and was not sent", gate="audit", **aud)

    # ── 11. the broker call ────────────────────────────────────────────────
    reply, failure = None, None
    try:
        reply = (broker or _default_broker())(req)
    except Exception as e:                                   # noqa: BLE001
        failure = e

    # ── 12. §6 the outcome, and what it does to the claim ──────────────────
    if failure is not None:
        # UNKNOWN. The call did not come back, so whether an order exists is
        # not established — and the claim is NOT released. See §6.
        _ledger.abandon_unknown(
            claim, detail=f"the broker call raised {type(failure).__name__} "
                          f"after the request was sent; whether an order "
                          f"exists is unknown")
        _audit_outcome(aud, req, {"error": type(failure).__name__},
                       position_id=None)
        return {"placed": False, "code": "BROKER_UNKNOWN",
                "gate": "broker", "order": req.as_dict(), "outcome": "unknown",
                "detail": f"the broker call failed with "
                          f"{type(failure).__name__}; the claim is held"}

    ok = bool((reply or {}).get("ok", True)) and "error" not in (reply or {})
    position_id = (reply or {}).get("positionId")
    if ok:
        _ledger.confirm_filled(claim, broker_reply=reply,
                               position_id=position_id)
    else:
        _ledger.confirm_rejected(
            claim, broker_reply=reply,
            code=str((reply or {}).get("code") or "BROKER_REJECTED"))
    _audit_outcome(aud, req, reply, position_id=position_id)

    return {"placed": ok, "code": None if ok else "BROKER_REJECTED",
            "gate": None if ok else "broker",
            "order": req.as_dict(), "outcome": reply,
            "positionId": position_id,
            "detail": "" if ok else str((reply or {}).get("error") or
                                        "the broker refused the order")}


def _audit_outcome(aud, req, reply, *, position_id):
    try:
        _audit.record_live_order(
            user_id=aud["user_id"], actor=aud["actor"],
            account_id=aud["account_id"],
            rule_doc_id=(aud["rule_doc"] or {}).get("ruleDocId"),
            rule_doc_version=(aud["rule_doc"] or {}).get("version"),
            decision_id=getattr(aud["decision"], "decision_id", None),
            request=req.as_dict(), broker_reply=reply,
            position_id=position_id)
    except Exception as e:                                   # noqa: BLE001
        print(f"[LiveExec] the outcome for {aud['user_id']} could not be "
              f"audited ({type(e).__name__}) — the order itself is recorded")


def _default_broker():
    """The real executor, imported lazily and never at module import.

    Keeping it out of the import graph is what lets this module be loaded and
    tested without the engine, and what keeps `test_platform_live_invariants`
    able to prove that nothing in production reaches a broker through here.
    """
    from apex import user_loop

    def _send(req):
        return user_loop.force_trade(
            req.user_id, req.side, symbol=req.symbol,
            sl_override=req.stop_loss, tp_override=req.take_profit,
            origin="rule")

    return _send
