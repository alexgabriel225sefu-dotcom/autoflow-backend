"""Payment to licence: the only path that grants, and what it refuses.

The property under test is one sentence: a licence appears only because a
payment provider signed for a payment. Everything below is an attempt to get
one some other way — an unsigned body, a forged signature, a replayed old
delivery, a duplicate, a payment for somebody else, a payment that did not
complete, a request from a browser — and each has to fail.

Run: python3 tests/test_platform_billing.py
"""
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-billing-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

from apex.platform import api as A            # noqa: E402
from apex.platform import billing as B        # noqa: E402
from apex.platform import licence as L        # noqa: E402

SECRET = "whsec_test_secret"
USER = "supabase-user-1"
OTHER = "supabase-user-2"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def sign(body: bytes, *, secret=SECRET, ts=None):
    ts = int(time.time()) if ts is None else int(ts)
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256)
    return f"t={ts},v1={mac.hexdigest()}"


def event(etype, obj, *, eid=None):
    return json.dumps({
        "id": eid or f"evt_{etype}_{time.time_ns()}",
        "type": etype,
        "data": {"object": obj},
    }).encode()


def paid_session(user_id=USER, **extra):
    return dict({"payment_status": "paid", "metadata": {B.USER_META_KEY: user_id}}, **extra)


def state(user_id):
    return L.status_for(user_id)["state"]


def reset(user_id):
    """Back to no licence at all, so each case starts from nothing."""
    from apex.platform import store as S
    S._write(L._key(str(user_id)), {})


# ── 1. a valid delivery grants ──────────────────────────────────────────────
print("\n[1] a signed, paid event grants a licence")
reset(USER)
body = event("checkout.session.completed", paid_session())
st, out = B.handle_event(body, sign(body), secret=SECRET)
check("status 200", st == 200, str(st))
check("handled", out.get("handled") is True, json.dumps(out))
check("licence is active", state(USER) == "active", state(USER))

# ── 2. nothing unsigned or wrongly signed grants ────────────────────────────
print("\n[2] a body the secret did not sign is refused")
reset(USER)
body = event("checkout.session.completed", paid_session())
for name, sig in [
    ("no signature", ""),
    ("garbage signature", "t=abc,v1=def"),
    ("signed with another secret", sign(body, secret="whsec_attacker")),
    ("valid mac, wrong body", sign(b'{"id":"evt_x","type":"x"}')),
]:
    st, out = B.handle_event(body, sig, secret=SECRET)
    check(f"{name} is refused", st == 400 and out["error"]["code"] == "BAD_SIGNATURE", str(st))
check("still no licence", state(USER) == "none", state(USER))

# ── 3. a replayed old delivery is refused ───────────────────────────────────
print("\n[3] an old signature cannot be replayed")
reset(USER)
body = event("checkout.session.completed", paid_session())
old = sign(body, ts=time.time() - (B.SIG_TOLERANCE_SEC + 60))
st, out = B.handle_event(body, old, secret=SECRET)
check("stale delivery refused", st == 400, str(st))
check("no licence from a replay", state(USER) == "none", state(USER))

# ── 4. duplicates do not grant twice ────────────────────────────────────────
print("\n[4] the same event delivered twice is handled once")
reset(USER)
body = event("checkout.session.completed", paid_session(), eid="evt_dup_1")
st1, out1 = B.handle_event(body, sign(body), secret=SECRET)
st2, out2 = B.handle_event(body, sign(body), secret=SECRET)
check("first is handled", out1.get("handled") is True, json.dumps(out1))
check("second says duplicate", st2 == 200 and out2.get("duplicate") is True, json.dumps(out2))
check("second did not re-grant", out2.get("handled") is not True, json.dumps(out2))
check("licence still active", state(USER) == "active", state(USER))

# ── 5. a payment that did not complete grants nothing ───────────────────────
print("\n[5] an incomplete payment grants nothing")
reset(USER)
for obj in [
    {"payment_status": "unpaid", "metadata": {B.USER_META_KEY: USER}},
    {"payment_status": "no_payment_required", "metadata": {B.USER_META_KEY: USER}},
]:
    body = event("checkout.session.completed", obj)
    st, out = B.handle_event(body, sign(body), secret=SECRET)
    check(f"{obj['payment_status']} grants nothing",
          st == 200 and out.get("handled") is False, json.dumps(out))
check("no licence", state(USER) == "none", state(USER))

# ── 6. a payment with no platform user grants nobody ────────────────────────
print("\n[6] a payment that names no platform user grants nobody")
reset(USER)
reset(OTHER)
body = event("checkout.session.completed",
             {"payment_status": "paid", "metadata": {}, "receipt_email": "victim@example.test"})
st, out = B.handle_event(body, sign(body), secret=SECRET)
check("acknowledged, not handled", st == 200 and out.get("handled") is False, json.dumps(out))
check("nobody was granted", state(USER) == "none" and state(OTHER) == "none")

print("\n[6b] the user comes from OUR metadata, never from an email")
reset(USER)
body = event("checkout.session.completed", {
    "payment_status": "paid",
    "metadata": {B.USER_META_KEY: OTHER},
    # A payer-controlled field naming somebody else. It must be ignored.
    "receipt_email": "victim@example.test",
    "customer_email": USER,
})
st, out = B.handle_event(body, sign(body), secret=SECRET)
check("granted to the metadata user", state(OTHER) == "active", state(OTHER))
check("not granted to the email user", state(USER) == "none", state(USER))
reset(OTHER)

# ── 7. refund, dispute and failure suspend ──────────────────────────────────
print("\n[7] a refund, a dispute or a failed renewal suspends the licence")
for etype in ["charge.refunded", "charge.dispute.created",
              "customer.subscription.deleted", "invoice.payment_failed"]:
    reset(USER)
    grant_body = event("checkout.session.completed", paid_session())
    B.handle_event(grant_body, sign(grant_body), secret=SECRET)
    check(f"active before {etype}", state(USER) == "active", state(USER))
    body = event(etype, {"metadata": {B.USER_META_KEY: USER}})
    st, out = B.handle_event(body, sign(body), secret=SECRET)
    check(f"{etype} revokes", state(USER) == "revoked", state(USER))

# ── 8. an unconfigured webhook refuses rather than accepting ────────────────
print("\n[8] with no secret configured, nothing is accepted")
reset(USER)
body = event("checkout.session.completed", paid_session())
os.environ.pop("A4T_STRIPE_WEBHOOK_SECRET", None)
st, out = B.handle_event(body, sign(body))
check("503, so the provider retries later", st == 503, str(st))
check("code says why", out["error"]["code"] == "BILLING_NOT_CONFIGURED", json.dumps(out))
check("no licence", state(USER) == "none", state(USER))

# ── 9. the route is reachable and carries no session ────────────────────────
print("\n[9] the API route verifies the signature and needs no bearer token")
reset(USER)
os.environ["A4T_STRIPE_WEBHOOK_SECRET"] = SECRET
body = event("checkout.session.completed", paid_session(), eid="evt_route_1")
st, out = A.handle("POST", "/api/v1/billing/webhook",
                   {"Stripe-Signature": sign(body)}, body)
check("no Authorization needed", st == 200, str(st))
check("granted through the route", state(USER) == "active", state(USER))

reset(USER)
st, out = A.handle("POST", "/api/v1/billing/webhook",
                   {"Stripe-Signature": "t=1,v1=00"}, body)
check("a bad signature through the route is refused", st == 400, str(st))
check("and grants nothing", state(USER) == "none", state(USER))

# ── 10. no browser-reachable route grants a licence ─────────────────────────
print("\n[10] nothing a client can call grants a licence")
reset(USER)


class _P:
    user_id = USER
    email = "t@example.test"
    email_verified = True

    def as_dict(self):
        return {"userId": self.user_id, "email": self.email, "emailVerified": True}


_real_verify = A._id.verify_token
A._id.verify_token = lambda tok, **kw: _P()
try:
    tried = []
    for method, path in [
        ("POST", "/api/v1/licence/grant"),
        ("POST", "/api/v1/me/licence"),
        ("PUT", "/api/v1/me"),
        ("POST", "/api/v1/billing/grant"),
        ("POST", "/api/v1/billing/activate"),
    ]:
        out = A.handle(method, path, {"Authorization": "Bearer x"},
                       json.dumps({"plan": "pro", "userId": USER}).encode())
        tried.append((method, path, out[0] if out else None))
    check("no authenticated route grants", state(USER) == "none", state(USER))
    check("and none of them answered 200",
          all(s in (None, 404, 405) for _, _, s in tried), str(tried))
finally:
    A._id.verify_token = _real_verify

# ── 11. the price is never guessed ──────────────────────────────────────────
print("\n[11] price, currency and SKU have no defaults")
for var in ["A4T_PRICE_MINOR", "A4T_CURRENCY", "A4T_SKU"]:
    os.environ.pop(var, None)
cfg = B.product_config()
check("no default price", cfg["priceMinor"] is None, repr(cfg["priceMinor"]))
check("no default currency", cfg["currency"] is None, repr(cfg["currency"]))
check("no default SKU", cfg["sku"] is None, repr(cfg["sku"]))
check("the old product's price is not the fallback", cfg["priceMinor"] != 29700)
check("the old product's SKU is not the fallback", cfg["sku"] != "apex-bot")

os.environ["A4T_LICENCE_DAYS"] = "30"
reset(USER)
body = event("checkout.session.completed", paid_session(), eid="evt_expiry_1")
B.handle_event(body, sign(body), secret=SECRET)
st_rec = L.status_for(USER)
check("a period grants an expiry", st_rec["expiresAt"] is not None, repr(st_rec))
check("the expiry is in the future", (st_rec["expiresAt"] or 0) > time.time())
os.environ.pop("A4T_LICENCE_DAYS", None)

# ── 12. a failed grant releases the claim, so a retry still provisions ──────
print("\n[12] a delivery that failed can be retried")
reset(USER)
body = event("checkout.session.completed", paid_session(), eid="evt_retry_1")
_real_grant = L.grant


def _boom(*a, **k):
    raise RuntimeError("storage is down")


L.grant = _boom
st, out = B.handle_event(body, sign(body), secret=SECRET)
check("the failure is a 5xx, so the provider retries", st == 500, str(st))
check("no licence was written", state(USER) == "none", state(USER))
L.grant = _real_grant
st, out = B.handle_event(body, sign(body), secret=SECRET)
check("the retry is NOT refused as a duplicate", out.get("duplicate") is not True, json.dumps(out))
check("the buyer is provisioned on retry", state(USER) == "active", state(USER))

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All billing checks passed.")
