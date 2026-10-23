"""A token nobody has verified must not buy a bucket of its own.

FOUND BY AN INDEPENDENT REVIEW (MEDIUM). The limiter keyed each request on a
hash of the bearer string BEFORE authentication. Every invented token was a new
bucket, so an anonymous caller could send unlimited control requests, each
forcing a Supabase lookup, until that service throttled the platform's key and
every client — including the Emergency button — got AUTH_UNAVAILABLE. And the
close route sat in the "default" bucket, twelve times looser than a Stop.

WHAT THESE TESTS WILL NOT ACCEPT

* One address getting unlimited requests by rotating tokens.
* The address floor throttling a different address.
* A position close metered as an ordinary read.
* A real, repeated token being treated differently from before.

Run: python3 tests/test_rate_limit_before_auth.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-rlauth-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["RATE_LIMIT_STORE"] = "memory"
os.environ["RL_A4T_ADDR_PER_MIN"] = "50"
os.environ["RL_A4T_ADDR_CONTROL_PER_MIN"] = "10"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import ratelimit as RL                    # noqa: E402

# ── 1. rotating tokens from one address is bounded ──────────────────────────
print("\n[1] one address cannot mint a fresh bucket per invented token")
allowed = 0
for i in range(40):
    ok, bucket, _ = RL.check("POST", "automation/stop", client_key="198.51.100.7",
                             auth_header=f"Bearer junk-token-{i}")
    allowed += 1 if ok else 0
check("only the address floor's worth of control requests got through",
      allowed == 10, f"{allowed} allowed")
ok, bucket, wait = RL.check("POST", "automation/stop", client_key="198.51.100.7",
                            auth_header="Bearer yet-another")
check("the refusal names the address bucket and a wait", not ok and bucket == "addr_control" and wait >= 1,
      f"{ok} {bucket} {wait}")

print("\n[1b] ordinary reads have the larger floor")
n = sum(1 for i in range(80) if RL.check("GET", "positions", client_key="198.51.100.8",
                                         auth_header=f"Bearer t{i}")[0])
check("capped at the address floor, not unlimited", n == 50, str(n))

# ── 2. other addresses are unaffected ───────────────────────────────────────
print("\n[2] a different address is not throttled by the first")
ok, bucket, _ = RL.check("POST", "automation/stop", client_key="203.0.113.9", auth_header="Bearer someone")
check("allowed", ok is True, f"{ok} {bucket}")

# ── 3. close is a control route ─────────────────────────────────────────────
print("\n[3] a position close is metered as a control action")
check("close route -> control", RL.classify("POST", "accounts/501/positions/7/close") == "control",
      RL.classify("POST", "accounts/501/positions/7/close"))
check("with the query string too", RL.classify("POST", "accounts/501/positions/7/close?x=1") == "control")
check("reading positions is still a read", RL.classify("GET", "accounts/501/positions") != "control")
check("the emergency stop has a bucket of its own, not the control one",
      RL.classify("POST", "emergency/stop") == "emergency",
      RL.classify("POST", "emergency/stop"))

# ── 4. a real repeated token still has its own budget ───────────────────────
print("\n[4] the per-token bucket still applies on top")
RL.LIMITERS["control"].limit = 3
RL.LIMITERS["control"].hits.clear() if hasattr(RL.LIMITERS["control"], "hits") else None
res = [RL.check("POST", "automation/stop", client_key="192.0.2.50", auth_header="Bearer real-token")[0] for _ in range(5)]
check("the same token is limited by the control bucket (3 then refused)", res[:3] == [True] * 3 and res[3] is False, str(res))

# ── 5. the panic button cannot be rate-limited away ─────────────────────────
print("\n[5] the emergency stop is not starved by junk or by closes")
# (a) Junk tokens from one shared address (a carrier NAT, an office) used up the
# stricter per-address floor for control routes, and the real client behind the
# same address then got 429 on Emergency. The emergency route carries only the
# generic address floor.
RL.reset_all() if hasattr(RL, "reset_all") else None
for i in range(30):
    RL.check("POST", "automation/stop", client_key="198.51.100.77",
             auth_header=f"Bearer junk-{i}")
ok, bucket, _ = RL.check("POST", "emergency/stop", client_key="198.51.100.77",
                         auth_header="Bearer the-real-client")
check("junk control traffic from the same address does not block Emergency",
      ok is True, f"{ok} {bucket}")
# (b) twenty single closes spend the control bucket; Emergency has its own.
RL.LIMITERS["control"].limit = 20
# (no client address here: this is about the per-token buckets, not the floor)
for i in range(25):
    RL.check("POST", "accounts/501/positions/7/close", client_key=None,
             auth_header="Bearer same-client")
ok_close, b_close, _ = RL.check("POST", "accounts/501/positions/8/close",
                                client_key=None, auth_header="Bearer same-client")
ok, bucket, _ = RL.check("POST", "emergency/stop", client_key=None,
                         auth_header="Bearer same-client")
check("the closes really were limited", ok_close is False and b_close == "control",
      f"{ok_close} {b_close}")
check("and Emergency still goes through for the same client",
      ok is True, f"{ok} {bucket}")
# (c) it is still bounded: its own per-token bucket applies.
RL.LIMITERS["emergency"].limit = 3
res = [RL.check("POST", "emergency/stop", client_key="192.0.2.91",
                auth_header="Bearer spammer")[0] for _ in range(5)]
check("pressing it in a loop is still limited (3 then refused)",
      res[:3] == [True] * 3 and res[3] is False, str(res))
# (d) and an address that floods it with junk is still bounded by the generic floor.
n = sum(1 for i in range(80) if RL.check("POST", "emergency/stop",
                                         client_key="198.51.100.200",
                                         auth_header=f"Bearer junk-e-{i}")[0])
check("a flood of junk tokens at Emergency from one address is still capped",
      n == 50, str(n))

# ── 6. and per PERSON, once the session is verified ─────────────────────────
print("\n[6] several sessions of one person share one Emergency budget")
RL.LIMITERS["emergency_user"].limit = 3
res = [RL.check_user("emergency_user", "person-1")[0] for _ in range(5)]
check("a person is limited whichever session the presses come from (3 then refused)",
      res[:3] == [True] * 3 and res[3] is False and res[4] is False, str(res))
ok, wait = RL.check_user("emergency_user", "person-1")
check("the refusal carries a wait", ok is False and wait >= 1, f"{ok} {wait}")
check("another person is unaffected",
      RL.check_user("emergency_user", "person-2")[0] is True)
check("an unknown bucket or an empty id does not refuse",
      RL.check_user("nonexistent", "x")[0] is True
      and RL.check_user("emergency_user", "")[0] is True)
api_src = open(os.path.join(ROOT, "apex", "platform", "api.py")).read()
route = api_src.split('if route == "emergency/stop":', 1)[1].split("# ── automation control", 1)[0]
_a, _c, _r = (route.find("_authenticate(headers, fresh=True)"),
              route.find('check_user("emergency_user"'),
              route.find("_panic.run("))
check("the route counts the person at all", _c != -1,
      "the per-person Emergency limit is not called")
check("after authenticating and before doing any work",
      -1 != _a < _c < _r,
      "a per-person limit needs the verified id, and must precede the work")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All pre-auth rate-limit checks passed.")
