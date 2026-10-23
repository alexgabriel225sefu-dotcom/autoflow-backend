"""The pilot guard: real money only for the operator's own account, at a capped size.

WHY THIS EXISTS

`docs/LIVE_EXECUTION_SPECIFICATION.md` §11 puts the operator's OWN live account
at step 2 of the rollout, before any client's. The release switch
(`A4T_LIVE_EXECUTION`) is per deployment, so on its own it cannot say that: the
day it opens, every client who holds a live plan and a live account is inside.
This module is the missing narrowing. It sits behind the switch and the
entitlement and it only ever REFUSES.

THREE VALUES, AND ALL THREE MUST BE SET

  A4T_LIVE_PILOT_PAIRS      comma-separated  user_id:account_id  pairs
  A4T_LIVE_PILOT_SYMBOLS    comma-separated instruments that may be traded
  A4T_LIVE_PILOT_MAX_UNITS  largest single order, in instrument units

A PAIR, NOT TWO LISTS. Two lists admit every listed user on every listed
account, so two clients who had linked the same cTrader login would both be
inside. A pair names one user on one account.

SYMBOLS ARE LISTED BECAUSE ONE NUMBER OF UNITS MEANS DIFFERENT THINGS. 10,000
units is about 0.1 lot on EURUSD and 10,000 ounces on XAUUSD. The cap is only
meaningful for the instruments it was chosen for, so the pilot trades only
those.

FAIL CLOSED, BY DEFAULT AND IN EVERY DIRECTION

  * Any of the three unset, empty or unparseable refuses every live order
    (`PILOT_UNCONFIGURED`). Opening the release switch alone therefore does
    nothing until someone has also said WHO, WHAT and HOW MUCH.
  * A pair that is not listed is refused, as is an instrument that is not.
  * A size that is over the cap, or that cannot be measured, is refused: a fact
    we could not establish is not a fact in our favour.

The account id compared is the one on the caller's own link record, never one
taken from a request (spec §4).

THE CAP MUST NOT BE BELOW THE BROKER'S MINIMUM ORDER. The broker raises a
smaller order to its minimum after this check has passed, and that order would
exceed the cap. This module refuses when the cap is below the code's own floor
(`forex.min_units`); the broker's real per-symbol minimum can be larger, and
the operator confirms it before setting the cap.

WIDENING IS NOT A CONFIG CHANGE. Step 3 of the rollout (one consenting client)
needs its own review; it is done by changing this module and its tests, not by
adding a name to a list and hoping the list means what it used to.

This module reads three environment variables and imports no execution
primitive, no broker and no store. It cannot place an order and cannot open
anything: every function returns a refusal or None.
"""
import os

PAIRS_ENV = "A4T_LIVE_PILOT_PAIRS"
SYMBOLS_ENV = "A4T_LIVE_PILOT_SYMBOLS"
MAX_UNITS_ENV = "A4T_LIVE_PILOT_MAX_UNITS"

PILOT_UNCONFIGURED = "PILOT_UNCONFIGURED"
NOT_PILOT_ACCOUNT = "NOT_PILOT_ACCOUNT"
NOT_PILOT_SYMBOL = "NOT_PILOT_SYMBOL"
OVER_PILOT_SIZE = "OVER_PILOT_SIZE"

CODES = (PILOT_UNCONFIGURED, NOT_PILOT_ACCOUNT, NOT_PILOT_SYMBOL,
         OVER_PILOT_SIZE)


def _items(name):
    raw = os.getenv(name) or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def _symbol(value):
    return str(value or "").strip().upper().replace("/", "").replace("_", "")


def _symbols():
    return {_symbol(s) for s in _items(SYMBOLS_ENV) if _symbol(s)}


def _pairs():
    out = set()
    for item in _items(PAIRS_ENV):
        user, sep, account = item.partition(":")
        user, account = user.strip(), account.strip()
        if sep and user and account:
            out.add((user, account))
    return out


def _max_units():
    raw = (os.getenv(MAX_UNITS_ENV) or "").strip()
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _unconfigured():
    if not _pairs() or not _symbols() or _max_units() is None:
        return (PILOT_UNCONFIGURED,
                "the live pilot is not configured (which account, which "
                "instruments, and the largest order), so no live order is sent")
    return None


def check_identity(user_id, account_id):
    """None if this user on this account is in the pilot, else (code, detail)."""
    refusal = _unconfigured()
    if refusal:
        return refusal
    if account_id is None or (str(user_id), str(account_id)) not in _pairs():
        return (NOT_PILOT_ACCOUNT,
                "this client and trading account are not part of the live "
                "pilot, which is limited to the operator's own account")
    return None


def check_order(symbol, units):
    """None if one order of `units` in `symbol` is inside the pilot, else (code, detail)."""
    refusal = _unconfigured()
    if refusal:
        return refusal
    if _symbol(symbol) not in _symbols():
        return (NOT_PILOT_SYMBOL,
                "this instrument is not part of the live pilot")
    cap = _max_units()
    # The broker raises an order below ITS minimum up to that minimum after this
    # check, so a cap under the minimum is not a cap. The code's own floor is the
    # smallest the broker could ever demand; the broker's real one may be larger
    # and is for the operator to confirm. Unknown floor: refuse.
    try:
        from apex import forex as _fx
        floor = _fx.min_units(symbol)
    except Exception:                                        # noqa: BLE001
        floor = None
    if floor is None or floor > cap:
        return (OVER_PILOT_SIZE,
                f"the pilot cap ({cap} units) is below the smallest order this "
                f"instrument allows, so no order of it is sent")
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
