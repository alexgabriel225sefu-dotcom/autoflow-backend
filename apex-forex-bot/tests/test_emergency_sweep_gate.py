"""The emergency sweep is the one close path that reached the broker ungated.

Found by the UX agent while mapping every screen to its safety gate, and it was
right: `gates.authorize_close` had exactly ONE call site — inside force_close().
force_close_all() closes the tracked position through that function, then
SWEEPS every other position on the account by calling broker.close_position()
directly.

The failure chain:

    operator taps "Close All"
        ↓
    two containers are live (deploy overlap), or the operator taps twice
        ↓
    both sweep the same symbol
        ↓
    nothing claims the close, because the gate never saw it
        ↓
    container A closes EURUSD
        ↓
    the loop reopens EURUSD seconds later
        ↓
    container B's sweep closes the NEW position
        ↓
    a position nobody asked to close is closed, and no audit records either

Gating it does not weaken the emergency. `emergency=True` still waives ownership
and still lets the operator out during a coordination outage. What it adds is
the idempotency claim keyed on CLOSE:{symbol} — and an audit entry, which is
exactly what an emergency most needs to leave behind.

Run: python tests/test_emergency_sweep_gate.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-sweep-")

from apex import gates, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
# force_close_all is currently the last function in the module, so the slice
# runs to EOF. Slicing on the closing `return` instead would catch the earlier
# sweepError early-return and cut the function off before the loop entirely —
# which is how this test first "passed" its own setup and then found nothing.
SWEEP = SRC[SRC.index("def force_close_all("):]
_next = SWEEP.find("\ndef ", 1)
if _next != -1:
    SWEEP = SWEEP[:_next]

print("\n🧪 EMERGENCY SWEEP — every close passes the gate\n")

print("1. The sweep no longer reaches the broker unannounced")
check("the sweep asks the gate before closing",
      "gates.authorize_close(" in SWEEP)
check("...for EACH swept position, inside the loop",
      SWEEP.index("for pos in remaining:") < SWEEP.index("gates.authorize_close("))
check("...and the gate call precedes the broker call",
      SWEEP.index("gates.authorize_close(") < SWEEP.index("broker.close_position(sym)"))
check("a refused claim skips the position rather than closing it anyway",
      re.search(r"if not _d:.*?continue", SWEEP, re.S) is not None)
check("the sweep is audited", 'gates.audit(user_id, "CLOSE"' in SWEEP)
check("...under its own origin, so it is distinguishable afterwards",
      'origin="emergency_sweep"' in SWEEP)

print("\n2. It is still an EMERGENCY — the gate must not block the exit")
check("ownership is waived, as before", "emergency=True" in SWEEP)
_gsrc = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
_ac = _gsrc[_gsrc.index("def authorize_close("):]
check("an emergency close does NOT fail closed on a coordination outage",
      "fail_closed=not emergency" in _ac)
check("and ownership is skipped for an emergency",
      "if not emergency:" in _ac)

print("\n3. An ambiguous broker answer never releases the claim")
check("a raised close keeps the claim and reports ambiguity",
      "broker_result_ambiguous(e)" in SWEEP)
check("...and does not record a close that may not have happened",
      SWEEP.index("broker_result_ambiguous(e)")
      < SWEEP.index('ledger.record(_rid, {"closed": True'))

print("\n4. Behaviour: the same position is not swept twice")
UID = "9100"
user_store.save(UID, {"paper": True, "active": True, "symbol": "EURUSD"})

_d1, _rid1 = gates.authorize_close(UID, symbol="EURUSD",
                                   origin="emergency_sweep", emergency=True)
check("the first claim on a symbol is granted", bool(_d1), _d1.reason)
_d2, _rid2 = gates.authorize_close(UID, symbol="EURUSD",
                                   origin="emergency_sweep", emergency=True)
check("a SECOND claim on the same symbol is refused — this is the "
      "double-close that was possible before",
      not _d2, f"{_d2.reason}: {_d2.detail}")
_d3, _rid3 = gates.authorize_close(UID, symbol="GBPUSD",
                                   origin="emergency_sweep", emergency=True)
check("a different symbol is unaffected", bool(_d3), _d3.reason)

print("\n5. Every EXTERNALLY-REQUESTED close passes the gate")
# The distinction that matters, and it is not a count. There are five
# broker.close_position() call sites and only two gate calls, which looks wrong
# until you see which is which:
#
#   in the trading LOOP  — a stop-loss breach, the weekend flatten, and the
#       exit-confirmation path. The loop is managing the position it already
#       owns: it holds the ownership lease, it is single-threaded per user, and
#       there is no second requester to race with. Claiming an idempotency key
#       on every stop-out would add churn and protect nothing.
#
#   from OUTSIDE          — force_close() (Telegram, AI, MCP) and the emergency
#       sweep. These arrive from an origin, can arrive twice, and can arrive
#       from two containers at once. These are the ones the gate exists for.
#
# So the assertion is about the second group, by name.
_ext = SRC[SRC.index("def force_close(user_id"):]
for _fn in ("def force_close(user_id", "def force_close_all("):
    _body = SRC[SRC.index(_fn):]
    _end = _body.find("\ndef ", 1)
    _body = _body[:_end] if _end != -1 else _body
    check(f"{_fn.split('(')[0][4:]}() gates before it reaches the broker",
          "gates.authorize_close(" in _body
          and _body.index("gates.authorize_close(")
          < _body.index("broker.close_position("))
check("authorize_close now has more than the single call site it had before",
      len(re.findall(r"gates\.authorize_close\(", SRC)) >= 2)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the emergency sweep is gated, and still an emergency.")
