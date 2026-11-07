"""Refunds and disputes are never silently dropped, and a refunded payment stays refunded.

From the security review (#110, findings 6, 7 and 9).

WHAT THESE TESTS WILL NOT ACCEPT

* A store outage while resolving a refund being treated as "no such payment"
  and marked done (the licence would stay with a refunded buyer).
* A refund that cannot be matched to anyone being dropped without a trace.
* A grant arriving after the refund of the SAME payment giving the licence back.
* A buyer in a taxed place getting the plan but not the live paid record.
* A test-mode event accepted in production because the env var said "prod".

Run: python3 tests/test_billing_reversal_strict.py
"""
import hashlib, hmac, json, os, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-revstrict-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
SECRET = "whsec_test_not_a_real_secret"
os.environ["A4T_STRIPE_WEBHOOK_SECRET"] = SECRET

from apex.platform import billing as B        # noqa: E402
from apex.platform import licence as LIC      # noqa: E402
from apex.platform import live_gate as LG     # noqa: E402
from apex.platform import store as PS         # noqa: E402

fails = []
def check(n, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'} {n}" + (f"  {d}" if d and not c else ""))
    if not c: fails.append(n)

USER = "ffffffff-6666-4666-8666-ffffffffffff"
_n = [0]

def deliver(event):
    raw = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return B.handle_event(raw, f"t={ts},v1={sig}", secret=SECRET)

def purchase(pi, **over):
    _n[0] += 1
    obj = {"id": f"cs_{_n[0]}", "object": "checkout_session", "payment_status": "paid",
           "payment_intent": pi, "amount_total": B.APPROVED_PRICE_MINOR,
           "currency": B.APPROVED_CURRENCY, "metadata": {B.USER_META_KEY: USER}}
    obj.update(over)
    return {"id": f"evt_p{_n[0]}", "type": "checkout.session.completed",
            "livemode": True, "data": {"object": obj}}

def refund(pi, eid):
    return {"id": eid, "type": "charge.refunded", "livemode": True,
            "data": {"object": {"id": "ch_x", "object": "charge", "payment_intent": pi,
                                "amount": B.APPROVED_PRICE_MINOR,
                                "amount_refunded": B.APPROVED_PRICE_MINOR, "metadata": {}}}}

print("[1] a store outage while resolving a refund is retried, not dropped")
st, out = deliver(purchase("pi_A"))
check("granted", st == 200 and LIC.status_for(USER)["state"] == LIC.ACTIVE, f"{st} {out}")
_real = PS._read_strict
def _down(key, *a, **k):
    if ":billing:ref:" in key:
        raise PS.StoreUnavailable("simulated outage") if hasattr(PS, "StoreUnavailable") else RuntimeError("simulated outage")
    return _real(key, *a, **k)
PS._read_strict = _down
try:
    st, out = deliver(refund("pi_A", "evt_r_outage"))
finally:
    PS._read_strict = _real
check("answers 5xx so the provider retries", st >= 500, f"{st} {out}")
check("the licence is still there (nothing was decided)", LIC.status_for(USER)["state"] == LIC.ACTIVE)
st, out = deliver(refund("pi_A", "evt_r_outage"))
check("the retry withdraws it", st == 200 and LIC.status_for(USER)["state"] == LIC.REVOKED, f"{st} {out}")

print("[2] a refund that matches nobody is held for a person")
st, out = deliver(refund("pi_unknown", "evt_r_nobody"))
check("acknowledged, not granted or revoked", st == 200 and out.get("handled") is False, f"{st} {out}")
review = PS._read(B._k_review("evt_r_nobody"))
check("and recorded for review", isinstance(review, dict) and review.get("paymentRef") == "pi_unknown", str(review))

print("[3] a grant for an already refunded payment is held, not honoured")
st, out = deliver(purchase("pi_A"))          # the SAME payment, delivered again after its refund
check("not granted", st == 200 and out.get("handled") is False, f"{st} {out}")
check("the licence stays withdrawn", LIC.status_for(USER)["state"] == LIC.REVOKED, str(LIC.status_for(USER)))
st, out = deliver(purchase("pi_B"))          # a NEW payment is a new purchase
check("a new payment still grants", st == 200 and LIC.status_for(USER)["state"] == LIC.ACTIVE, f"{st} {out}")

print("[4] the live paid record follows the same tax-aware amount rule")
obj_ok = {"amount_total": 54000, "currency": "usd", "total_details": {"amount_tax": 4300}}
check("offer plus declared tax counts", B.explicit_offer_charge(obj_ok) is True)
check("exact offer counts", B.explicit_offer_charge({"amount_total": 49700, "currency": "usd"}) is True)
check("a discount does not", B.explicit_offer_charge({"amount_total": 39700, "currency": "usd"}) is False)
check("tax that does not explain the difference does not",
      B.explicit_offer_charge({"amount_total": 54000, "currency": "usd", "total_details": {"amount_tax": 100}}) is False)
check("an object that states nothing does not", B.explicit_offer_charge({}) is False)
check("a wrong currency does not", B.explicit_offer_charge({"amount_total": 49700, "currency": "eur"}) is False)
check("a missing currency does not", B.explicit_offer_charge({"amount_total": 49700}) is False)
written = LG.note_confirmed_payment("taxed-user", obj_ok, payment_ref="pi_tax", lifetime=True)
check("the live gate writes the paid record for a taxed full-price payment", written is True)
check("and not for a discounted one", LG.note_confirmed_payment("cheap-user", {"amount_total": 39700, "currency": "usd"}, lifetime=True) is False)

print("[5] 'prod' and 'production' are both production for the test-mode check")
for env, expect in (("production", False), ("prod", False), ("dev", True), ("", True)):
    os.environ["APP_ENV"] = env
    ok, _ = B._livemode_ok({"livemode": False})
    check(f"APP_ENV={env!r}: a test-mode event is {'accepted' if expect else 'refused'}", ok is expect)
os.environ["APP_ENV"] = "dev"

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
