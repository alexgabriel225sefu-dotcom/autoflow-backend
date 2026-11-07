"""The daily-loss stop counts the money that is already gone in open trades.

`should_stop` read only REALISED P&L. A day down 2.5% realised with another
2% of open losses sat at -4.5% of real equity against a 4% stop, and the
engine kept opening trades, because only the closed half counted.

Floating P&L is added when the broker reports it (equitySource "broker").
Only LOSSES count: an open profit that may never be banked must not buy room
for more realised losses. Nothing is flattened — the stop halts new entries,
exactly as the realised stop always has.

Run: python tests/test_should_stop_floating.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["PAPER_TRADING"] = "true"

from apex import strategies  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


START = 1000.0
_n = [0]


def _fresh(daily_pnl):
    _n[0] += 1
    uid = f"float-stop-{os.getpid()}-{_n[0]}"
    strategies.should_stop(START, START, max_daily_loss_pct=4.0,
                           max_dd_pct=50.0, user_id=uid)
    strategies.get_session(uid)["dailyPnL"] = daily_pnl
    return uid


def _stop(uid, floating=None):
    return strategies.should_stop(START + strategies.get_session(uid)["dailyPnL"],
                                  START, max_daily_loss_pct=4.0, max_dd_pct=50.0,
                                  user_id=uid, floating_pnl=floating)


print("\n1. Realised only — unchanged")
uid = _fresh(-25.0)
check("-2.5% realised, no floating figure -> no stop", not _stop(uid)["stop"])
uid = _fresh(-45.0)
check("-4.5% realised -> stop", _stop(uid)["stop"])

print("\n2. Floating losses count")
uid = _fresh(-25.0)
r = _stop(uid, floating=-20.0)
check("-2.5% realised + -2% floating -> stop", r["stop"], str(r))
check("...and the reason says floating was counted",
      any("floating" in x.lower() for x in r["reasons"]), str(r["reasons"]))
uid = _fresh(-25.0)
check("-2.5% realised + -1% floating -> no stop",
      not _stop(uid, floating=-10.0)["stop"])

print("\n3. Floating profit never offsets a realised loss")
uid = _fresh(-45.0)
check("-4.5% realised + +3% floating -> still stopped",
      _stop(uid, floating=30.0)["stop"])

print("\n4. The stored daily P&L is not changed by asking")
uid = _fresh(-25.0)
_stop(uid, floating=-20.0)
check("dailyPnL is still the realised figure",
      strategies.get_session(uid)["dailyPnL"] == -25.0,
      str(strategies.get_session(uid)["dailyPnL"]))

print("\n5. Garbage floating figures are ignored, not trusted")
uid = _fresh(-25.0)
check("a string is ignored", not _stop(uid, floating="nan?")["stop"])
check("NaN is ignored", not _stop(uid, floating=float("nan"))["stop"])

print("\n6. The loop passes the broker's floating figure, only when it is the broker's")
with open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8") as fh:
    SRC = fh.read()
i = SRC.find("stop_check = strategies.should_stop(")
call = SRC[i:i + 900]
check("the loop passes floating_pnl", "floating_pnl=" in call, call[:400])
check("...gated on equitySource == broker",
      'equitySource") == "broker"' in SRC[i - 1200:i + 900])

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - open losses count toward the daily stop.")
