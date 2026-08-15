"""Regression test: access must gate the EXECUTION path, not just commands.

Observed live: a Telegram chat got "🔒 Activation required" for both /terminal
and /restart, while the same chat kept receiving "💗 Bot alive — GBPUSD |
Balance: $27128.63" heartbeats. Access was enforced when handling a command and
nowhere else, so start_all() on boot and the watchdog every 180s kept the
trading loop alive off `active: True` alone.

Two ways a legitimate client can look unlisted, neither of which may cost them
their bot:
  * the access store is unreachable (Redis hiccup)
  * the local-JSON backend is wiped on every redeploy

Run: python tests/test_access_gates_loop.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-access-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import access, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


CLIENT = "8963896517"       # the chat from the screenshot
OWNER = "7585109158"        # hardcoded admin
STRANGER = "1111111111"

# Keep the real store out of this; drive access through a stub we control.
_state = {}
_degraded = {"on": False}


def fake_read():
    d = {"admins": [], "allowed": list(_state.get("allowed", []))}
    if _degraded["on"]:
        return {"admins": [], "allowed": [], "_degraded": True}
    return d


access._read = fake_read

print("\n── allowed_state gives the three-way answer is_allowed cannot ──")
_state["allowed"] = [CLIENT]
check("granted client → allowed", access.allowed_state(CLIENT) == "allowed")
check("stranger → denied", access.allowed_state(STRANGER) == "denied")
check("hardcoded owner → allowed", access.allowed_state(OWNER) == "allowed")
_degraded["on"] = True
check("store unreachable → unknown, NOT denied",
      access.allowed_state(CLIENT) == "unknown",
      access.allowed_state(CLIENT))
check("owner still allowed with the store down (never depends on it)",
      access.allowed_state(OWNER) == "allowed")
_degraded["on"] = False

print("\n── _entitled: only a definite denial stops a loop ──")
user_store.update(CLIENT, {"license_key": None})
user_store.update(STRANGER, {"license_key": None})
_state["allowed"] = [CLIENT]
check("granted client is entitled", user_loop._entitled(CLIENT) is True)
check("stranger with no grant and no license is NOT entitled",
      user_loop._entitled(STRANGER) is False)
check("owner is entitled", user_loop._entitled(OWNER) is True)

_degraded["on"] = True
check("REDIS HICCUP: a paying client keeps its bot",
      user_loop._entitled(CLIENT) is True)
check("REDIS HICCUP: even an unknown chat is allowed, not killed",
      user_loop._entitled(STRANGER) is True)
_degraded["on"] = False

print("\n── redeploy wiped the local store → license_key is the fallback ──")
_state["allowed"] = []
check("no grant, no license → not entitled",
      user_loop._entitled(CLIENT) is False)
user_store.update(CLIENT, {"license_key": "FORX-AAAA-BBBB-CCCC"})
check("no grant but a license on file → entitled",
      user_loop._entitled(CLIENT) is True)
user_store.update(CLIENT, {"license_key": None})

print("\n── start() refuses an unentitled chat ──")
_state["allowed"] = []
user_store.update(STRANGER, {"active": True, "license_key": None})
started = user_loop.start(STRANGER, alert_fn=None)
check("start() returns False", started is False)
check("no loop is running", user_loop.is_running(STRANGER) is False)
check("`active` is cleared so the watchdog stops resurrecting it",
      user_store.load(STRANGER).get("active") is False,
      str(user_store.load(STRANGER).get("active")))

print("\n── a broken access module must never take the bot down ──")
_orig = access.allowed_state


def boom(_):
    raise RuntimeError("redis exploded")


access.allowed_state = boom
check("an exception in the access check allows the loop",
      user_loop._entitled(CLIENT) is True)
access.allowed_state = _orig

print("\n── the screenshot's exact situation ──")
# Chat is refused on the command path (not in `allowed`, no license) yet its
# record still says active: True — which is what kept the heartbeats coming.
_state["allowed"] = []
user_store.update(CLIENT, {"active": True, "license_key": None})
check("commands would be refused (is_allowed False)",
      access.is_allowed(CLIENT) is False)
check("and now the loop is refused too — no more heartbeats",
      user_loop._entitled(CLIENT) is False)
check("start_all() will not resurrect it",
      user_loop.start(CLIENT) is False)
check("its active flag is cleared",
      user_store.load(CLIENT).get("active") is False)

print("\n── _write never persists the degraded marker ──")
written = {}
access._USE_REDIS = False
_f = access._FILE
access._FILE = os.path.join(os.environ["DATA_DIR"], "access.json")
access._write({"admins": [], "allowed": ["x"], "_degraded": True})
import json  # noqa: E402
written = json.load(open(access._FILE))
check("_degraded is stripped before writing", "_degraded" not in written,
      str(written))
check("real data survives", written.get("allowed") == ["x"])
access._FILE = _f

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL ACCESS-GATE CHECKS PASSED.")
