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

FREE_DEMO = "free_demo"
PAID_LIVE = "paid_live"
ENTITLEMENTS = (FREE_DEMO, PAID_LIVE)

DEMO = _link.DEMO
LIVE = _link.LIVE
UNKNOWN = "unknown"
MODES = (DEMO, LIVE, UNKNOWN)

# Badges the UI renders. Named here so the server decides what a client is
# told, rather than the browser inferring it from a combination of fields.
BADGE_DEMO = "DEMO"
BADGE_LIVE_BLOCKED = "LIVE BLOCKED"
BADGE_NOT_CONNECTED = "NOT CONNECTED"
BADGE_REAUTH = "REAUTH REQUIRED"

# The one sentence this release makes about paid access. Kept here so the API,
# the UI and the tests cannot drift into three different promises.
PLAN_NOTICE = ("Demo accounts are free. Real-money account access will be a "
               "paid plan, and live execution is not enabled in this release.")

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

    An active licence is `paid_live`. Everything else — none, expired,
    revoked — is `free_demo`, which is the free tier and NOT a statement that
    the client is in good standing. Revocation is carried separately, in
    `licence_state`, and `capability()` blocks on it.
    """
    st = _lic.status_for(user_id, now=now)
    return PAID_LIVE if st.get("state") == _lic.ACTIVE else FREE_DEMO


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
    ent = PAID_LIVE if lic.get("state") == _lic.ACTIVE else FREE_DEMO
    mode = account_mode(user_id)

    out = {
        "accountMode": mode,
        "entitlement": ent,
        "licenceState": lic.get("state"),
        "liveExecutionEnabled": live_execution_enabled(),
        "planNotice": PLAN_NOTICE,
        "canAutomate": False,
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
        # Both entitlements land here. A paid plan does not unlock an
        # execution path that does not exist, and pretending otherwise is the
        # single most dangerous thing this file could do.
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
    return {"entitlement": PAID_LIVE if lic.get("state") == _lic.ACTIVE
            else FREE_DEMO, "licenceState": lic.get("state")}
