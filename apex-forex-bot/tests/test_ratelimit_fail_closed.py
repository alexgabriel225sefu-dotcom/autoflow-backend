"""A broken limiter refuses money-moving writes and still serves reads.

FOUND BY THE SECURITY AUDIT. `ratelimit.check` answered "allowed" whenever the
limiter itself raised, for every route. A fault that made the limiter throw
therefore removed the only per-caller ceiling on automation start, rule
activation and position closes, exactly the routes a flood would aim at.

WHAT THESE TESTS WILL NOT ACCEPT

* An authenticated mutating route allowed through a limiter that raised.
* A read refused because the limiter raised (reads stay lenient).
* The emergency stop or the payment webhook refused because the limiter
  raised: refusing a safety stop or a payment delivery over a limiter bug is
  worse than the hole it would close.
* A fail-closed refusal that looks like an ordinary 429 (it is a 503 with its
  own code, because the client did nothing wrong).

Run: python3 tests/test_ratelimit_fail_closed.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-rlclosed-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["RATE_LIMIT_STORE"] = "memory"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import ratelimit as RL                    # noqa: E402


def _boom(_key):
    raise RuntimeError("limiter exploded")


_saved = {n: lim.check for n, lim in RL.LIMITERS.items()}
for lim in RL.LIMITERS.values():
    lim.check = _boom

try:
    print("\n[1] authenticated mutating routes fail closed")
    for method, route in (("POST", "automation/start"),
                          ("POST", "rules/r1/activate"),
                          ("POST", "rules/r1/resume"),
                          ("POST", "accounts/501/positions/7/close"),
                          ("POST", "rules"),
                          ("PUT", "rules/r1"),
                          ("POST", "ctrader/select"),
                          ("DELETE", "account")):
        ok, bucket, wait = RL.check(method, route, client_key="1.1.1.1",
                                    auth_header="Bearer t")
        check(f"{method} {route} refused", ok is False and bucket == RL.UNAVAILABLE
              and wait >= 1, f"{ok} {bucket} {wait}")

    print("\n[2] reads stay lenient")
    for route in ("journal", "positions", "rules", "automation", "me",
                  "account/export"):
        ok, _b, _w = RL.check("GET", route, client_key="1.1.1.1",
                              auth_header="Bearer t")
        check(f"GET {route} allowed", ok is True)

    print("\n[3] the safety stop and the payment webhook stay lenient")
    ok, _b, _w = RL.check("POST", "emergency/stop", client_key="1.1.1.1",
                          auth_header="Bearer t")
    check("emergency stop allowed", ok is True)
    ok, _b, _w = RL.check("POST", "billing/webhook", client_key="1.1.1.1")
    check("payment webhook allowed", ok is True)

    print("\n[4] the per-person check fails closed only when asked")
    ok, _w = RL.check_user("emergency_user", "u1")
    check("default per-person check is lenient", ok is True)
    ok, _w = RL.check_user("account_delete", "u1", fail_closed=True)
    check("fail_closed per-person check refuses", ok is False)
finally:
    for n, fn in _saved.items():
        RL.LIMITERS[n].check = fn

print("\n[5] the refusal is a 503 with its own code, not a 429")
status, body = RL.refusal(RL.UNAVAILABLE, 5)
check("503", status == 503, str(status))
check("code RATE_LIMIT_UNAVAILABLE",
      body["error"]["code"] == "RATE_LIMIT_UNAVAILABLE", str(body))
status, body = RL.refusal("control", 5)
check("an ordinary refusal is still 429 RATE_LIMITED",
      status == 429 and body["error"]["code"] == "RATE_LIMITED")

print("\n[6] a healthy limiter still allows mutating routes")
RL.reset_all()
ok, bucket, _w = RL.check("POST", "automation/start", client_key="2.2.2.2",
                          auth_header="Bearer t")
check("allowed", ok is True, f"{ok} {bucket}")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All fail-closed limiter checks passed.")
