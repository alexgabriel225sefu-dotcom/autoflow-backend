"""A payment that arrives must provision, or refuse — never silently neither.

Written before checkout is turned on, from a review of the whole path. None
of this has ever run against the real provider; what it pins is the
behaviour that decides whether a $497 payment reaches the buyer.

THE FOUR FAILURES, WORST FIRST

1. A FAILED LICENCE WRITE ANSWERED 200 "GRANTED".
   `licence.grant` used `store._write`, which discards the result of the
   underlying SET — and `_redis_set` returns False on an Upstash 429 or a
   Redis outage rather than raising. `user_store`'s own docstring says
   callers throwing that result away made "a Redis outage look exactly like
   a successful save". So the grant could fail completely, the handler
   returned 200, the provider recorded delivery as successful and never
   retried, and the buyer was left with no licence and no trace. Their
   trial then ran out and locked them out of what they had paid for.

2. A REFUND OR CHARGEBACK REVOKED NOTHING.
   The user id was read only from `metadata.a4tUserId` or
   `client_reference_id`. A real `charge.refunded` is a Charge and a real
   `charge.dispute.created` is a Dispute: neither carries
   `client_reference_id`, and a Dispute carries none of our metadata at all.
   Every reversal resolved to "no platform user", was marked done, and the
   client kept the licence they had been refunded for. The existing tests
   missed it by building those events as a metadata dict, which the provider
   never sends — a harness that cannot detect a positive proves nothing.

3. NOTHING COMPARED THE MONEY TAKEN AGAINST THE OFFER.
   `_paid` asked only whether a payment completed, so any cheaper Payment
   Link, coupon or product on the same provider account granted a full
   Founder licence. `offer_drift` does not cover this: it watches the price
   we DISPLAY, not what was charged.

4. A FAILED NOTIFICATION UNDID A SUCCESSFUL GRANT.
   `notify` sat inside the same try as the grant, so a notification store
   having a bad moment answered 500 for a payment already provisioned. The
   provider then retried a delivery that had worked, and a provider that
   keeps getting 500s disables the endpoint.

Run: python3 tests/test_billing_integrity.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-billint-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
SECRET = "whsec_test_not_a_real_secret"
os.environ["A4T_STRIPE_WEBHOOK_SECRET"] = SECRET

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import billing as B                      # noqa: E402
from apex.platform import licence as LIC                    # noqa: E402
from apex.platform import store as PS                       # noqa: E402

USER = "eeeeeeee-5555-4555-8555-eeeeeeeeeeee"
PI = "pi_3TestPaymentIntent001"
_n = [0]


def deliver(event):
    """Sign a body the way the provider does and hand it to the handler."""
    raw = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + raw,
                   hashlib.sha256).hexdigest()
    return B.handle_event(raw, f"t={ts},v1={sig}", secret=SECRET)


def session(**over):
    """A paid Checkout Session, the shape the provider actually sends."""
    _n[0] += 1
    obj = {"id": f"cs_test_{_n[0]}", "object": "checkout_session",
           "payment_status": "paid", "payment_intent": PI,
           "amount_total": B.APPROVED_PRICE_MINOR,
           "currency": B.APPROVED_CURRENCY,
           "metadata": {B.USER_META_KEY: USER}}
    obj.update(over.pop("obj", {}))
    ev = {"id": f"evt_{_n[0]}", "type": "checkout.session.completed",
          "livemode": True, "data": {"object": obj}}
    ev.update(over)
    return ev


# ── 1. a licence write that does not land must NOT answer 200 granted ───────
print("\n[1] a failed licence write is not reported as a grant")
_real_set = PS.user_store.set_blob
_real_use = PS.user_store._USE_REDIS


def _refusing_set(key, value, ttl_s=None):
    """What an Upstash 429 looks like: False, not an exception."""
    return False


PS.user_store._USE_REDIS = True
PS.user_store.set_blob = _refusing_set
try:
    st, payload = deliver(session())
    check("the delivery is a 5xx, so the provider retries", st >= 500,
          f"{st} {payload}")
    check("and it is not reported as granted",
          (payload or {}).get("outcome") != "granted", str(payload))
finally:
    PS.user_store.set_blob = _real_set
    PS.user_store._USE_REDIS = _real_use

print("\n[2] and the retry then provisions the buyer")
# The claim must not outlive a failed delivery, or every retry is answered
# "duplicate" and the buyer is never provisioned.
st, payload = deliver(session())
check("a clean delivery grants", st == 200
      and (payload or {}).get("outcome") == "granted", f"{st} {payload}")
check("the licence is actually readable afterwards",
      LIC.status_for(USER)["state"] == LIC.ACTIVE,
      str(LIC.status_for(USER)))
check("on the approved plan",
      LIC.status_for(USER)["plan"] == B.APPROVED_PLAN,
      str(LIC.status_for(USER)["plan"]))


# ── 3. a refund in the shape the provider really sends ──────────────────────
print("\n[3] a refund revokes, with the object the provider actually sends")
# A Charge. No client_reference_id, no metadata of ours — which is exactly
# why the old handler did nothing and the old test passed.
refund = {"id": "evt_refund_1", "type": "charge.refunded", "livemode": True,
          "data": {"object": {"id": "ch_test_1", "object": "charge",
                              "payment_intent": PI,
                              "amount": B.APPROVED_PRICE_MINOR,
                              "amount_refunded": B.APPROVED_PRICE_MINOR,
                              "metadata": {}}}}
st, payload = deliver(refund)
check("it is handled", st == 200 and (payload or {}).get("handled") is True,
      f"{st} {payload}")
check("and the licence is withdrawn",
      LIC.status_for(USER)["state"] == LIC.REVOKED,
      str(LIC.status_for(USER)))

print("\n[4] a chargeback does too — a Dispute carries no metadata at all")
LIC.grant(USER, plan=B.APPROVED_PLAN, payment_ref=PI)
dispute = {"id": "evt_dispute_1", "type": "charge.dispute.created",
           "livemode": True,
           "data": {"object": {"id": "dp_test_1", "object": "dispute",
                               "charge": "ch_test_1", "payment_intent": PI}}}
st, payload = deliver(dispute)
check("it is handled", st == 200 and (payload or {}).get("handled") is True,
      f"{st} {payload}")
check("and the licence is withdrawn",
      LIC.status_for(USER)["state"] == LIC.REVOKED,
      str(LIC.status_for(USER)))

print("\n[5] a PARTIAL refund does not take the whole licence away")
# `charge.refunded` fires on partial refunds too, and revoking everything
# for one takes away access the client has still paid for.
LIC.grant(USER, plan=B.APPROVED_PLAN, payment_ref=PI)
partial = {"id": "evt_refund_partial", "type": "charge.refunded",
           "livemode": True,
           "data": {"object": {"id": "ch_test_2", "object": "charge",
                               "payment_intent": PI,
                               "amount": B.APPROVED_PRICE_MINOR,
                               "amount_refunded": 5000, "metadata": {}}}}
st, payload = deliver(partial)
check("it is acknowledged rather than retried", st == 200, str(st))
check("the licence survives", LIC.status_for(USER)["state"] == LIC.ACTIVE,
      str(LIC.status_for(USER)))
check("and the answer says why", "partial" in json.dumps(payload).lower(),
      str(payload))


# ── 6. the money taken must match the offer ─────────────────────────────────
print("\n[6] a payment for a different amount does not grant the plan")
LIC.revoke(USER)
cheap = session(obj={"amount_total": 100})
cheap["id"] = "evt_cheap_1"
st, payload = deliver(cheap)
check("it is acknowledged, not retried forever", st == 200, str(st))
check("and nothing is granted",
      (payload or {}).get("handled") is False, str(payload))
check("the licence stays withdrawn",
      LIC.status_for(USER)["state"] == LIC.REVOKED,
      str(LIC.status_for(USER)))

print("\n[7] and nor does one in a different currency")
wrong_ccy = session(obj={"currency": "eur"})
wrong_ccy["id"] = "evt_eur_1"
st, payload = deliver(wrong_ccy)
check("nothing is granted", (payload or {}).get("handled") is False,
      str(payload))

print("\n[8] an object with no amount is still granted, not refused")
# Which field holds the total differs by shape and some carry none. Refusing
# a legitimate payment because this code did not recognise its shape would
# be worse than the hole being closed.
LIC.revoke(USER)
noamt = session()
noamt["id"] = "evt_noamount_1"
noamt["data"]["object"].pop("amount_total")
noamt["data"]["object"].pop("currency")
st, payload = deliver(noamt)
check("it grants", (payload or {}).get("outcome") == "granted", str(payload))


# ── 9. a notification failure must not undo a grant ─────────────────────────
print("\n[9] a grant survives a notification store that is down")
LIC.revoke(USER)
_real_notify = B._notify.notify
B._notify.notify = lambda *a, **kw: (_ for _ in ()).throw(
    RuntimeError("the notification store is down"))
try:
    ok_ev = session()
    ok_ev["id"] = "evt_notify_down_1"
    st, payload = deliver(ok_ev)
    check("the delivery is a 200, so the provider does not retry", st == 200,
          f"{st} {payload}")
    check("and it reports the grant", (payload or {}).get("outcome")
          == "granted", str(payload))
    check("and the licence really is active",
          LIC.status_for(USER)["state"] == LIC.ACTIVE,
          str(LIC.status_for(USER)))
finally:
    B._notify.notify = _real_notify


# ── 10. a test-mode event must not mint a real licence in production ────────
print("\n[10] a test-mode payment is refused in production")
_env = os.environ.get("APP_ENV")
os.environ["APP_ENV"] = "production"
try:
    LIC.revoke(USER)
    test_ev = session(livemode=False)
    test_ev["id"] = "evt_testmode_1"
    st, payload = deliver(test_ev)
    check("nothing is granted", (payload or {}).get("handled") is False,
          str(payload))
    check("the licence stays withdrawn",
          LIC.status_for(USER)["state"] == LIC.REVOKED,
          str(LIC.status_for(USER)))
finally:
    if _env is None:
        os.environ.pop("APP_ENV", None)
    else:
        os.environ["APP_ENV"] = _env


# ── 11. readiness must not claim a checkout that cannot be created ──────────
print("\n[11] the flags cannot make a dead end look ready")
check("this build cannot create a checkout", B.checkout_implemented() is False,
      "if this is now True, the checkout creator exists and /readyz should "
      "say ok — see tests/test_platform_health.py")
_prev = os.environ.get("A4T_CHECKOUT_ENABLED")
os.environ["A4T_CHECKOUT_ENABLED"] = "1"
try:
    check("A4T_CHECKOUT_ENABLED=1 is on, as /readyz has always read it",
          B.checkout_enabled() is True,
          "health._flag_on accepted 1/true/yes/on and this module accepted "
          "only 'true', so one half of the product thought it was selling")
finally:
    if _prev is None:
        os.environ.pop("A4T_CHECKOUT_ENABLED", None)
    else:
        os.environ["A4T_CHECKOUT_ENABLED"] = _prev

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All billing-integrity checks passed.")
