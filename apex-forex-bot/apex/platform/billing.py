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


def _k_ref(ref):
    """Payment id → the platform user it granted to."""
    return f"{_store._ns()}:{_store._P}:billing:ref:{ref}"


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
    if got != want_minor:
        return False, f"charged {got}, the approved offer is {want_minor}"
    if ccy and ccy != want_ccy:
        return False, f"charged in {ccy}, the approved offer is {want_ccy}"
    return True, ""


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
    if (os.getenv("APP_ENV") or "").strip().lower() != "production":
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

    if _already_done(event_id):
        # A duplicate is a success: the provider retried, the work is done.
        return 200, {"ok": True, "duplicate": True, "type": etype}

    ref = _payment_ref(obj)
    user_id = _user_id_of(obj)
    if not user_id and ref:
        # A REFUND OR CHARGEBACK ARRIVES ON AN OBJECT THAT CARRIES NEITHER
        # THE METADATA NOR THE REFERENCE WE WROTE AT CHECKOUT.
        #
        # `charge.refunded` is a Charge and `charge.dispute.created` is a
        # Dispute. Neither has `client_reference_id`, and a Dispute carries
        # no metadata of ours at all. So every reversal resolved to "no
        # platform user", was marked done, and the client kept the licence
        # they had been refunded for. The billing tests did not catch it
        # because they built those events as a metadata dict, which the
        # provider never sends.
        #
        # So the grant writes down which payment it was for, and a reversal
        # is matched through that. The PaymentIntent id is the one id all
        # four shapes share.
        try:
            _rec = _store._read(_k_ref(ref))
            user_id = str((_rec or {}).get("userId") or "") or None
        except Exception as e:                               # noqa: BLE001
            print(f"[Billing] could not resolve payment {ref} to a user: "
                  f"{type(e).__name__}")
            _release(event_id)
            return 500, {"ok": False, "error": {
                "code": "BILLING_FAILED", "message": "StoreUnavailable"}}

    if not user_id:
        # Marked done so the provider stops retrying, and LOGGED, because
        # money was taken and nobody is being provisioned for it. This file
        # used to print nothing at all, from any branch.
        print(f"[Billing] {etype} {event_id} carries no platform user "
              f"(payment={ref or 'unknown'}) — nothing granted or revoked")
        _mark_done(event_id, "no-user")
        return 200, {"ok": True, "handled": False, "reason": "no platform user on this payment"}

    notice = None
    try:
        if etype in GRANTING:
            if not _paid(obj, etype):
                _mark_done(event_id, "not-paid")
                return 200, {"ok": True, "handled": False, "reason": "payment not completed"}
            cfg = product_config()
            ok_live, why_live = _livemode_ok(event)
            if not ok_live:
                print(f"[Billing] REFUSED {event_id}: {why_live}")
                _mark_done(event_id, "livemode-mismatch")
                return 200, {"ok": True, "handled": False,
                             "reason": "this payment is not for this environment"}
            ok_amt, why_amt = _amount_matches(obj, cfg)
            if not ok_amt:
                # Not an error to retry: the payment is real and is for
                # something other than the approved offer. Granting the full
                # plan for it would be the product giving itself away.
                print(f"[Billing] REFUSED {event_id} for {user_id}: {why_amt}")
                _mark_done(event_id, "amount-mismatch")
                return 200, {"ok": True, "handled": False,
                             "reason": "this payment does not match the "
                                       "approved offer"}
            expires = None
            if cfg["periodDays"]:
                expires = (time.time() if now is None else now) + cfg["periodDays"] * 86400
            _lic.grant(user_id, plan=cfg["plan"], expires_at=expires,
                       masked_key=None, now=now, payment_ref=ref)
            # The founder plan and the live paid record are different facts.
            # A missing amount still grants the plan (see _amount_matches)
            # and does not write the paid record. A failed write raises, so
            # the provider retries.
            from apex.platform import live_gate as _live_gate
            lifetime = (not cfg.get("periodDays")
                        and str(cfg.get("purchaseMode") or "").lower()
                        == "one_time")
            _live_gate.note_confirmed_payment(
                user_id, obj, payment_ref=ref, lifetime=lifetime)
            if ref:
                # Best effort, and deliberately NOT strict: the licence is
                # written and the buyer is provisioned. Failing the delivery
                # here would make the provider retry a grant that already
                # worked. A missing reverse index costs a manual lookup on a
                # refund; a retried grant costs the buyer their entitlement
                # when the retry races the first one.
                try:
                    _store._write(_k_ref(ref), {"userId": str(user_id),
                                                "at": time.time()})
                except Exception as e:                       # noqa: BLE001
                    print(f"[Billing] granted {user_id} but could not index "
                          f"payment {ref} ({type(e).__name__}) — a refund on "
                          f"it will need a manual lookup")
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
                _mark_done(event_id, "partial-refund")
                return 200, {"ok": True, "handled": False,
                             "reason": "a partial refund does not withdraw "
                                       "the licence"}
            _lic.revoke(user_id)
            # The paid record has to go with the licence. Revoke does not
            # stop a loop that is already running; that is a separate gap.
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
        _release(event_id)
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
    _mark_done(event_id, outcome)
    if notice:
        try:
            _notify.notify(user_id, type="system", title=notice[0],
                           level=notice[1], body=notice[2])
        except Exception as e:                               # noqa: BLE001
            print(f"[Billing] {outcome} for {user_id} but the notification "
                  f"could not be delivered ({type(e).__name__})")
    return 200, {"ok": True, "handled": True, "type": etype, "outcome": outcome}
