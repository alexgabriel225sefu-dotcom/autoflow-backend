"""The pilot guard: real money only for the operator's own account, at a capped size.

WHY THIS EXISTS

`docs/LIVE_EXECUTION_SPECIFICATION.md` §11 puts the operator's OWN live account
at step 2 of the rollout, before any client's. The release switch
(`A4T_LIVE_EXECUTION`) is per deployment, so on its own it cannot say that: the
day it opens, every client who holds a live plan and a live account is inside.
This module is the missing narrowing. It sits behind the switch and the
entitlement and it only ever REFUSES.

THREE VALUES, AND ALL THREE MUST BE SET

  A4T_LIVE_PILOT_USERS      comma-separated platform user ids allowed to trade
  A4T_LIVE_PILOT_ACCOUNTS   comma-separated cTrader account ids allowed
  A4T_LIVE_PILOT_MAX_UNITS  largest single order, in instrument units

FAIL CLOSED, BY DEFAULT AND IN EVERY DIRECTION

  * Any of the three unset, empty or unparseable refuses every live order
    (`PILOT_UNCONFIGURED`). Opening the release switch alone therefore does
    nothing until someone has also said WHO and HOW MUCH.
  * A user or an account that is not listed is refused.
  * A size that is over the cap, or that cannot be measured, is refused: a fact
    we could not establish is not a fact in our favour.

The account id compared is the one on the caller's own link record, never one
taken from a request (spec §4).

WIDENING IS NOT A CONFIG CHANGE. Step 3 of the rollout (one consenting client)
needs its own review; it is done by changing this module and its tests, not by
adding a name to a list and hoping the list means what it used to.

This module reads three environment variables and imports no execution
primitive, no broker and no store. It cannot place an order and cannot open
anything: every function returns a refusal or None.
"""
import os

USERS_ENV = "A4T_LIVE_PILOT_USERS"
ACCOUNTS_ENV = "A4T_LIVE_PILOT_ACCOUNTS"
MAX_UNITS_ENV = "A4T_LIVE_PILOT_MAX_UNITS"

PILOT_UNCONFIGURED = "PILOT_UNCONFIGURED"
NOT_PILOT_USER = "NOT_PILOT_USER"
NOT_PILOT_ACCOUNT = "NOT_PILOT_ACCOUNT"
OVER_PILOT_SIZE = "OVER_PILOT_SIZE"

CODES = (PILOT_UNCONFIGURED, NOT_PILOT_USER, NOT_PILOT_ACCOUNT, OVER_PILOT_SIZE)


def _ids(name):
    raw = os.getenv(name) or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def _max_units():
    raw = (os.getenv(MAX_UNITS_ENV) or "").strip()
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _unconfigured():
    if not _ids(USERS_ENV) or not _ids(ACCOUNTS_ENV) or _max_units() is None:
        return (PILOT_UNCONFIGURED,
                "the live pilot is not configured (who may trade, on which "
                "account, and the largest order), so no live order is sent")
    return None


def check_identity(user_id, account_id):
    """None if this user on this account is in the pilot, else (code, detail)."""
    refusal = _unconfigured()
    if refusal:
        return refusal
    if str(user_id) not in _ids(USERS_ENV):
        return (NOT_PILOT_USER,
                "this client is not part of the live pilot, which is limited "
                "to the operator's own account")
    if account_id is None or str(account_id) not in _ids(ACCOUNTS_ENV):
        return (NOT_PILOT_ACCOUNT,
                "this trading account is not part of the live pilot")
    return None


def check_size(units):
    """None if one order of `units` is within the pilot cap, else (code, detail)."""
    refusal = _unconfigured()
    if refusal:
        return refusal
    cap = _max_units()
    try:
        if isinstance(units, bool):
            raise TypeError("a bool is not a size")
        size = abs(float(units))
    except (TypeError, ValueError):
        size = None
    if size is None or size != size or size <= 0:
        return (OVER_PILOT_SIZE,
                "the size of this order could not be measured, so it is not "
                "sent during the live pilot")
    if size > cap:
        return (OVER_PILOT_SIZE,
                f"this order is larger than the live pilot allows "
                f"({size:g} units, the cap is {cap})")
    return None
