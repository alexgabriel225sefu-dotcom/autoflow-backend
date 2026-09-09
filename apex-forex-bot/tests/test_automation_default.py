"""A brand-new account is not put into unattended trading by default.

WHY THIS TEST EXISTS

`automation.mode()` resolves one setting from two fields, and its docstring
explains the backward-compatibility rule carefully: every existing client
carries `copilot: true|false` and no `automation` key, so the boolean stays
authoritative. That reasoning is sound for every account it describes.

It does not describe a NEW account, which carries neither field. There,
`bool(u.get("copilot"))` is `bool(None)` — False — and False meant "copilot
off, so autopilot on". A fresh account therefore resolved to `full`: the bot
executes on its own. Onboarding (connect → account → style → method → risk)
never asks about automation, and linking a live account writes only
`paper: False`, so this was the state a client reached by following the
advertised flow, without ever choosing it.

THE DISTINCTION THIS TEST PROTECTS

Absent is not False. False is a decision — a client turned copilot off and
kept autopilot — and it still resolves to `full`. Absent is the absence of a
decision, and the answer to "nobody has chosen" must not be the most
permissive level available.

Every other resolution is asserted here too, because the fix is only correct
if it changed exactly one case and left the rest alone.

Run: python tests/test_automation_default.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import automation  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def mode(rec):
    return automation.mode(rec)


print("\n1. Nobody has chosen — the answer is not 'trade unattended'")
check("an empty record resolves to approval", mode({}) == "approval", mode({}))
check("None resolves to approval", mode(None) == "approval", str(mode(None)))
check("a record with unrelated keys only", mode({"paper": False, "risk": 0.02})
      == "approval", mode({"paper": False, "risk": 0.02}))
check("...and it is never the most permissive level",
      mode({}) != "full",
      "the fallback used to land here for every new live account")

print("\n2. An actual decision is still honoured, in both directions")
check("copilot False means the client kept autopilot",
      mode({"copilot": False}) == "full", mode({"copilot": False}))
check("copilot True means approval", mode({"copilot": True}) == "approval",
      mode({"copilot": True}))

print("\n3. An explicit mode still wins where it does not contradict")
check("explicit full", mode({"automation": "full", "copilot": False}) == "full")
check("explicit signals survives — it is not the same as full",
      mode({"automation": "signals", "copilot": False}) == "signals",
      "signals and full are both copilot=False; only the stored mode separates them")
check("explicit approval", mode({"automation": "approval", "copilot": True})
      == "approval")

print("\n4. A contradiction still resolves to the boolean, as documented")
check("boolean True overrides a stored full",
      mode({"automation": "full", "copilot": True}) == "approval",
      "the boolean is the more recent instruction")
check("boolean False overrides a stored approval",
      mode({"automation": "approval", "copilot": False}) == "full")

print("\n5. It never raises and never returns None")
for rec in ({}, None, {"copilot": None}, {"automation": ""},
            {"automation": "nonsense"}, {"automation": None, "copilot": None}):
    got = mode(rec)
    check(f"{str(rec)[:34]:36s} -> {got}", got in automation.MODES, str(got))

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - absence of a choice is not consent to trade alone.")
