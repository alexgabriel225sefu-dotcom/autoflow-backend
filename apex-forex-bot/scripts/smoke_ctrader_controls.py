"""The automation CONTROLS against a real cTrader demo account.

WHY THIS IS A SECOND SCRIPT

`scripts/smoke_ctrader_demo.py` is read-only by construction, and a test walks
its AST to keep it that way. This one is the opposite: start, pause, resume and
stop are the only part of the platform that CHANGES something at the broker
rather than reading from it, and `docs/RELEASE_READINESS.md` gate 1 is open
precisely because they have never been sent to cTrader. Every test of them runs
against a stub.

Mixing the two would have cost the read script its guarantee, so they are
separate files with opposite contracts, and `tests/test_smoke_harness.py`
asserts both.

WHAT STARTING AUTOMATION ACTUALLY DOES

`automation.start` hands the account to the trading engine (`user_loop.start`).
The engine then evaluates the rule and MAY OPEN A DEMO POSITION. That is the
product working, not a side effect — but it is the reason this script asks for
a second, separate confirmation. Knowing that an account is a demo account and
agreeing to trade on it are two different statements.

It places no order itself. It calls the four control functions and reads the
state they leave behind.

WHAT IT REFUSES

It will not run unless the operator confirms BOTH that the account is demo and
that automation may be started. It refuses if live execution is anything but
off, if the selected account's mode is not demo — whatever the environment says
— and if automation is ALREADY running, because then the loop belongs to
somebody else and stopping it at the end would be destructive.

IT ALWAYS STOPS WHAT IT STARTED

The stop runs in a `finally`, including after a failed step and after a crash,
and the final state is asserted and printed. A smoke test that leaves a trading
loop running because it failed halfway is worse than no smoke test.

RUN IT

    export SMOKE_CONFIRM_DEMO_ONLY=yes
    export SMOKE_CONFIRM_START_AUTOMATION=yes
    export SMOKE_USER_ID=<the Supabase user id>
    export SMOKE_RULE_ID=<an ACTIVE ruleDocId>   # required
    cd apex-forex-bot && python3 scripts/smoke_ctrader_controls.py

EXIT CODES

    0  every step passed, and automation is stopped
    1  a step failed. Read the final state line before anything else
    2  refused to run, and said why. Nothing was contacted
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIRM_DEMO = "SMOKE_CONFIRM_DEMO_ONLY"
CONFIRM_START = "SMOKE_CONFIRM_START_AUTOMATION"
DEMO = "demo"
_YES = ("yes", "y", "true")


class Refused(RuntimeError):
    """The script will not start. Distinct from a step that failed."""


def guard_env(env=None):
    """The refusals that need nothing imported. Returns (user_id, rule_id).

    Runs BEFORE importing apex, for the same reason as the read script:
    `apex.platform.store` refuses at import time without TOKEN_ENCRYPTION_KEY,
    so an operator who merely forgot a confirmation would otherwise be told
    about encryption — a true statement about a different problem, naming the
    wrong variable to set.
    """
    env = os.environ if env is None else env

    if (env.get(CONFIRM_DEMO) or "").strip().lower() not in _YES:
        raise Refused(
            f"{CONFIRM_DEMO} is not set to 'yes'. This talks to a real broker "
            f"account, so it will not start until an operator states that the "
            f"account is a DEMO account")

    # Deliberately a SECOND variable. The read script's confirmation says "this
    # account is demo". This one says "you may trade on it", and the engine may
    # open a position once started. One variable covering both would let an
    # operator who meant the first grant the second.
    if (env.get(CONFIRM_START) or "").strip().lower() not in _YES:
        raise Refused(
            f"{CONFIRM_START} is not set to 'yes'. Starting automation hands "
            f"the account to the trading engine, which may OPEN A DEMO "
            f"POSITION. That is a separate statement from 'this is a demo "
            f"account', so it needs its own confirmation")

    user_id = (env.get("SMOKE_USER_ID") or "").strip()
    if not user_id:
        raise Refused("SMOKE_USER_ID is not set — there is no client whose "
                      "automation to exercise")

    rule_id = (env.get("SMOKE_RULE_ID") or "").strip()
    if not rule_id:
        raise Refused(
            "SMOKE_RULE_ID is not set. The controls need an ACTIVE rule: a "
            "draft has never been validated and frozen, so there are no terms "
            "to trade and `start` would refuse anyway")

    if not (env.get("TOKEN_ENCRYPTION_KEY") or "").strip():
        raise Refused("TOKEN_ENCRYPTION_KEY is not set, so the stored broker "
                      "token cannot be decrypted. Run this where the "
                      "deployment's environment is")

    return user_id, rule_id


if __name__ == "__main__":
    try:
        guard_env()
    except Refused as _e:
        print(f"REFUSED: {_e}")
        sys.exit(2)

from apex import redact                                     # noqa: E402

# Before anything can print. Installing this after the first output would leave
# exactly the line that carried the token.
redact.install()

from apex.platform import automation as _auto               # noqa: E402
from apex.platform import ctrader_link as _link             # noqa: E402
from apex.platform import entitlement as _ent               # noqa: E402
from apex.platform import journal_store as _jstore          # noqa: E402
from apex.platform import store as _store                    # noqa: E402

RUNNING, PAUSED, STOPPED = "running", "paused", "stopped"

# The control sequence, named as data so a test can assert the order without
# running any of it, and so adding a control here is a visible diff.
SEQUENCE = ("status", "start", "start_again", "pause", "resume", "stop",
            "stop_again")


def mask_ctid(ctid):
    """An account number is not a credential, and it does identify a person."""
    s = str(ctid or "")
    return f"…{s[-3:]}" if len(s) > 3 else s


def guard(env=None):
    """Every refusal, including the ones that need the platform imported."""
    user_id, rule_id = guard_env(env)

    if _ent.live_execution_enabled() is not False:
        raise Refused(
            "the platform reports live execution as enabled. This script's "
            "demo-only guarantee assumes a release that cannot place a live "
            "order, so it stops rather than assuming")

    rule = _store.get(user_id, rule_id)          # raises NotFound — ownership
    if rule.get("state") != "active":
        raise Refused(
            f"rule {rule_id} is {rule.get('state')!r}, not active. Activate it "
            f"first — `start` would refuse, and the refusal would be the only "
            f"thing this run proved")

    status = _link.public_status(user_id)
    selected = (status or {}).get("selected") or {}
    if not selected.get("ctid"):
        raise Refused("a cTrader account is connected but none is selected")
    if selected.get("mode") != DEMO:
        raise Refused(
            f"the selected account is {selected.get('mode')!r}, not {DEMO!r}. "
            f"This script refuses to touch anything else, whatever the "
            f"environment says")

    state = (_auto.status(user_id) or {}).get("state")
    if state != STOPPED:
        raise Refused(
            f"automation is already {state!r}. That loop was started by "
            f"somebody else, and this script stops what it starts — so "
            f"running now would stop their automation. Stop it deliberately "
            f"first, or wait")

    return user_id, rule_id, selected


class Report:
    """Steps and outcomes. Everything printed goes through scrub()."""

    def __init__(self, out=None):
        self.out = out if out is not None else sys.stdout
        self.failures = []
        self.steps = []

    def say(self, line):
        print(redact.scrub(line), file=self.out)

    def step(self, name, ok, detail=""):
        self.steps.append((name, bool(ok)))
        if not ok:
            self.failures.append(name)
        self.say(f"  {'PASS' if ok else 'FAIL'}  {name}"
                 + (f"  —  {detail}" if detail else ""))
        return bool(ok)


def _attempt(rep, name, call):
    """Call a control; a raised exception becomes a failed step.

    A traceback here would abort the run before the `finally` that stops
    automation had printed anything, so the operator would be left not knowing
    whether a loop is still running. The step fails under its own name instead.
    """
    try:
        return call()
    except Exception as e:                                  # noqa: BLE001
        rep.step(name, False, f"{type(e).__name__}: {redact.scrub(str(e))}")
        return None


def _journal_statuses(user_id, limit=25):
    """The statuses this client's journal records, newest first.

    Uses `journal_store.query`, which is the function that exists. An earlier
    draft of this called a `recent()` that does not, inside a bare `except`
    returning [] — so a missing API would have been reported as "no journal
    rows", which is a claim about the product rather than about the script.
    Exceptions propagate here and become a failed step under their own name.
    """
    page = _jstore.query(user_id, limit=limit) or {}
    return [str(r.get("status") or "") for r in (page.get("entries") or [])]


def run(user_id, rule_id, *, report=None, controls=None):
    """Walk the control sequence. Always leaves automation stopped."""
    rep = report or Report()
    c = dict({"status": _auto.status, "start": _auto.start,
              "pause": _auto.pause, "resume": _auto.resume,
              "stop": _auto.stop}, **(controls or {}))

    try:
        before = _attempt(rep, "automation starts from stopped",
                          lambda: c["status"](user_id))
        if before is None:
            return rep
        rep.step("automation starts from stopped",
                 before.get("state") == STOPPED, str(before.get("state")))

        out = _attempt(rep, "start is accepted",
                       lambda: c["start"](user_id, rule_id))
        if out is not None:
            rep.step("start is accepted", out.get("state") == RUNNING,
                     str(out.get("state")))
            rep.step("and it reports that it started, not that it was already",
                     out.get("started") is True
                     and out.get("alreadyRunning") is False,
                     f"started={out.get('started')} "
                     f"already={out.get('alreadyRunning')}")
            rep.step("and the running rule is the one asked for",
                     out.get("ruleDocId") == rule_id, str(out.get("ruleDocId")))
            # The mode is re-read from the record the engine was handed, not
            # from what this script believes.
            rep.step("and the recorded mode is DEMO",
                     out.get("mode") == DEMO, str(out.get("mode")))

        # A double-tapped button, a retried request and a second tab must not
        # produce a second loop against one account.
        again = _attempt(rep, "a second start is idempotent, not a second loop",
                         lambda: c["start"](user_id, rule_id))
        if again is not None:
            rep.step("a second start is idempotent, not a second loop",
                     again.get("alreadyRunning") is True
                     and again.get("started") is False,
                     f"started={again.get('started')} "
                     f"already={again.get('alreadyRunning')}")
            rep.step("and it is still the same rule running",
                     again.get("ruleDocId") == rule_id,
                     str(again.get("ruleDocId")))

        paused = _attempt(rep, "pause is accepted",
                          lambda: c["pause"](user_id))
        if paused is not None:
            rep.step("pause is accepted", paused.get("state") == PAUSED,
                     str(paused.get("state")))
            # A 'paused' that forgot the rule could not be resumed, and a
            # 'paused' that left the loop ticking would be the most dangerous
            # word on the screen.
            rep.step("and pause remembers which rule was running",
                     paused.get("ruleDocId") == rule_id,
                     str(paused.get("ruleDocId")))

        resumed = _attempt(rep, "resume is accepted",
                           lambda: c["resume"](user_id))
        if resumed is not None:
            rep.step("resume is accepted", resumed.get("state") == RUNNING,
                     str(resumed.get("state")))
            rep.step("and it resumed the remembered rule",
                     resumed.get("ruleDocId") == rule_id,
                     str(resumed.get("ruleDocId")))

        # The journal is what the client sees afterwards, so a control that
        # worked but recorded nothing is a control they cannot audit. Two
        # starts are expected, not three: the idempotent second start returns
        # before recording anything, and resume goes through start.
        seen = _attempt(rep, "the journal records the controls",
                        lambda: _journal_statuses(user_id))
        if seen is not None:
            rep.step("the journal records the controls",
                     seen.count(_jstore._j.AUTOMATION_STARTED) >= 2
                     and _jstore._j.AUTOMATION_PAUSED in seen,
                     ",".join(seen[:6]) or "no journal rows")
    finally:
        # ALWAYS. Including after a failed step, and including after a crash:
        # leaving a trading loop running because the script gave up is worse
        # than any failure it could report.
        final = _attempt(rep, "stop is accepted", lambda: c["stop"](user_id))
        if final is not None:
            rep.step("stop is accepted", final.get("state") == STOPPED,
                     str(final.get("state")))
            rep.step("and stopping clears the rule, rather than remembering it",
                     final.get("ruleDocId") in (None, ""),
                     str(final.get("ruleDocId")))
        twice = _attempt(rep, "stopping something stopped is fine",
                         lambda: c["stop"](user_id))
        if twice is not None:
            rep.step("stopping something stopped is fine",
                     twice.get("alreadyStopped") is True,
                     f"already={twice.get('alreadyStopped')}")
        now = _attempt(rep, "and the account is left with nothing running",
                       lambda: c["status"](user_id))
        left = (now or {}).get("state")
        rep.step("and the account is left with nothing running",
                 left == STOPPED, str(left))
        if left != STOPPED:
            rep.say(f"\n  !! AUTOMATION IS {str(left).upper()} AND THIS SCRIPT "
                    f"COULD NOT STOP IT. Stop it from the dashboard before "
                    f"anything else.")
    return rep


def summarise(rep):
    """The last thing an operator reads, and the exit code. 0, or 1.

    Split from main() so it can be tested: main() cannot be exercised without a
    broker, and the summary is where a half-finished run either says so or
    looks like a pass.
    """
    rep.say("")
    if rep.failures:
        rep.say(f"FAILED ({len(rep.failures)}):")
        for f in rep.failures:
            rep.say(f"  - {f}")
        rep.say("\nThe automation controls are NOT working against the real "
                "broker. Do not record gate 1 as closed.")
        return 1
    rep.say(f"All {len(rep.steps)} control steps passed against a real demo "
            f"account, and automation is stopped.")
    rep.say("Record this in docs/RELEASE_READINESS.md, with the date and the "
            "masked account number.")
    return 0


def main(argv=None):
    rep = Report()
    try:
        user_id, rule_id, selected = guard()
    except Refused as e:
        rep.say(f"\nREFUSED: {redact.scrub(str(e))}")
        rep.say("Nothing was contacted.")
        return 2
    except Exception as e:                                  # noqa: BLE001
        rep.say(f"\nREFUSED: {type(e).__name__}: {redact.scrub(str(e))}")
        rep.say("Nothing was contacted.")
        return 2
    rep.say(f"cTrader demo CONTROLS smoke test — account "
            f"{mask_ctid(selected['ctid'])}, rule {rule_id}")
    rep.say("Starting automation hands the account to the trading engine, "
            "which may open a demo position.")
    rep.say("")
    run(user_id, rule_id, report=rep)
    return summarise(rep)


if __name__ == "__main__":
    sys.exit(main())
