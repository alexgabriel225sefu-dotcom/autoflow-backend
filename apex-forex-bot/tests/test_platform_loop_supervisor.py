"""Automation that says RUNNING must still be running after a restart.

THE BUG THIS FILE EXISTS TO CATCH, AND IT WAS LIVE IN PRODUCTION

`automation.start` runs the engine loop as a DAEMON THREAD inside the API
process. The process dies, the thread dies — and `active: True` stays in the
store, so the automation record and the dashboard both go on reporting RUNNING
over a loop that no longer exists.

The engine has always had the cure: `start_all` on boot and `start_watchdog`
every 180 seconds. Both are called in `apex/bot.py` and `apex/telegram.py` —
the TELEGRAM entry points — and `platform_server.py` called neither. `bot.py`
is not deployed anywhere, so NOTHING in production revived a platform client's
loop after a deploy, an instance recycle or a crash. The logs show
`[API] signal 15 — shutting down` on an ordinary day.

A client pressed Start, saw RUNNING, and stopped trading at the next restart
without being told. Same shape as the two bugs fixed earlier this week: the
screen asserting a state that is not true.

WHAT MAKES THIS TEST WORTH ANYTHING

It does not ask whether the supervisor FUNCTION exists. A function nothing
calls is exactly what the engine's watchdog was from this server's point of
view. It asserts the wiring: that `main` calls it, that a boot revives a
platform account marked active, that the periodic cycle does too, and — the
half that protects the other product — that a Telegram account is left alone.

Run: python3 tests/test_platform_loop_supervisor.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-supervisor-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
# Short enough that the periodic cycle can be observed without a slow test.
os.environ["A4T_SUPERVISE_INTERVAL_S"] = "1"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


import platform_server as PS                                # noqa: E402
from apex import user_loop, user_store                      # noqa: E402
from apex.platform import automation as AUTO                # noqa: E402
from apex.platform import ctrader_link as CTL               # noqa: E402

PLATFORM_USER = "11111111-2222-4333-8444-555555555555"
TELEGRAM_USER = "99887766"

# ── 1. the supervisor is WIRED, not merely written ──────────────────────────
# The failure mode being guarded is precisely "the cure exists and nobody
# calls it", which is what start_all was to this server for its whole life.
print("\n[1] the supervisor is called at startup, not just defined")
src = open(os.path.join(ROOT, "platform_server.py"), encoding="utf-8").read()
check("the supervisor exists", "def _supervise_platform_loops" in src)
_main = src.split("def main(")[1]
check("and main() calls it",
      "_supervise_platform_loops()" in _main,
      "a supervisor nothing calls is the bug, not the fix")
check("and it runs on its own thread, so it cannot block serving",
      "loop-supervisor" in src)
# THE SPLIT THAT tests/test_platform_server.py INSISTED ON, and was right to.
# The first version of this fix called user_loop.start from the server, which
# skips automation._preflight — the licence, the rule, the connection and the
# mode the BROKER confirms. A weekend is long enough for a trial to lapse.
check("the server does not reach the engine itself",
      "user_loop.start(" not in src,
      "reviving past _preflight starts a loop on nobody's authority")
check("it calls the platform's supervisor instead",
      "_auto.supervise()" in src,
      "the schedule belongs here, the decision does not")

# ── 2. a dead loop is revived THROUGH THE PREFLIGHT ─────────────────────────
print("\n[2] a platform loop whose thread died is started again")
calls = []
_real_start = AUTO.start
_real_all = user_store.all_active
_real_is_platform = CTL.is_platform_account
_real_read = AUTO._read
_real_is_running = user_loop.is_running
_real_stop = user_loop.stop
_real_write = AUTO._write
_real_lic = AUTO._licence_active
try:
    user_store.all_active = lambda: [PLATFORM_USER, TELEGRAM_USER]
    CTL.is_platform_account = lambda uid: str(uid) == PLATFORM_USER
    # Revival is only for an active licence. This user stands in for one.
    AUTO._licence_active = lambda uid: True
    AUTO._read = lambda uid: {"state": AUTO.RUNNING, "ruleDocId": "rule-1"}
    user_loop.is_running = lambda uid: False          # the process restarted
    AUTO.start = lambda uid, rid, **kw: calls.append((str(uid), rid, kw))

    alive, revived = AUTO.supervise()
    check("the platform account is revived", revived == 1, f"revived={revived}")
    check("and it is the right rule",
          calls and calls[0][:2] == (PLATFORM_USER, "rule-1"), str(calls))
    # The whole reason the server was not allowed to do this itself.
    check("the revival goes through automation.start, so _preflight runs",
          calls and calls[0][2].get("revive") is True,
          "a revival that skips the preflight starts a loop unchecked")
    check("the Telegram account is NOT touched",
          all(c[0] != TELEGRAM_USER for c in calls), str(calls))

    print("\n[3] a healthy loop is left alone")
    calls.clear()
    user_loop.is_running = lambda uid: True
    alive, revived = AUTO.supervise()
    check("nothing is restarted", revived == 0 and not calls, str(calls))
    check("and it is counted as alive", alive == 1, f"alive={alive}")

    print("\n[4] a record that is not RUNNING is not resurrected")
    calls.clear()
    user_loop.is_running = lambda uid: False
    AUTO._read = lambda uid: {"state": AUTO.STOPPED, "ruleDocId": "rule-1"}
    alive, revived = AUTO.supervise()
    check("a stopped automation stays stopped", revived == 0 and not calls,
          "the client stopped it on purpose")

    print("\n[4b] revive actually gets PAST the idempotency guards")
    # THE BUG THIS SECTION EXISTS FOR, AND IT SHIPPED FOR TWO MINUTES.
    #
    # Everything above mocks `AUTO.start` and asserts only that supervise
    # CALLS it with revive=True. That is a claim about a call, not about
    # behaviour — and the real `start` has TWO idempotency guards. The first
    # fix exempted one. The second still raised ALREADY_RUNNING, so the
    # supervisor refused every account it was built to rescue, and production
    # logged "0 alive, 0 revived" beside the refusal.
    #
    # So this drives the REAL function far enough to prove the guards let a
    # revival through. It fails at the first check that needs a store, which
    # is already past both guards — reaching NO_RULE or any later refusal
    # means the guards did not stop it. ALREADY_RUNNING means they did.
    AUTO.start = _real_start
    AUTO._read = lambda uid: {"state": AUTO.RUNNING, "ruleDocId": "rule-1"}
    got = None
    try:
        AUTO.start(PLATFORM_USER, "rule-1", revive=True)
    except AUTO.AutomationRefused as e:
        got = e.code
    except Exception as e:                                   # noqa: BLE001
        got = type(e).__name__
    check("a revival is not refused as ALREADY_RUNNING",
          got != "ALREADY_RUNNING",
          "revive=True must clear BOTH idempotency guards")
    # And the guard still protects the case it is actually for: a client
    # starting a second rule while one runs.
    got2 = None
    try:
        AUTO.start(PLATFORM_USER, "a-different-rule")
    except AUTO.AutomationRefused as e:
        got2 = e.code
    check("but a normal start of a second rule still IS refused",
          got2 == "ALREADY_RUNNING", str(got2))

    print("\n[4c] a lapsed licence is marked blocked and is not started")
    calls.clear()
    stopped = []
    written = []
    AUTO._licence_active = lambda uid: False
    user_loop.is_running = lambda uid: True
    user_loop.stop = lambda uid: stopped.append(str(uid)) or True
    AUTO._write = lambda uid, rec: written.append((str(uid), dict(rec))) or rec
    AUTO.start = lambda *a, **k: calls.append("start")
    alive, revived = AUTO.supervise()
    check("an unlicensed account is not started", not calls and revived == 0,
          str(calls))
    check("a loop that is still ticking is stopped",
          stopped == [PLATFORM_USER], str(stopped))
    check("the stored state is blocked, not running",
          written and written[-1][1].get("state") == "blocked", str(written))
    AUTO._licence_active = lambda uid: True

    print("\n[5] a refusal is survivable and does not stop the sweep")
    # A lapsed trial is the expected case over a weekend. It must refuse, say
    # why, and leave the record alone — not crash the supervisor.
    user_loop.is_running = lambda uid: False
    AUTO._read = lambda uid: {"state": AUTO.RUNNING, "ruleDocId": "rule-1"}
    def _refuse(uid, rid, **kw):
        raise AUTO.AutomationRefused("NOT_ENTITLED", "the trial has ended")
    AUTO.start = _refuse
    alive, revived = AUTO.supervise()
    check("a refused revival is not counted", revived == 0, f"{revived}")
    check("and the sweep returned rather than raising", alive == 0)
finally:
    AUTO.start = _real_start
    AUTO._licence_active = _real_lic
    AUTO._write = _real_write
    user_store.all_active = _real_all
    CTL.is_platform_account = _real_is_platform
    AUTO._read = _real_read
    user_loop.is_running = _real_is_running
    user_loop.stop = _real_stop

# ── 6. the supervisor is not silent when healthy ────────────────────────────
# The first version printed only on boot and on a revival, so a healthy cycle
# said nothing — and a supervisor quietly working looked, from the logs,
# exactly like one that had died. That is the ambiguity this whole mechanism
# exists to remove, reintroduced one level up.
print("\n[6] a healthy supervisor still says so, periodically")
check("it has a heartbeat interval",
      "_HEARTBEAT_EVERY" in src,
      "silence must not be the only evidence of health")
_body = src.split("def _supervise_platform_loops(")[1]
check("and the periodic cycle can print without a revival",
      "revived or _cycle % _HEARTBEAT_EVERY" in _body,
      "printing only on a revival leaves a dead supervisor indistinguishable "
      "from a quiet one")
check("while a revival is still reported immediately",
      _body.index("if revived") < _body.index("_HEARTBEAT_EVERY == 0"),
      "a revival must not wait for the next heartbeat to be visible")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All loop-supervisor checks passed.")
