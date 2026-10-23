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
from apex import account_mode, portfolio
from apex import config as cfg

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


def _platform_mode(user_id):
    """"demo" / "live" / "unknown" for a platform account, None otherwise.

    THE HOLE THIS CLOSES, AND IT MADE EVERY LIVE GATE DECORATIVE

    `_live` reads the user record's `paper` flag. Nothing in apex/platform
    writes that flag — only `telegram._handle_paper` does — so for every
    platform client `_live` returned False, whatever account they had
    selected at the broker. `live` being False is what skips the broker
    environment check, the ownership live lease, the ledger's fail-closed
    claim and the whole of step 5b: the release switch, the paid plan, the
    broker-confirmed mode and the audit trail.

    So the platform's live safety was unreachable for platform accounts. It
    reads as working because no platform client can select a live account
    yet — `ctrader_link.select_account` refuses while the release switch is
    closed — which means today's blast radius is nil and the day the switch
    opens it would have been total. Same shape as every other bug this week:
    a mechanism that cannot fire looks exactly like one that passes.

    Imports ctrader_link ONLY, which imports clean. See the note in step 5b:
    importing the live path to ask this question takes the legacy engine down
    on a deployment with no shared backend.

    Raises on a store it could not read, so the caller fails closed. "We
    cannot tell" is not "no real money here".
    """
    from apex.platform import ctrader_link as _ctl
    return _ctl.selected_mode(user_id)


def live_entitlement(user_id, user=None):
    """May this account open NEW live positions? allowed / denied / unknown.

    Deliberately NOT the same question as `access.allowed_state`, which governs
    whether a chat may use the bot at all. That one treats UNKNOWN as
    allow-and-log, and it is right to: a store hiccup must not black out a
    paying client's interface. This one governs money, so UNKNOWN is a refusal.

    A stored licence key still counts as entitlement. The access index is wiped
    on every redeploy when it falls back to local JSON, and a paying client
    must not lose live trading to that.

    UNLESS the licence is in GRACE. `telegram._revalidate_license` sets
    `license_grace_since` when the verifier cannot answer: the client keeps
    their interface and their open positions keep being managed, but nobody
    can currently confirm they are still entitled — so no NEW live risk is
    taken on their behalf. The stored key is exactly what must NOT override
    that, because the key is what could not be verified.
    """
    user_id = str(user_id)
    try:
        u = user if user is not None else user_store.load(user_id)
    except Exception as e:
        return "unknown", f"user store unreachable: {str(e)[:80]}"
    if (u or {}).get("license_grace_since"):
        return "unknown", "licence unverifiable — in grace, no new live orders"
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

    # 0. WHOSE ACCOUNT IS THIS, and is real money at stake? Asked once, here,
    #    because every check below branches on the answer and two of them
    #    answer it differently if left to themselves.
    #
    #    `_live` above is the LEGACY answer: the stored paper flag, which only
    #    the Telegram path writes. For a platform client it is always False.
    #    See _platform_mode for what that cost.
    #
    #    THE DISTINCTION THAT MAKES THIS SAFE TO ASK AT ALL
    #
    #    `_live` cannot tell "paper is stored as True" from "there is no
    #    paper key", because `.get("paper", True)` collapses them. They are
    #    completely different statements:
    #
    #      * stored True  — the Telegram path positively marked this order as
    #        simulated. There is no real money, whatever any other system
    #        thinks, and nothing needs asking.
    #      * key absent   — nobody has said anything. Every platform record
    #        is in this state, including one trading a live account.
    #
    #    Separating them is what keeps `tests/test_final_hardening.py`
    #    honest: it installs a DOWN store and requires that a demo order
    #    still runs. That invariant is right and deliberate — refusing to
    #    simulate because a store blipped is a cost with no matching danger,
    #    the same reasoning step 2 gives for not holding DEMO to broker
    #    confirmation. A blanket fail-closed here broke it.
    #
    #    It also keeps the legacy hot path free: an explicitly-paper order
    #    pays for no extra store read.
    is_platform = False
    if u.get("paper") is not True:
        try:
            _pmode = _platform_mode(user_id)
        except Exception as e:
            # Fails closed, and ONLY for an account nobody has declared
            # simulated. A store that cannot be read cannot rule out a live
            # platform account, and "we could not tell" must never be spent
            # as "no real money here".
            print(f"[Gates] could not classify {user_id}: {e}")
            return Decision(False, "LIVE_CLASSIFY_FAILED", str(e)[:120]), None
        is_platform = _pmode is not None
        if is_platform and _pmode != "demo":
            # live, or a mode the broker would not confirm. Both are real
            # money until proven otherwise, and step 5b §3 is what proves it.
            live = True

    # 1. Entitlement. UNKNOWN denies for live money, allows for a simulation.
    ent, why = live_entitlement(user_id, u)
    if ent == "denied":
        return Decision(False, "NOT_ENTITLED", why), None
    if ent == "unknown" and live:
        return Decision(False, "ENTITLEMENT_UNKNOWN", why), None

    # 2. Broker environment. `live` above comes from the STORED paper flag,
    #    which says what we last recorded — not what the account is now. When
    #    the broker cannot be reached, account_mode resolves to UNVERIFIED, and
    #    an account whose environment nobody can currently confirm must not
    #    take on NEW live risk: the failure mode is opening a real-money
    #    position while believing it is a demo.
    #
    #    Deliberately only on the OPEN path. authorize_close does not carry
    #    this check, because an existing position must keep being managed
    #    exactly when verification is degraded — refusing to close is the one
    #    outcome worse than refusing to open.
    #
    #    LEGACY ACCOUNTS ONLY. `account_mode.resolve` reads broker fields off
    #    the user record, and a platform client's record has none of them, so
    #    for them it can only ever answer UNVERIFIED. The platform asks the
    #    same question properly in step 5b §3 — the mode as the BROKER
    #    reports it — and routing a platform order through this check instead
    #    would deny it with a reason that is about the legacy record rather
    #    than about the account.
    if live and not is_platform:
        try:
            mode, _src = account_mode.resolve(u)
        except Exception as e:
            return Decision(False, "ACCOUNT_MODE_UNKNOWN",
                            f"could not resolve the broker environment: "
                            f"{str(e)[:80]}"), None
        if mode not in (account_mode.LIVE, account_mode.DEMO):
            return Decision(False, "ACCOUNT_MODE_UNVERIFIED",
                            "the broker cannot confirm this account's "
                            "environment; no new live orders until it can"), None
        # A LIVE reading that came from our own stored flag is not confirmation.
        # `_src == "broker"` means the account answered just now; "stored-env"
        # means we are repeating what we last wrote down, and the whole reason
        # that distinction exists is that it can be stale. Real money does not
        # get opened on a stale reading.
        #
        # DEMO is deliberately NOT held to this. There is no real money at
        # risk, and refusing to trade a demo account because a status lookup
        # timed out would stop the product working for the case it is mostly
        # used in — a cost with no matching danger.
        if mode == account_mode.LIVE and _src != "broker":
            return Decision(False, "LIVE_MODE_UNCONFIRMED",
                            f"live account, but the environment came from "
                            f"{_src} rather than the broker; no new real-money "
                            "orders until the broker confirms"), None

    # 3. Risk guard, as the LOOP published it. Recomputing here would advance
    #    the peak-balance and daily-reset state — a check must not move the
    #    thing it is checking.
    d = dash if dash is not None else _dash(user_id)
    guard = (d or {}).get("riskGuard")
    if isinstance(guard, dict) and guard.get("halted"):
        reasons = "; ".join(str(r) for r in (guard.get("reasons") or [])) or "risk limit"
        return Decision(False, "RISK_HALTED", reasons), None

    # 4. Portfolio. These checks existed, were correct, and lived inside the
    #    autonomous loop — so an autonomous entry was checked against exposure
    #    and correlation while a manual /buy was not. §14 requires every path
    #    through one engine, so they moved to apex/portfolio.py and are called
    #    from here. This is a move, not a new policy: the same USD-side cap
    #    the loop applied is the default.
    #
    #    Deliberately AFTER the risk-guard check and BEFORE the ledger claim.
    #    A denial here must not burn an idempotency claim, and it must not
    #    outrank a halted account — "trading is paused" is the more useful
    #    thing to tell a client than "you already hold two dollar shorts".
    try:
        _lim = {
            "max_positions": (u.get("maxpos")
                              if u.get("maxpos") is not None
                              else getattr(cfg, "MAX_POSITIONS", None)),
            "max_same_usd_side": int(
                u.get("max_same_usd_side")
                or getattr(cfg, "MAX_SAME_USD_SIDE", 0)
                or portfolio.DEFAULT_MAX_SAME_USD_SIDE),
            "max_data_age_s": (u.get("max_data_age_s")
                               or getattr(cfg, "MAX_DATA_AGE_S", 0) or None),
        }
        _exp = portfolio.state(d, max_positions=_lim["max_positions"])
        _age = None
        _last = (d or {}).get("lastTickTs")
        if _last:
            _age = max(0.0, time.time() - float(_last))
        _ok, _code, _why = portfolio.check(symbol, side, _exp, limits=_lim,
                                           data_age_s=_age)
        if not _ok:
            return Decision(False, _code, portfolio.deny_text(_code)
                            + (f" ({_why})" if _why else "")), None
    except Exception as e:
        # A portfolio-check bug must not become a way to open a position. This
        # is a risk gate: it fails closed, like every other branch here.
        print(f"[Gates] portfolio check failed for {user_id}: {e}")
        return Decision(False, "PORTFOLIO_CHECK_FAILED", str(e)[:120]), None

    # 5. Ownership. Another container managing the same account is worse than
    #    a missed entry, and an unverifiable lease is not ownership.
    own_ok, own_why = ownership.may_trade(user_id, live=live)
    if not own_ok:
        return Decision(False, "NOT_OWNER", own_why), None

    # 5b. The PLATFORM's live gates — §1 the release switch, §2 the plan that
    #     pays for live, §3 the mode as the broker reports it, §9 the order
    #     rate — plus §7's record of whichever way this went.
    #
    #     Here, and not somewhere in the platform, because THIS function is
    #     the single point every order origin in this codebase converges on:
    #     the autonomous loop and force_trade both call it and nothing else
    #     reaches a broker. A guard anywhere else would be a guard with a way
    #     around it.
    #
    #     Deliberately AFTER ownership and BEFORE the ledger claim, for the
    #     same two reasons the portfolio check sits where it does: a refusal
    #     must not burn an idempotency claim, and the cheap local checks
    #     should have spoken before anything asks the broker a question.
    #
    #     Only for live, and only for platform accounts. `guard_engine_order`
    #     returns None when the account has no platform connection, which is
    #     every Telegram-bot user — they traded through this gate for a long
    #     time before the platform existed and their path is unchanged.
    #     WHETHER THIS IS A PLATFORM ACCOUNT WAS ASKED IN STEP 0, AND
    #     SEPARATELY FROM IMPORTING ANY OF THIS.
    #
    #     Not a tidiness choice. `apex/platform/audit.py` refuses AT IMPORT on
    #     a process with no shared backend — correctly, §7 permits no live
    #     order without a trail — and `live_execution` imports it. So merely
    #     importing the live path to find out "this is not a platform
    #     account" raised SharedBackendRequired and denied the order.
    #
    #     Every Telegram-bot live order went through that branch. The legacy
    #     engine's own safety tests caught it, with the words
    #     "this would stop legitimate live trading", which is exactly what it
    #     did. Step 0 asks ctrader_link, which imports clean, so the cheap
    #     question is answered before the expensive import happens at all.
    if live and is_platform:
        try:
            from apex.platform import live_execution as _live_exec
            _pv = _live_exec.guard_engine_order(
                user_id, symbol=symbol, side=side, units=units,
                origin=origin)
        except Exception as e:
            # Fails closed, like every other branch in this function — but
            # only for accounts the platform actually owns. A missing audit
            # backend denying a platform live order is §7 working.
            print(f"[Gates] platform live guard failed for {user_id}: {e}")
            return Decision(False, "LIVE_GUARD_FAILED", str(e)[:120]), None
        if _pv is not None and not _pv.get("allowed"):
            return Decision(False, _pv.get("code") or "LIVE_REFUSED",
                            f"{_pv.get('gate')}: {_pv.get('detail')}"), None

    # 6. Idempotency, last — so the claim is only taken for a request that has
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


def authorize_platform_demo_close(user_id, *, position_id, origin="platform",
                                  user=None, account=None):
    """Platform adapter for the same close gate used by every other origin.

    The platform checks the broker account is DEMO before calling this
    adapter. Keeping the adapter here makes that policy explicit while the
    platform package remains outside the legacy execution import graph.
    """
    # With an account, the claim is per ACCOUNT and per position (as an integer).
    # Keyed on the position alone, a close sent under the wrong account answered
    # "already closed" and used up the claim the right account then needed.
    intent = (f"{account}:{int(position_id)}"
              if account is not None and str(position_id).strip().isdigit()
              else position_id)
    return authorize_close(user_id, position_id=intent, origin=origin,
                           user=user)


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
