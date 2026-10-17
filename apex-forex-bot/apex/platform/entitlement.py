"""What this client may actually do, decided on the server.

THE QUESTION THIS ANSWERS

Three facts have to be combined before automation can start, and each one has
been a separate place to get it wrong:

  account mode   is the connected broker account demo or live? This comes from
                 cTrader's own account list, recorded at link time. It is
                 never read from a request body, because a value the browser
                 supplies is a value the browser can change.
  entitlement    free_demo or paid_live. Demo access is free; a paid plan is
                 intended to unlock live-account automation later.
  capability     what this DEPLOYMENT is permitted to execute at all.

The third is the one that is easy to lose, and it changed meaning once. It
used to mean "live execution is not implemented" — there was nothing behind
the flag, so no entitlement could unlock it. The path exists now
(`live_execution`, every gate in §1-§9, wired into `gates.authorize_order`
so no order site can go round it), and the third fact became what it should
always have been: a RELEASE DECISION, held in one environment variable,
closed unless somebody opened it deliberately.

Which means the two other facts now carry real weight. `paid_live` + a live
account + the switch open is the only combination that trades real money;
`free_demo` + a live account is refused on the plan, and every combination
is refused while the switch is closed. The tests assert all of them, not
only the ones that happen to differ.

WHY DEMO IS FREE HERE AND NOT IN licence.py

`licence.py` still means what it always meant: a deliberate, recorded
entitlement, granted by the payment path or by hand. What changed is that
holding one is no longer the condition for running a rule on a DEMO account —
that is free, by decision. A licence now means `paid_live`, and a REVOKED one
still blocks everything, because revocation is how support stops a client and
it would be worthless if free demo access routed around it.

An absent licence is `free_demo`. A revoked one is not.
"""

import os

from apex.platform import ctrader_link as _link
from apex.platform import licence as _lic
from apex.platform import plans as _plans

# §1, the release switch. One variable, one value that opens it, and that
# value is a sentence nobody sets by accident or inherits from a copied
# config. See live_execution_enabled().
LIVE_SWITCH_ENV = "A4T_LIVE_EXECUTION"
LIVE_SWITCH_ON = "enabled-i-accept-real-money-risk"

FREE_DEMO = "free_demo"
PAID_LIVE = "paid_live"
ENTITLEMENTS = (FREE_DEMO, PAID_LIVE)

DEMO = _link.DEMO
LIVE = _link.LIVE
UNKNOWN = _link.UNKNOWN
MODES = _link.MODES

# Badges the UI renders. Named here so the server decides what a client is
# told, rather than the browser inferring it from a combination of fields.
BADGE_DEMO = "DEMO"
# Real money, and the screen says so in its own word rather than by the
# ABSENCE of "LIVE BLOCKED". A client must never have to infer that they are
# trading real money from a badge that stopped appearing.
BADGE_LIVE = "LIVE"
BADGE_LIVE_BLOCKED = "LIVE BLOCKED"
BADGE_NOT_CONNECTED = "NOT CONNECTED"
BADGE_REAUTH = "REAUTH REQUIRED"

# The one sentence this release makes about paid access. Kept here so the API,
# the UI and the tests cannot drift into three different promises. The trial
# length comes from plans.py; the PRICE is deliberately absent — it is served
# from billing/offer, where one figure is watched by offer_drift(), and a
# number baked into this sentence would go stale the day it changes.
PLAN_NOTICE = (
    f"Demo accounts are free for a {_plans.TRIAL_DAYS}-day trial. Real-money "
    f"account access is a paid plan, and live execution is not enabled in "
    f"this release.")

# What a client is told when the free trial has run out. Names the two things
# they can do, because a refusal that does not is a dead end.
TRIAL_EXPIRED_MESSAGE = (
    f"the {_plans.TRIAL_DAYS}-day free demo trial for this account has "
    f"ended — reconnect once a plan is active, or contact support")
NO_LICENCE_MESSAGE = (
    "this account has no demo trial on file — contact support to start one")

LIVE_REFUSAL = "live trading is not available in this release"
# Different from the one above, and the difference is the point: this client
# is on a deployment where live trading IS open, and the thing in the way is
# their own plan. It names the next step rather than leaving a dead end.
LIVE_NOT_ENTITLED_MESSAGE = (
    "this account is on the free demo trial, which covers demo accounts only "
    "— real-money automation needs the paid plan")


class NotEntitled(PermissionError):
    """Refused, with a code the UI branches on instead of matching English."""

    def __init__(self, code, message, *, state=None):
        self.code = code
        self.state = state
        super().__init__(message)


def live_execution_enabled():
    """Whether THIS DEPLOYMENT may place real-money orders. Closed by default.

    This is §1, the release switch, and it is the first thing every live path
    asks after the emergency stop. It is read in `live_execution.authorize`
    and again in `capability()`, so a deployment that has not opened it
    refuses live automation at the screen AND at the order gate.

    WHY IT READS AN ENVIRONMENT VARIABLE NOW, HAVING DELIBERATELY NOT BEFORE

    It used to `return False` with no input at all, and the invariants test
    asserted that it read no name — no getenv, no flag. That was right for
    exactly as long as there was no execution path: a config string that
    enabled a feature which did not exist would have been the only thing
    standing between a deployment and an undefined code path.

    The path exists now and every gate in front of it is wired and tested, so
    the honest shape is the ordinary one — a release decision an operator
    makes per deployment, not a code change. What the invariants test asserts
    instead is the part that still matters: it is CLOSED unless the variable
    says exactly one thing, and nothing else in the codebase reads that name.

    ONLY ONE VALUE OPENS IT. Not "1", not "true", not "yes" — a variable left
    over from a copied config, or set to "false" by somebody who meant it,
    must never open real-money trading by accident. The value is a sentence
    that cannot be arrived at except on purpose.
    """
    return (os.getenv(LIVE_SWITCH_ENV) or "").strip() == LIVE_SWITCH_ON


def account_mode(user_id):
    """`demo`, `live`, or `unknown`. From the broker, never from the browser.

    `unknown` covers every case where there is nothing to judge: no account
    connected, none selected, or a record that predates the mode being
    stored. It is deliberately not folded into `demo` — "I do not know what
    this account is" and "this account is a practice account" must never be
    the same answer.
    """
    try:
        status = _link.public_status(user_id)
    except Exception:                                   # noqa: BLE001
        return UNKNOWN
    if not status.get("connected"):
        return UNKNOWN
    selected = status.get("selected") or {}
    mode = selected.get("mode")
    return mode if mode in (DEMO, LIVE) else UNKNOWN


def entitlement_of(user_id, *, now=None):
    """`free_demo` or `paid_live`.

    An active licence ON A LIVE PLAN is `paid_live`. Everything else — none,
    expired, revoked, and an active FREE TRIAL — is `free_demo`, which is the
    free tier and NOT a statement that the client is in good standing.
    Revocation is carried separately, in `licence_state`, and `capability()`
    blocks on it.

    THE STATE IS NOT ENOUGH. This read the state alone, which was right while
    there was one plan to sell and became wrong the moment a free trial was
    also an ACTIVE licence: fourteen free days would have reported themselves
    as the paid live entitlement. `plans.is_live_plan` is the only thing that
    answers "does this plan pay for live".
    """
    st = _lic.status_for(user_id, now=now)
    return (PAID_LIVE
            if st.get("state") == _lic.ACTIVE and _plans.is_live_plan(st.get("plan"))
            else FREE_DEMO)


def _reauth_needed(user_id, *, now=None):
    """Whether the stored broker session can no longer be used.

    A connection whose access token has expired and which holds no refresh
    token cannot be revived; the client has to reconnect. Saying so is the
    difference between a screen that asks for one action and a screen that
    shows an empty list.
    """
    try:
        _link.access_token_for(user_id, now=now, refresher=_no_refresh)
    except _link.LinkError as e:
        return e.code in ("REFRESH_UNAVAILABLE", "REFRESH_FAILED")
    except Exception:                                   # noqa: BLE001
        return False
    return False


def _no_refresh(*_a, **_k):
    """A refresher that refuses to perform network I/O.

    `capability()` is called on read paths, including ones a dashboard polls.
    Refreshing a broker token as a side effect of rendering a badge would be
    a request the client never asked for, so this probe asks only whether the
    token in hand is still usable.
    """
    raise _link.LinkError("REFRESH_UNAVAILABLE",
                          "the access token has expired — reconnect the "
                          "account")


def capability(user_id, *, now=None):
    """The server's whole verdict on what this client may do, right now.

    Safe to hand a browser: it carries no token, no account number and no
    licence key. It is the single thing the UI needs in order to render a
    badge and to know whether to offer an automation control at all.
    """
    lic = _lic.status_for(user_id, now=now)
    ent = entitlement_of(user_id, now=now)
    trial = _plans.trial_state(user_id, now=now)
    mode = account_mode(user_id)

    # Activation and automation are different permissions and the UI must not
    # infer one from the other. Freezing a rule version records terms; it does
    # not trade, needs no connected account, and is allowed on the free tier —
    # see require_activation. The rule page used to decide this for itself with
    # `licence !== "active"`, which dead-ended every free demo client: they
    # could build a rule and then never activate it, so they could never start
    # anything. Carried here so the server states it and no screen has to
    # guess.
    can_activate = lic.get("state") != _lic.REVOKED

    out = {
        "accountMode": mode,
        "entitlement": ent,
        "licenceState": lic.get("state"),
        "liveExecutionEnabled": live_execution_enabled(),
        "planNotice": PLAN_NOTICE,
        "plan": trial["plan"],
        "onTrial": trial["onTrial"],
        "trialDaysLeft": trial["daysLeft"],
        "trialExpiresAt": trial["expiresAt"],
        # How many distinct accounts this client may trade through the
        # platform. One, unless the operator has confirmed their broker
        # account against the IB report — see plans.account_allowance.
        "accountAllowance": _plans.account_allowance(user_id),
        "canAutomate": False,
        "canActivate": can_activate,
        "activationRefusal": ("this licence was withdrawn — contact support"
                              if not can_activate else None),
        "reason": None,
        "message": "",
        "badge": BADGE_NOT_CONNECTED,
    }

    # Withdrawal outranks everything. It is how support stops a client, and a
    # free tier that routed around it would make it decorative.
    if lic.get("state") == _lic.REVOKED:
        return dict(out, reason="LICENCE_REVOKED",
                    badge=BADGE_NOT_CONNECTED if mode == UNKNOWN
                    else BADGE_LIVE_BLOCKED if mode == LIVE else BADGE_DEMO,
                    message="this licence was withdrawn — contact support")

    # The demo trial, and the hole this closes.
    #
    # `user_loop._entitled` has always allowed an ACTIVE platform licence and
    # refused everything else, so demo automation already required one at the
    # ENGINE. This function claimed the opposite — canAutomate=True for a
    # connected demo account with no licence at all — so the UI offered a
    # Start button that came back ENGINE_REFUSED. The two gates now agree, and
    # the message says which of the two situations it is rather than making
    # the client guess from a generic refusal.
    #
    # Checked before the connection, because the licence is a property of the
    # account: a client whose trial ran out should be told that, not told to
    # connect something.
    if lic.get("state") != _lic.ACTIVE:
        badge = (BADGE_NOT_CONNECTED if mode == UNKNOWN
                 else BADGE_LIVE_BLOCKED if mode == LIVE else BADGE_DEMO)
        expired = lic.get("state") == _lic.EXPIRED
        return dict(out, badge=badge,
                    reason="TRIAL_EXPIRED" if expired else "NO_LICENCE",
                    message=(TRIAL_EXPIRED_MESSAGE if expired
                             else NO_LICENCE_MESSAGE))

    if mode == UNKNOWN:
        if _reauth_needed(user_id, now=now):
            return dict(out, reason="REAUTH_REQUIRED", badge=BADGE_REAUTH,
                        message="this cTrader connection has expired — "
                                "connect the account again")
        return dict(out, reason="NOT_CONNECTED", badge=BADGE_NOT_CONNECTED,
                    message="connect a cTrader demo account and select it")

    if _reauth_needed(user_id, now=now):
        return dict(out, reason="REAUTH_REQUIRED", badge=BADGE_REAUTH,
                    message="this cTrader connection has expired — connect "
                            "the account again")

    if mode == LIVE:
        # LOCK 2, and it is now two questions asked in this order, because the
        # order decides what the client is TOLD.
        #
        # The switch first. While this deployment has live execution closed,
        # nobody trades real money and the honest answer names the release —
        # not the client's plan. Telling a paying client "your plan does not
        # cover this" when the truth is "nothing is open yet" would be a lie
        # about something they paid for.
        if not live_execution_enabled():
            return dict(out, reason="LIVE_NOT_AVAILABLE",
                        badge=BADGE_LIVE_BLOCKED,
                        message=LIVE_REFUSAL)
        # Then the plan, and it is NOT a comparison written here.
        #
        # This is still the function guarding the path that moves real money,
        # and a tier comparison living in it is one edit away from becoming
        # the thing that lets the wrong plan through. The commercial rule —
        # the free trial covers demo accounts only, the paid plan covers live
        # — is `plans.may_trade_live`, which reads a plan name, returns a
        # boolean, and can unlock nothing by itself. The invariants test
        # asserts this function CALLS it rather than re-deciding it.
        if not _plans.may_trade_live(lic.get("plan")):
            return dict(out, reason="LIVE_NOT_ENTITLED",
                        badge=BADGE_LIVE_BLOCKED,
                        message=LIVE_NOT_ENTITLED_MESSAGE)
        # Both locks open. This is the only return in this function that
        # permits an order against real money, and it is still not the last
        # word: `gates.authorize_order` re-asks every one of these questions
        # at the order itself, where the broker's own answer about the account
        # is available and this one is a screen's worth of state.
        return dict(out, canAutomate=True, badge=BADGE_LIVE,
                    message="live automation is available on this account")

    return dict(out, canAutomate=True, badge=BADGE_DEMO,
                message="demo automation is available on this account")


def require_automation(user_id, *, now=None):
    """The capability, or NotEntitled. Called before anything starts."""
    cap = capability(user_id, now=now)
    if not cap["canAutomate"]:
        raise NotEntitled(cap["reason"], cap["message"],
                          state=cap["licenceState"])
    return cap


def require_activation(user_id, *, now=None):
    """Freezing a rule version.

    Deliberately weaker than `require_automation`: activation records terms,
    it does not trade. A client may build and activate a rule before they
    have connected an account, and refusing that would make the product
    unusable in the order people actually use it. A withdrawn licence still
    refuses, because that client should not be accumulating anything.
    """
    lic = _lic.status_for(user_id, now=now)
    if lic.get("state") == _lic.REVOKED:
        raise NotEntitled("LICENCE_REVOKED",
                          "this licence was withdrawn — contact support",
                          state=lic.get("state"))
    # Through entitlement_of, not the state, for the same reason it does: a
    # free trial is an ACTIVE licence and is not the paid live entitlement.
    return {"entitlement": entitlement_of(user_id, now=now),
            "licenceState": lic.get("state")}
