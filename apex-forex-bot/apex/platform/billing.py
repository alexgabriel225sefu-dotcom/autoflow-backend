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

WHAT IS NOT DECIDED HERE

Price, currency, SKU and plan shape are read from the environment with no
defaults. A default price is a business decision taken by whoever wrote the
code, which is the wrong person. See docs/PAYMENT_AND_LICENCE_DECISIONS.md.
"""

import hashlib
import hmac
import json
import os
import time

from apex import user_store
from apex.platform import licence as _lic
from apex.platform import notifications as _notify
from apex.platform import store as _store

# Stripe signs `t=<unix>,v1=<hex>`. Deliveries outside this window are refused
# so a captured body cannot be replayed later.
SIG_TOLERANCE_SEC = 300

# Events that grant. Both shapes are accepted because which one arrives
# depends on whether checkout is a Session or a PaymentIntent, and that is a
# decision the owner has not made yet.
GRANTING = ("checkout.session.completed", "payment_intent.succeeded",
            "invoice.payment_succeeded")
# Events that take the entitlement away.
REVOKING = ("charge.refunded", "charge.dispute.created",
            "customer.subscription.deleted", "invoice.payment_failed")

# The metadata key this server writes when it creates a checkout. The webhook
# reads the user id from here and from nowhere else.
USER_META_KEY = "a4tUserId"


class BillingNotConfigured(RuntimeError):
    """Raised when the webhook is reachable but no secret is set.

    Answered as a refusal rather than a silent 200: a webhook that accepts
    everything while unconfigured is worse than one that is switched off,
    because Stripe stops retrying and the operator never learns.
    """


def _env(name):
    v = (os.getenv(name) or "").strip()
    return v or None


def configured():
    """Whether a signed webhook can be verified at all."""
    return bool(_env("A4T_STRIPE_WEBHOOK_SECRET"))


def product_config():
    """Price, currency and SKU — from the environment, with no defaults.

    Returns None for anything the owner has not set. Callers must refuse
    rather than substitute: `29700` and `"apex-bot"` describe the previous
    product, and guessing either of them would put a number on an invoice that
    nobody approved.
    """
    minor = _env("A4T_PRICE_MINOR")
    try:
        minor = int(minor) if minor is not None else None
    except ValueError:
        minor = None
    return {
        "priceMinor": minor,
        "currency": _env("A4T_CURRENCY"),
        "sku": _env("A4T_SKU"),
        "plan": _env("A4T_PLAN") or "standard",
        # How long a granted licence lasts. Unset means no expiry, which is
        # correct for a one-off purchase and wrong for a subscription — which
        # is why the plan shape is an owner decision, not a default.
        "periodDays": int(_env("A4T_LICENCE_DAYS") or 0) or None,
    }


def verify_signature(payload: bytes, sig_header: str, secret: str, *, now=None) -> bool:
    """True only for a body this secret actually signed, recently."""
    if not secret or not sig_header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    except ValueError:
        return False
    ts, v1 = parts.get("t"), parts.get("v1")
    if not ts or not v1:
        return False
    try:
        age = abs((time.time() if now is None else now) - int(ts))
    except ValueError:
        return False
    if age > SIG_TOLERANCE_SEC:
        return False
    expected = hmac.new(secret.encode(),
                        f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    # compare_digest, not ==: a timing difference on a signature comparison is
    # a signature oracle.
    return hmac.compare_digest(expected, v1)


def _event_key(event_id):
    return f"{_store._ns()}:{_store._P}:billing:evt:{event_id}"


def _already_done(event_id):
    """True when this event has been processed. None when we cannot tell.

    Two mechanisms, because they fail differently. `user_store.claim` is a
    cross-process SET NX and is the only one that is correct when more than
    one instance is running; it returns None when there is no shared backend.
    The record read is the fallback, and it is honest about being a read
    followed by a write rather than an atomic operation.
    """
    got = user_store.claim(_event_key(event_id), ttl_s=86400)
    if got is True:
        return False
    if got is False:
        return True
    rec = _store._read(_event_key(event_id))
    return bool(rec)


def _mark_done(event_id, outcome):
    _store._write(_event_key(event_id), {"at": time.time(), "outcome": outcome})


def _release(event_id):
    """Give the claim back after a delivery that did not complete.

    Without this the two defences deadlock: the claim says "handled" while no
    licence was written, so every retry is answered "duplicate" and a buyer who
    has paid is never provisioned.
    """
    try:
        user_store.set_blob(_event_key(event_id), "", ttl_s=1)
    except Exception:
        pass


def _user_id_of(obj):
    """The Supabase user id this payment belongs to.

    Read only from metadata this server wrote at checkout, or from
    client_reference_id which the same code sets. Never from an email, and
    never from a field the payer controls: matching on an address would let
    anyone who knows a client's email buy them a licence, or worse, claim one.
    """
    meta = obj.get("metadata") or {}
    uid = meta.get(USER_META_KEY) or obj.get("client_reference_id")
    return str(uid) if uid else None


def _paid(obj, event_type):
    """Whether this object represents money actually taken."""
    if event_type == "checkout.session.completed":
        return obj.get("payment_status") == "paid"
    if event_type == "payment_intent.succeeded":
        return obj.get("status") == "succeeded"
    if event_type == "invoice.payment_succeeded":
        return (obj.get("status") or "paid") == "paid"
    return False


def handle_event(raw_body: bytes, sig_header: str, *, secret=None, now=None):
    """(status, payload) for a webhook delivery.

    Never raises for a bad request: the provider retries on a 5xx, so a
    malformed or unsigned body must be a 4xx and stay one.
    """
    secret = secret or _env("A4T_STRIPE_WEBHOOK_SECRET")
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

    if _already_done(event_id):
        # A duplicate is a success: the provider retried, the work is done.
        return 200, {"ok": True, "duplicate": True, "type": etype}

    user_id = _user_id_of(obj)
    if not user_id:
        _mark_done(event_id, "no-user")
        return 200, {"ok": True, "handled": False, "reason": "no platform user on this payment"}

    try:
        if etype in GRANTING:
            if not _paid(obj, etype):
                _mark_done(event_id, "not-paid")
                return 200, {"ok": True, "handled": False, "reason": "payment not completed"}
            cfg = product_config()
            expires = None
            if cfg["periodDays"]:
                expires = (time.time() if now is None else now) + cfg["periodDays"] * 86400
            _lic.grant(user_id, plan=cfg["plan"], expires_at=expires,
                       masked_key=None, now=now)
            _notify.notify(user_id, type="system", level=_notify.INFO,
                           title="Licence activated",
                           body="Your payment was confirmed and your licence is active.")
            outcome = "granted"
        else:
            _lic.revoke(user_id)
            _notify.notify(user_id, type="system", level=_notify.CRITICAL,
                           title="Licence suspended",
                           body="A payment was refunded, disputed or failed, so "
                                "the licence on this account was suspended.")
            outcome = "revoked"
    except Exception as e:
        # The claim must not outlive a delivery that failed, or the retry is
        # refused as a duplicate and the buyer is never provisioned.
        _release(event_id)
        return 500, {"ok": False, "error": {
            "code": "BILLING_FAILED", "message": f"{type(e).__name__}"}}

    _mark_done(event_id, outcome)
    return 200, {"ok": True, "handled": True, "type": etype, "outcome": outcome}
