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
    "symbols",       # the FIRST one only; the rest are reported as not applied
    "timeframe",
    "sizing",        # risk_percent only; fixed volume is reported
    "stopLoss",      # pips exactly; ATR switches the mode, not the multiple
    "takeProfit",    # pips exactly; an RR target is reported
    "trailingStop",  # on/off; the distance is the engine's
    "breakEven",     # at R, or 0 for off
    "limits",        # daily trades and spread cap; max positions is reported
}

RECORDED_ONLY = {
    # The loop reads none of these from the rule. Each one that moves up is a
    # real improvement; each one that stays is something the screen must not
    # present as governing the loop — and `engine_config.translate` must name
    # it in `notApplied` so the client is told per rule rather than in
    # general.
    "evaluateOn", "entry", "exit", "sides", "order", "schedule",
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

print("\n[4] the rule's own terms now drive the loop")
# Each of these differed from the account's stored setting, so a match proves
# the rule's value crossed and did not merely happen to agree.
for field, engine_key, want, was in (
    ("sizing.riskPercent 0.25%", "risk", 0.0025, ENGINE_BEFORE["risk"]),
    ("stopLoss 77 pips", "sl_pips", 77.0, ENGINE_BEFORE["sl_pips"]),
    ("takeProfit 155 pips", "tp_pips", 155.0, ENGINE_BEFORE["tp_pips"]),
    ("limits.maxDailyTrades 2", "max_trades_day", 2, ENGINE_BEFORE["max_trades_day"]),
):
    got = engine.get(engine_key)
    check(f"{field} reaches the engine", got == want,
          f"engine holds {got!r}, rule asked for {want!r}, account had {was!r}")

check("a pip stop switches ATR stops off",
      engine.get("atr_stops") is False, str(engine.get("atr_stops")))
check("the rule's trailing setting wins over the account's",
      engine.get("trailing") is False,
      f"the rule disables it, the account had {ENGINE_BEFORE['trailing']!r}")
check("break even off is written as 0, not left alone",
      engine.get("breakeven_r") == 0.0, str(engine.get("breakeven_r")))

print("\n[4b] what still does NOT cross is REPORTED, not silent")
from apex.platform import engine_config as _ecfg          # noqa: E402

_applied, _missed = _ecfg.translate(_store.get(USER, rid))
terms = {m["term"] for m in _missed}
for term in ("Instruments", "Entry conditions", "Sides"):
    check(f"{term!r} is named as not applied", term in terms, str(sorted(terms)))
check("every reported term says WHY, in words a client can read",
      all(len(m["why"]) > 40 for m in _missed),
      str([m["term"] for m in _missed if len(m["why"]) <= 40]))
check("the running record carries the report to the client",
      {m["term"] for m in (AU.status(USER).get("notApplied") or [])} == terms,
      str(AU.status(USER).get("notApplied")))

print("\n[4b2] a term that does not map is NOT approximated")
# The builder's own default rule uses an ATR stop and a 2R target, neither of
# which the engine has a setting for. Applying something near enough — a pip
# number derived from the R multiple, say — is the failure this module exists
# to refuse: the client sees 2R on the screen and the engine trades a number
# nobody chose. A mutation that did exactly that passed every other check
# here, which is why this one asks directly.
_default = _rd.blank(user_id=USER, account_id="901", symbols=["EURUSD"],
                     timeframe="1h")
_app, _miss = _ecfg.translate(_default)
check("the builder's default target is an RR one",
      _default["takeProfit"]["mode"] == "rr",
      str(_default.get("takeProfit")))
check("and NO pip target is invented from it",
      "tp_pips" not in _app,
      f"translate wrote tp_pips={_app.get('tp_pips')!r} for a rule that "
      f"asked for {_default['takeProfit'].get('rr')}R")
check("it is reported instead", "Take profit" in {m["term"] for m in _miss},
      str(sorted(m["term"] for m in _miss)))
check("the builder's default ATR stop writes no pip stop either",
      "sl_pips" not in _app, f"sl_pips={_app.get('sl_pips')!r}")
check("but it does switch the engine to ATR stops, which it CAN honour",
      _app.get("atr_stops") is True, str(_app.get("atr_stops")))
check("and the multiple it cannot honour is reported",
      "Stop loss" in {m["term"] for m in _miss},
      str(sorted(m["term"] for m in _miss)))

print("\n[4c] the schedule still does not reach the session filter")
check("and the account's own session filter is untouched",
      engine.get("session_filter") == ["LONDON"],
      str(engine.get("session_filter")))

print("\n[4d] stopping puts the account's settings back")
# Before this, a rule that ran once left its risk, stop and target on the
# account for whatever ran next. With two terms that was untidy; with eight
# it would mean a client who stopped a 0.25% rule still carries 0.25% risk.
AU.stop(USER, stopper=lambda uid: True)
restored = user_store.load(USER)
for key in ("risk", "sl_pips", "tp_pips", "max_trades_day", "trailing",
            "symbol", "timeframe"):
    check(f"{key} is back to what the account had",
          restored.get(key) == ENGINE_BEFORE[key],
          f"{restored.get(key)!r}, was {ENGINE_BEFORE[key]!r}")
check("and the loop is switched off", restored.get("active") is False,
      str(restored.get("active")))
check("the stopped record carries no stale report",
      not AU.status(USER).get("notApplied"),
      str(AU.status(USER).get("notApplied")))

# Restart for the sections below, which expect a running loop.
AU.start(USER, rid, starter=lambda uid: started.append(uid) or True)

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

print("\n[6] the product tells the client which terms it will not act on")
# Not a fixed sentence: which terms apply depends on the rule, so the screen
# has to render the server's per-rule answer. A page that said "none of these
# run" would now be as wrong as one that said they all do.
terms = os.path.join(ROOT, "..", "web", "src", "components", "app",
                     "rule-summary.tsx")
page = os.path.join(ROOT, "..", "web", "src", "app", "(app)", "rules",
                    "[id]", "page.tsx")
for path in (terms, page):
    check(f"{os.path.basename(path)} exists", os.path.exists(path), path)
if os.path.exists(terms) and os.path.exists(page):
    body = open(terms, encoding="utf-8").read()
    check("the terms component takes the server's per-rule answer",
          "notApplied" in body, "RuleTerms cannot show what is not applied")
    check("and renders each term's reason, not just its name",
          "n.why" in body or "{n.term}" in body,
          "the list is rendered without the explanation")
    check("the rule page passes it down from the rule it loaded",
          "notApplied" in open(page, encoding="utf-8").read(),
          "the component can show it and the page never supplies it")

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All rule-reaches-engine checks passed.")
