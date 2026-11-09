"""The 14-day withdrawal waiver is recorded, and a refund still revokes.

Article 16(m) of Directive 2011/83/EU: the withdrawal right for digital
content is lost only with prior express consent, an acknowledgement of that
loss, and confirmation on a durable medium. Checkout refuses to start
without the consent. The grant notification is that confirmation. A later
refund or dispute still withdraws the licence.

Run: python3 tests/test_withdrawal_consent.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-waiver-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

from apex.platform import billing as B                       # noqa: E402
from apex.platform import licence as L                       # noqa: E402
from apex.platform import notifications as N                 # noqa: E402
from apex.platform import plans as P                         # noqa: E402
from apex.platform import refund_policy as RP                # noqa: E402

SECRET = "whsec_waiver_only"
USER = "waiver-user"
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


def deliver(obj, eid, etype="checkout.session.completed"):
    body = json.dumps({"id": eid, "type": etype, "data": {"object": obj}}).encode()
    return B.handle_event(body, sign(body), secret=SECRET)


def paid(uid):
    held = L.status_for(uid)
    return held["state"] == L.ACTIVE and P.is_live_plan(held.get("plan"))


print("\n[1] the web copy and the server copy are the same sentences")
web = open(os.path.join(REPO, "web", "src", "content", "refund-policy.ts"),
           encoding="utf-8").read()
for sentence in (RP.PURCHASE_NOTE, RP.DEMO_CONDITIONS_NOTE,
                 RP.CONSENT_STATEMENT, RP.DURABLE_MEDIUM, RP.POLICY_VERSION):
    check(f"web copy contains {sentence[:48]!r}", sentence in web)
for page in ("terms/page.tsx", "refunds/page.tsx"):
    body = open(os.path.join(REPO, "web", "src", "app", page), encoding="utf-8").read()
    check(f"{page} uses the shared refund copy", 'from "@/content/refund-policy"' in body)
    check(f"{page} does not leave refunds to be confirmed",
          "TO BE CONFIRMED — refund" not in body
          and "TO BE CONFIRMED — whether a customer may request a refund" not in body
          and "refund policy is a draft" not in body.lower())
    check(f"{page} still names the company block as unfinished",
          "CompanyBlock" in body and "TO BE CONFIRMED" in body
          and "not final" in body)


print("\n[2] a granted payment confirms the waiver, then a full refund revokes")
rec = B.record_withdrawal_consent(USER, now=1_760_000_000)
check("consent names the account, the version and the time",
      rec["userId"] == USER and rec["policyVersion"] == RP.POLICY_VERSION
      and rec["consentedAt"] == 1_760_000_000
      and rec["statement"] == RP.CONSENT_STATEMENT
      and rec.get("accessGrantedAt") is None, str(rec)[:240])
session = {
    "payment_status": "paid",
    "amount_total": B.APPROVED_PRICE_MINOR,
    "currency": "usd",
    "payment_intent": "pi_waiver_full",
    "metadata": {
        B.USER_META_KEY: USER,
        RP.META_AT: str(rec["consentedAt"]),
        RP.META_VERSION: rec["policyVersion"],
        RP.META_USER: USER,
    },
}
st, out = deliver(session, "evt_waiver_grant")
check("the payment grants", st == 200 and out.get("outcome") == "granted" and paid(USER),
      str(out))
public = B.purchase_confirmation_public(USER)
text = public.get("confirmation") or ""
check("the receipt quotes the waiver and names who consented",
      public.get("recorded") is True
      and RP.CONSENT_STATEMENT in text
      and f"Consent recorded for user {USER} at 2025-10-09T08:53:20Z" in text
      and f"refund policy {RP.POLICY_VERSION}" in text
      and "Access was granted at" in text
      and RP.PURCHASE_NOTE in text
      and RP.DEMO_CONDITIONS_NOTE in text
      and RP.DURABLE_MEDIUM in text
      and "identical" not in text.lower(),
      text)
notes = N.query(USER, type="system")["notifications"]
body = notes[0]["body"] if notes else ""
check("the licence notification carries the same confirmation",
      body.startswith("Your payment was confirmed and your licence is active.")
      and text in body and len(body) <= 1000, body[-180:])

st, out = deliver(
    {"payment_intent": "pi_waiver_full", "amount": B.APPROVED_PRICE_MINOR,
     "amount_refunded": B.APPROVED_PRICE_MINOR},
    "evt_waiver_refund", "charge.refunded")
check("a full refund still revokes the licence",
      st == 200 and out.get("outcome") == "revoked" and L.status_for(USER)["state"] == "revoked",
      str(out))


print("\n[3] a partial refund leaves the licence; a dispute withdraws it")
OTHER = "waiver-partial"
B.record_withdrawal_consent(OTHER, now=1_760_000_100)
st, out = deliver({
    "payment_status": "paid",
    "amount_total": B.APPROVED_PRICE_MINOR,
    "currency": "usd",
    "payment_intent": "pi_waiver_part",
    "metadata": {B.USER_META_KEY: OTHER},
}, "evt_waiver_part_grant")
check("a payment link style grant still confirms from the stored consent",
      out.get("outcome") == "granted" and paid(OTHER)
      and "Access was granted at" in (B.purchase_confirmation_public(OTHER).get("confirmation") or ""),
      str(out))
st, out = deliver(
    {"payment_intent": "pi_waiver_part", "amount": B.APPROVED_PRICE_MINOR,
     "amount_refunded": 500},
    "evt_waiver_partial", "charge.refunded")
check("a partial refund does not withdraw the licence",
      out.get("handled") is False and paid(OTHER), str(out))
st, out = deliver(
    {"payment_intent": "pi_waiver_part"},
    "evt_waiver_dispute", "charge.dispute.created")
check("a dispute still withdraws the licence",
      out.get("outcome") == "revoked" and L.status_for(OTHER)["state"] == "revoked",
      str(out))


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for item in _fails:
        print("  -", item)
    sys.exit(1)
print("All withdrawal-consent checks passed.")
