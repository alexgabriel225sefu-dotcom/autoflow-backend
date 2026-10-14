"""Who arrived through the operator's link, and whose broker account is under it.

THE TWO FACTS THIS FILE KEEPS APART, AND WHY

They look like one fact and they are not, and conflating them is the whole
risk in this file.

  1. **ARRIVAL.** This client reached the product through the operator's
     referral link. The platform can establish this itself: the link carries a
     code, the code is recorded against the account at sign-up, and it is
     recorded once and never rewritten.

  2. **THE BROKER ACCOUNT BEING UNDER THE OPERATOR'S IB.** The platform
     CANNOT establish this. It is a fact held by the broker, reported in the
     broker's own IB report. Nothing visible through the cTrader Open API says
     "this account was opened under introducing broker X" — the API exposes
     the trader's accounts, not who introduced them.

So arrival is attributed automatically and confirmation is an OPERATOR ACT,
recorded with who did it and which report it came from. There is deliberately
no code path that infers 2 from 1. A client can arrive through the link and
open their broker account directly; treating that as confirmed would grant
paid-for capability on a guess, and the guess would be discovered as missing
rebate revenue months later.

WHY A CONFIRMATION THAT CANNOT BE AUDITED IS REFUSED

Confirming one of these grants a client extra tradable accounts, which is an
entitlement change. §7 of docs/LIVE_EXECUTION_SPECIFICATION.md requires every
entitlement change to be recorded with its actor, append-only. So the
confirmation writes an audit record FIRST and refuses outright if the audit
trail cannot take it. An entitlement change nobody can later attribute is
exactly the one somebody will dispute.

WHAT THIS FILE DOES NOT DO

It holds no money, computes no commission and talks to no affiliate network.
It answers one question — may this client trade more than one account — and
records the basis for the answer.
"""

import os
import re
import time

from apex.platform import store as _store

# The operator's own code. An empty value means referral attribution is not
# configured, which is NOT the same as "nobody is referred": it means the
# question cannot be answered, and `attribute` refuses rather than filing
# every arrival under a blank code.
CODE_ENV = "A4T_REFERRAL_CODE"

# Where a client opens a broker account under the operator's introducing-broker
# code. Configuration, never hardcoded: the operator can change brokers, and a
# URL compiled into the product is one that outlives the arrangement it
# describes.
SIGNUP_URL_ENV = "A4T_BROKER_SIGNUP_URL"

# THE DISCLOSURE, AND WHY IT IS NOT OPTIONAL.
#
# An introducing-broker arrangement pays the operator from the volume the
# client trades, while this platform decides how often to trade. That is a
# conflict of interest, and a client sent to a signup link without being told
# has not been given the one fact they would want. In the EU, disclosing an
# inducement of this kind is not a courtesy.
#
# So `broker_signup()` returns the URL and this sentence TOGETHER and there is
# no accessor that returns the URL alone — the disclosure cannot be dropped by
# whoever writes the screen, because the API never hands out a bare link.
# tests/test_platform_plans_referral.py asserts that no such accessor exists.
REBATE_DISCLOSURE = (
    "Opening an account through this link pays the operator of this platform "
    "a commission from the broker, based on the volume you trade. You do not "
    "have to use it: you can open an account with any cTrader broker and "
    "connect it here instead, and the accounts you already use are "
    "unaffected.")

# Where an attribution came from. Recorded because "they clicked the link" and
# "support typed it in" are different kinds of evidence and a dispute needs to
# know which one it is looking at.
SRC_LINK = "link"
SRC_OPERATOR = "operator"
SOURCES = (SRC_LINK, SRC_OPERATOR)

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")


class ReferralError(ValueError):
    """A referral fact that cannot be recorded as stated."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def operator_code():
    """The configured referral code, or "" when there is none."""
    return (os.getenv(CODE_ENV) or "").strip()


def _k(user_id):
    return f"{_store._ns()}:{_store._P}:referral:{user_id}"


def _read(user_id):
    raw = _store._read(_k(str(user_id)))
    return raw if isinstance(raw, dict) else None


def normalise(code):
    """The stored form of a code, or ReferralError.

    Case-folded, because a link pasted from a phone keyboard arrives
    capitalised and a client should not lose their attribution to it.
    """
    raw = str(code or "").strip()
    if not _CODE_RE.match(raw):
        raise ReferralError(
            "BAD_CODE",
            "a referral code must be 2-64 characters of letters, digits, "
            "underscore or hyphen — a code that cannot be stored as written "
            "would attribute this client to something nobody can look up")
    return raw.lower()


def attribute(user_id, *, code, source=SRC_LINK, now=None):
    """Record that this client arrived through a referral code. Once.

    Idempotent for the SAME code and refused for a different one. Attribution
    decides who is owed a rebate, so an account whose attribution can be
    overwritten is an account whose attribution is worth nothing — and the
    overwrite would always arrive later than the original, which is the wrong
    way round.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ReferralError("NO_USER", "an attribution needs an account")
    if source not in SOURCES:
        raise ReferralError("BAD_SOURCE", f"source must be one of {SOURCES}")
    wanted = normalise(code)

    existing = _read(uid)
    if existing:
        if existing.get("code") == wanted:
            return existing
        raise ReferralError(
            "ALREADY_ATTRIBUTED",
            f"this account is already attributed to {existing.get('code')!r} "
            f"and attribution is not rewritten — a later claim cannot "
            f"displace an earlier one")

    rec = {"userId": uid, "code": wanted, "source": source,
           "attributedAt": float(time.time() if now is None else now),
           # Confirmation is a separate act and starts absent, not false: it
           # has not been looked at yet, which is a different state from
           # having been looked at and refused.
           "brokerConfirmed": None,
           "brokerAccount": None, "reportRef": None,
           "confirmedBy": None, "confirmedAt": None}
    _store._write(_k(uid), rec)
    return rec


def attribution_of(user_id):
    """What is on file, or None. Never invents an attribution."""
    return _read(user_id)


def arrived_through_link(user_id):
    """Whether this client arrived through the operator's own code.

    Attribution to some OTHER code is not the operator's referral, and this
    returns False for it rather than treating any attribution as theirs.
    """
    rec = _read(user_id)
    if not rec:
        return False
    mine = operator_code()
    if not mine:
        return False
    try:
        return rec.get("code") == normalise(mine)
    except ReferralError:
        return False


def is_confirmed(user_id):
    """Whether the broker account is CONFIRMED under the operator's IB.

    Fail-closed: absent, unreadable or merely-arrived all answer False. The
    only True is an explicit operator confirmation on file.
    """
    rec = _read(user_id)
    return bool(rec and rec.get("brokerConfirmed") is True)


def _audit_confirmation(uid, *, actor, broker_account, report_ref, granted):
    """Record the entitlement change, or raise so the caller does not proceed.

    Imported lazily because `apex.platform.audit` refuses to import without a
    shared backend — correctly, since a per-container audit trail is not one.
    That refusal reaches here as "this confirmation cannot be recorded", and
    the right answer to that is not to make it.
    """
    from apex.platform import audit as _audit
    return _audit.record_entitlement_change(
        user_id=uid, actor=actor, field="referral.brokerConfirmed",
        old_value=None, new_value=bool(granted),
        reason=(f"broker account {broker_account} confirmed under the "
                f"operator's IB from report {report_ref}"))


def confirm_broker_account(user_id, *, actor, broker_account, report_ref,
                           granted=True, now=None):
    """Record the operator's confirmation, from the broker's IB report.

    `report_ref` is required and is the point of the whole function: it names
    the evidence. A confirmation that cannot say which report it came from is
    an assertion, and this grants paid-for capability.

    The audit record is written FIRST. If it cannot be written, nothing is
    changed and this raises — see §7.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ReferralError("NO_USER", "a confirmation needs an account")
    if not str(actor or "").strip():
        raise ReferralError(
            "NO_ACTOR",
            "a confirmation must record who made it — this grants extra "
            "tradable accounts and an unattributable grant is one nobody "
            "can answer for")
    if not str(broker_account or "").strip():
        raise ReferralError(
            "NO_ACCOUNT",
            "a confirmation must name the broker account it is about")
    if not str(report_ref or "").strip():
        raise ReferralError(
            "NO_REPORT",
            "a confirmation must name the IB report it came from — the "
            "platform cannot see who introduced an account, so the report is "
            "the only evidence there is")

    rec = _read(uid)
    if not rec:
        raise ReferralError(
            "NOT_ATTRIBUTED",
            f"{uid} has no referral attribution on file, so there is nothing "
            f"to confirm — attribute the arrival first")

    _audit_confirmation(uid, actor=actor, broker_account=broker_account,
                        report_ref=report_ref, granted=granted)

    out = dict(rec)
    out.update({"brokerConfirmed": bool(granted),
                "brokerAccount": str(broker_account),
                "reportRef": str(report_ref),
                "confirmedBy": str(actor),
                "confirmedAt": float(time.time() if now is None else now)})
    _store._write(_k(uid), out)
    return out


def broker_signup():
    """{"url", "disclosure"} for opening an account under the operator's IB,
    or None when no link is configured.

    Deliberately ONE accessor returning BOTH. There is no `signup_url()`,
    because a screen built from one would show the link without the
    disclosure, and that is the version a regulator and a client both object
    to. See REBATE_DISCLOSURE.

    A link that is not plainly an https URL is treated as absent rather than
    passed through: a malformed value in an environment variable must not
    become an href the product shows to a client.
    """
    raw = (os.getenv(SIGNUP_URL_ENV) or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith("https://") or len(raw) > 2000 \
            or any(c.isspace() for c in raw):
        print(f"[Referral] {SIGNUP_URL_ENV} is not a plain https URL — "
              f"treating it as unset rather than showing it to a client")
        return None
    return {"url": raw, "disclosure": REBATE_DISCLOSURE}


def state_of(user_id):
    """The whole referral picture for one client, safe to hand a browser.

    Carries no report reference and no operator identity: a client may know
    that their account is confirmed, not which internal document says so.
    """
    rec = _read(user_id) or {}
    out = {"attributed": bool(rec),
           "arrivedThroughLink": arrived_through_link(user_id),
           "brokerConfirmed": bool(rec.get("brokerConfirmed") is True),
           "awaitingConfirmation": bool(rec)
           and rec.get("brokerConfirmed") is None}
    # DELIBERATELY NOT the signup link.
    #
    # This is the general referral state, read by any screen that wants it, so
    # putting the link here would show it to every unconfirmed client —
    # including the overwhelming majority who want exactly one account. That
    # is a nudge to open accounts nobody needs, and it earns nothing.
    #
    # The link belongs to one moment: the ACCOUNT_LIMIT refusal, raised when a
    # client has just tried to add another real-money account and is therefore
    # the one client actually asking for it. `api.handle` attaches it there.
    return out
