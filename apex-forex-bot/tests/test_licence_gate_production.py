"""The licence gate cannot be switched off in production, and the account
badge cannot present a stale reading as a fact.

TWO CONTROLS, ONE THEME: a value that is not currently verifiable must not be
displayed or acted on as though it were.

LICENCE GATE. A missing REQUIRE_LICENSE already defaulted to ON. An explicit
`false` was honoured — so the control that decides who may trade at all could
be removed by anyone with environment access, leaving one variable nobody
re-reads as the only record of that decision. In production it now refuses to
start.

ACCOUNT BADGE. account_mode.resolve() returns (mode, source) and badge() takes
both, because a mode read back out of our own stored flag is not the same
claim as one the broker just made. bot.py passed only the mode, throwing that
distinction away and rendering "🔴 LIVE" for an account nobody could currently
confirm was live.

Run: python tests/test_licence_gate_production.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-licgate-")

from apex import telegram as tg, account_mode as am  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def gate(**env):
    """_license_required() under a given environment. 'REFUSED' if it will not start."""
    saved = {k: os.environ.get(k) for k in ("APP_ENV", "REQUIRE_LICENSE")}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        return tg._license_required()
    except tg.LicenceGateDisabledInProduction:
        return "REFUSED"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


print("\nLICENCE GATE - it cannot be turned off where it matters\n")

print("1. Production")
check("REQUIRE_LICENSE=false REFUSES to start",
      gate(APP_ENV="production", REQUIRE_LICENSE="false") == "REFUSED",
      "the entitlement control can still be switched off")
for spelling in ("false", "FALSE", "0", "no", "No"):
    check(f"…including spelled {spelling!r}",
          gate(APP_ENV="production", REQUIRE_LICENSE=spelling) == "REFUSED")
check("REQUIRE_LICENSE=true is allowed, gate ON",
      gate(APP_ENV="production", REQUIRE_LICENSE="true") is True)
check("a MISSING REQUIRE_LICENSE means the gate is ON",
      gate(APP_ENV="production") is True,
      "a deployment that forgot the variable must not trade unlicensed")

print("\n2. An unset APP_ENV counts as production")
# The deployment that forgot APP_ENV is exactly the one that must not get the
# loose rules, so absence is not evidence of development.
check("unset APP_ENV + REQUIRE_LICENSE=false REFUSES",
      gate(REQUIRE_LICENSE="false") == "REFUSED")
check("unset APP_ENV alone means the gate is ON", gate() is True)

print("\n3. Development may still run open")
for env_name in ("dev", "development", "local", "test"):
    check(f"APP_ENV={env_name} + REQUIRE_LICENSE=false is allowed",
          gate(APP_ENV=env_name, REQUIRE_LICENSE="false") is False)

print("\n4. The refusal explains itself")
try:
    gate(APP_ENV="production", REQUIRE_LICENSE="false")
    os.environ.update({"APP_ENV": "production", "REQUIRE_LICENSE": "false"})
    tg._license_required()
    check("it raises", False)
except tg.LicenceGateDisabledInProduction as e:
    msg = str(e)
    check("it raises", True)
    check("it names the variable", "REQUIRE_LICENSE" in msg, msg[:90])
    check("it says what to do instead", "APP_ENV" in msg, msg[:120])
finally:
    for k in ("APP_ENV", "REQUIRE_LICENSE"):
        os.environ.pop(k, None)
    os.environ["APP_ENV"] = "test"

print("\nACCOUNT BADGE - five cases, and UNVERIFIED is never DEMO\n")

CASES = (
    ("broker confirms live",      am.LIVE,      "broker",     "🔴 LIVE",                  True),
    ("broker confirms demo",      am.DEMO,      "broker",     "🧪 DEMO",                  False),
    ("broker down + stored live", am.LIVE,      "stored-env", "🔴 LIVE (unconfirmed)",    True),
    ("broker down + stored demo", am.DEMO,      "stored-env", "🧪 DEMO (unconfirmed)",    False),
    ("no broker information",     "UNVERIFIED", None,         "🟠 VERIFICATION REQUIRED", False),
)
for label, mode, source, want_badge, want_real in CASES:
    got = am.badge(mode, source)
    check(f"{label}: {want_badge}", got == want_badge, f"got {got!r}")
    check(f"{label}: realMoney={want_real}", am.is_real_money(mode) is want_real)

print("\n5. UNVERIFIED never borrows another label")
unver = am.badge("UNVERIFIED", None)
check("it is not DEMO", "DEMO" not in unver, unver)
check("it is not LIVE", "LIVE" not in unver, unver)
check("and it is never real money", am.is_real_money("UNVERIFIED") is False)

print("\n6. A stored reading is always marked unconfirmed")
for mode in (am.LIVE, am.DEMO):
    check(f"stored {mode} says so", "unconfirmed" in am.badge(mode, "stored-env"))
    check(f"broker-confirmed {mode} does not",
          "unconfirmed" not in am.badge(mode, "broker"))

print("\n7. bot.py actually passes the source")
BOT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "bot.py"), encoding="utf-8").read()
check("badge() is called with both values",
      "_account_mode.badge(_m[0], _m[1])" in BOT,
      "the Mini App payload throws the source away again")
check("…and never with the mode alone",
      "_account_mode.badge(_m[0])" not in BOT)
check("the payload carries mode, source, badge and realMoney",
      all(f'"{f}"' in BOT for f in ("mode", "source", "badge", "realMoney")))

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL LICENCE-GATE AND BADGE CHECKS PASSED.")
