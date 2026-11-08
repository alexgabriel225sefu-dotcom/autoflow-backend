"""Delayed Checkout payments grant once, and only when the session is paid.

`checkout.session.completed` fires before a bank debit settles, with
`payment_status` unpaid. The money arrives later as
`checkout.session.async_payment_succeeded`. Those are two event ids for one
payment. A card is paid on the first event and the second does not fire.

No network. No secret from the environment. The signing secret below is
synthetic. This is not a provider-signed delivery.

Run: python3 tests/test_platform_async_payment.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-async-")
os.environ["ALLOW_PLAINTEXT_DEV_STORAGE"] = "true"
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_STRIPE_WEBHOOK_SECRET", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

from apex.platform import billing as B                               # noqa: E402
from apex.platform import licence as LIC                             # noqa: E402
from apex import user_store                                          # noqa: E402

_fails = []
SECRET = "whsec_synthetic_async_payment"
USER = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
OTHER = "cccccccc-3333-4333-8333-cccccccccccc"
PI = "pi_async_1"


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


def sign(raw):
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def deliver(event):
    raw = json.dumps(event).encode()
    return B.handle_event(raw, sign(raw), secret=SECRET)


def session(eid, etype, **obj):
    body = {
        "id": "cs_async_1",
        "object": "checkout.session",
        "payment_status": "paid",
        "payment_intent": PI,
        "amount_total": B.APPROVED_PRICE_MINOR,
        "currency": "usd",
        "metadata": {B.USER_META_KEY: USER},
    }
    body.update(obj)
    return {"id": eid, "type": etype, "livemode": True, "data": {"object": body}}


grants = []
_real_fenced = B._fenced_grant


def counting_fenced(*args, **kwargs):
    result = _real_fenced(*args, **kwargs)
    if result == "granted":
        grants.append(args[0] if args else kwargs.get("ref"))
    return result


B._fenced_grant = counting_fenced

print("\n[1] an unpaid completed session does not grant")
st, out = deliver(session(
    "evt_completed_unpaid", "checkout.session.completed", payment_status="unpaid"))
check("acknowledged", st == 200 and out.get("handled") is False, str(out))
check("not granted", out.get("outcome") != "granted" and not grants)
check("no licence", LIC.status_for(USER)["state"] == LIC.NONE)

print("\n[2] the later paid async event grants that same payment")
st, out = deliver(session(
    "evt_async_paid", "checkout.session.async_payment_succeeded"))
check("granted", st == 200 and out.get("outcome") == "granted", str(out))
check("one grant", grants == [PI], str(grants))
check("licence active", LIC.status_for(USER)["state"] == LIC.ACTIVE)

print("\n[3] a paid completed event for that payment does not grant again")
st, out = deliver(session(
    "evt_completed_paid_later", "checkout.session.completed"))
check("duplicate payment", st == 200 and out.get("duplicate") is True, str(out))
check("still one grant", grants == [PI], str(grants))
check("still active", LIC.status_for(USER)["state"] == LIC.ACTIVE)

print("\n[4] the async event again is an event duplicate")
st, out = deliver(session(
    "evt_async_paid", "checkout.session.async_payment_succeeded"))
check("event duplicate", out.get("duplicate") is True, str(out))
check("still one grant after the replay", grants == [PI], str(grants))

print("\n[5] async fulfillment still refuses an unpaid, foreign, or chat id")
LIC.revoke(USER)
grants.clear()
st, out = deliver(session(
    "evt_async_unpaid", "checkout.session.async_payment_succeeded",
    payment_status="unpaid", payment_intent="pi_async_unpaid"))
check("unpaid async does not grant",
      out.get("outcome") != "granted" and LIC.status_for(USER)["state"] != LIC.ACTIVE,
      str(out))
st, out = deliver(session(
    "evt_async_foreign", "checkout.session.async_payment_succeeded",
    payment_intent="pi_async_foreign",
    metadata={"product": "apex-forex", B.USER_META_KEY: USER}))
check("foreign async does not grant",
      out.get("handled") is False and out.get("outcome") != "granted", str(out))
check("foreign async left no licence", LIC.status_for(USER)["state"] != LIC.ACTIVE)
st, out = deliver(session(
    "evt_async_chat", "checkout.session.async_payment_succeeded",
    payment_intent="pi_async_chat", metadata={}, client_reference_id="47765456"))
check("a chat id is not a platform user",
      out.get("outcome") != "granted" and LIC.status_for("47765456")["state"] == LIC.NONE,
      str(out))
check("none of those granted", grants == [], str(grants))

print("\n[6] a paid async event grants, and the reversal events still match it")
st, out = deliver(session(
    "evt_async_own", "checkout.session.async_payment_succeeded",
    payment_intent="pi_async_own"))
check("own async grants", out.get("outcome") == "granted", str(out))
foreign_refund = {
    "id": "evt_async_foreign_refund", "type": "charge.refunded", "livemode": True,
    "data": {"object": {
        "object": "charge", "payment_intent": "pi_not_async_own",
        "amount": 29700, "amount_refunded": 29700,
        "metadata": {"product": "apex-forex", B.USER_META_KEY: USER}}}}
st, out = deliver(foreign_refund)
check("foreign refund does not revoke it",
      out.get("outcome") != "revoked" and LIC.status_for(USER)["state"] == LIC.ACTIVE,
      str(out))
refund = {
    "id": "evt_async_refund", "type": "charge.refunded", "livemode": True,
    "data": {"object": {
        "object": "charge", "payment_intent": "pi_async_own",
        "amount": B.APPROVED_PRICE_MINOR,
        "amount_refunded": B.APPROVED_PRICE_MINOR, "metadata": {}}}}
st, out = deliver(refund)
check("the indexed refund revokes", out.get("outcome") == "revoked", str(out))
st, out = deliver(refund)
check("the refund again is a duplicate", out.get("duplicate") is True, str(out))
LIC.grant(USER, plan=B.APPROVED_PLAN, payment_ref="pi_async_dispute")
from apex.platform import store as ST
ST._write(B._k_ref("pi_async_dispute"), {"userId": USER, "at": time.time()})
dispute = {
    "id": "evt_async_dispute", "type": "charge.dispute.created", "livemode": True,
    "data": {"object": {"object": "dispute", "payment_intent": "pi_async_dispute"}}}
st, out = deliver(dispute)
check("the indexed dispute revokes", out.get("outcome") == "revoked", str(out))

print("\n[7] completed and async for a new payment cannot both grant")
LIC.revoke(OTHER)
grants.clear()
user_store.claim = lambda *a, **k: None
first_inside = threading.Event()
release_first = threading.Event()
real_claim = B._claim_payment


def held_claim(ref):
    result = real_claim(ref)
    if result == "go" and ref == "pi_async_race":
        first_inside.set()
        release_first.wait(5)
    return result


B._claim_payment = held_claim
results = []


def hit(eid, etype):
    results.append(deliver(session(
        eid, etype, metadata={B.USER_META_KEY: OTHER}, payment_intent="pi_async_race")))


first = threading.Thread(target=hit, args=("evt_race_completed", "checkout.session.completed"))
second = threading.Thread(
    target=hit, args=("evt_race_async", "checkout.session.async_payment_succeeded"))
try:
    first.start()
    entered = first_inside.wait(5)
    check("the first grant is held", entered)
    second.start()
    second.join(5)
    check("the other event is refused while the grant is in flight",
          len(results) == 1 and results[0][0] == 500, str(results))
    check("nothing granted while it is held",
          LIC.status_for(OTHER)["state"] != LIC.ACTIVE and grants == [])
finally:
    release_first.set()
    first.join(5)
    B._claim_payment = real_claim
check("the held event grants",
      any(out.get("outcome") == "granted" for _st, out in results), str(results))
check("one grant for the raced payment", grants == ["pi_async_race"], str(grants))
st, out = deliver(session(
    "evt_race_async", "checkout.session.async_payment_succeeded",
    metadata={B.USER_META_KEY: OTHER}, payment_intent="pi_async_race"))
check("the async retry does not grant again",
      out.get("duplicate") is True and grants == ["pi_async_race"], str(out))
check("the other user was not granted", LIC.status_for(USER)["state"] == LIC.REVOKED)
check("one active licence for the payer", LIC.status_for(OTHER)["state"] == LIC.ACTIVE)

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
