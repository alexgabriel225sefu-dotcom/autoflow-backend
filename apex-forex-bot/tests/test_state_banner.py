"""The state banner is decoration. It must never cost a client an alert.

`_state_line` was added to put "Paper / Demo / LIVE · automation level" on every
screen, which is right — but it then got wired into the trade alerts too, and it
reads two stores to build itself. `_guard_label` in particular reads the
published dash, which on this deployment is a network hop to Upstash. An
f-string is not lazy: the moment that read raised, the whole

    f"⚡ <b>Trade opportunity</b>\n{_state_line(uid, guard=True)}\n..."

blew up before send_to() was ever called, and the client was simply not told
their money had moved. A badge took down the notification it was decorating.

What this pins:
  * nothing inside the banner can escape it — every backing store is allowed
    to fail and the banner still returns a string;
  * an unreadable account reads as UNKNOWN, never as "Paper · simulated".
    `{}.get("paper", True)` is True, so the naive fallback prints the most
    reassuring possible label over a live, real-money account;
  * the alert call sites still ask for the guard line, so this stays a live
    concern rather than one fixed by quietly dropping the feature.

Run: python tests/test_state_banner.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import telegram as tg, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


class _Boom:
    """Stands in for a store that is down, not slow."""

    def __call__(self, *a, **k):
        raise RuntimeError("upstash unreachable")


_real_load, _real_dash = user_store.load, user_loop.get_dash


def _restore():
    user_store.load, user_loop.get_dash = _real_load, _real_dash


print("\n🧪 STATE BANNER — decoration that cannot cost an alert\n")

print("1. Every backing store is allowed to fail")
try:
    user_store.load = _Boom()
    out = tg._state_line(123, guard=True)
    check("user store down → still a string", isinstance(out, str), repr(out))
    check("and it says the mode is unknown", "unknown" in out.lower(), out)
    check("it does NOT claim the account is on paper",
          "paper" not in out.lower(), out)
finally:
    _restore()

try:
    user_loop.get_dash = _Boom()
    out = tg._state_line(123, guard=True)
    check("dash down → still a string", isinstance(out, str), repr(out))
    check("and the guard line degrades to 'no report yet'",
          "no report yet" in out, out)
finally:
    _restore()

try:
    user_store.load = _Boom()
    user_loop.get_dash = _Boom()
    out = tg._state_line(123, guard=True)
    check("both down → still a string", isinstance(out, str), repr(out))
finally:
    _restore()

print("\n2. The honest-label rule, stated directly")
# This is the bug the None case exists for: an empty dict is not an empty
# account, it is an unread one, and .get("paper", True) makes it look safe.
check("{}.get('paper', True) really is True (why {} was unusable)",
      {}.get("paper", True) is True)
check("unread account → unknown, not Paper",
      "unknown" in tg._mode_label(None).lower(), tg._mode_label(None))
check("a genuinely empty record is still Paper",
      "paper" in tg._mode_label({}).lower(), tg._mode_label({}))
check("a live record still reads LIVE",
      "LIVE" in tg._mode_label({"paper": False, "ctrader_env": "live"}),
      tg._mode_label({"paper": False, "ctrader_env": "live"}))
check("a demo record still reads Demo",
      "Demo" in tg._mode_label({"paper": False, "ctrader_env": "demo"}),
      tg._mode_label({"paper": False, "ctrader_env": "demo"}))

print("\n3. The normal path is unchanged")
try:
    user_store.load = lambda _uid: {"paper": False, "ctrader_env": "live"}
    user_loop.get_dash = lambda _uid: {"riskGuard": {"halted": False}}
    out = tg._state_line(123, guard=True)
    check("live account still shows LIVE", "LIVE" in out, out)
    check("and an active guard still shows active", "active" in out, out)
    check("guard=False leaves the guard line off",
          "Risk Guard" not in tg._state_line(123), tg._state_line(123))
    user_loop.get_dash = lambda _uid: {
        "riskGuard": {"halted": True, "reasons": ["daily loss cap"]}}
    out = tg._state_line(123, guard=True)
    check("a halted guard is still reported as HOLDING", "HOLDING" in out, out)
    check("with the reason kept", "daily loss cap" in out, out)
finally:
    _restore()

print("\n4. The alert path still asks for the banner")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "telegram.py"), encoding="utf-8").read()
check("trade alerts embed it", "_state_line(uid, guard=True)" in SRC)
check("the signal alert embeds it too", "_state_line(uid)" in SRC)
check("and it is still wired into many screens",
      SRC.count("_state_line(") >= 15, SRC.count("_state_line("))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the banner cannot swallow an alert.")
