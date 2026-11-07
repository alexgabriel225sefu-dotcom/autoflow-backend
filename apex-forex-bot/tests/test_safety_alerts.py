"""When the engine loses control of real exposure, the client hears about it.

THE GAP, AND IT IS THE QUIETEST ONE FOUND THIS WEEK

`automation.engine_alert` is the single alert function the engine gets for a
platform client. It offered every alert to two sinks: `approvals`, which
answers for SUGGEST, and `signals`, which answers for SIGNAL. Both allowlist,
and both are right to — burying the one alert that needs an answer under
heartbeats is what `notifications.py` exists to prevent.

Between them that is two actions. Everything else the engine raises was
dropped, and two of those are not reports:

  UNPROTECTED  the position is open at the broker with NO stop-loss, and the
               safety close failed too. `user_loop`'s own comment where it
               raises this reads: "Nothing here can fix it remotely — the
               client has to be told, now, and told exactly what to do."
  EXIT_FAILED  the rule asked to close and the broker refused. The position
               is still open.

A Telegram client got both, through `telegram._user_alert`. A platform client
got neither, from any screen, ever. Their money sat unprotected at a broker
and the dashboard said "Watching market".

WHAT THIS FILE WILL NOT ACCEPT

That the sink exists. The two sinks it sits beside were each wired correctly
and the bug was still live, because what matters is the composition: the one
function the ENGINE is handed must deliver these. So section [2] drives
`automation.engine_alert` — the real composition point — rather than the new
helper, and section [4] holds all three allowlists apart.

Run: python3 tests/test_safety_alerts.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-safety-")
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


from apex.platform import approvals as APPR                 # noqa: E402
from apex.platform import automation as AUTO                # noqa: E402
from apex.platform import notifications as NOTIFY           # noqa: E402
from apex.platform import signals as SIG                    # noqa: E402

USER = "dddddddd-4444-4444-8444-dddddddddddd"


def inbox():
    """Every notification on this account, newest first."""
    return NOTIFY.query(USER, limit=200)["notifications"]


# ── 1. the engine's raise sites still use the actions this sink answers ─────
print("\n[1] the actions this sink claims are the ones the engine raises")
# If `user_loop` renames one, this sink goes quiet again with every test
# green — the exact failure mode it was built to end.
_UL = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
for action in AUTO.SAFETY_ACTIONS:
    check(f"the engine raises {action!r}",
          f'"action": "{action}"' in _UL,
          "a sink answering an action nothing raises is silence with "
          "extra steps")


# ── 2. THE COMPOSITION POINT, not the helper ────────────────────────────────
print("\n[2] the alert function the ENGINE is handed delivers them")
AUTO.engine_alert(USER, {"action": "UNPROTECTED", "symbol": "EURUSD",
                         "price": 1.0921})
rows = inbox()
_unp = [r for r in rows if "EURUSD" in str(r.get("title"))]
check("an UNPROTECTED alert becomes a notification", bool(_unp),
      f"{len(rows)} notifications in total")
if _unp:
    r = _unp[0]
    check("at CRITICAL, because only the client can act",
          r.get("level") == NOTIFY.CRITICAL, str(r.get("level")))
    check("and it says there is no stop-loss, in those words",
          "stop-loss" in str(r.get("title")) + str(r.get("body")),
          str(r.get("title")))
    # The engine's comment demands "told exactly what to do". A critical
    # alert with no action is an alarm the client cannot answer.
    check("and names the one action that fixes it",
          "cTrader" in str(r.get("body")), str(r.get("body")))

AUTO.engine_alert(USER, {"action": "EXIT_FAILED", "symbol": "XAUUSD"})
rows = inbox()
_ef = [r for r in rows if "XAUUSD" in str(r.get("title"))]
check("an EXIT_FAILED alert becomes a notification", bool(_ef))
if _ef:
    check("saying the position is still open",
          "still open" in str(_ef[0].get("body")), str(_ef[0].get("body")))
    # Not alarming the client about a stop that IS still in force matters:
    # an exit that failed is not an unprotected position.
    check("and that the broker-side stop is still in force",
          "still in force" in str(_ef[0].get("body")),
          str(_ef[0].get("body")))


# ── 3. the firehose is still a firehose ─────────────────────────────────────
print("\n[3] the rest of the firehose is still dropped")
# Alerting on these trains a client to dismiss the two above, which is worse
# than not alerting at all.
_count_before = len(inbox())
for action in ("HEARTBEAT", "BROKER_HEALTH", "SKIP_WARN", "WEEKEND_CLOSE",
               "OWNERSHIP_LOST", "STOP", "CLOSE", "SHADOW_OPEN"):
    AUTO.engine_alert(USER, {"action": action, "symbol": "EURUSD"})
check("none of the eight routine actions notifies",
      len(inbox()) == _count_before,
      f"{len(inbox()) - _count_before} got through")


# ── 4. three allowlists, no overlap, in all three directions ────────────────
print("\n[4] no action is delivered twice")
# The allowlists ARE the routing. If any two claim the same action, one event
# becomes two rows on two screens.
_s = set(SIG.DELIVERED_ACTIONS)
_a = {APPR.SUGGEST}
_f = set(AUTO.SAFETY_ACTIONS)
check("signals and safety do not overlap", not (_s & _f), str(_s & _f))
check("approvals and safety do not overlap", not (_a & _f), str(_a & _f))
check("signals and approvals do not overlap", not (_s & _a), str(_s & _a))


# ── 5. it cannot cost a client their stop management ────────────────────────
print("\n[5] a failing notification store does not break the tick")
# This runs on the trading thread. An exception here abandons the rest of the
# tick, and the rest of the tick is trailing stops, exits and position
# management.
_real = NOTIFY.notify
NOTIFY.notify = lambda *a, **kw: (_ for _ in ()).throw(
    RuntimeError("the notification store is down"))
try:
    AUTO.engine_alert(USER, {"action": "UNPROTECTED", "symbol": "EURUSD"})
    check("engine_alert returned instead of raising", True)
except Exception as e:                                       # noqa: BLE001
    check("engine_alert returned instead of raising", False,
          f"{type(e).__name__}: {e}")
finally:
    NOTIFY.notify = _real

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All safety-alert checks passed.")
