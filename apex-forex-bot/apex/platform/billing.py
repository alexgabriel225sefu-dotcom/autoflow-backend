"""Payment to licence, and nothing else.

THE ONE RULE THIS FILE ENFORCES: a licence is granted only by a payment the
payment provider signed for.

Nothing a browser sends can produce an entitlement. `handle_event` is the only
function here that grants, it refuses any body whose signature does not verify,
and the user it grants to comes from metadata that **this server** wrote when
the checkout was created — never from the request that claims the payment.

WHY THE SIGNATURE IS CHECKED HERE AND NOT BY AN SDK

The verification is thirty lines of stdlib HMAC. Handing the raw body to a
library that parses it first is how a webhook ends up trusting a body it then
re-reads; keeping the check on the exact bytes received removes that gap. The
legacy Telegram-era handler in apex/stripe_license.py does the same thing for
the same reason, and this is deliberately a separate store keyed by the
Supabase user id.

THE OWNER-APPROVED OFFER

The owner has chosen a one-time Founder Lifetime unlock at 497 USD. Checkout
still remains disabled unless A4T_CHECKOUT_ENABLED is explicitly set and the
authenticated checkout path has been reviewed. The defaults below exist so the
approved offer is not retyped differently across deploys; they do not enable
payments by themselves. See docs/PAYMENT_AND_LICENCE_DECISIONS.md.
"""

import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid

from apex import user_store
from apex.platform import licence as _lic
from apex.platform import notifications as _notify
from apex.platform import store as _store

# Stripe signs `t=<unix>,v1=<hex>`. Deliveries outside this window are refused
# so a captured body cannot be replayed later.
SIG_TOLERANCE_SEC = 300

# Events that grant. The approved platform endpoint subscribes to
# checkout.session.completed and checkout.session.async_payment_succeeded.
# A card is paid on completed. A delayed method completes unpaid, then
# async_payment_succeeded carries payment_status paid. The other two names
# are older branches. They are not part of that endpoint.
GRANTING = ("checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "payment_intent.succeeded",
            "invoice.payment_succeeded")
# Events that take the entitlement away.
REVOKING = ("charge.refunded", "charge.dispute.created",
            "customer.subscription.deleted", "invoice.payment_failed")

# The metadata key this server writes when it creates a checkout. The webhook
# reads the user id from here and from nowhere else.
USER_META_KEY = "a4tUserId"
# Supabase ids used by this platform are not numeric. A legacy Telegram
# checkout puts the chat id in client_reference_id. That number must never
# be treated as a platform user, for a grant or a revoke.
_PLATFORM_USER_ID = re.compile(r"^[A-Za-z0-9_.:@+-]{1,128}$")

# 49700, not 49900. The owner set the Founder Lifetime price at 497 USD;
# this is the ONE place it is written, which is why `offer_drift()` can
# watch it and why no component carries a figure of its own.
APPROVED_PRICE_MINOR = 49700
APPROVED_CURRENCY = "usd"
APPROVED_SKU = "founder_lifetime"
APPROVED_PLAN = "founder_lifetime"
APPROVED_PURCHASE_MODE = "one_time"


class BillingNotConfigured(RuntimeError):
    """Raised when the webhook is reachable but no secret is set.

    Answered as a refusal rather than a silent 200: a webhook that accepts
    everything while unconfigured is worse than one that is switched off,
    because Stripe stops retrying and the operator never learns.
    """


def _env(name):
    v = (os.getenv(name) or "").strip()
    return v or None


def webhook_secret():
    """The signing secret, from either name. Never a default.

    ``A4T_STRIPE_WEBHOOK_SECRET`` is the name this platform has always read.
    ``STRIPE_WEBHOOK_SECRET`` is accepted as well, so an owner copying the
    name from Stripe's dashboard is not silently unverified. Neither value
    is logged.
    """
    return _env("A4T_STRIPE_WEBHOOK_SECRET") or _env("STRIPE_WEBHOOK_SECRET")


def configured():
    """Whether a signed webhook can be verified at all."""
    return bool(webhook_secret())


def product_config():
    """The approved one-time offer, overrideable only by explicit env.

    The previous product used `29700` and `"apex-bot"`; those values are never
    fallback values here. The owner-approved default is the 499 USD Founder
    Lifetime unlock. Leaving A4T_LICENCE_DAYS unset means no expiry, which is
    the intended shape of a one-time purchase.
    """
    minor = _env("A4T_PRICE_MINOR")
    try:
        minor = int(minor) if minor is not None else None
    except ValueError:
        minor = None
    return {
        "priceMinor": minor if minor is not None else APPROVED_PRICE_MINOR,
        "currency": _env("A4T_CURRENCY") or APPROVED_CURRENCY,
        "sku": _env("A4T_SKU") or APPROVED_SKU,
        "plan": _env("A4T_PLAN") or APPROVED_PLAN,
        "purchaseMode": _env("A4T_PURCHASE_MODE") or APPROVED_PURCHASE_MODE,
        # How long a granted licence lasts. Unset means no expiry, which is
        # correct for a one-off purchase and wrong for a subscription — which
        # is why the plan shape is an owner decision, not a default.
        "periodDays": int(_env("A4T_LICENCE_DAYS") or 0) or None,
    }


def offer_drift():
    """Which environment variables move the live offer off the approved one.

    NAMES ONLY, never values. This answer reaches /readyz, which is reachable
    without a session, and a variable name is the whole truth an operator needs
    in order to go and look.

    WHY THIS EXISTS, rather than a presence check

    Price, currency, SKU and plan now have approved defaults in this module, so
    "is it set?" can never fail — and a readiness check that cannot fail is
    decoration. The gate in health.py was asking exactly that, and had been
    unfalsifiable since the defaults landed.

    What can actually go wrong is the opposite: a deployment quietly
    overriding the approved offer, or setting it to something unusable. Nothing
    anywhere compared the live offer against the approved one, so a price
    nobody approved could reach an invoice with every check green.
    """
    drift = []
    raw = _env("A4T_PRICE_MINOR")
    if raw is not None:
        try:
            if int(raw) != APPROVED_PRICE_MINOR:
                drift.append("A4T_PRICE_MINOR")
        except ValueError:
            # Set, and unusable. product_config() swallows the ValueError and
            # returns the APPROVED price, so without this the deployment would
            # serve 499 while the environment plainly says something else —
            # the most dangerous of the three states, because it looks fine.
            drift.append("A4T_PRICE_MINOR")
    # Case-folded on purpose: "USD" and "usd" are the same currency, and
    # failing readiness over capitalisation would teach operators to ignore
    # this check, which is how a real drift gets waved through.
    for name, got, approved in (
            ("A4T_CURRENCY", _env("A4T_CURRENCY"), APPROVED_CURRENCY),
            ("A4T_SKU", _env("A4T_SKU"), APPROVED_SKU),
            ("A4T_PLAN", _env("A4T_PLAN"), APPROVED_PLAN),
            ("A4T_PURCHASE_MODE", _env("A4T_PURCHASE_MODE"),
             APPROVED_PURCHASE_MODE)):
        if got is not None and got.strip().lower() != approved:
            drift.append(name)
    # An expiry on a one-time purchase is a contradiction rather than a
    # preference: the buyer paid once, for access that then stops.
    cfg = product_config()
    if (str(cfg.get("purchaseMode") or "").strip().lower() == "one_time"
            and cfg.get("periodDays") is not None):
        drift.append("A4T_LICENCE_DAYS")
    return drift


def _flag_on(name):
    """A switch an operator set, in any of the spellings they might set it in.

    `health._flag_on` has always accepted 1/true/yes/on and this module
    accepted only the literal "true". So `A4T_CHECKOUT_ENABLED=1` made
    /readyz report billing as enabled while the pricing page said it was
    off — two parts of one product disagreeing about whether it is selling,
    which is the worst possible thing to be unsure about.

    Permissive on spelling, not on intent: anything that is not one of these
    is still off.
    """
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def checkout_enabled():
    """First checkout gate. Off unless explicitly enabled."""
    return _flag_on("A4T_CHECKOUT_ENABLED")


def authenticated_checkout_enabled():
    """Second gate: checkout creation must be behind verified platform auth."""
    return _flag_on("A4T_AUTHENTICATED_CHECKOUT_ENABLED")


def checkout_implemented():
    """Whether this process can send a buyer to Stripe.

    The creator is ``stripe_checkout``. It stays false until either
    ``A4T_STRIPE_PAYMENT_LINK`` is a Stripe Payment Link, or
    ``STRIPE_SECRET_KEY``, ``A4T_STRIPE_PRICE_ID`` and
    ``A4T_PUBLIC_WEB_ORIGIN`` are all set. There is no default URL and no
    default key.

    THIS STAYS FALSE WHEN NOTHING IS SET, ON PURPOSE.

    With both checkout flags on and a webhook secret set, /readyz used to
    report billing ready while ``POST billing/checkout`` answered 501. A
    flag is intent. This function is whether a buyer can actually be sent
    somewhere. Unset configuration is still "not implemented" for this
    deployment, so the pricing page keeps "Not on sale yet" and readiness
    still fails a deploy that has been told to sell and cannot.
    """
    from apex.platform import stripe_checkout as _stripe
    return _stripe.purchase_ready()


def public_offer():
    """Safe offer metadata for UI/API responses. Carries no provider secret."""
    cfg = product_config()
    return {
        "sku": cfg["sku"],
        "plan": cfg["plan"],
        "purchaseMode": cfg["purchaseMode"],
        "priceMinor": cfg["priceMinor"],
        "currency": cfg["currency"],
        "periodDays": cfg["periodDays"],
        "checkoutEnabled": checkout_enabled()
                            and authenticated_checkout_enabled(),
        # A fact, not a flag. False until a checkout creator exists, so a
        # deployment with the flags on still cannot be described as selling.
        "checkoutImplemented": checkout_implemented(),
    }


def verify_signature(payload: bytes, sig_header: str, secret: str, *, now=None) -> bool:
    """True only for a body this secret actually signed, recently.

    EVERY `v1` is compared, not the last one. While a signing secret is being
    rolled Stripe sends one `v1` per active secret, in no promised order, and
    a dict of the header kept only the last: a delivery signed with the secret
    this server holds was refused whenever the other signature came last.
    Exactly one `t` is required.
    """
    if not secret or not sig_header:
        return False
    ts_values, v1s = [], []
    for part in str(sig_header).split(","):
        name, sep, value = part.strip().partition("=")
        if not sep:
            continue
        if name == "t":
            ts_values.append(value.strip())
        elif name == "v1" and value.strip():
            v1s.append(value.strip())
    if len(ts_values) != 1 or not ts_values[0] or not v1s:
        return False
    ts = ts_values[0]
    try:
        age = abs((time.time() if now is None else now) - int(ts))
    except ValueError:
        return False
    if age > SIG_TOLERANCE_SEC:
        return False
    expected = hmac.new(secret.encode(),
                        f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    # compare_digest, not ==: a timing difference on a signature comparison is
    # a signature oracle. Every candidate is compared, so the time taken does
    # not depend on WHICH one matched.
    matched = False
    for v1 in v1s:
        # Bytes, because compare_digest raises on a non-ASCII str.
        if hmac.compare_digest(expected.encode(), v1.encode("utf-8")):
            matched = True
    return matched


def _event_key(event_id):
    return f"{_store._ns()}:{_store._P}:billing:evt:{event_id}"


# Used only when the shared claim cannot be asked (no Redis, or it errored).
# Two webhook threads in one process must not both grant the same event.
# "busy" means another thread in this process is still handling it: the
# provider should retry, not be told the work is finished.
_fallback_lock = threading.Lock()
_fallback_inflight = set()
BUSY = "busy"


def _foreign_product(obj):
    """True when the event names a product this platform does not sell.

    The live Stripe account still delivers the legacy site's
    `checkout.session.completed` events. Those sessions set
    `metadata.product` to a legacy catalogue key such as `apex-forex` and
    do not set `a4tUserId`. Pointing a second endpoint at this handler
    delivers those events even while platform checkout is off. A present
    product that is not the approved sku is not granted and does not revoke,
    including when the object also names a platform user.

    This platform's own Checkout Session does not set `metadata.product`,
    so a missing product is not treated as foreign.
    """
    meta = obj.get("metadata") if isinstance(obj, dict) else None
    if not isinstance(meta, dict):
        return False
    named = str(meta.get("product") or meta.get("sku") or "").strip()
    if not named:
        return False
    return named not in (APPROVED_SKU, APPROVED_PLAN)


# The lease is how long a dead worker blocks a replacement. It is not the
# proof that the grant happened. Ownership is a random token. Releasing and
# publishing compare that token, so an expired worker cannot delete the
# replacement's lease. Sixty seconds is only the recovery bound.
_LEASE_S = 60
_tls = threading.local()


class _LostLease(RuntimeError):
    """This worker no longer owns the lease it was going to publish."""


def _push_token(kind, key, token):
    box = getattr(_tls, kind, None)
    if box is None:
        box = {}
        setattr(_tls, kind, box)
    box.setdefault(key, []).append(token)


def _take_token(kind, key):
    box = getattr(_tls, kind, None) or {}
    stack = box.get(key) or []
    if not stack:
        return None
    return stack.pop()


_event_local_owner = {}


def _refund_state(ref):
    """'yes' when this payment was refunded or disputed, 'no' when not,
    'unknown' when the store could not say.
    """
    try:
        rec = _store._read_strict(_k_refunded(ref))
    except Exception:
        return "unknown"
    return "yes" if rec else "no"


def _outcome_of(key):
    """'done' when a durable outcome is stored, 'open' when it is not,
    'unknown' when the store could not be asked or the record is unreadable.

    A lease written by SET NX is the string ``1``. That is not an outcome.
    """
    try:
        rec = _store._read_strict(key)
    except Exception:
        return "unknown"
    if isinstance(rec, dict) and rec.get("outcome"):
        return "done"
    return "open"


def _event_lease(event_id):
    return _event_key(event_id) + ":lease"


def _already_done(event_id):
    """True when this event has a durable outcome. False when THIS call owns
    the lease and the caller must continue. `BUSY` when another owner holds
    it. `'unknown'` when the store could not say.

    The lease value is this call's token, not ``1``. After the lease is
    acquired the outcome is read again. A worker that saw "open" before
    another worker finished must not continue once the record exists.
    """
    key = _event_key(event_id)
    lease = _event_lease(event_id)
    if user_store._USE_REDIS:
        state = _outcome_of(key)
        if state == "unknown":
            return "unknown"
        if state == "done":
            return True
        token = uuid.uuid4().hex
        got = user_store.claim_value(lease, token, ttl_s=_LEASE_S)
        if got is None:
            return "unknown"
        if got is False:
            again = _outcome_of(key)
            if again == "done":
                return True
            if again == "unknown":
                return "unknown"
            return BUSY
        again = _outcome_of(key)
        if again == "done":
            user_store.release_claim(lease, token)
            return True
        if again == "unknown":
            user_store.release_claim(lease, token)
            return "unknown"
        _push_token("event", event_id, token)
        return False
    with _fallback_lock:
        if event_id in _fallback_inflight:
            return BUSY
        state = _outcome_of(key)
        if state == "done":
            return True
        if state == "unknown":
            return "unknown"
        token = uuid.uuid4().hex
        _fallback_inflight.add(event_id)
        _event_local_owner[event_id] = token
        _push_token("event", event_id, token)
        return False


def _mark_done(event_id, outcome, token):
    """Publish the outcome only while `token` still owns the event lease."""
    payload = {"at": time.time(), "outcome": outcome}
    if not token:
        raise _LostLease("this delivery does not own the event lease")
    if user_store._USE_REDIS:
        ok = user_store.publish_if_owner(
            _event_lease(event_id), token, _event_key(event_id),
            json.dumps(payload, separators=(",", ":")))
        if ok is None:
            raise user_store.StoreUnavailable("the event outcome was not stored")
        if ok is False:
            raise _LostLease("the event lease was no longer ours")
        return
    with _fallback_lock:
        if _event_local_owner.get(event_id) != token:
            raise _LostLease("the event lease was no longer ours")
        _store._write(_event_key(event_id), payload)
        _event_local_owner.pop(event_id, None)
        _fallback_inflight.discard(event_id)


def _release(event_id, token):
    """Give this worker's event lease back. Does not delete another owner's."""
    if not token:
        return
    if user_store._USE_REDIS:
        try:
            user_store.release_claim(_event_lease(event_id), token)
        except Exception:
            pass
        return
    with _fallback_lock:
        if _event_local_owner.get(event_id) == token:
            _event_local_owner.pop(event_id, None)
            _fallback_inflight.discard(event_id)


def _k_intent(user_id):
    """Who this server sent to the Payment Link, and with which address."""
    return f"{_store._ns()}:{_store._P}:billing:intent:{user_id}"


def _k_review(event_id):
    return f"{_store._ns()}:{_store._P}:billing:review:{event_id}"


def record_link_intent(user_id, email, *, now=None, acknowledged_at=None):
    """Note that THIS server sent `user_id` to the Payment Link.

    Called by `stripe_checkout.start_checkout` from an authenticated session.
    The webhook later requires it, plus a matching e-mail, before trusting a
    bare `client_reference_id` (see `_trusted_user_of`). Raises when the write
    did not land, so a checkout is never started that could only end in a
    manual review.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("a user id is required")
    rec = {"userId": uid, "email": str(email or "").strip().lower(),
           "at": time.time() if now is None else now}
    if acknowledged_at is not None:
        rec["acknowledgedTrialAt"] = acknowledged_at
    _store._write_strict(_k_intent(uid), rec)


def _session_email(obj):
    details = obj.get("customer_details") or {}
    mail = details.get("email") if isinstance(details, dict) else None
    return str(mail or obj.get("customer_email") or "").strip().lower()


def _platform_user_candidate(value):
    """A platform user id, or None.

    Digit-only values are Telegram chat ids from the legacy checkout. They
    are not platform users. Empty and oversized values are not either.
    """
    text = str(value or "").strip()
    if not text or text.isdigit():
        return None
    if not _PLATFORM_USER_ID.match(text):
        return None
    return text


def _trusted_user_of(obj):
    """(user_id, None) when the grant may go ahead, (claimed, why) otherwise.

    `metadata.a4tUserId` is written by this server on a Checkout Session and
    the payer cannot edit it: trusted. A Payment Link carries only
    `client_reference_id`, which rides in the URL and the BUYER CAN EDIT —
    taken alone it would let anyone attach their payment to another account,
    or route a stolen-card purchase to a victim. So it is believed only when
    this server recorded sending that user to the link AND the e-mail Stripe
    collected matches the one that user signed in with. Anything else is held
    for a person to look at, never granted.
    """
    meta = obj.get("metadata") or {}
    meta_user = _platform_user_candidate(meta.get(USER_META_KEY))
    if meta_user:
        return meta_user, None
    claimed = _platform_user_candidate(obj.get("client_reference_id"))
    if not claimed:
        return None, None
    intent = _store._read_strict(_k_intent(claimed))
    if not isinstance(intent, dict) or str(intent.get("userId")) != claimed:
        return claimed, "no checkout was started for this account"
    want, got = str(intent.get("email") or ""), _session_email(obj)
    if not want or not got:
        return claimed, "no e-mail to cross-check the account against"
    if not hmac.compare_digest(want.encode(), got.encode()):
        return claimed, "the payer's e-mail does not match the account"
    return claimed, None


def _hold_for_review(event_id, etype, claimed, ref, why):
    _store._write(_k_review(event_id), {
        "eventId": event_id, "type": etype, "claimedUserId": claimed,
        "paymentRef": ref, "reason": why, "at": time.time()})
    print(f"[Billing] HELD {event_id} for manual review "
          f"(payment={ref or 'unknown'}): {why}")


def _user_id_of(obj):
    """The Supabase user id this payment belongs to.

    Read only from metadata this server wrote at checkout, or from
    client_reference_id which the same code sets. Never from an email, and
    never from a field the payer controls: matching on an address would let
    anyone who knows a client's email buy them a licence, or worse, claim one.
    """
    meta = obj.get("metadata") or {}
    return (_platform_user_candidate(meta.get(USER_META_KEY))
            or _platform_user_candidate(obj.get("client_reference_id")))


def _paid(obj, event_type):
    """Whether this object represents money actually taken.

    `checkout.session.completed` is not enough. A delayed method fires it
    with `payment_status` unpaid, and the money arrives later as
    `checkout.session.async_payment_succeeded`. Both grant only when the
    session says paid. An unpaid async event does not grant either.
    """
    if event_type in ("checkout.session.completed",
                      "checkout.session.async_payment_succeeded"):
        return obj.get("payment_status") == "paid"
    if event_type == "payment_intent.succeeded":
        return obj.get("status") == "succeeded"
    if event_type == "invoice.payment_succeeded":
        return (obj.get("status") or "paid") == "paid"
    return False


def _payment_ref(obj):
    """The id a later refund or chargeback can be matched back to.

    The PaymentIntent, because it is the one id that appears on all of the
    shapes involved: the Checkout Session carries it, the PaymentIntent IS
    it, and both the Charge and the Dispute that a refund or chargeback
    arrives as carry it too. The session id does not appear on a Charge at
    all, which is why matching on metadata alone could never work for a
    reversal.
    """
    for k in ("payment_intent", "id"):
        v = obj.get(k)
        if isinstance(v, str) and v.startswith("pi_"):
            return v
    return ""


def _k_refunded(ref):
    """Payment id → that it was refunded or disputed (a tombstone)."""
    return f"{_store._ns()}:{_store._P}:billing:refunded:{ref}"


def _k_ref(ref):
    """Payment id → the platform user it granted to."""
    return f"{_store._ns()}:{_store._P}:billing:ref:{ref}"


def _k_once(ref):
    """Payment id → the durable fact that a grant for it finished.

    This key is written only after the licence write returns. It is not
    the in-flight lease.
    """
    return f"{_store._ns()}:{_store._P}:billing:once:{ref}"


def _k_once_lease(ref):
    """Payment id → the token of the worker currently granting it.

    The value is that worker's token. It is not a completed grant, and it
    is not a shared ``1`` that any worker may delete.
    """
    return f"{_store._ns()}:{_store._P}:billing:once-lease:{ref}"


_once_owner = {}


def _release_owned(lease_key, token, local_key=None):
    """Drop this token's lease. A token that lost the lease deletes nothing."""
    if not token:
        return
    if user_store._USE_REDIS:
        try:
            user_store.release_claim(lease_key, token)
        except Exception:
            pass
        return
    with _fallback_lock:
        if local_key is not None and _once_owner.get(local_key) == token:
            _once_owner.pop(local_key, None)


def _claim_payment(ref):
    """'go' when this caller may grant `ref`. 'done' when a durable grant
    record exists. 'refunded' when the payment was already reversed.
    `BUSY` when another token holds the lease. `'unknown'` when the store
    could not be asked.

    The done record is read again after this caller acquires the lease.
    Seeing "open" and then acquiring is not enough: another worker can
    finish in between those two steps.
    """
    if not ref:
        return "go"
    record = _k_once(ref)
    lease = _k_once_lease(ref)
    if user_store._USE_REDIS:
        state = _outcome_of(record)
        if state == "unknown":
            return "unknown"
        if state == "done":
            return "done"
        token = uuid.uuid4().hex
        got = user_store.claim_value(lease, token, ttl_s=_LEASE_S)
        if got is None:
            return "unknown"
        if got is False:
            again = _outcome_of(record)
            if again == "done":
                return "done"
            if again == "unknown":
                return "unknown"
            return BUSY
        again = _outcome_of(record)
        refunded = _refund_state(ref)
        if again == "done" or refunded == "yes":
            _release_owned(lease, token)
            return "done" if again == "done" else "refunded"
        if again == "unknown" or refunded == "unknown":
            _release_owned(lease, token)
            return "unknown"
        _push_token("payment", ref, token)
        return "go"
    with _fallback_lock:
        if ref in _once_owner:
            return BUSY
        state = _outcome_of(record)
        if state == "done":
            return "done"
        if state == "unknown":
            return "unknown"
        refunded = _refund_state(ref)
        if refunded == "yes":
            return "refunded"
        if refunded == "unknown":
            return "unknown"
        token = uuid.uuid4().hex
        _once_owner[ref] = token
        _push_token("payment", ref, token)
        return "go"


def _finish_payment(ref, token):
    """Publish the grant only if `token` still owns the lease.

    The licence write has already returned. Losing the lease here does not
    delete the replacement's lease and does not count as a finished grant.
    A later delivery can grant again only when no refund tombstone exists;
    that second write is the same active licence, not a revival of a
    revoked one.
    """
    if not ref:
        return
    payload = json.dumps({"at": time.time(), "outcome": "granted"},
                         separators=(",", ":"))
    if user_store._USE_REDIS:
        ok = user_store.publish_if_owner(_k_once_lease(ref), token, _k_once(ref), payload)
        if ok is None:
            raise user_store.StoreUnavailable("the payment grant was not stored")
        if ok is False:
            raise _LostLease("the payment lease was no longer ours")
        return
    with _fallback_lock:
        if _once_owner.get(ref) != token:
            raise _LostLease("the payment lease was no longer ours")
        _store._write(_k_once(ref), {"at": time.time(), "outcome": "granted"})
        _once_owner.pop(ref, None)


def _release_payment(ref, token):
    """Drop this token's payment lease. Does not remove a durable grant."""
    if not ref:
        return
    _release_owned(_k_once_lease(ref), token, ref)


# Test hook. A stalled worker pauses here, before the fenced write, so a
# replacement can grant and a refund can withdraw. Production leaves it unset.
_before_fenced_grant = None


def _dumps(doc):
    return json.dumps(doc, separators=(",", ":"))


def _fenced_grant(ref, token, user_id, plan, expires_at, obj, lifetime):
    """Write the licence, and the paid record when this charge is the offer.

    Returns 'granted', 'lost', 'refunded', or 'unknown'. A lost lease or a
    refund tombstone writes nothing. The check and the writes are one step
    on the shared store, and one lock on the local store.
    """
    if _before_fenced_grant is not None:
        _before_fenced_grant(ref, token)
    from apex.platform import live_gate as _lg
    now = time.time()
    licence = {"state": _lic.ACTIVE, "plan": plan, "expiresAt": expires_at,
               "maskedKey": None, "grantedAt": now}
    if ref:
        licence["paymentRef"] = str(ref)
    pairs = [(_lic._key(user_id), _dumps(licence))]
    if ref:
        pairs.append((_k_ref(ref), _dumps({"userId": str(user_id), "at": now})))
        pairs.append((_k_once(ref), _dumps({"at": now, "outcome": "granted"})))
    if (lifetime and ref
            and explicit_offer_charge(obj, _lg.PRICE_MINOR, _lg.CURRENCY)):
        paid = {
            "confirmed": True,
            "priceMinor": _lg.PRICE_MINOR,
            "currency": _lg.CURRENCY,
            "term": _lg.TERM,
            "source": "payment",
            "recordedAt": now,
            "actor": "system:billing",
            "paymentRef": str(ref),
        }
        pairs.append((_lg._key(f"paid:{user_id}"), _dumps(paid)))
    if user_store._USE_REDIS:
        code = user_store.apply_if_lease(
            _k_once_lease(ref), token, _k_refunded(ref), pairs)
        if code is None:
            return "unknown"
        if code == 0:
            return "lost"
        if code == 2:
            return "refunded"
        return "granted"
    with _fallback_lock:
        if ref and _once_owner.get(ref) != token:
            return "lost"
        refunded = _refund_state(ref) if ref else "no"
        if refunded == "yes":
            return "refunded"
        if refunded == "unknown":
            return "unknown"
        for key, raw in pairs:
            _store._write(key, json.loads(raw))
        if ref:
            _once_owner.pop(ref, None)
        return "granted"


def _fenced_reverse(ref, user_id, event_id, etype):
    """Tombstone, withdraw the licence, and delete the paid record together.

    The tombstone is written in the same step as the withdrawal, so a grant
    that still holds an old lease sees it and does not put the licence back.
    """
    now = time.time()
    current = _lic._read(user_id) or {}
    current["state"] = _lic.REVOKED
    current["revokedAt"] = now
    tomb = {"userId": str(user_id), "eventId": event_id,
            "type": etype, "at": now}
    from apex.platform import live_gate as _lg
    paid_key = _lg._key(f"paid:{user_id}")
    if user_store._USE_REDIS:
        ok = user_store.commit_reversal(
            _k_refunded(ref), _dumps(tomb),
            _lic._key(user_id), _dumps(current),
            paid_key)
        if not ok:
            raise user_store.StoreUnavailable("the reversal was not stored")
        return
    with _fallback_lock:
        _store._write(_k_refunded(ref), tomb)
        _store._write(_lic._key(user_id), current)
        _store._delete(paid_key)


def _amount_matches(obj, cfg):
    """(ok, detail) — did this payment charge the approved price?

    NOTHING COMPARED THE MONEY TAKEN AGAINST THE OFFER. `_paid` asked only
    whether a payment completed, so any Payment Link on the same provider
    account — a discounted one, a coupon, a cheaper product — granted a full
    Founder licence. `offer_drift` does not close this: it watches whether
    environment variables moved the PRICE WE DISPLAY off the approved one,
    and says nothing about what was actually charged.

    An object that carries no amount is NOT treated as a mismatch. Which
    field holds the total differs by shape and some carry none at all, and
    refusing a legitimate payment because this function did not recognise
    its shape would be worse than the hole it closes. It says so instead, so
    the refusal-or-not decision stays with the caller and the log records
    which it was.
    """
    want_minor, want_ccy = int(cfg["priceMinor"]), str(cfg["currency"]).lower()
    got = None
    for k in ("amount_total", "amount_received", "amount_paid", "amount"):
        v = obj.get(k)
        if isinstance(v, (int, float)):
            got = int(v)
            break
    ccy = str(obj.get("currency") or "").strip().lower()
    if got is None:
        return True, "no amount on this object; not compared"
    # TAX IS NOT A DISCOUNT. A price set "tax exclusive" with tax collection on
    # charges the offer PLUS the tax, so the total is above the approved
    # amount for a buyer in a taxed place. That payment is the full price and
    # must not be held as an overcharge. `total_details.amount_tax` is what
    # the provider says the tax was; the offer is met when the total is the
    # offer, or when the total less that tax is the offer (exclusive pricing).
    # A discount still fails: it lowers the total below the offer, and
    # subtracting tax only lowers it further. A total ABOVE the offer with no
    # declared tax still fails, as before.
    details = obj.get("total_details")
    tax = details.get("amount_tax") if isinstance(details, dict) else None
    tax = int(tax) if (isinstance(tax, (int, float)) and not isinstance(tax, bool)
                       and tax > 0) else 0
    if got != want_minor and not (tax and got - tax == want_minor):
        return False, f"charged {got}, the approved offer is {want_minor}"
    if ccy and ccy != want_ccy:
        return False, f"charged in {ccy}, the approved offer is {want_ccy}"
    return True, ""


def explicit_offer_charge(obj, want_minor=None, want_ccy=None):
    """True only when the object itself states an amount AND a currency and they
    meet the approved offer, tax-aware (the offer, or the offer plus declared
    tax). Unlike `_amount_matches`, an object that states nothing is NOT a
    match: this is the check for writing the live paid record.
    """
    if not isinstance(obj, dict):
        return False
    want_minor = APPROVED_PRICE_MINOR if want_minor is None else want_minor
    want_ccy = APPROVED_CURRENCY if want_ccy is None else want_ccy
    got = None
    for k in ("amount_total", "amount_received", "amount_paid", "amount"):
        v = obj.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            got = int(v)
            break
    ccy = str(obj.get("currency") or "").strip().lower()
    if got is None or not ccy or ccy != want_ccy:
        return False
    details = obj.get("total_details")
    tax = details.get("amount_tax") if isinstance(details, dict) else None
    tax = int(tax) if (isinstance(tax, (int, float)) and not isinstance(tax, bool)
                       and tax > 0) else 0
    return got == want_minor or bool(tax and got - tax == want_minor)


def _fully_refunded(obj):
    """Whether a Charge was refunded in FULL.

    `charge.refunded` fires for a partial refund as well, and the handler
    revoked everything either way — taking away access the client has still
    paid for, over a goodwill refund of part of it.

    A Charge with no amounts on it is treated as a full refund. That is the
    cautious direction for this question: the provider said the charge was
    refunded, and withdrawing an entitlement that should have stayed is
    recoverable by granting it again, while leaving one in place that should
    have gone is money.
    """
    amount = obj.get("amount")
    refunded = obj.get("amount_refunded")
    if not isinstance(amount, (int, float)) or \
            not isinstance(refunded, (int, float)):
        return True
    return int(refunded) >= int(amount)


def _livemode_ok(event):
    """Refuse a test-mode payment in production, and say nothing otherwise.

    The failure this closes: a test-mode webhook secret left configured on
    the production service. Every $0 test purchase would then mint a real
    founder licence, and every check in the product would be green.

    Only asserted in production. Outside it both modes are legitimate and
    insisting would break every staging deployment.
    """
    if (os.getenv("APP_ENV") or "").strip().lower() not in ("production", "prod"):
        return True, ""
    if event.get("livemode") is False:
        return False, "a test-mode event reached the production endpoint"
    return True, ""


def handle_event(raw_body: bytes, sig_header: str, *, secret=None, now=None):
    """(status, payload) for a webhook delivery.

    Never raises for a bad request: the provider retries on a 5xx, so a
    malformed or unsigned body must be a 4xx and stay one.
    """
    secret = secret or webhook_secret()
    if not secret:
        # 503, not 200. Retries are wanted once the secret is configured.
        return 503, {"ok": False, "error": {
            "code": "BILLING_NOT_CONFIGURED",
            "message": "no webhook secret is configured, so no delivery can be verified"}}

    if not verify_signature(raw_body or b"", sig_header or "", secret, now=now):
        return 400, {"ok": False, "error": {
            "code": "BAD_SIGNATURE",
            "message": "the signature does not match this body"}}

    try:
        event = json.loads((raw_body or b"").decode("utf-8"))
    except Exception:
        return 400, {"ok": False, "error": {
            "code": "BAD_BODY", "message": "the body is not valid JSON"}}
    if not isinstance(event, dict):
        return 400, {"ok": False, "error": {
            "code": "BAD_BODY", "message": "the body must be a JSON object"}}

    event_id = str(event.get("id") or "")
    etype = str(event.get("type") or "")
    obj = ((event.get("data") or {}).get("object")) or {}
    if not event_id:
        return 400, {"ok": False, "error": {
            "code": "BAD_BODY", "message": "the event has no id"}}

    if etype not in GRANTING and etype not in REVOKING:
        # Acknowledged so the provider stops retrying something we do not act
        # on. Recorded as ignored rather than as handled.
        return 200, {"ok": True, "handled": False, "type": etype}

    done = _already_done(event_id)
    event_token = _take_token("event", event_id) if done is False else None
    if done is False and not event_token:
        return 500, {"ok": False, "error": {
            "code": "BILLING_FAILED", "message": "StoreUnavailable"}}
    if done == "unknown":
        return 500, {"ok": False, "error": {
            "code": "BILLING_FAILED", "message": "StoreUnavailable"}}
    if done == BUSY:
        # Not marked done. The provider retries after the in-flight delivery
        # finishes, instead of being told this event was already applied.
        return 500, {"ok": False, "error": {
            "code": "BILLING_FAILED",
            "message": "this delivery is already being handled"}}
    if done:
        # A duplicate is a success: the provider retried, the work is done.
        return 200, {"ok": True, "duplicate": True, "type": etype}

    if _foreign_product(obj):
        # A legacy payment on the same Stripe account. Do not grant it, and
        # do not revoke from it. The object may still carry metadata.a4tUserId;
        # that name does not make the payment one this platform sold.
        _mark_done(event_id, "foreign-product", event_token)
        return 200, {"ok": True, "handled": False,
                     "reason": "this payment is not the Apex4Traders offer"}

    ref = _payment_ref(obj)
    claimed = _user_id_of(obj)
    user_id = claimed
    # A Charge and a Dispute belong to a payment, not to whoever is named in
    # metadata. metadata.a4tUserId is trusted for a Checkout Session this
    # server created. On a reversal it used to skip the payment index and
    # revoke that named account even when the payment was a different one.
    if etype in ("charge.refunded", "charge.dispute.created"):
        owner = None
        if ref:
            try:
                _rec = _store._read_strict(_k_ref(ref))
                owner = str((_rec or {}).get("userId") or "") or None
            except Exception as e:                           # noqa: BLE001
                print(f"[Billing] could not resolve payment {ref} to a user: "
                      f"{type(e).__name__}")
                _release(event_id, event_token)
                return 500, {"ok": False, "error": {
                    "code": "BILLING_FAILED", "message": "StoreUnavailable"}}
        user_id = owner
    elif not user_id and ref:
        # A reversal other than a Charge or Dispute (a deleted subscription,
        # a failed invoice) may not carry the account. The grant wrote the
        # payment id for this lookup. A Charge or Dispute never reaches
        # here: those two revoke only the account stored for that payment.
        try:
            # STRICT: a store that did not answer must not look like "no such
            # payment". The old non-strict read returned None on an outage,
            # the event was marked done as "no platform user", and a refund
            # never withdrew the licence. Strict raises, the handler answers
            # 500 and the provider retries.
            _rec = _store._read_strict(_k_ref(ref))
            user_id = str((_rec or {}).get("userId") or "") or None
        except Exception as e:                               # noqa: BLE001
            print(f"[Billing] could not resolve payment {ref} to a user: "
                  f"{type(e).__name__}")
            _release(event_id, event_token)
            return 500, {"ok": False, "error": {
                "code": "BILLING_FAILED", "message": "StoreUnavailable"}}

    if not user_id:
        # Marked done so the provider stops retrying, and LOGGED, because
        # money was taken and nobody is being provisioned for it. This file
        # used to print nothing at all, from any branch.
        print(f"[Billing] {etype} {event_id} carries no platform user "
              f"(payment={ref or 'unknown'}) — nothing granted or revoked")
        if etype in REVOKING:
            # Money moved back and nobody was matched to it. A person has to
            # look; quietly marking it done would leave the licence in place.
            try:
                _hold_for_review(event_id, etype, None, ref,
                                 "a refund or dispute could not be matched to "
                                 "a platform user")
            except Exception as e:                           # noqa: BLE001
                print(f"[Billing] could not record the held reversal "
                      f"({type(e).__name__})")
                _release(event_id, event_token)
                return 500, {"ok": False, "error": {
                    "code": "BILLING_FAILED", "message": "StoreUnavailable"}}
        _mark_done(event_id, "no-user", event_token)
        return 200, {"ok": True, "handled": False, "reason": "no platform user on this payment"}

    notice = None
    payment_claimed = False
    pay_token = None
    try:
        if etype in GRANTING:
            if not _paid(obj, etype):
                _mark_done(event_id, "not-paid", event_token)
                return 200, {"ok": True, "handled": False, "reason": "payment not completed"}
            trusted, why_untrusted = _trusted_user_of(obj)
            if why_untrusted or trusted != user_id:
                # Recorded, not granted, and not retried: the payment is real
                # and a person has to decide whose it is.
                _hold_for_review(event_id, etype, user_id, ref,
                                 why_untrusted or "user id mismatch")
                _mark_done(event_id, "manual-review", event_token)
                return 200, {"ok": True, "handled": False,
                             "reason": "held for manual review"}
            if ref:
                # A grant that arrives AFTER the refund of the same payment
                # (an out-of-order or retried delivery) would give the licence
                # back. Strict read: unknown is a retry, not a grant.
                if _store._read_strict(_k_refunded(ref)):
                    _hold_for_review(event_id, etype, user_id, ref,
                                     "this payment was already refunded or "
                                     "disputed")
                    _mark_done(event_id, "refunded-before-grant", event_token)
                    return 200, {"ok": True, "handled": False,
                                 "reason": "this payment was already refunded"}
            cfg = product_config()
            ok_live, why_live = _livemode_ok(event)
            if not ok_live:
                print(f"[Billing] REFUSED {event_id}: {why_live}")
                _mark_done(event_id, "livemode-mismatch", event_token)
                return 200, {"ok": True, "handled": False,
                             "reason": "this payment is not for this environment"}
            ok_amt, why_amt = _amount_matches(obj, cfg)
            if not ok_amt:
                # Not an error to retry: the payment is real and is for
                # something other than the approved offer. Granting the full
                # plan for it would be the product giving itself away.
                print(f"[Billing] REFUSED {event_id} for {user_id}: {why_amt}")
                _mark_done(event_id, "amount-mismatch", event_token)
                return 200, {"ok": True, "handled": False,
                             "reason": "this payment does not match the "
                                       "approved offer"}
            expires = None
            if cfg["periodDays"]:
                expires = (time.time() if now is None else now) + cfg["periodDays"] * 86400
            gate = _claim_payment(ref)
            pay_token = _take_token("payment", ref) if gate == "go" else None
            if gate == "unknown" or (gate == "go" and ref and not pay_token):
                _release(event_id, event_token)
                return 500, {"ok": False, "error": {
                    "code": "BILLING_FAILED", "message": "StoreUnavailable"}}
            if gate == BUSY:
                _release(event_id, event_token)
                return 500, {"ok": False, "error": {
                    "code": "BILLING_FAILED",
                    "message": "this payment is already being granted"}}
            if gate == "done":
                _mark_done(event_id, "already-granted", event_token)
                return 200, {"ok": True, "duplicate": True, "type": etype,
                             "reason": "this payment was already granted"}
            if gate == "refunded":
                _hold_for_review(event_id, etype, user_id, ref,
                                 "this payment was already refunded or "
                                 "disputed")
                _mark_done(event_id, "refunded-before-grant", event_token)
                return 200, {"ok": True, "handled": False,
                             "reason": "this payment was already refunded"}
            payment_claimed = bool(ref)
            from apex.platform import live_gate as _live_gate
            lifetime = (not cfg.get("periodDays")
                        and str(cfg.get("purchaseMode") or "").lower()
                        == "one_time")
            if ref:
                # The licence, the paid record, the payment index, and the
                # durable grant share the lease and the refund tombstone.
                # A worker whose lease expired writes none of them.
                result = _fenced_grant(
                    ref, pay_token, user_id, cfg["plan"], expires, obj, lifetime)
                if result == "unknown":
                    raise user_store.StoreUnavailable("the grant was not stored")
                if result == "lost":
                    payment_claimed = False
                    raise _LostLease("the payment lease was no longer ours")
                if result == "refunded":
                    _release_payment(ref, pay_token)
                    payment_claimed = False
                    _hold_for_review(event_id, etype, user_id, ref,
                                     "this payment was already refunded or "
                                     "disputed")
                    _mark_done(event_id, "refunded-before-grant", event_token)
                    return 200, {"ok": True, "handled": False,
                                 "reason": "this payment was already refunded"}
                payment_claimed = False
                if lifetime and explicit_offer_charge(
                        obj, _live_gate.PRICE_MINOR, _live_gate.CURRENCY):
                    _live_gate._audit_best_effort(
                        lambda audit: audit.record_entitlement_change(
                            user_id=str(user_id), actor="system:billing",
                            field="paid_licence", old_value=None,
                            new_value="lifetime", reason="confirmed payment"))
            else:
                _lic.grant(user_id, plan=cfg["plan"], expires_at=expires,
                           masked_key=None, now=now, payment_ref=ref)
                _live_gate.note_confirmed_payment(
                    user_id, obj, payment_ref=ref, lifetime=lifetime)
            notice = ("Licence activated", _notify.INFO,
                      "Your payment was confirmed and your licence is active.")
            outcome = "granted"
        else:
            if etype == "charge.refunded" and not _fully_refunded(obj):
                # `charge.refunded` fires on PARTIAL refunds too, and
                # revoking everything for a partial one takes away access
                # the client has still paid for.
                print(f"[Billing] {event_id}: partial refund on {ref} for "
                      f"{user_id} — licence left in place")
                _mark_done(event_id, "partial-refund", event_token)
                return 200, {"ok": True, "handled": False,
                             "reason": "a partial refund does not withdraw "
                                       "the licence"}
            if ref:
                # Tombstone and withdrawal together. A stale grant then sees
                # the tombstone and does not restore the licence or the paid
                # record. Revoke does not stop a loop that is already running.
                _fenced_reverse(ref, user_id, event_id, etype)
            else:
                _lic.revoke(user_id)
                from apex.platform import live_gate as _live_gate
                _live_gate.clear_paid_licence(user_id)
            notice = ("Licence suspended", _notify.CRITICAL,
                      "A payment was refunded, disputed or failed, so "
                      "the licence on this account was suspended.")
            outcome = "revoked"
    except Exception as e:
        # The claim must not outlive a delivery that failed, or the retry is
        # refused as a duplicate and the buyer is never provisioned.
        print(f"[Billing] {etype} {event_id} FAILED for {user_id}: "
              f"{type(e).__name__}: {e}")
        if payment_claimed:
            _release_payment(ref, pay_token)
        _release(event_id, event_token)
        return 500, {"ok": False, "error": {
            "code": "BILLING_FAILED", "message": f"{type(e).__name__}"}}

    # THE NOTIFICATION IS SENT AFTER THE WORK IS RECORDED, AND OUTSIDE THE
    # TRY, because a failure to notify is not a failure to provision.
    #
    # It used to sit beside the grant inside that block. A notification store
    # having a bad moment therefore answered 500 for a payment that had
    # already been granted — so the provider retried a delivery that had
    # worked, and a provider that keeps getting 500s disables the endpoint.
    # The buyer has their licence either way; what they would lose is the
    # message saying so.
    _mark_done(event_id, outcome, event_token)
    if notice:
        try:
            _notify.notify(user_id, type="system", title=notice[0],
                           level=notice[1], body=notice[2])
        except Exception as e:                               # noqa: BLE001
            print(f"[Billing] {outcome} for {user_id} but the notification "
                  f"could not be delivered ({type(e).__name__})")
    return 200, {"ok": True, "handled": True, "type": etype, "outcome": outcome}
