"""A legacy checkout on the same Stripe account must not grant a platform licence.

The live account still has one endpoint, on the legacy host. If a second
endpoint is later pointed at this handler, Stripe delivers the existing
account's events here too, including while platform checkout is off.
`metadata.product` on those sessions is a legacy catalogue key. This
platform's own session does not set that field.

No network. No secret from the environment. The signing secret below is
synthetic.

Run: python3 tests/test_platform_foreign_checkout.py
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
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-foreign-")
os.environ["ALLOW_PLAINTEXT_DEV_STORAGE"] = "true"
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_STRIPE_WEBHOOK_SECRET", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

from apex.platform import api as API                                 # noqa: E402
from apex.platform import billing as B                               # noqa: E402
from apex.platform import licence as LIC                             # noqa: E402
from apex import user_store                                          # noqa: E402

_fails = []
SECRET = "whsec_synthetic_foreign_checkout"
USER = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


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


def session(eid, **obj):
    body = {
        "id": "cs_legacy",
        "object": "checkout.session",
        "payment_status": "paid",
        "payment_intent": "pi_legacy_1",
        "amount_total": B.APPROVED_PRICE_MINOR,
        "currency": "usd",
        "metadata": {"product": "apex-forex", "ref": "ad"},
        "client_reference_id": USER,
    }
    body.update(obj)
    return {"id": eid, "type": "checkout.session.completed", "livemode": True,
            "data": {"object": body}}


print("\n[1] a legacy product does not grant, even with a platform user id")
st, out = deliver(session("evt_legacy_1", metadata={
    "product": "apex-forex", B.USER_META_KEY: USER}))
check("acknowledged", st == 200, str(st))
check("not granted", out.get("handled") is False and out.get("outcome") != "granted",
      str(out))
check("licence untouched", LIC.status_for(USER)["state"] == LIC.NONE,
      str(LIC.status_for(USER)))

print("\n[2] the same legacy event again is a duplicate, still not a grant")
st, out = deliver(session("evt_legacy_1", metadata={
    "product": "apex-forex", B.USER_META_KEY: USER}))
check("duplicate", out.get("duplicate") is True, str(out))
check("still no licence", LIC.status_for(USER)["state"] == LIC.NONE)

print("\n[3] our own session, which sets no product, still grants")
ours = session("evt_ours_1", metadata={B.USER_META_KEY: USER},
               payment_intent="pi_ours_1")
ours["data"]["object"].pop("client_reference_id", None)
st, out = deliver(ours)
check("granted", st == 200 and out.get("outcome") == "granted", str(out))
check("licence active", LIC.status_for(USER)["state"] == LIC.ACTIVE)

print("\n[4] a legacy refund does not revoke that licence")
LIC.grant(USER, plan=B.APPROVED_PLAN, payment_ref="pi_ours_1")
refund = {"id": "evt_legacy_refund", "type": "charge.refunded", "livemode": True,
          "data": {"object": {
              "object": "charge", "payment_intent": "pi_legacy_1",
              "amount": 29700, "amount_refunded": 29700,
              "metadata": {"product": "apex-forex"}}}}
st, out = deliver(refund)
check("legacy refund is not a platform revoke",
      LIC.status_for(USER)["state"] == LIC.ACTIVE, str(LIC.status_for(USER)))

print("\n[5] two threads without a shared claim cannot both grant")
user_store.claim = lambda *a, **k: None
barrier = threading.Barrier(2)
results = []

def hit():
    barrier.wait()
    results.append(deliver(session(
        "evt_race_1", metadata={B.USER_META_KEY: USER},
        payment_intent="pi_race_1")))

LIC.revoke(USER)
threads = [threading.Thread(target=hit), threading.Thread(target=hit)]
for t in threads:
    t.start()
for t in threads:
    t.join()
codes = sorted(st for st, _out in results)
check("one delivery is refused as in flight", 500 in codes, str(results))
check("the other applies", any(out.get("outcome") == "granted" for _st, out in results),
      str(results))
st, out = deliver(session("evt_race_1", metadata={B.USER_META_KEY: USER},
                          payment_intent="pi_race_1"))
check("the retry is a duplicate", out.get("duplicate") is True, str(out))
check("still one active licence", LIC.status_for(USER)["state"] == LIC.ACTIVE)

print("\n[6] a Telegram chat id is not a platform user")
CHAT = "47765456"
LIC.grant(USER, plan=B.APPROVED_PLAN, payment_ref="pi_keep_1")
legacy_user = session(
    "evt_tg_1",
    metadata={},
    client_reference_id=CHAT,
    payment_intent="pi_tg_1",
    amount_total=B.APPROVED_PRICE_MINOR,
    currency="usd",
    payment_status="paid",
)
st, out = deliver(legacy_user)
check("not granted from a chat id", out.get("outcome") != "granted", str(out))
check("no licence under the chat id", LIC.status_for(CHAT)["state"] == LIC.NONE,
      str(LIC.status_for(CHAT)))
check("the real platform licence stays", LIC.status_for(USER)["state"] == LIC.ACTIVE)
refund_tg = {"id": "evt_tg_refund", "type": "charge.refunded", "livemode": True,
             "data": {"object": {
                 "object": "charge", "client_reference_id": CHAT,
                 "payment_intent": "pi_not_ours",
                 "amount": B.APPROVED_PRICE_MINOR,
                 "amount_refunded": B.APPROVED_PRICE_MINOR}}}
st, out = deliver(refund_tg)
check("a chat id on a refund does not revoke the platform user",
      LIC.status_for(USER)["state"] == LIC.ACTIVE, str(LIC.status_for(USER)))

print("\n[7] GET 404 is the method, POST is the handler")
st, out = API.handle("GET", "/api/v1/billing/webhook", {}, b"{}")
check("GET is 404", st == 404, str(st))
body = json.dumps({"id": "evt_post_shape", "type": "checkout.session.completed"}).encode()
st, out = API.handle("POST", "/api/v1/billing/webhook",
                     {"Stripe-Signature": "t=1,v1=00"}, body)
check("POST without a valid signature is refused, not 404",
      st in (400, 503) and st != 404, str(st))

print("\n[8] handler route and secret names, no values")
check("webhook secret names",
      "A4T_STRIPE_WEBHOOK_SECRET" in B.webhook_secret.__doc__
      and "STRIPE_WEBHOOK_SECRET" in B.webhook_secret.__doc__)
check("granting events include checkout, refund and dispute are revoking",
      "checkout.session.completed" in B.GRANTING
      and "charge.refunded" in B.REVOKING
      and "charge.dispute.created" in B.REVOKING)

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
