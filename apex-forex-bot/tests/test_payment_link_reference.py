"""A Payment Link's client_reference_id is not trusted on its own.

FOUND BY THE SECURITY AUDIT. A Payment Link purchase reaches the webhook with
the user id only in `client_reference_id`, which travels in the URL the buyer
opens and can edit. The webhook granted to whatever id it carried, so a buyer
could attach a payment (a stolen card's, say) to somebody else's account.

WHAT THESE TESTS WILL NOT ACCEPT

* A grant for an id this server never sent to the Payment Link.
* A grant when the e-mail Stripe collected differs from the account's.
* A grant when there is no e-mail to compare.
* An untrusted payment being dropped silently: it is recorded for review.
* The trusted paths breaking: server-written metadata (Checkout Session), and
  a Payment Link with a recorded intent and a matching e-mail.

Run: python3 tests/test_payment_link_reference.py
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
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-plink-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["A4T_STRIPE_PAYMENT_LINK"] = "https://buy.stripe.com/test_link"

from apex.platform import billing as B                       # noqa: E402
from apex.platform import licence as L                       # noqa: E402
from apex.platform import plans as P                         # noqa: E402
from apex.platform import store as S                         # noqa: E402
from apex.platform import stripe_checkout as SC              # noqa: E402

SECRET = "whsec_test_only"
_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def sign(body):
    ts = int(time.time())
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256)
    return f"t={ts},v1={mac.hexdigest()}"


def deliver(obj, eid):
    body = json.dumps({"id": eid, "type": "checkout.session.completed",
                       "data": {"object": obj}}).encode()
    return B.handle_event(body, sign(body), secret=SECRET)


def link_obj(uid, email=None, **extra):
    obj = {"payment_status": "paid", "client_reference_id": uid,
           "amount_total": B.APPROVED_PRICE_MINOR, "currency": "usd",
           "payment_intent": f"pi_{uid}_{time.time_ns()}"}
    if email is not None:
        obj["customer_details"] = {"email": email}
    obj.update(extra)
    return obj


def founder(uid):
    held = L.status_for(uid)
    return held["state"] == L.ACTIVE and P.is_live_plan(held.get("plan"))


class _P:
    def __init__(self, uid, email):
        self.user_id, self.email = uid, email


print("\n[1] an id nobody was sent to the link with is held, not granted")
st, out = deliver(link_obj("victim", "attacker@example.test"), "evt_1")
check("not granted", st == 200 and out.get("handled") is False
      and not founder("victim"), str(out))
review = S._read(f"{S.namespace_prefix()}billing:review:evt_1")
check("recorded for review with the reason", isinstance(review, dict)
      and review.get("claimedUserId") == "victim"
      and "no checkout" in review.get("reason", ""), str(review))

print("\n[2] a recorded intent with a DIFFERENT e-mail is held")
SC.start_checkout(_P("alice", "Alice@Example.test"), {"method": "payment_link"})
st, out = deliver(link_obj("alice", "someone-else@example.test"), "evt_2")
check("not granted", out.get("handled") is False and not founder("alice"),
      str(out))
check("recorded", S._read(f"{S.namespace_prefix()}billing:review:evt_2"))

print("\n[3] a recorded intent with no e-mail on the session is held")
st, out = deliver(link_obj("alice"), "evt_3")
check("not granted", out.get("handled") is False and not founder("alice"),
      str(out))

print("\n[4] a recorded intent with a matching e-mail grants")
st, out = deliver(link_obj("alice", "alice@example.TEST"), "evt_4")
check("granted", out.get("outcome") == "granted" and founder("alice"),
      str(out))

print("\n[5] server-written metadata is still trusted")
obj = {"payment_status": "paid", "metadata": {B.USER_META_KEY: "bob"},
       "client_reference_id": "bob", "amount_total": B.APPROVED_PRICE_MINOR,
       "currency": "usd", "payment_intent": "pi_bob"}
st, out = deliver(obj, "evt_5")
check("granted", out.get("outcome") == "granted" and founder("bob"), str(out))

print("\n[6] when they disagree, the server-written metadata wins")
obj = dict(obj, metadata={B.USER_META_KEY: "carol"},
           client_reference_id="dave", payment_intent="pi_cd")
st, out = deliver(obj, "evt_6")
check("granted to the metadata's user, never the editable one",
      founder("carol") and not founder("dave"), str(out))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All payment-link reference checks passed.")
