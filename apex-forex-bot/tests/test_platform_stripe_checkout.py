"""Stripe checkout stays dark, and a paid 497 USD event grants once.

No network. urllib is replaced with a function that fails the test if
anything calls it. The Payment Link URL in here is the owner's public link,
used as a shape, not as a default.

Run: python3 tests/test_platform_stripe_checkout.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-stripe-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
for _name in (
        "A4T_CHECKOUT_ENABLED", "A4T_AUTHENTICATED_CHECKOUT_ENABLED",
        "A4T_STRIPE_PAYMENT_LINK", "A4T_STRIPE_PRICE_ID", "STRIPE_SECRET_KEY",
        "A4T_PUBLIC_WEB_ORIGIN", "A4T_STRIPE_WEBHOOK_SECRET",
        "STRIPE_WEBHOOK_SECRET", "A4T_LEGAL_PUBLISH"):
    os.environ.pop(_name, None)


def _no_network(*_args, **_kwargs):
    raise AssertionError("Stripe was called over the network")


urllib.request.urlopen = _no_network

from apex.platform import api as A                        # noqa: E402
from apex.platform import billing as B                    # noqa: E402
from apex.platform import licence as L                    # noqa: E402
from apex.platform import live_gate as LG                 # noqa: E402
from apex.platform import plans as P                      # noqa: E402
from apex.platform import store as ST                     # noqa: E402
from apex.platform import stripe_checkout as SC           # noqa: E402

EXAMPLE = "https://buy.stripe.com/bJe9AT0EF2gD99Bcii2Ji02"
USER = "supabase-user-1"
SECRET = "whsec_test_secret"
_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class _Principal:
    def __init__(self, user_id=USER, email="buyer@example.test"):
        self.user_id = user_id
        self.email = email
        self.email_verified = True

    def as_dict(self):
        return {"userId": self.user_id, "email": self.email,
                "emailVerified": True}


A._id.verify_token = lambda tok, **kw: _Principal()


def call(body=None):
    raw = json.dumps(body if body is not None else {}).encode()
    return A.handle("POST", "/api/v1/billing/checkout",
                    {"Authorization": "Bearer x"}, raw)


def sign(body, secret=SECRET):
    ts = int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256)
    return f"t={ts},v1={mac.hexdigest()}"


def event(obj, eid):
    return json.dumps({
        "id": eid, "type": "checkout.session.completed",
        "data": {"object": obj},
    }).encode()


def reset(user_id=USER):
    ST._write(L._key(str(user_id)), {})
    ST._delete(LG._key(f"paid:{user_id}"))


def founder(user_id):
    """A paid founder licence, not the free trial an authenticated read starts."""
    held = L.status_for(user_id)
    return held["state"] == L.ACTIVE and P.is_live_plan(held.get("plan"))


print("\n[1] nothing is configured, so nothing is on sale")
src = open(os.path.join(ROOT, "apex", "platform", "stripe_checkout.py"),
           encoding="utf-8").read()
check("the public payment link is not a default in code",
      "bJe9AT0EF2gD99Bcii2Ji02" not in src)
check("checkout is not implemented", B.checkout_implemented() is False)
check("the offer says so", B.public_offer()["checkoutImplemented"] is False)
for bad in ("", "http://buy.stripe.com/abc", "https://evil.test/abc",
            "https://buy.stripe.com.evil.test/abc",
            "https://user:pass@buy.stripe.com/abc", "javascript:alert(1)"):
    os.environ["A4T_STRIPE_PAYMENT_LINK"] = bad
    check(f"rejects {bad!r}", SC.payment_link_base() is None)
os.environ.pop("A4T_STRIPE_PAYMENT_LINK", None)

print("\n[2] the flag stays the purchase gate")
os.environ["A4T_STRIPE_PAYMENT_LINK"] = EXAMPLE
check("a configured link means a purchase path exists",
      B.checkout_implemented() is True)
st, out = call()
check("without the flag the route still refuses",
      st == 503 and out["error"]["code"] == "CHECKOUT_NOT_ENABLED", str(st))
check("and granted no founder licence", founder(USER) is False,
      str(L.status_for(USER)))

os.environ["A4T_CHECKOUT_ENABLED"] = "true"
os.environ["A4T_AUTHENTICATED_CHECKOUT_ENABLED"] = "true"
st, out = call({
    "userId": "victim-user",
    "email": "victim@example.test",
    "client_reference_id": "victim-user",
})
url = (out or {}).get("url") or ""
check("the signed-in user is sent to the payment link",
      st == 200 and out.get("kind") == "payment_link"
      and url.startswith(EXAMPLE + "?"), str(out)[:240])
query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
check("client_reference_id is the signed-in user",
      query.get("client_reference_id") == USER, str(query))
check("prefilled_email is that account",
      query.get("prefilled_email") == "buyer@example.test", str(query))
check("a user id in the body is ignored", "victim" not in url)
check("opening checkout grants no founder licence", founder(USER) is False,
      str(L.status_for(USER)))

print("\n[3] Checkout Session is the alternative, and it does not call Stripe")
os.environ.pop("A4T_STRIPE_PAYMENT_LINK", None)
check("no link and no session config is not implemented",
      B.checkout_implemented() is False)
st, out = call()
check("the route says not on sale yet",
      st == 501 and out["error"]["code"] == "CHECKOUT_NOT_IMPLEMENTED"
      and out["error"]["message"] == "Not on sale yet", str(out)[:240])

os.environ["STRIPE_SECRET_KEY"] = "sk_test_not_a_real_key"
os.environ["A4T_STRIPE_PRICE_ID"] = "price_founder"
check("a session still needs the public origin",
      B.checkout_implemented() is False)
os.environ["A4T_PUBLIC_WEB_ORIGIN"] = "https://app.example.test"
check("key, price and origin make the session path ready",
      B.checkout_implemented() is True)
seen = {}


def transport(body, key):
    seen["body"] = body
    seen["key"] = key
    return json.dumps({
        "url": "https://checkout.stripe.com/c/pay/cs_test_123",
    }).encode()


SC._transport = transport
try:
    st, out = call({"method": "session", "userId": "victim-user"})
finally:
    SC._transport = None
form = dict(urllib.parse.parse_qsl((seen.get("body") or b"").decode()))
check("the route returns the session url",
      st == 200 and out.get("kind") == "checkout_session"
      and out.get("url") == "https://checkout.stripe.com/c/pay/cs_test_123",
      str(out)[:240])
check("the price id is the configured one",
      form.get("line_items[0][price]") == "price_founder", str(form))
check("mode is a one-time payment", form.get("mode") == "payment")
check("client_reference_id is the signed-in user",
      form.get("client_reference_id") == USER, str(form))
check("metadata carries the same user",
      form.get(f"metadata[{B.USER_META_KEY}]") == USER, str(form))
check("success and cancel come back to /license",
      form.get("success_url") == "https://app.example.test/license?checkout=success"
      and form.get("cancel_url") == "https://app.example.test/license?checkout=cancel",
      str(form))
check("the secret is not in the response",
      "sk_test" not in json.dumps(out))
check("the transport saw the key and the network did not",
      seen.get("key") == "sk_test_not_a_real_key")


def evil(_body, _key):
    return json.dumps({"url": "https://evil.test/pay"}).encode()


SC._transport = evil
try:
    st, out = call({"method": "session"})
finally:
    SC._transport = None
check("a non-Stripe session url is refused",
      st == 502 and out["error"]["code"] == "CHECKOUT_FAILED", str(out)[:240])
check("and still grants no founder licence", founder(USER) is False,
      str(L.status_for(USER)))

print("\n[4] a paid Payment Link event records the licence once")
reset()
os.environ["STRIPE_WEBHOOK_SECRET"] = SECRET
os.environ.pop("A4T_STRIPE_WEBHOOK_SECRET", None)
check("the Stripe-named webhook secret is enough", B.configured() is True)


def paid_link(user=USER, **extra):
    base = {
        "payment_status": "paid",
        "client_reference_id": user,
        "amount_total": 49700,
        "currency": "usd",
        "payment_intent": "pi_link_" + user,
        "payment_link": "plink_founder",
        # The address the buyer signed in with (see _Principal). A bare
        # client_reference_id is no longer trusted without it — see
        # tests/test_payment_link_reference.py.
        "customer_details": {"email": "buyer@example.test"},
    }
    base.update(extra)
    return base


body = event(paid_link(), "evt_link_1")
st, payload = B.handle_event(body, sign(body))
held = L.status_for(USER)
check("the payment link grants",
      st == 200 and payload.get("outcome") == "granted"
      and held["state"] == "active" and held["plan"] == P.FOUNDER_LIVE,
      str(payload))
paid = ST._read_strict(LG._key(f"paid:{USER}"))
check("the paid record is 49700 usd lifetime",
      paid and paid.get("priceMinor") == 49700 and paid.get("currency") == "usd"
      and paid.get("term") == "lifetime" and paid.get("confirmed") is True,
      str(paid))
st, payload = B.handle_event(body, sign(body))
check("the same event is idempotent",
      st == 200 and payload.get("duplicate") is True and payload.get("handled") is not True,
      str(payload))
check("the plan was not rewritten away",
      L.status_for(USER)["plan"] == P.FOUNDER_LIVE)

reset("payer-small")
body = event(paid_link("payer-small", amount_total=100), "evt_link_small")
st, payload = B.handle_event(body, sign(body))
check("a smaller charge grants nothing",
      payload.get("handled") is False and L.status_for("payer-small")["state"] == "none",
      str(payload))
check("and writes no paid record",
      ST._read_strict(LG._key("paid:payer-small")) is None)

reset("payer-eur")
body = event(paid_link("payer-eur", currency="eur"), "evt_link_eur")
st, payload = B.handle_event(body, sign(body))
check("the wrong currency grants nothing",
      payload.get("handled") is False and L.status_for("payer-eur")["state"] == "none",
      str(payload))

reset("payer-unpaid")
body = event(paid_link("payer-unpaid", payment_status="unpaid"), "evt_link_unpaid")
st, payload = B.handle_event(body, sign(body))
check("an unpaid session grants nothing",
      payload.get("handled") is False and L.status_for("payer-unpaid")["state"] == "none",
      str(payload))

reset("payer-anon")
anon = paid_link("payer-anon")
anon.pop("client_reference_id")
body = event(anon, "evt_link_anon")
st, payload = B.handle_event(body, sign(body))
check("no client_reference_id grants nobody",
      payload.get("handled") is False and L.status_for("payer-anon")["state"] == "none",
      str(payload))

reset()
body = event(paid_link(), "evt_link_bad_sig")
st, payload = B.handle_event(body, "t=1,v1=00")
check("a bad signature grants nothing",
      st == 400 and L.status_for(USER)["state"] == "none", str(st))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for item in _fails:
        print("  -", item)
    sys.exit(1)
print("All Stripe checkout checks passed.")
