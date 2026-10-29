"""scripts/stripe_webhook_replay.py signs exactly what billing.py verifies.

Three layers, no network beyond loopback:
  1. the script's signature is accepted by `billing.verify_signature`, and a
     tampered, stale or wrong-secret one is rejected;
  2. the script's price constant equals billing.APPROVED_PRICE_MINOR (the single
     source of truth), so the two cannot drift;
  3. the full scenario run against an in-process platform server: every
     scenario passes, and the licence store ends in the state the runbook says
     (granted-then-revoked, never granted for unpaid / wrong amount / no user).

Run: python3 tests/test_stripe_webhook_replay.py
"""
import importlib.util
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-replay-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
SECRET = "whsec_unit_test_only"
os.environ["A4T_STRIPE_WEBHOOK_SECRET"] = SECRET
for _n in ("STRIPE_WEBHOOK_SECRET", "A4T_PRICE_MINOR", "A4T_CURRENCY",
           "A4T_SKU", "A4T_PLAN", "A4T_PURCHASE_MODE", "A4T_LICENCE_DAYS",
           "A4T_CHECKOUT_ENABLED", "A4T_AUTHENTICATED_CHECKOUT_ENABLED",
           "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(_n, None)
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

_spec = importlib.util.spec_from_file_location(
    "stripe_webhook_replay",
    os.path.join(ROOT, "scripts", "stripe_webhook_replay.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

from apex.platform import billing as B                  # noqa: E402
from apex.platform import licence as L                  # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


print("\n[1] the script's signature against billing's verifier")
body = b'{"id":"evt_x","type":"charge.refunded"}'
good = R.sign_payload(body, SECRET)
check("valid signature verifies", B.verify_signature(body, good, SECRET))
check("tampered body fails", not B.verify_signature(body + b" ", good, SECRET))
check("wrong secret fails",
      not B.verify_signature(body, R.sign_payload(body, SECRET + "x"), SECRET))
check("stale timestamp fails",
      not B.verify_signature(body, R.sign_payload(body, SECRET,
                                                  ts=time.time() - 3600), SECRET))
check("header has Stripe's t=,v1= shape",
      good.startswith("t=") and ",v1=" in good)

print("\n[2] single source of truth for the price")
check("script price == billing.APPROVED_PRICE_MINOR",
      R.PRICE_MINOR == B.APPROVED_PRICE_MINOR == 49700)
check("script currency == billing currency", R.CURRENCY == B.APPROVED_CURRENCY)
check("metadata key matches billing", R.USER_META_KEY == B.USER_META_KEY)

print("\n[3] guards")
try:
    R.check_target("https://example.com/api/v1/billing/webhook")
    check("a remote target is refused", False)
except SystemExit:
    check("a remote target is refused", True)
try:
    R.check_target("http://127.0.0.1:8080/x")
    R.check_target("http://localhost:8080/x")
    check("loopback targets are allowed", True)
except SystemExit:
    check("loopback targets are allowed", False)
os.environ.pop(R.SECRET_ENV, None)
try:
    R.main([])
    check("missing secret env is refused", False)
except SystemExit as e:
    check("missing secret env is refused", "whsec_" in str(e))
os.environ[R.SECRET_ENV] = "not-a-whsec"
try:
    R.main([])
    check("a non-whsec secret is refused", False)
except SystemExit:
    check("a non-whsec secret is refused", True)
os.environ[R.SECRET_ENV] = SECRET

print("\n[4] every scenario against an in-process server")
import platform_server as ps                            # noqa: E402

srv = ps.build_server(0)
port = srv.server_address[1]
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
RID = "t1"
out = []
try:
    results = R.run(f"http://127.0.0.1:{port}/api/v1/billing/webhook", SECRET,
                    run_id=RID, out=out.append)
finally:
    srv.shutdown()
for name, passed in results:
    check(f"scenario: {name}", passed)
check("twelve scenarios ran", len(results) == 12, str(len(results)))
check("the secret is not in the report", all(SECRET not in l for l in out))

print("\n[5] the store ends where the runbook says")
st = lambda n: L.status_for(f"a4t-replay-{RID}-{n}")["state"]
check("refunded buyer is revoked", st("a") == L.REVOKED, st("a"))
check("unpaid buyer has no licence", st("b") == L.NONE, st("b"))
check("wrong-amount buyer has no licence", st("c") == L.NONE, st("c"))
check("disputed buyer is revoked", st("d") == L.REVOKED, st("d"))

print()
if _fails:
    print(f"{len(_fails)} FAILED: {_fails}")
    sys.exit(1)
print("ALL PASSED")
