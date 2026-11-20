"""A Stripe signature header with several v1 entries verifies on ANY match.

FOUND BY THE SECURITY AUDIT. `billing.verify_signature` parsed the header into
a dict, so of several `v1=` entries only the LAST survived. Stripe sends one
`v1` per active signing secret while a secret is being rolled, and the order
is not promised: a delivery signed with the secret this server holds was
refused whenever the other signature came last, and the provider then retried
into the same refusal until the roll finished.

WHAT THESE TESTS WILL NOT ACCEPT

* A header whose matching v1 is first, middle or last being refused.
* A header with no matching v1 being accepted, however many it carries.
* A stale timestamp being accepted because a v1 matches.
* A missing timestamp, or no v1 at all, being accepted.

Run: python3 tests/test_stripe_signature_rotation.py
"""
import hashlib
import hmac
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-sigrot-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

from apex.platform import billing as B                       # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


OURS = "whsec_current_test_only"
BODY = b'{"id":"evt_x","type":"checkout.session.completed"}'


def mac(secret, ts, body=BODY):
    return hmac.new(secret.encode(), f"{ts}.".encode() + body,
                    hashlib.sha256).hexdigest()


now = int(time.time())
good = mac(OURS, now)
other = mac("whsec_other_secret", now)
junk = "0" * 64

print("\n[1] any matching v1 verifies")
for label, header in (
        ("matching v1 last", f"t={now},v1={other},v1={good}"),
        ("matching v1 first", f"t={now},v1={good},v1={other}"),
        ("matching v1 in the middle", f"t={now},v1={junk},v1={good},v1={other}"),
        ("a single matching v1", f"t={now},v1={good}"),
        ("with a v0 entry and spaces", f"t={now}, v0={junk}, v1={other}, v1={good}")):
    check(label, B.verify_signature(BODY, header, OURS) is True, header)

print("\n[2] no matching v1 is refused")
check("two non-matching v1", B.verify_signature(
    BODY, f"t={now},v1={other},v1={junk}", OURS) is False)
check("matching v0 only is not a v1", B.verify_signature(
    BODY, f"t={now},v0={good}", OURS) is False)
check("a different body", B.verify_signature(
    b"{}", f"t={now},v1={good},v1={other}", OURS) is False)

print("\n[3] the timestamp still rules")
old = now - B.SIG_TOLERANCE_SEC - 10
check("stale timestamp refused even when v1 matches", B.verify_signature(
    BODY, f"t={old},v1={other},v1={mac(OURS, old)}", OURS) is False)
check("missing timestamp refused", B.verify_signature(
    BODY, f"v1={good}", OURS) is False)
check("two timestamps refused", B.verify_signature(
    BODY, f"t={now},t={now},v1={good}", OURS) is False)
check("no v1 refused", B.verify_signature(BODY, f"t={now}", OURS) is False)
check("empty header refused", B.verify_signature(BODY, "", OURS) is False)
check("no secret refused", B.verify_signature(
    BODY, f"t={now},v1={good}", "") is False)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All signature rotation checks passed.")
