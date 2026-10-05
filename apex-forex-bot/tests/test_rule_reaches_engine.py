"""Which of a rule's terms actually reach the loop that trades.

THE FACT THIS PINS

A client builds a rule, activates it, and presses Start. `automation.start`
then calls `user_loop.start`, and the loop trades from the CLIENT'S OWN STORED
SETTINGS — `sl_pips`, `tp_pips`, `trailing`, `breakeven_r`, `risk`, `maxpos`
and the rest — not from the RuleDoc. The only module that carries a RuleDoc's
terms into an order is `bridge.py`, and nothing in production imports it.

Two fields DO cross: `symbol` and `timeframe`, written into the engine config
by `automation.start`. For a multi-instrument rule only the FIRST symbol
crosses, and the others are silently not traded.

WHY A TEST AND NOT A NOTE IN A DOCUMENT

Because the product tells the client otherwise. The rule page renders a "Rule
terms" table of every field, the journal records a start against a ruleDocId,
and the button says "Start on demo" underneath. Every one of those implies the
terms drive the loop. A document saying otherwise is read once; this fails.

AND BECAUSE IT IS THE RATCHET

The inventory below lists every top-level RuleDoc field in exactly one of two
sets. Add a field to `ruledoc.blank` and this test fails until somebody says
which set it belongs to — which is the moment to also fix what the screen
claims about it. Wire a field through to the engine and the same thing
happens. The gap can close, field by field, and cannot widen unnoticed.

Run: python3 tests/test_rule_reaches_engine.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-reach-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/cb"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("A4T_EMERGENCY_HALT", None)

from apex import user_store                             # noqa: E402
from apex.platform import automation as AU              # noqa: E402
from apex.platform import ctrader_link as CL            # noqa: E402
from apex.platform import ruledoc as _rd                # noqa: E402
from apex.platform import store as _store               # noqa: E402

from apex.brokers import ctrader as _ct_broker          # noqa: E402

_ct_broker.list_accounts = lambda token: [{"ctid": 901, "live": False}]

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── the inventory ───────────────────────────────────────────────────────────
# Every top-level field a RuleDoc carries, in exactly one set.

BOOKKEEPING = {
    # Identity and lifecycle. Not terms, and not expected to reach anything.
    "ruleDocId", "version", "state", "userId", "accountId", "name",
    "createdAt", "updatedAt", "activatedAt",
}

REACHES_THE_ENGINE = {
    "symbols",      # the FIRST one only
    "timeframe",
}

RECORDED_ONLY = {
    # Shown to the client as the terms of their rule. The loop does not read
    # any of them. Each one that moves to REACHES_THE_ENGINE is a real
    # improvement; each one that stays is something the screen must not
    # present as governing the loop.
    "evaluateOn", "entry", "exit", "sides", "order", "sizing",
    "stopLoss", "takeProfit", "trailingStop", "breakEven", "limits",
    "schedule",
}

print("\n[1] every field is accounted for")
blank = _rd.blank(user_id="u", account_id="1", symbols=["EURUSD"],
                  timeframe="1h")
known = BOOKKEEPING | REACHES_THE_ENGINE | RECORDED_ONLY
unaccounted = set(blank) - known
check("no RuleDoc field is missing from this inventory",
      not unaccounted,
      f"{sorted(unaccounted)} — decide whether each reaches the engine, and "
      f"fix what the rule page claims about it")
stale = known - set(blank)
check("and the inventory names no field that no longer exists",
      not stale, str(sorted(stale)))
check("the three sets do not overlap",
      len(BOOKKEEPING) + len(REACHES_THE_ENGINE) + len(RECORDED_ONLY)
      == len(known), "a field is in two sets")

# ── a real start, measured ──────────────────────────────────────────────────
USER = "eeee1111-2222-4333-8444-eeee55556666"

begun = CL.begin(USER)
_state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
CL.handle_callback({"code": "c", "state": _state},
                   exchanger=lambda c, u: {"accessToken": "TOK",
                                           "refreshToken": "REF",
                                           "expiresIn": 2592000})
CL.complete(USER, begun["nonce"], lister=lambda a: [{"ctid": 901,
                                                     "live": False}])
CL.select_account(USER, 901)

# Engine settings that differ from the rule in every field below, so anything
# that crossed is visible as a change and anything that did not is visible as
# the original.
ENGINE_BEFORE = {
    "symbol": "GBPUSD", "timeframe": "5m",
    "sl_pips": 11, "tp_pips": 22, "risk": 0.07, "maxpos": 9,
    "trailing": True, "breakeven_r": 3.0, "exit_mode": "fixed",
    "max_trades_day": 8, "max_dd_pct": 44, "session_filter": ["LONDON"],
}
user_store.save(USER, dict(ENGINE_BEFORE))

doc = _rd.blank(user_id=USER, account_id="901",
                symbols=["EURUSD", "XAUUSD"], timeframe="4h")
doc["name"] = "reach rule"
doc["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                               "value": 30}]
doc["sides"] = "BUY"
doc["sizing"] = {"mode": _rd.SIZING_RISK, "riskPercent": 0.25,
                 "fixedVolume": None}
doc["stopLoss"] = {"mode": "pips", "atrMultiple": None, "pips": 77}
doc["takeProfit"] = {"mode": "pips", "rr": None, "pips": 155}
doc["limits"] = {"maxOpenPositions": 1, "maxDailyTrades": 2,
                 "maxExposurePercent": None, "maxSpreadPips": None,
                 "onLimit": "block"}
rid = doc["ruleDocId"]
_store.create(USER, doc)
_store.activate(USER, rid, known_condition_ids={"rsi"})

started = []
AU.start(USER, rid, starter=lambda uid: started.append(uid) or True)
check("automation started", started == [USER], str(started))

engine = user_store.load(USER)

print("\n[2] what DOES cross into the engine")
check("the rule's instrument is traded, not the engine's old one",
      engine.get("symbol") == "EURUSD", str(engine.get("symbol")))
check("the rule's timeframe is used",
      engine.get("timeframe") == "4h", str(engine.get("timeframe")))
check("and the loop is switched on",
      engine.get("active") is True, str(engine.get("active")))

print("\n[3] only the FIRST instrument of a multi-symbol rule")
# The rule says EURUSD and XAUUSD. One of them is traded and the client is
# not told which, or that the other is not.
check("the second instrument does not reach the engine",
      "XAUUSD" not in str(engine.get("symbol")),
      "if this now passes both, the rule page must stop implying one")

print("\n[4] what does NOT cross — the terms the screen shows as the rule")
for field, engine_key, rule_value in (
    ("stopLoss.pips", "sl_pips", 77),
    ("takeProfit.pips", "tp_pips", 155),
    ("sizing.riskPercent", "risk", 0.25),
    ("limits.maxOpenPositions", "maxpos", 1),
    ("limits.maxDailyTrades", "max_trades_day", 2),
):
    before = ENGINE_BEFORE[engine_key]
    now = engine.get(engine_key)
    check(f"{field} does not reach the engine",
          now == before,
          f"the engine now holds {now!r}; if the rule's {rule_value!r} "
          f"reached it, move this field to REACHES_THE_ENGINE and fix the "
          f"rule page")

check("trailingStop does not switch the engine's trailing off",
      engine.get("trailing") is True,
      "the rule says disabled and the engine still trails")
check("breakEven does not reach the engine",
      engine.get("breakeven_r") == 3.0, str(engine.get("breakeven_r")))
check("the rule's schedule does not reach the engine's session filter",
      engine.get("session_filter") == ["LONDON"],
      str(engine.get("session_filter")))

print("\n[5] the loop is not given the rule at all")
# Not an inference from the fields above: the starter is called with the user
# id and nothing else, so there is no argument through which a rule could
# arrive.
seen = []
AU.stop(USER, stopper=lambda uid: True)


def _recording_starter(uid, *a, **kw):
    seen.append({"args": a, "kwargs": kw})
    return True


AU.start(USER, rid, starter=_recording_starter)
check("the starter receives no rule, by argument or keyword",
      seen and not seen[0]["args"] and not seen[0]["kwargs"], str(seen))

src = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
check("and the loop never reads a RuleDoc",
      src.count("ruleDocId") == 0,
      "user_loop now mentions ruleDocId — if it reads one, this whole file "
      "is out of date and the rule page can start telling the truth")

print("\n[6] the product must not claim otherwise")
# The one place a client is told what their rule does. If the terms table
# ever promises these drive the loop, it has to be here that it is caught.
terms = os.path.join(ROOT, "..", "web", "src", "components", "app",
                     "rule-summary.tsx")
if os.path.exists(terms):
    body = open(terms, encoding="utf-8").read()
    check("the rule terms carry a note that they are not all executed",
          "not executed" in body.lower() or "recorded" in body.lower(),
          "web/src/components/app/rule-summary.tsx shows every term as the "
          "rule's own without saying which the loop actually reads")
else:
    check("the rule terms component was found", False, terms)

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All rule-reaches-engine checks passed.")
