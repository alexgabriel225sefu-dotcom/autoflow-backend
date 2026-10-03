"""Every handler the control plane exposes must be classified, deliberately.

WHY

level_of() returns 3 for anything it does not recognise, and level 3 is
refused unless financial actions are explicitly enabled. That default is
right — an unclassified action is an unreviewed one, and guessing "probably a
read" would be how a write slips through.

But it also means adding a handler and forgetting the classification produces
a confusing failure rather than an obvious one. `trade_journal` shipped, was
registered as a handler, and answered every call with
"LEVEL_3_FINANCIAL_DISABLED — financial actions are not available" — for a
function that only reads rows out of the store.

So this test asserts the direction that matters: every handler the control
plane dispatches is classified. The reverse is deliberately not asserted —
see section 2.

WHAT IT DOES NOT DO

It does not decide which level anything belongs to. A test that inferred the
level would just be a second, weaker copy of the judgement the sets already
encode — and it would happily agree that a new financial action is a read.
Choosing the level stays a human decision; this only refuses to let one be
skipped.

Run: python tests/test_action_levels_complete.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-levels-")

from apex import control, control_actions  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


handlers = set(control_actions.build())
classified = (control.LEVEL_1_READ | control.LEVEL_2_CONTROLLED
              | control.LEVEL_3_FINANCIAL)

print(f"\n{len(handlers)} handlers, {len(classified)} classified actions")

print("\n1. No handler is left to the fail-closed default")
missing = sorted(handlers - classified)
check("every handler appears in exactly one level set", not missing,
      f"unclassified, so refused as level 3: {missing}")

print("\n2. The reverse does NOT hold, and must not be asserted")
# A first draft of this test also demanded that every classified name be a
# handler. That is false by design, and the failure it produced was the test's
# fault, not the code's: several MCP tools never reach the command queue at
# all. bot_alive reads the heartbeat key straight from Redis; recent_events,
# audit_log and recent_commands read their lists directly; bot_status maps to
# the action named "status". Those names appear in the level sets as
# documentation of the surface, not as dispatch targets.
#
# So the guarantee is one-directional on purpose: a handler must be
# classified, but a classification need not be a handler.
outside = sorted(classified - handlers)
print(f"     ({len(outside)} classified names are served outside build(): "
      f"{', '.join(outside) if outside else 'none'})")

print("\n3. The sets do not overlap")
for a, b, an, bn in (
        (control.LEVEL_1_READ, control.LEVEL_2_CONTROLLED, "1", "2"),
        (control.LEVEL_1_READ, control.LEVEL_3_FINANCIAL, "1", "3"),
        (control.LEVEL_2_CONTROLLED, control.LEVEL_3_FINANCIAL, "2", "3")):
    both = sorted(a & b)
    check(f"level {an} and level {bn} are disjoint", not both,
          f"in both: {both} — level_of would silently pick the lower one")

print("\n4. The read set really is read-only, by name")
# A cheap guardrail, not a proof: a verb that changes something has no business
# in the set that skips the operator check entirely.
WRITE_VERBS = ("open_", "close", "force", "set_", "restart", "power",
               "send_", "grant", "revoke", "purge", "delete", "refresh_")
suspect = sorted(a for a in control.LEVEL_1_READ
                 if a.startswith(WRITE_VERBS) and not a.startswith("ops_"))
check("no level-1 action is named like a write", not suspect, str(suspect))

print("\n5. trade_journal specifically — the one that prompted this")
check("it is a handler", "trade_journal" in handlers)
check("it is level 1", control.level_of("trade_journal") == 1)
ok, reason = control.authorize("trade_journal", {})
check("it authorizes with no operator and no confirmation",
      ok is True and reason == "LEVEL_1_READ", f"{ok} {reason}")

print("\n6. An unknown action is still refused")
check("an invented action is level 3", control.level_of("drain_account") == 3)

print("\n" + "=" * 60)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL LEVEL-COMPLETENESS CHECKS PASSED.")
