"""The guided setup refuses a live start while the gates are off, and it
refuses risk the platform will not keep.

The screen can be skipped. These checks post the body the screen posts, with
the live switches unset, and require that `automation.start` is not called.
They also require that a risk, a daily loss, a capital allocation, a position
cap and a stop outside the platform's numbers are refused before a rule is
stored, and that an order which fits the balance but not the allocated
capital is refused by the risk gate.

Run: python3 tests/test_platform_automation_setup.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-setup-")
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

import requests                                             # noqa: E402

from apex.platform import api as A                          # noqa: E402
from apex.platform import automation as AU                  # noqa: E402
from apex.platform import automation_setup as S             # noqa: E402
from apex.platform import engine_config as ECFG             # noqa: E402
from apex.platform import identity as I                     # noqa: E402
from apex.platform import risk_gates as G                   # noqa: E402
from apex.platform import store as ST                       # noqa: E402
from apex.platform import strategy_catalog as SC            # noqa: E402

USER = "setup-user-1"
_fails = []
_starts = []
_real_start = AU.start


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def _spy_start(*args, **kwargs):
    _starts.append((args, kwargs))
    raise AssertionError("automation.start must not run for this case")


AU.start = _spy_start


def body(**over):
    base = {
        "symbols": ["EURUSD"],
        "timeframe": "1h",
        "strategy": "trend",
        "capitalAllocated": 1000,
        "riskPercent": 1,
        "maxDailyLossPercent": 2,
        "maxOpenPositions": 1,
        "stopLossPips": 20,
        "takeProfitPips": 40,
        "automationLevel": "full",
        "account": "demo",
    }
    base.update(over)
    return base


print("\n[1] the library is the registry, and it invents no result")
lib = S.library()
offered = {row["id"] for row in lib["strategies"]}
withheld = {row["id"] for row in lib["withheld"]}
check("every offered strategy is registered",
      offered <= set(SC.ids()) and offered == set(SC.ids()),
      str(sorted(offered ^ set(SC.ids()))))
check("withheld strategies are listed too, so nothing registered is missing",
      not (set(SC.catalogue() and []) or (offered | withheld)
           ^ (set(SC.ids()) | {r["id"] for r in SC.withheld()})))
registered = set()
from apex import strategy_api as SA                         # noqa: E402
registered = set(SA.load_builtins())
check("offered plus withheld is every registered strategy",
      offered | withheld == registered,
      str(sorted(registered - (offered | withheld))))
check("each offered strategy has a timeframe note and no backtest figure",
      all(row.get("timeframeNote") and row.get("backtest") is None
          for row in lib["strategies"]),
      str([row["id"] for row in lib["strategies"]
           if not row.get("timeframeNote") or row.get("backtest") is not None]))
check("no timeframe was left unstated", lib.get("timeframeUnstated") in (None, []))
check("the disclaimer is the one the screen must show",
      "does not guarantee" in lib["disclaimer"])
check("the daily-loss ceiling is the platform's, not a looser one",
      lib["bounds"]["maxDailyLossPercent"]["max"]
      == G.PLATFORM["maxDailyLossPercent"])
check("live risk cannot exceed the platform's live cap",
      lib["bounds"]["riskPercentLive"]["max"]
      == G.PLATFORM["maxRiskPercentLive"])


print("\n[2] risk outside the platform's numbers is refused before a start")


def _refused(name, **over):
    before = list(_starts)
    try:
        S.submit(USER, body(**over))
        check(name, False, "submit accepted it")
    except S.SetupInvalid as e:
        check(name, True)
        check(name + " names the field",
              any(any(str(k) in p for k in over) for p in e.problems),
              str(e.problems))
    check(name + " did not start", _starts == before)


_refused("live risk above 1%", account="live", riskPercent=1.5)
_refused("a daily loss above the 4% ceiling", maxDailyLossPercent=4.5)
_refused("a daily loss of zero", maxDailyLossPercent=0)
_refused("no capital", capitalAllocated=0)
_refused("capital above the ceiling", capitalAllocated=10_000_001)
_refused("zero open positions", maxOpenPositions=0)
_refused("too many open positions", maxOpenPositions=9)
_refused("a stop of zero", stopLossPips=0)
_refused("a target of zero", takeProfitPips=0)
_refused("a strategy that is withheld", strategy="grid")
_refused("a strategy that is not registered", strategy="does_not_exist")
_refused("an instrument outside the allowlist", symbols=["BTCUSD"])
_refused("no account mode", account="paper")

check("a valid demo body has no problems", S.validate(body()) == [],
      str(S.validate(body())))
check("1% on live is inside the cap",
      S.validate(body(account="live", riskPercent=1)) == [])
check("1.0 on live is inside the cap and 1.01 is not",
      S.validate(body(account="live", riskPercent=1.0)) == []
      and S.validate(body(account="live", riskPercent=1.01)) != [])


print("\n[3] live stays blocked while the gates are off")
check("the release switch is off",
      os.environ.get("A4T_LIVE_EXECUTION") is None
      and os.environ.get("APEX_ALLOW_LIVE_ACCOUNTS") is None)
out = S.submit(USER, body(account="live", riskPercent=1))
check("a valid live body does not execute",
      out.get("executed") is False and out.get("started") is False, str(out))
check("the live state is a request or a wait, never an open gate",
      out.get("live", {}).get("open") is False
      and out["live"]["state"] in ("request", "awaiting", "unknown")
      and out["live"]["label"] in ("Request live access", "Awaiting approval",
                                   "Live status unknown"),
      str(out.get("live")))
check("start was not called", _starts == [])
check("no rule was stored for the blocked live setup",
      ST.list_docs(USER) == [], str(ST.list_docs(USER)))


print("\n[4] a demo setup stores the limits and can start")
_starts.clear()


def _ok_start(uid, rid):
    _starts.append(rid)
    return {"state": "running", "started": True, "ruleDocId": rid}


demo = S.submit(USER, body(riskPercent=1, capitalAllocated=1000),
                binder=lambda uid, intent: "501", starter=_ok_start)
check("demo executes", demo.get("executed") is True and demo.get("started") is True,
      str(demo))
check("start was handed the new rule", _starts == [demo.get("ruleDocId")])
stored = ST.get(USER, demo["ruleDocId"])
check("the rule is active", stored.get("state") == "active", stored.get("state"))
check("risk, capital, daily loss, positions, stop and target are the body's",
      stored["sizing"]["riskPercent"] == 1
      and stored["limits"]["capitalAllocated"] == 1000
      and stored["limits"]["maxDailyLossPercent"] == 2
      and stored["limits"]["maxOpenPositions"] == 1
      and stored["stopLoss"]["pips"] == 20
      and stored["takeProfit"]["pips"] == 40
      and stored["strategy"] == "trend",
      str({k: stored.get(k) for k in ("sizing", "limits", "stopLoss",
                                      "takeProfit", "strategy")}))
applied, _ = ECFG.translate(stored)
scaled, state = ECFG.scale_risk_to_capital(applied, stored, 5000)
check("1% of 1000 on a 5000 balance is 0.2% of the balance",
      state is None and abs(scaled["risk"] - 0.002) < 1e-9, str(scaled))
check("without a balance the scale is refused, not guessed",
      ECFG.scale_risk_to_capital(applied, stored, None)[1] == "unchecked")
unscaled, _ = ECFG.scale_risk_to_capital(applied, {"limits": {}}, None)
check("a rule with no allocation is not scaled",
      unscaled.get("risk") == applied.get("risk"))


print("\n[5] the risk gate holds an order to the allocated capital")
rule = dict(stored)
# $20 of risk (8,000 units, 25 pips) is 0.2% of 10,000 and 2% of 1,000.
intent = G.OrderIntent(symbol="EURUSD", side="BUY", entry_price=1.1000,
                       stop_price=1.0975, volume=8000.0)
facts = {"positions": [], "dailyRealisedPnl": 0.0, "dailyTradesOpened": 0,
         "peakBalance": 10000.0, "spreadPips": 0.4, "slippagePoints": 0.0}
over = G.authorize(rule, intent, mode="demo", balance_reader=lambda: 10000.0,
                   state=facts)
check("an order inside 1% of the balance but outside 1% of the allocation "
      "is refused",
      (not over.allowed) and over.code == "RISK_OVER_ALLOCATION",
      f"{over.code} {over.detail}")
small = G.OrderIntent(symbol="EURUSD", side="BUY", entry_price=1.1000,
                      stop_price=1.0975, volume=2000.0)
inside = G.authorize(rule, small, mode="demo", balance_reader=lambda: 10000.0,
                     state=facts)
check("an order inside 1% of the allocation is allowed",
      inside.allowed, f"{inside.code} {inside.detail}")
bare = dict(rule)
bare["limits"] = dict(rule["limits"])
bare["limits"].pop("capitalAllocated", None)
untouched = G.authorize(bare, intent, mode="demo",
                        balance_reader=lambda: 10000.0, state=facts)
check("without an allocation the same order is judged on the balance",
      untouched.allowed, f"{untouched.code} {untouched.detail}")


print("\n[6] the route serves the library and refuses live the same way")


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._b = status, payload

    def json(self):
        return self._b


_USER = {"id": USER, "email": "setup@example.com",
         "email_confirmed_at": "2026-01-01T00:00:00Z"}
requests.get = lambda url, **kw: _Resp(200, _USER)


def _call(method, path, payload=None):
    I.forget_all()
    raw = None
    if payload is not None:
        import json
        raw = json.dumps(payload)
    return A.handle(method, path, {"Authorization": "Bearer token"}, raw)


_starts.clear()
st, res = _call("POST", "/api/v1/automation/setup",
                body(account="live", riskPercent=1))
check("POST live answers 200", st == 200, str(st))
check("and reports that nothing executed",
      isinstance(res, dict) and res.get("executed") is False
      and res.get("started") is False, str(res))
check("the route did not call start", _starts == [])
st, res = _call("POST", "/api/v1/automation/setup",
                body(account="live", riskPercent=5))
check("POST live risk above the cap is 400", st == 400, str((st, res)))
check("the code is SETUP_INVALID",
      (res.get("error") or {}).get("code") == "SETUP_INVALID", str(res))
check("the problems name riskPercent",
      any("riskPercent" in p for p in ((res.get("error") or {}).get("problems")
                                       or [])),
      str(res))
st, res = _call("GET", "/api/v1/automation/setup")
check("GET setup answers 200", st == 200, str(st))
check("GET lists the strategies and the disclaimer",
      st == 200 and len(res.get("strategies") or []) >= 15
      and "does not guarantee" in (res.get("disclaimer") or ""),
      str(len(res.get("strategies") or [])))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All automation-setup checks passed.")
