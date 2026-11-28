"""The post-loss cooldown must honour the symbol it is asked about.

strategies.py defined `cooldown_remaining` twice. The second definition (no
`symbol` argument, global session only) silently replaced the first, so the
per-symbol cooldown the module documents could not be asked for: passing
`symbol=` raised TypeError, and a loss on one instrument could only ever be
read as a cooldown on the whole account.

Run: python tests/test_cooldown_symbol.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("CTRADER_CLIENT_SECRET", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-cooldown-")

from apex import strategies  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


USER = "u_cooldown_symbol"
strategies._sessions.pop(USER, None)
strategies.get_symbol_session(USER, "EURUSD")["lastLossAt"] = time.time() - 60

try:
    eur = strategies.cooldown_remaining(5, USER, symbol="EURUSD")
    other = strategies.cooldown_remaining(5, USER, symbol="XAUUSD")
    glob = strategies.cooldown_remaining(5, USER)
except TypeError as exc:
    eur = other = glob = None
    check("cooldown_remaining accepts a symbol", False, str(exc))

if eur is not None:
    check("a recent loss on EURUSD blocks EURUSD", eur > 0, eur)
    check("it does not block another symbol", other == 0, other)
    check("it does not block the account-wide read", glob == 0, glob)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the cooldown is read per symbol.")
