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
  capability     what this RELEASE can execute at all.

The third is the one that is easy to lose. Live execution is not implemented.
No entitlement unlocks it, including a paid one, because there is nothing
behind the flag to unlock. `paid_live` + a live account is refused exactly as
`free_demo` + a live account is refused, and the tests assert all four
combinations rather than the two that happen to differ.

WHY DEMO IS FREE HERE AND NOT IN licence.py

`licence.py` still means what it always meant: a deliberate, recorded
entitlement, granted by the payment path or by hand. What changed is that
holding one is no longer the condition for running a rule on a DEMO account —
that is free, by decision. A licence now means `paid_live`, and a REVOKED one
still blocks everything, because revocation is how support stops a client and
it would be worthless if free demo access routed around it.

An absent licence is `free_demo`. A revoked one is not.
"""

from apex.platform import ctrader_link as _link
from apex.platform import licence as _lic
from apex.platform import plans as _plans

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


class NotEntitled(PermissionError):
    """Refused, with a code the UI branches on instead of matching English."""

    def __init__(self, code, message, *, state=None):
        self.code = code
        self.state = state
        super().__init__(message)


def live_execution_enabled():
    """Always False in this release, and stated rather than assumed.

    There is no execution path for a live account: `bridge` supports MARKET
    orders only, `automation.start` refuses a non-demo account, and nothing
    reads a live-trading flag to decide otherwise. This function exists so
    that fact is something a caller can ASK, and something a test can pin.
    """
    return False


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
        # REFUSED FOR EVERYONE, with NO reference to the entitlement.
        #
        # That absence is a structural invariant, asserted on this
        # function's own SOURCE by tests/test_platform_live_invariants.py:
        # lock 2 must not compare the entitlement against the paid tier at
        # all. The guard is literal, and deliberately so — this very comment
        # failed it once by quoting the forbidden comparison in prose.
        #
        # The reason is not that such a check would be wrong today. A version
        # that varied only the MESSAGE behaved identically. It is that a
        # comparison sitting here is one edit away from becoming the thing
        # that lets a paid plan through, and this is the function guarding the
        # path that moves real money.
        #
        # The commercial rule that a trial covers demo accounts only lives in
        # `plans.may_trade_live`, which answers that question and can unlock
        # nothing. Whoever opens this lock calls it rather than writing a
        # comparison here.
        return dict(out, reason="LIVE_NOT_AVAILABLE",
                    badge=BADGE_LIVE_BLOCKED,
                    message=LIVE_REFUSAL)

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
