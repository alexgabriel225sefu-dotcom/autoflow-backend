"""What a client is on, what it costs, and how many accounts it may trade.

THE TRAP THIS FILE EXISTS TO CLOSE

`licence.py` holds a state and a plan. `entitlement.py` used to read only the
STATE: any ACTIVE licence became `paid_live`. That was correct while there was
exactly one plan to sell, and it becomes a hole the moment a free trial is
also an active licence — a fourteen-day demo trial would have reported itself
as the paid live entitlement, and the only reason it would not have unlocked
live trading is that live trading does not exist yet.

So the plan is now what decides, and this file is where a plan's meaning
lives. `is_live_plan` is the single answer to "does this plan pay for live",
and `entitlement.py` asks it rather than inferring from the state.

THE THREE PLANS

  demo_trial    fourteen days, free, demo accounts only. The engine gate
                already enforces the expiry: `user_loop._entitled` allows an
                ACTIVE platform licence and refuses an EXPIRED one, and the
                watchdog re-checks, so a trial that runs out stops a loop that
                is already running rather than only refusing the next start.

  founder_live  497 USD, one-time. Pays for live execution when live
                execution ships. It does NOT turn live on: `live_execution_
                enabled()` stays false and every lock stays in place. A plan
                that unlocked an execution path which has not been reviewed
                would be the most dangerous line in this product.

  none          no licence. Demo automation is refused, which is what the
                engine already did — `capability()` was the only thing
                claiming otherwise.

ACCOUNT ALLOWANCE

One tradable account by default. More only when the operator has CONFIRMED,
from the broker's IB report, that the client's broker account sits under their
introducing-broker code — `referral.is_confirmed`. Fail-closed throughout: an
unknown referral state, an unreadable record or an unconfigured referral code
all answer one.

What this allowance is NOT: permission to trade several accounts AT ONCE.
`user_loop.start` runs one loop per platform user and `automation` keys its
state by user, so simultaneous multi-account trading is an engine change this
file does not pretend to have made. The allowance governs how many distinct
accounts a client may trade THROUGH the platform; switching between them is
the supported shape today.
"""

import os

from apex.platform import licence as _lic
from apex.platform import referral as _referral

# ── the catalogue ───────────────────────────────────────────────────────────
NONE = "none"
DEMO_TRIAL = "demo_trial"

# The name the PAYMENT PATH already grants — `billing.APPROVED_PLAN`. Not a
# new string invented here: this started life as "founder_live" and that was a
# bug worth recording, because `billing.py` writes `plan="founder_lifetime"`
# and nothing would have matched it. A client who paid would have been read as
# a free trial, and the symptom — paid customer, free tier — is one nobody
# would have connected to a constant in this file.
#
# tests/test_platform_plans_referral.py pins this against billing's own
# constant so the two cannot drift apart again.
FOUNDER_LIVE = "founder_lifetime"
PLANS = (DEMO_TRIAL, FOUNDER_LIVE)

# Exactly the plans that pay for live execution. Named rather than inferred,
# so a new plan is not a live plan until somebody says it is.
LIVE_PLANS_SHIPPED = (FOUNDER_LIVE,)

# `billing.py` reads its plan name from A4T_PLAN, falling back to the shipped
# one. So the name a paying client actually receives is settable at runtime,
# and a check that knew only the shipped name would read a legitimately
# renamed plan as the free tier — the same defect as above, arriving by
# configuration instead of by typo.
_BILLING_PLAN_ENV = "A4T_PLAN"


def live_plans():
    """Every plan that pays for live: the shipped one, plus billing's.

    DEMO_TRIAL can never join this set, whatever A4T_PLAN is set to. Without
    that line, pointing the billing plan name at the trial would hand the free
    tier the paid entitlement — the exact confusion this module was written to
    end, re-entering through an environment variable.
    """
    configured = (os.getenv(_BILLING_PLAN_ENV) or "").strip()
    out = list(LIVE_PLANS_SHIPPED)
    if configured and configured != DEMO_TRIAL:
        out.append(configured)
    return tuple(out)

TRIAL_DAYS = 14
TRIAL_SECONDS = TRIAL_DAYS * 86400

# THE PRICE IS NOT HERE, ON PURPOSE.
#
# It lives in `billing.APPROVED_PRICE_MINOR`, reaches the browser through GET
# billing/offer, and is formatted in one place. `billing.offer_drift()` reports
# on /readyz when a deployment moves off the approved figure — a guard that can
# only work while there is one figure to guard. A second copy here would be a
# price no gate is watching, and the web suite forbids a currency literal in
# any file a client can read for exactly that reason.
#
# So this module owns the plan NAME and the trial length. The money is
# billing's.

DEFAULT_ACCOUNT_ALLOWANCE = 1

# How many accounts a confirmed referral unlocks. Operator-settable because it
# is a commercial decision, floored at the default so a bad value can never
# take away an account the client already has.
_REFERRED_ALLOWANCE_ENV = "A4T_REFERRED_ACCOUNT_ALLOWANCE"
REFERRED_ACCOUNT_ALLOWANCE_DEFAULT = 5


def is_live_plan(plan):
    """Whether this plan pays for live execution.

    The only place that answers this. Note what it does NOT consult: the
    licence state. A revoked founder plan is still a live PLAN; whether it is
    currently in force is the licence's question, and keeping the two apart is
    what stops "active" and "paid for live" being the same word again.
    """
    return str(plan or "") in live_plans()


def referred_account_allowance():
    """The allowance a confirmed referral unlocks.

    A malformed value falls back to the shipped number and a value below the
    default is raised to it — the failure mode of a mistyped environment
    variable must not be a client losing access they already paid for.
    """
    raw = (os.getenv(_REFERRED_ALLOWANCE_ENV) or "").strip()
    if not raw:
        return REFERRED_ACCOUNT_ALLOWANCE_DEFAULT
    try:
        n = int(raw)
    except ValueError:
        print(f"[Plans] {_REFERRED_ALLOWANCE_ENV}={raw!r} is not a whole "
              f"number — using {REFERRED_ACCOUNT_ALLOWANCE_DEFAULT}")
        return REFERRED_ACCOUNT_ALLOWANCE_DEFAULT
    return max(DEFAULT_ACCOUNT_ALLOWANCE, n)


def account_allowance(user_id):
    """How many distinct accounts this client may trade through the platform.

    Fail-closed: anything other than a confirmed referral is the default.
    """
    try:
        if _referral.is_confirmed(user_id):
            return referred_account_allowance()
    except Exception:                                        # noqa: BLE001
        # A referral store that cannot answer is not a confirmation. Granting
        # the larger allowance on an error would make an outage into free
        # capability.
        pass
    return DEFAULT_ACCOUNT_ALLOWANCE


def plan_of(user_id, *, now=None):
    """The plan on file, whatever its state, or NONE."""
    st = _lic.status_for(user_id, now=now)
    if st.get("state") == _lic.NONE:
        return NONE
    return st.get("plan") or NONE


def start_trial(user_id, *, now=None):
    """Grant the free fourteen-day demo trial. Idempotent, and never extends.

    Called once, when an account is created. Re-calling it returns the
    existing trial rather than moving its expiry: a trial that restarts on
    every sign-in is not a trial, and the client who discovers that is the one
    who never pays.

    A client who already holds any other plan keeps it — granting a trial over
    a paid plan would downgrade a paying customer.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("a trial needs an account to belong to")
    import time
    now = time.time() if now is None else float(now)

    st = _lic.status_for(uid, now=now)
    if st.get("state") != _lic.NONE:
        # Already has something — a live trial, an expired one, a paid plan,
        # or a revocation. Each of those is an answer; none of them is
        # "give them fourteen fresh days".
        return _lic.status_for(uid, now=now)

    _lic.grant(uid, plan=DEMO_TRIAL, expires_at=now + TRIAL_SECONDS, now=now)
    return _lic.status_for(uid, now=now)


def trial_state(user_id, *, now=None):
    """The client's trial, in the terms a screen needs.

    `daysLeft` is rounded UP, because a client with eleven hours left has one
    day left, not zero, and a screen that says zero while the product still
    works is a screen nobody trusts.
    """
    import math
    import time
    now = time.time() if now is None else float(now)
    st = _lic.status_for(user_id, now=now)
    plan = st.get("plan") or NONE
    exp = st.get("expiresAt")
    on_trial = plan == DEMO_TRIAL

    left = None
    if on_trial and exp is not None:
        left = max(0, int(math.ceil((float(exp) - now) / 86400.0)))

    return {"plan": plan,
            "onTrial": on_trial,
            "state": st.get("state"),
            "expiresAt": exp,
            "daysLeft": left,
            "trialDays": TRIAL_DAYS,
            "expired": bool(on_trial and st.get("state") == _lic.EXPIRED)}
