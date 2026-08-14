"""The weekend flatten must close what it says it closed.

Reported live, Friday evening: Telegram said the market had closed for the
weekend, and the cTrader position was still open. Three separate defects in
one block made that possible, and every one of them is a lie told to a client
about their own money:

1. The message was sent BEFORE any close was attempted, and unconditionally.
   "Any open position was closed to avoid gap risk" went out whether or not
   anything happened.
2. Only the FOCUSED symbol was closed. Auto-Pilot rotates focus, and with
   maxpos > 1 there can be several positions — the rest rode into the gap
   while the message claimed they were flat.
3. A broker failure was swallowed by a bare `except Exception: pass`, and the
   code then journalled the trade as closed anyway — booking a P&L, updating
   the balance and alerting the client for a position still open at the broker.

A position held through the weekend gap can reopen Sunday far past its stop.
Standing on the wrong side of that while being told you are flat is the worst
outcome the whole feature exists to prevent.

Run: python tests/test_weekend_flatten.py
"""
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-wk-")

from apex import market      # noqa: E402
from apex import telegram as tg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n── the window itself ──")
def at(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)

# 2026-08-14 is a Friday.
check("Friday 19:00 → still trading", not market.is_weekend_close_window(at(2026, 8, 14, 19)))
check("Friday 20:00 → flatten window", market.is_weekend_close_window(at(2026, 8, 14, 20)))
check("Friday 21:00 → flatten window", market.is_weekend_close_window(at(2026, 8, 14, 21)))
check("Saturday → flatten window", market.is_weekend_close_window(at(2026, 8, 15, 12)))
check("Sunday 20:00 → still closed", market.is_weekend_close_window(at(2026, 8, 16, 20)))
check("Sunday 21:00 → open again", not market.is_weekend_close_window(at(2026, 8, 16, 21)))
check("Monday → open", not market.is_weekend_close_window(at(2026, 8, 17, 9)))

print("\n── the announcement comes AFTER the attempt ──")
_flat = LOOP.index("if in_weekend_window:")
_alert = LOOP.index('"action": "WEEKEND_CLOSE"', _flat)
_attempt = LOOP.index("broker.close_position(_wsym)", _flat)
check("the close is attempted before the alert is built", _attempt < _alert)
check("the alert carries what actually happened",
      '"closed": _wk_closed' in LOOP and '"failed": sorted(_wk_failed)' in LOOP)
check("no unconditional pre-announcement survives",
      'alert_fn(user_id, {"action": "WEEKEND_CLOSE", "symbol": symbol})' not in LOOP)

print("\n── a failed close is never booked as a close ──")
_body = LOOP[_flat:LOOP.index("time.sleep(_LOOP_INTERVAL)", _flat)]
check("the broker error is not swallowed by a bare pass",
      not re.search(r"except Exception:\s*\n\s*pass", _body), "bare pass still there")
check("a failure skips the journal entirely", "_wk_failed.add(_wsym)" in _body
      and "continue" in _body[_body.index("_wk_failed.add(_wsym)"):
                              _body.index("_wk_failed.add(_wsym)") + 120])
check("an already-flat position is not journalled either",
      '(_close_res or {}).get("status") == "FLAT"' in _body)

print("\n── every position, not just the focused one ──")
check("it asks the broker for the whole list", "broker.get_all_positions()" in _body)
check("it closes each position's own symbol", "broker.close_position(_wsym)" in _body)
check("and files the close under that symbol", '"symbol": _wsym' in _body)
check("the stats are credited to it too", "symbol=_wsym" in _body)
check("the focus price is not used to value another instrument",
      "_nrm(_wsym) == _nrm(symbol)" in _body)

print("\n── what the client is told ──")
sent = []
_orig = tg.send_to
tg.send_to = lambda cid, text, extra=None: sent.append(text)
try:
    for _payload, _must, _must_not in (
        ({"action": "WEEKEND_CLOSE", "closed": 0, "failed": ["USDCAD"]},
         ("Still open", "USDCAD", "cTrader"), ("Closed 0",)),
        ({"action": "WEEKEND_CLOSE", "closed": 2, "failed": []},
         ("Closed 2 positions",), ("Still open",)),
        ({"action": "WEEKEND_CLOSE", "closed": 1, "failed": []},
         ("Closed 1 position",), ("positions",)),
        ({"action": "WEEKEND_CLOSE", "closed": 0, "failed": []},
         ("Nothing was open",), ("Still open", "Closed")),
    ):
        del sent[:]
        tg._user_alert("1", _payload)
        txt = " ".join(sent)
        for _m in _must:
            check(f"{_payload['closed']}c/{len(_payload['failed'])}f says '{_m}'",
                  _m in txt, txt[:90])
        for _n in _must_not:
            check(f"{_payload['closed']}c/{len(_payload['failed'])}f avoids '{_n}'",
                  _n not in txt, txt[:90])
finally:
    tg.send_to = _orig

check("the old blanket claim is gone from the copy",
      "Any open position was closed" not in TG)

print("\n── and it re-announces only when the failure set changes ──")
check("the alert gate compares against the last reported set",
      "_wk_failed != weekend_failed" in LOOP)
check("the set is remembered for the next tick", "weekend_failed = _wk_failed" in LOOP)
check("and cleared when the market reopens",
      "weekend_failed = set()" in LOOP[:LOOP.index('"action": "WEEKEND_REOPEN"')])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the weekend flatten tells the truth.")
