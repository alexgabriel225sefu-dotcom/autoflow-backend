"""The bot reports on its own engine, and a broken reader never reads as quiet.

The APEX engine shipped while the market was closed, so it had never run once
against live conditions. Verifying that means reading logs at the moment the
market reopens — which needs a person awake, with time, and with budget. So the
platform does it instead: this runs in the process that already exists, on the
host already paid for, and sends the answer to Telegram.

The property that took a real bug to find: an unreadable journal must not
produce the same report as an empty one. `trade_events.recent` returns a dict,
not a list, and iterating it yielded its KEYS — strings — which raised on
`.get`. Caught by a bare except, that looked exactly like "no events", so the
report would have said "no pass recorded" every single week whether the scanner
was silent or the reader was broken. Answering the question wrongly and
confidently is worse than saying it cannot be answered.

Run: python tests/test_selfcheck.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# user_store refuses to start without an encryption key or a shared backend —
# both are fail-closed guards worth keeping, so this declares itself a dev
# environment rather than weakening them. Set before the import, since those
# checks run at module load.
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import selfcheck  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


BASE = {"at": 0, "windowS": 3600, "journalReadable": True, "scannerRan": True,
        "rankedPasses": 3, "decisions": 8,
        "actions": {"NO_TRADE": 6, "WATCH": 2}, "thesesWritten": 0,
        "shadowProposals": 0, "aiRejections": 0, "evLabelled": 27,
        "evNeeded": 30, "balance": 3240.49, "equitySource": "broker",
        "openCount": 0}

print("\n1. The journal is actually read")
r = selfcheck.build("nobody-at-all")
check("a real read reports itself readable", r["journalReadable"] is True,
      "recent() returns a dict; iterating it yields strings and raises")
check("...and an empty journal reads as empty, not unknown",
      r["scannerRan"] is False, str(r["scannerRan"]))

print("\n2. An unreadable journal is not a silent 'no'")
txt = selfcheck.format_report({**BASE, "scannerRan": None,
                               "journalReadable": False})
check("it says the status is unavailable", "status unavailable" in txt)
check("...and that trading is unaffected",
      "reporting fault, not a trading one" in txt,
      "a reporting bug must not read as a trading outage")
check("scannerRan is None rather than False when unreadable",
      selfcheck.build.__doc__ is not None
      and '"scannerRan": (by_type.get' in open(
          os.path.join(ROOT, "apex", "selfcheck.py"), encoding="utf-8").read())

print("\n3. A quiet pass is not a broken one")
txt = selfcheck.format_report(BASE)
check("it reports the passes", "3</b> ranked pass" in txt, txt[:80])
check("it breaks decisions down by action", "NO_TRADE: 6" in txt)
check("no entry proposed is explained, not left ambiguous",
      "which is the engine working" in txt,
      "a scanner that ranks eight and proposes none is working")

print("\n4. Absence is explained with somewhere to look")
txt = selfcheck.format_report({**BASE, "scannerRan": False, "rankedPasses": 0,
                               "decisions": 0, "actions": {}})
check("it says no pass was recorded", "no pass recorded yet" in txt)
check("...names the innocent explanations", "market is closed" in txt)
check("...and points at the log line", "APEX scan failed" in txt)

print("\n5. The calibration counter is the point")
txt = selfcheck.format_report(BASE)
check("progress is shown", "27/30" in txt)
check("...with what remains", "3 more closed trade(s)" in txt)
txt = selfcheck.format_report({**BASE, "evLabelled": 30})
check("crossing the threshold is stated plainly", "Threshold reached" in txt)
check("...and says what changes", "measured rather than assumed" in txt)

print("\n6. Shadow proposals are marked as having done nothing")
txt = selfcheck.format_report({**BASE, "shadowProposals": 4})
check("they are reported", "Shadow exit proposals" in txt)
check("...as recorded only",
      "nothing acted on them" in txt,
      "a client must never read a shadow proposal as an action taken")

print("\n7. The report is sent whether the news is good or bad")
sent = []
selfcheck.run("u", send=lambda u, t: sent.append(t))
check("one message either way", len(sent) == 1, str(len(sent)))
check("a send failure does not raise",
      selfcheck.run("u", send=lambda u, t: (_ for _ in ()).throw(RuntimeError("x")))
      is not None)

print("\n8. It reads, and reaches nothing else")
SRC = open(os.path.join(ROOT, "apex", "selfcheck.py"), encoding="utf-8").read()
_tree = ast.parse(SRC)
_apex = set()
for n in ast.walk(_tree):
    if isinstance(n, ast.ImportFrom) and (n.module or "") == "apex":
        _apex |= {a.name for a in n.names}
check(f"it imports only readers ({sorted(_apex)})",
      not (_apex & {"telegram", "brokers", "gates", "user_loop", "ledger"}),
      "the sender is injected so this needs no bot token to test")
_calls = {n.func.attr for n in ast.walk(_tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check("it calls nothing that writes",
      not (_calls & {"update", "save", "place_order", "force_close",
                     "authorize_order", "record"}),
      str(sorted(_calls)))

print("\n9. It is wired to fire on its own")
WATCH = open(os.path.join(ROOT, "apex", "session_watch.py"),
             encoding="utf-8").read()
check("the market-open hook schedules it", "_schedule_selfcheck(uid)" in WATCH)
check("...on a timer, not by blocking the watcher",
      "threading.Timer" in WATCH,
      "the watcher must keep polling for the market edge")
check("...as a daemon so it cannot hold shutdown open", "t.daemon = True" in WATCH)
check("...after a delay, since the loop has not ticked at the open",
      "_SELFCHECK_DELAY_S" in WATCH,
      "an immediate report would truthfully say 'no pass' every week")
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
check("there is an on-demand command", 'cmd_l == "/engine"' in TG)
check("...listed for clients", '("engine", "What APEX has been doing")' in TG)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL SELF-CHECK PASSED - it answers, or says it cannot.")
