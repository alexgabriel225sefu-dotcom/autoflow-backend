"""A close the broker never confirmed must never be reported as a close.

Audit of every path that shuts a position found the same defect three times,
each written independently, each with the same shape:

    try:
        broker.close_position(...)
    except Exception:
        pass
    ...then journal the trade, move the balance, alert the client...

The client is told they are out. The position is still open. Their money is
still exposed, and now nothing is watching it, because every local record says
the trade is finished.

  • the weekend flatten      — gap risk over Sat/Sun, the exact thing it exists to stop
  • the strategy exit        — the path that runs most often
  • the stop-loss safety net — the worst one: the position is open AND has no
                               stop at the broker, and it was reported as
                               "closed immediately for safety"

Run: python tests/test_close_honesty.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-honest-")

from apex import telegram as tg      # noqa: E402
from apex import alert_policy        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
CT = open(os.path.join(ROOT, "apex", "brokers", "ctrader.py"), encoding="utf-8").read()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def block(src, start_marker, end_marker):
    i = src.index(start_marker)
    return src[i:src.index(end_marker, i)]


print("\n── no close path swallows the broker's failure ──")
for label, marker in (
        ("weekend flatten", "if in_weekend_window:"),
        ("strategy exit", 'elif action == "CLOSE" and open_pos:')):
    i = LOOP.index(marker)
    seg = LOOP[i:i + 2600]
    check(f"{label}: no bare `except: pass` around the close",
          not re.search(r"broker\.close_position\([^)]*\)\s*\n\s*except Exception:\s*\n\s*pass",
                        seg), "still swallowed")
    check(f"{label}: the error is logged", "FAILED" in seg)

check("the broker's safety net no longer swallows its own close",
      not re.search(r"close_res = self\.close_position\(instrument\)\s*\n\s*except Exception:\s*\n\s*pass", CT))

print("\n── a failed close is not journalled ──")
wk = block(LOOP, "if in_weekend_window:", "time.sleep(_LOOP_INTERVAL)")
check("weekend: a failure `continue`s past the accounting",
      "_wk_failed.add(_wsym)" in wk and "continue" in wk[wk.index("_wk_failed.add"):][:120])
ex = block(LOOP, 'elif action == "CLOSE" and open_pos:', "except Exception as e:")
check("strategy exit: the accounting sits under a success branch",
      "if not _close_ok:" in ex and ex.index("if not _close_ok:") < ex.index("_log_trade"))
check("strategy exit: a failure keeps the position tracked",
      "_persist_open_snapshot(_with_initial_stop(open_pos, symbol))"
      in ex[ex.index("if not _close_ok:"):ex.index("else:", ex.index("if not _close_ok:"))])
check("strategy exit: and re-persists the dashboard position",
      'dash["openPosition"] = open_pos'
      in ex[ex.index("if not _close_ok:"):ex.index("else:", ex.index("if not _close_ok:"))])

print("\n── the unprotected state has a name ──")
check("the broker reports UNPROTECTED instead of SAFETY_CLOSED",
      '"status": "UNPROTECTED"' in CT)
check("it is only used when the safety close truly failed",
      "if close_err is not None or not close_res:" in CT)
check("the loop handles it before the SAFETY_CLOSED branch",
      LOOP.index('"status") == "UNPROTECTED"') < LOOP.index('"status") == "SAFETY_CLOSED"'))
check("and refuses to treat it as a completed trade",
      "order_ok = False" in LOOP[LOOP.index('"status") == "UNPROTECTED"'):][:600])

print("\n── the client hears about all three ──")
for _action in ("EXIT_FAILED", "UNPROTECTED", "WEEKEND_CLOSE"):
    check(f"{_action} is ESSENTIAL, so /verbose off cannot hide it",
          _action in alert_policy.ESSENTIAL)
    check(f"{_action} reaches a client who muted diagnostics",
          alert_policy.allowed(_action, {"verbose_alerts": False}))

sent = []
_orig = tg.send_to
tg.send_to = lambda cid, text, extra=None: sent.append(text)
try:
    del sent[:]
    tg._user_alert("1", {"action": "EXIT_FAILED", "symbol": "EURUSD"})
    _t = " ".join(sent)
    check("EXIT_FAILED says the position is still open", "still open" in _t.lower(), _t[:80])
    check("and that the stop is still protecting it", "stop" in _t.lower(), _t[:80])
    check("and offers the manual way out", "/close" in _t, _t[:80])

    del sent[:]
    tg._user_alert("1", {"action": "UNPROTECTED", "symbol": "EURUSD"})
    _t = " ".join(sent)
    check("UNPROTECTED says there is NO stop", "no stop-loss" in _t.lower(), _t[:80])
    check("and tells them to act now", "now" in _t.lower() and "cTrader" in _t, _t[:80])
    check("and does not claim the bot handled it",
          "closed for safety" not in _t.lower(), _t[:80])
finally:
    tg.send_to = _orig

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — no path reports a close it did not make.")
