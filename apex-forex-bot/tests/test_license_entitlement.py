"""The licence gate, end to end — what proves an account may trade live.

A valid HMAC proves this server MINTED the key. It proves nothing about
payment: a refunded customer, an expired trial and an abandoned checkout all
keep a permanently valid signature forever. So the signature is a
precondition, never the answer, and the licences row is the only authority.

Four defects this file exists to keep dead:

  * SIGNATURE ALONE GRANTED ACCESS. A signed key with no row fell through as a
    "legacy/manual key", and the endpoint then UPSERTED it active:true — so
    verification minted its own entitlement and the payment webhook stopped
    being the authority on anything.
  * AN UNREADABLE STORE READ AS "no such row". supabase-js reports network
    failures in `error` and does not always throw; the code destructured only
    `data`, so an outage was indistinguishable from a miss, and a miss allowed.
  * REQUIRE_LICENSE DEFAULTED TO FALSE. A deployment that forgot the variable
    served the product free to whoever messaged first, silently.
  * REVALIDATION RETURNED TRUE ON ANY FAILURE. "Fail open until somebody
    notices" is the absence of a policy. An unverifiable client now keeps
    their interface and their open positions, but takes NO new live risk,
    and the grace is bounded.

The asymmetry that looks like an inconsistency and is not: a FIRST activation
denies on unknown (a stranger is owed nothing), REVALIDATION grants a bounded
grace on unknown (an already-verified client has done nothing wrong). Unknown
means "no new information" in both; it just points opposite ways.

Run: python tests/test_license_entitlement.py
"""
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-lic-")

from apex import gates, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name}  → {detail}")
    if not cond:
        failures.append(name)


SERVER = open(os.path.join(REPO, "server.js"), encoding="utf-8").read()
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
# The verify-license handler only — so an assertion cannot pass by matching
# some other route that happens to contain the same words.
VERIFY_RAW = SERVER[SERVER.index("app.post('/api/verify-license'"):]
VERIFY_RAW = VERIFY_RAW[:VERIFY_RAW.index("\n});")]


def _strip_js_comments(src):
    """Drop // line comments so assertions read CODE, not prose.

    Two checks in this file first passed by matching the explanatory comments
    that describe the very defects they exist to catch — "the auto-upsert that
    used to sit here", "the old code swallowed this with catch (_) {}". An
    assertion satisfied by a sentence about a bug is not testing the bug.
    The `(?<!:)` guard keeps `https://` intact.
    """
    return re.sub(r"(?<!:)//.*", "", src)


VERIFY = _strip_js_comments(VERIFY_RAW)

print("\n🔑  LICENCE ENTITLEMENT\n")

print("1. A signature is not proof of payment")
check("a signed key with NO row is denied",
      "signed key with no licence row" in VERIFY
      and "This licence is not registered" in VERIFY,
      "no row means never sold")
check("verification does not upsert an entitlement",
      ".upsert(" not in VERIFY,
      "verification that writes active:true IS the authority, and must not be")
check("the row must be active", "row.active !== true" in VERIFY)
check("a refunded row is denied", "row.refunded === true" in VERIFY)
check("an expired row is denied", "row.expires_at" in VERIFY
      and "getTime() <= Date.now()" in VERIFY)
check("the row's product must match the caller",
      "claimedProduct !== row.product" in VERIFY)

print("\n2. An unreadable store denies — it does not read as 'no row'")
check("the supabase error field is checked, not just a thrown exception",
      "error: rowErr" in VERIFY and "if (rowErr)" in VERIFY,
      "supabase-js reports network failures in `error` and does not always throw")
check("an unreachable store answers 503", "status(503)" in VERIFY)
check("no licence store configured is also a denial",
      "no licence store configured" in VERIFY,
      "nothing to consult means nothing to grant")
check("the legacy path applies the SAME rules",
      "lrow.refunded === true" in VERIFY and "lrow.active !== true" in VERIFY
      and "lrow.expires_at" in VERIFY,
      "the legacy route skips the signature entirely — it cannot be laxer")
check("the legacy path does not swallow its errors",
      "catch (_) {}" not in VERIFY,
      "a swallowed read failure told a paying customer their key was bad")

print("\n3. REQUIRE_LICENSE fails closed in production")
check("an absent setting does not mean open access",
      'os.getenv("REQUIRE_LICENSE", "false")' not in TG,
      "defaulting to false gives the product away silently")
check("the production default is resolved, not assumed",
      "def _license_required()" in TG and "_is_production()" in TG)
from apex import telegram as tg  # noqa: E402

# Behaviour, not the comment that describes it: make the production probe
# itself fail and confirm the answer is still "gate ON".
_real_is_prod = user_store._is_production
try:
    def _boom():
        raise RuntimeError("environment unreadable")
    user_store._is_production = _boom
    os.environ.pop("REQUIRE_LICENSE", None)
    check("an unreadable environment takes the safe direction",
          tg._license_required() is True,
          "cannot tell whether this is production → assume it is")
finally:
    user_store._is_production = _real_is_prod

check("in a test (non-production) environment the gate is off",
      tg._license_required() is False,
      "local work must not need a licence server")
for raw, expect in (("true", True), ("1", True), ("yes", True),
                    ("false", False), ("0", False), ("no", False)):
    os.environ["REQUIRE_LICENSE"] = raw
    check(f"REQUIRE_LICENSE={raw!r} is honoured", tg._license_required() is expect)
os.environ.pop("REQUIRE_LICENSE", None)

print("\n4. Unknown entitlement takes no new LIVE risk")
U = "lic-9001"
user_store.update(U, {"license_key": "FORX-AAAA-BBBB-CCCC", "paper": False})
check("a verified licence on a live account is allowed",
      gates.live_entitlement(U)[0] == "allowed", gates.live_entitlement(U))

user_store.update(U, {"license_grace_since": int(time.time())})
state, why = gates.live_entitlement(U)
check("a licence in grace reads UNKNOWN, not allowed", state == "unknown", why)
check("…and the stored key does NOT override it", "grace" in why,
      "the key is precisely what could not be verified")
d, _rid = gates.authorize_order(U, symbol="EURUSD", side="BUY", units=5000)
check("a NEW LIVE order is refused during grace",
      d.allowed is False and d.reason == "ENTITLEMENT_UNKNOWN",
      f"{d.allowed}/{d.reason}")

user_store.update(U, {"paper": True})
d2, _ = gates.authorize_order(U, symbol="EURUSD", side="BUY", units=5000)
check("the same order in PAPER still runs", d2.allowed is True,
      f"{d2.allowed}/{d2.reason} — grace must not black out a simulation")

user_store.update(U, {"paper": False, "license_grace_since": None})
check("clearing grace restores live entitlement",
      gates.live_entitlement(U)[0] == "allowed")

print("\n5. Grace is bounded, and an explicit refusal revokes")
check("grace has a maximum", "_GRACE_MAX_S" in TG and "LICENSE_GRACE_HOURS" in TG)
REV = TG[TG.index("def _revalidate_license"):]
REV = REV[:REV.index("\ndef ")]
check("past the maximum, access is revoked", "access.revoke(cid)" in REV
      and "_GRACE_MAX_S" in REV)
check("a 5xx enters grace rather than revoking",
      "if r.status_code >= 500:" in REV and "_enter_grace" in REV,
      "the 503 body says valid:false; acting on it revokes everyone")
check("an explicit valid:false revokes and stops the loop",
      'data.get("valid") is False' in REV and "user_loop.stop(cid)" in REV)
check("a verified re-check clears the grace marker",
      "grace cleared" in REV)
check("admins never hit this path", "access.is_admin(cid)" in REV)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — a signature is not a licence.")
