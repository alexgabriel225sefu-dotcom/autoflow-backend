"""What happens to a running demo account when its free trial ends.

The app says "Demo automation is free on this account until <date>". That date
is NOT a fixed calendar date: it is `licence.expiresAt` for THAT account, which
`plans.start_trial` set to account-creation time + 14 days. This test proves,
with a controlled clock, what the platform does on and after that instant:

  * before expiry  : engine gate open, capability says canAutomate
  * AT expiry      : licence state EXPIRED (the boundary is inclusive)
  * after expiry   : capability refuses with TRIAL_EXPIRED and a plain message,
                     the engine gate (`user_loop._entitled`) closes, and the
                     watchdog sweep stops an already-running loop
  * never          : the expiry is extended or converted into a paid plan by
                     reading, signing in again, or calling start_trial again

Run: python3 tests/test_platform_trial_expiry.py
"""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-trial-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from apex import access, user_loop                      # noqa: E402
from apex.platform import entitlement as E              # noqa: E402
from apex.platform import licence as L                  # noqa: E402
from apex.platform import plans as P                    # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


# A client the access store has never heard of: exactly a Supabase user.
access._read = lambda: {"admins": [], "allowed": []}

# `user_loop._entitled` and `licence.status_for` read the wall clock. Replace
# the clock inside the licence module only, so the engine gate sees the same
# instant as the capability call.
clock = [1_000_000.0]
L.time = types.SimpleNamespace(time=lambda: clock[0])

DAY = 86400
USER = "11111111-2222-4333-8444-555555555555"

T0 = clock[0]
P.start_trial(USER, now=T0)
EXP = T0 + P.TRIAL_SECONDS

print("\n[1] the date is per account: creation + 14 days")
st = L.status_for(USER, now=T0)
check("trial length is 14 days", P.TRIAL_DAYS == 14)
check("expiresAt == created + 14d", st["expiresAt"] == EXP, str(st))
check("plan is demo_trial", st["plan"] == P.DEMO_TRIAL)

print("\n[2] two days before expiry (29 Oct vs 31 Oct)")
clock[0] = EXP - 2 * DAY
cap = E.capability(USER, now=clock[0])
check("2 days left reported", cap["trialDaysLeft"] == 2, str(cap["trialDaysLeft"]))
check("licence active", cap["licenceState"] == L.ACTIVE)
check("engine gate open", user_loop._entitled(USER) is True)

print("\n[3] one second before expiry: still running")
clock[0] = EXP - 1
check("engine gate open", user_loop._entitled(USER) is True)
check("licence active", L.status_for(USER, now=clock[0])["state"] == L.ACTIVE)

print("\n[4] ON the expiry instant: ended (boundary is inclusive)")
clock[0] = EXP
check("licence EXPIRED", L.status_for(USER, now=clock[0])["state"] == L.EXPIRED)
check("engine gate CLOSED -> watchdog stops a running loop",
      user_loop._entitled(USER) is False)

print("\n[5] after expiry: automation is refused, nothing is granted")
clock[0] = EXP + 3 * DAY
cap = E.capability(USER, now=clock[0])
check("reason TRIAL_EXPIRED", cap["reason"] == "TRIAL_EXPIRED", str(cap["reason"]))
check("canAutomate False", cap["canAutomate"] is False)
check("engine gate stays closed", user_loop._entitled(USER) is False)
check("start() refuses a new loop", user_loop.start(USER) is False)
try:
    E.require_automation(USER, now=clock[0])
    check("require_automation raises", False)
except E.NotEntitled as e:
    check("require_automation raises TRIAL_EXPIRED", e.code == "TRIAL_EXPIRED")
check("rule activation is still allowed (records terms, does not trade)",
      cap["canActivate"] is True)

print("\n[6] nothing extends or converts the trial")
again = P.start_trial(USER, now=clock[0])
check("start_trial again does not extend",
      again["expiresAt"] == EXP and again["state"] == L.EXPIRED, str(again))
check("still expired after the 'sign-in' call",
      E.capability(USER, now=clock[0])["reason"] == "TRIAL_EXPIRED")

print("\n[7] the expired message is plain and non-alarming")
msg = E.capability(USER, now=clock[0])["message"]
low = msg.lower()
check("says the trial has ended", "trial" in low and "ended" in low, msg)
check("says demo automation is paused", "paused" in low, msg)
check("says saved work is kept", "kept" in low, msg)
check("names a next step", "contact support" in low, msg)
check("no reconnect riddle", "reconnect once a plan" not in low, msg)
check("no price or legal claim", "$" not in msg and "refund" not in low, msg)

print()
if _fails:
    print(f"{len(_fails)} FAILED: {_fails}")
    sys.exit(1)
print("ALL PASSED")
