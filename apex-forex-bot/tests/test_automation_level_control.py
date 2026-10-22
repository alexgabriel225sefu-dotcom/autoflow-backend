"""The automation level a client picks is the level the engine runs at.

WHY THIS EXISTS

The platform could service three levels (signals, approval, full) and had no
way to ask for one: every rule omitted the field and ran at `full`. The Telegram
bot let a client choose who acts on a setup, and the choice that matters most
on a money product is "tell me, don't trade" or "ask me first".

The danger of a control here is the one the comments in `engine_config` warn
about: `_automation_level` falls back to `full` for any name it does not
know. A rule carrying `"aproval"` would therefore PLACE ORDERS for a client who
asked to be asked. So the name is refused at the rule boundary, and these tests
measure what the ENGINE resolves from what the rule says, not only what is
written.

WHAT THESE TESTS WILL NOT ACCEPT

* A level the engine does not resolve to the one the rule named.
* A misspelt or empty level that validates.
* A rule stored before this field existed running at anything but `full`.
* The two lists of levels drifting apart.
* The level lost on the PUT that follows creation (the strategy page's path).

Run: python3 tests/test_automation_level_control.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-level-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


import apex.automation as ENGINE                             # noqa: E402
from apex.platform import engine_config as EC               # noqa: E402
from apex.platform import ruledoc as RD                     # noqa: E402
from apex.platform import store as PS                       # noqa: E402

USER = "level-user"
COND = {"id": "rsi", "params": {"period": 14, "comparator": "below",
                                "value": 30}}


def doc(level="__absent__"):
    d = RD.blank(user_id=USER, account_id="901", symbols=["EURUSD"],
                 timeframe="5m")
    d["entry"] = {"mode": "all", "conditions": [COND]}
    d["sides"] = "BUY"
    if level == "__absent__":
        d.pop("automationLevel", None)
    else:
        d["automationLevel"] = level
    return d


def level_problems(d):
    return [p for p in RD.validate(d, known_condition_ids={"rsi"})
            if str(p).startswith("automationLevel")]


def engine_resolves(d):
    """What the ENGINE runs this rule at — not what translate happens to write."""
    applied, _ = EC.translate(d)
    return ENGINE.mode(applied), ENGINE.executes(applied)


# ── 1. each level reaches the engine as itself ──────────────────────────────
print("\n[1] the engine resolves exactly the level the rule names")
for lvl, executes in (("signals", False), ("approval", False), ("full", True)):
    mode, ex = engine_resolves(doc(lvl))
    check(f"{lvl}: engine mode is {lvl}", mode == lvl, mode)
    check(f"{lvl}: places orders only when it is full "
          f"(executes={executes})", ex is executes, str(ex))

# ── 2. a new draft says its level out loud ──────────────────────────────────
print("\n[2] a blank draft carries the level it will run at")
b = RD.blank(user_id=USER, account_id="901")
check("it is present, not implied", "automationLevel" in b, str(sorted(b)))
check("and it is the behaviour the platform already had (full)",
      b.get("automationLevel") == "full", str(b.get("automationLevel")))

# ── 3. a rule from before the field existed behaves as it always did ────────
print("\n[3] an old rule with no level still runs at full, and still validates")
mode, ex = engine_resolves(doc())
check("absent resolves to full", mode == "full" and ex is True, f"{mode} {ex}")
check("absent is not a validation problem", level_problems(doc()) == [],
      str(level_problems(doc())))

# ── 4. a bad name is refused, because the fallback would be `full` ──────────
print("\n[4] a level nobody can service is refused, not defaulted")
for bad in ("aproval", "Approval ", "", "manual", "none", 1, True, ["full"]):
    check(f"{bad!r} is a validation problem", level_problems(doc(bad)) != [],
          str(level_problems(doc(bad))))
for ok in ("signals", "approval", "full"):
    check(f"{ok!r} validates", level_problems(doc(ok)) == [],
          str(level_problems(doc(ok))))
# The reason the refusal exists, demonstrated rather than asserted:
mode, ex = engine_resolves(doc("aproval"))
check("(without it, a typo for approval would TRADE — this is what the "
      "refusal prevents)", mode == "full" and ex is True, f"{mode} {ex}")

# ── 5. the two lists of levels cannot drift ─────────────────────────────────
print("\n[5] the rule may name exactly the levels the platform services")
check("ruledoc names what engine_config services",
      set(RD.AUTOMATION_LEVELS) == set(EC.SERVICEABLE_LEVELS),
      f"{RD.AUTOMATION_LEVELS} vs {EC.SERVICEABLE_LEVELS}")
check("and the engine knows every one of them",
      set(RD.AUTOMATION_LEVELS) <= set(ENGINE.MODES), str(ENGINE.MODES))

# ── 6. the choice survives the save path a browser uses ─────────────────────
print("\n[6] the level survives create, patch and read-back")
d = doc("approval")
rid = d["ruleDocId"]
PS.create(USER, d)
check("stored as created", PS.get(USER, rid).get("automationLevel") == "approval")
PS.save_draft(USER, {"ruleDocId": rid, "automationLevel": "signals"})
check("a PUT changes it", PS.get(USER, rid).get("automationLevel") == "signals")
PS.save_draft(USER, {"ruleDocId": rid, "name": "renamed"})
check("a PUT about something else does not reset it",
      PS.get(USER, rid).get("automationLevel") == "signals",
      str(PS.get(USER, rid).get("automationLevel")))

# ── 7. the API copies it on creation ────────────────────────────────────────
print("\n[7] POST /rules does not drop the field")
src = open(os.path.join(ROOT, "apex", "platform", "api.py")).read()
check("api._create lists automationLevel among the copied fields",
      '"automationLevel"' in src.split("def _create", 1)[1].split("def _rule_action", 1)[0])

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All automation-level checks passed.")
