"""A stop the client did not choose is not accepted inside spread and noise.

The Trade wizard prefills a stop from the instrument's ATR. When that stop is
the wizard's own default (the client never edited it) the wizard says so in
`stopSource: "default"`, and the server holds it to the floor the engine uses
for a stop it places itself: at least 4x the live spread and 20 pips. A stop
the client typed is never checked against it, and a body that does not say is
read as the client's own, so nothing existing is refused.

Run: python3 tests/test_platform_default_stop_floor.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-stopfloor-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
for _banned in ("A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS",
                "A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS",
                "A4T_LIVE_PILOT_MAX_UNITS", "PAPER_TRADING",
                "A4T_EMERGENCY_HALT"):
    os.environ.pop(_banned, None)

from apex.platform import automation_setup as S             # noqa: E402
from apex.platform import store as ST                       # noqa: E402

USER = "stopfloor-user-1"
_fails = []
_starts = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def body(**over):
    base = {
        "symbols": ["XAUUSD"], "timeframe": "1h", "strategy": "trend",
        "capitalAllocated": 1000, "riskPercent": 1, "maxDailyLossPercent": 2,
        "maxOpenPositions": 1, "stopLossPips": 300, "takeProfitPips": 600,
        "automationLevel": "full", "account": "demo",
    }
    base.update(over)
    return base


def _start(uid, rid):
    _starts.append(rid)
    return {"state": "running", "started": True, "ruleDocId": rid}


def submit(spread, **over):
    return S.submit(USER, body(**over), binder=lambda u, i: "501",
                    starter=_start, spread_reader=lambda u, sym, ct: spread)


print("[1] the floor")
check("20 pips with no spread reading", S.stop_floor_pips() == 20.0)
check("20 pips for an unusable spread",
      S.stop_floor_pips(None) == S.stop_floor_pips(0) == S.stop_floor_pips(-1)
      == S.stop_floor_pips("x") == 20.0)
check("20 pips while 4x the spread is smaller", S.stop_floor_pips(3) == 20.0)
check("4x the spread once that is larger", S.stop_floor_pips(8) == 32.0)

print("\n[2] only a stop that is not the client's is judged")
check("a client stop of 5 pips is not refused by validate",
      S.validate(body(stopLossPips=5, stopSource="client")) == [])
check("a body without stopSource is read as the client's own",
      S.validate(body(stopLossPips=5)) == [])
check("a default stop of 5 pips is refused",
      any("stopLossPips" in p and "20" in p
          for p in S.validate(body(stopLossPips=5, stopSource="default"))))
check("a default stop of 20 pips (the engine's floor) passes the static check",
      S.validate(body(stopLossPips=20, stopSource="default")) == [])
check("a default stop of 300 pips passes", S.validate(body(stopSource="default")) == [])
check("an unknown stopSource is refused, naming the field",
      any(p.startswith("stopSource") for p in S.validate(body(stopSource="auto"))))
check("the live-spread part names the spread",
      "live spread of 10 pips" in S.default_stop_problems(
          body(stopLossPips=30, stopSource="default"), 10)[0])
check("a stop of exactly the floor passes",
      S.default_stop_problems(body(stopLossPips=40, stopSource="default"), 10) == [])

print("\n[3] submit asks for the live spread only for a default stop")
asked = []


def spy(u, sym, ct):
    asked.append((sym, ct))
    return 12


S.submit(USER, body(stopLossPips=30, stopSource="client"),
         binder=lambda u, i: "501", starter=_start, spread_reader=spy)
check("an explicit stop is never compared with the spread", asked == [])
try:
    S.submit(USER, body(stopLossPips=30, stopSource="default"),
             binder=lambda u, i: "501", starter=_start, spread_reader=spy)
    check("a default stop inside 4x a 12-pip spread is refused", False)
except S.SetupInvalid as e:
    check("a default stop inside 4x a 12-pip spread is refused",
          any("48" in p for p in e.problems), str(e.problems))
check("the spread was read for the traded symbol and the bound account",
      asked == [("XAUUSD", "501")], str(asked))

before = len(_starts)
rules_before = len(ST.list_docs(USER))
try:
    submit(12, stopLossPips=30, stopSource="default")
except S.SetupInvalid:
    pass
check("a refusal starts nothing and stores nothing",
      len(_starts) == before and len(ST.list_docs(USER)) == rules_before)

out = submit(12, stopLossPips=300, stopSource="default")
check("a default stop above the floor starts", out.get("executed") is True, str(out))
check("an unreadable spread falls back to the static floor and still starts a 300-pip stop",
      submit(None, stopLossPips=300, stopSource="default").get("executed") is True)
try:
    submit(None, stopLossPips=5, stopSource="default")
    check("an unreadable spread does not let a 5-pip default through", False)
except S.SetupInvalid:
    check("an unreadable spread does not let a 5-pip default through", True)

print("\n[4] the real reader fails to the static floor, never raises")
check("with no connected account the spread is unknown",
      S._live_spread_pips("nobody", "XAUUSD", None) is None)

print("\n[5] nothing about live changed")
check("a live body with a closed gate still does not execute",
      S.submit(USER, body(account="live", riskPercent=1, stopSource="client"),
               gate_reader=lambda u: {"open": False}).get("executed") is False)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("Default-stop floor checks passed.")
