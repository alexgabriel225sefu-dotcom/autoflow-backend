"""Choosing one of the engine's ready-made strategies, on the platform.

WHAT WAS WRONG

The engine ships fifteen strategies in a registry. A Telegram client picked
one off a menu. A platform client could not pick any: `engine_config.translate`
writes `applied["strategy"] = RULE_STRATEGY_ID` for every rule, so the only
way to trade here was to write a rule from scratch — and the owner's
description of the product is the opposite of that ("you connect your account
and you choose yourself how you want to trade").

THE FOUR FACTS THIS FILE PINS

  1 THE CATALOGUE CANNOT DRIFT FROM THE REGISTRY. A strategy added to the
    engine and not described here is reported, not quietly offered. A strategy
    described here and registered nowhere is not offered at all — a client
    must never be able to select their way into the loop's
    "no strategy module is loaded for ..." hold. Both directions are proved by
    actually registering and unregistering one.

  2 NOTHING CLAIMS BEHAVIOUR THE CLASS DOES NOT HAVE. Labels come from the
    registry, so a label cannot disagree with its class — proved by changing a
    class's label and watching the catalogue follow. Every description carries
    a `source` pointer, and every pointer resolves to code that exists.

  3 A PRESET IS A RULEDOC. One field different, every other term the same, so
    the frozen version, the journal, the risk gates and the engine snapshot
    all keep working unchanged. A preset document that carries conditions is
    REFUSED, because a condition on it would be a term the client can read and
    the engine will never consult.

  4 AND THE EMPTY-CONDITIONS HOLE IS SHUT. `evaluator._eval_block` treats an
    empty AND block as satisfied — vacuously true. The only thing that kept
    that unreachable was validate() requiring an entry condition, which a
    preset document does not have. So a preset document with `sides: BUY`
    would have read "entry conditions met" on EVERY BAR. The evaluator refuses
    a preset outright, and the test below is the one that would have caught
    that buy-every-bar machine.

Run: python3 tests/test_strategy_catalog.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-catalog-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

import requests                                             # noqa: E402

from apex import strategy_api as SA                          # noqa: E402
from apex.platform import api as A                           # noqa: E402
from apex.platform import decision as D                      # noqa: E402
from apex.platform import engine_config as ECFG              # noqa: E402
from apex.platform import evaluator as EV                    # noqa: E402
from apex.platform import identity as I                      # noqa: E402
from apex.platform import ruledoc as RD                      # noqa: E402
from apex.platform import snapshot as SNAP                   # noqa: E402
from apex.platform import store as ST                        # noqa: E402
from apex.platform import strategy_catalog as SC             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── [1] the catalogue against the registry ──────────────────────────────────
print("\n[1] the catalogue cannot drift from the registry")

_registered = set(SA.load_builtins())
_offered = set(SC.ids())

check("every strategy on offer is actually registered",
      _offered <= _registered,
      f"{sorted(_offered - _registered)} would be offered and the loop would "
      f"hold with 'no strategy module is loaded for ...'")
check("the catalogue is in sync with the engine right now",
      SC.drift() == {"unclassified": [], "stale": []}, str(SC.drift()))
check("and it offers the fifteen the bot's menu had, plus the extras",
      len(_offered) == 15, f"{len(_offered)}: {sorted(_offered)}")


print("\n[1a] ADDING a registered strategy is noticed")


@SA.register
class _DriftProbe(SA.Strategy):
    strategy_id = "_drift_probe"
    strategy_version = "0.0.1"
    label = "Drift probe"


_drift = SC.drift()
check("a strategy the engine registers and this file does not describe is "
      "reported as unclassified",
      "_drift_probe" in _drift["unclassified"], str(_drift))
check("it is NOT offered to a client",
      "_drift_probe" not in SC.ids() and not SC.is_preset("_drift_probe"))
check("and the API payload carries the drift, so it is visible in production "
      "and not only in this file",
      "_drift_probe" in (SC.catalogue().get("unclassified") or []),
      str(SC.catalogue().get("unclassified")))
SA.unregister("_drift_probe")
check("the probe is gone again", SC.drift()["unclassified"] == [])


print("\n[1b] REMOVING a registered strategy is noticed")
_removed = SA.unregister("momentum")
check("unregistering a described strategy makes it stale",
      SC.drift()["stale"] == ["momentum"], str(SC.drift()))
check("and it drops straight out of what is offered",
      "momentum" not in SC.ids() and SC.get("momentum") is None)
check("so a client cannot choose it",
      not SC.is_preset("momentum"))
# The subset check in [1] above cannot fail while the two tables agree, which
# they do in a healthy tree. Asserted again HERE, with a described strategy
# deliberately missing from the registry, is where "never offer what is not
# registered" is actually load-bearing.
check("nothing on offer is unregistered, checked while one is missing",
      set(SC.ids()) <= set(SA.available()),
      f"{sorted(set(SC.ids()) - set(SA.available()))} would be offered from "
      f"this release's table alone, and the loop holds on an id nothing "
      f"registers")
_names = [d["id"] for d in SC.describe()]
check("the rest of the catalogue is unaffected",
      len(_names) == 14 and "zscore" in _names, str(len(_names)))
SA.register(_removed)
check("re-registering puts it back",
      SC.is_preset("momentum") and SC.drift()["stale"] == [])


# ── [2] no claim the code does not support ──────────────────────────────────
print("\n[2] nothing claims behaviour the class does not have")

_entries = SC.describe()
check("every entry has all four descriptive fields filled in",
      all(e["what"] and e["decides"] and e["refuses"] and e["source"]
          for e in _entries),
      str([e["id"] for e in _entries
           if not (e["what"] and e["decides"] and e["refuses"]
                   and e["source"])]))

# The `source` pointer is the reviewer's way back to the function the sentence
# was written from. A pointer at code that does not exist is a sentence nobody
# can check.
_bad_sources = []
for e in _entries:
    for ref in e["source"].split(";"):
        ref = ref.strip()
        path, _, symbol = ref.partition(":")
        if not os.path.exists(os.path.join(ROOT, path)):
            _bad_sources.append(f"{e['id']}: no file {path}")
            continue
        symbol = symbol.split()[0] if symbol else ""
        if not symbol:
            continue
        text = open(os.path.join(ROOT, path)).read()
        if f"def {symbol}" not in text and f"class {symbol}" not in text:
            _bad_sources.append(f"{e['id']}: {path} has no {symbol}")
check("every source pointer resolves to a file, and to the function or class "
      "it names", not _bad_sources, str(_bad_sources))

# A label kept in the catalogue could disagree with the class it describes.
# This proves it is read from the registry instead.
from apex import strategy_modules as _SM                      # noqa: E402
_orig_label = _SM.AutoStrategy.label
_SM.AutoStrategy.label = "Renamed in the engine"
check("the label comes from the strategy class, not from this platform's "
      "own table",
      SC.get("auto")["label"] == "Renamed in the engine",
      SC.get("auto")["label"])
_SM.AutoStrategy.label = _orig_label

check("and the version is the class's own, so a trade can be traced to it",
      SC.get("auto")["version"] == _SM.AutoStrategy.strategy_version)


print("\n[2a] the rule builder is not a preset, and the dangerous two are "
      "withheld with reasons")
_withheld = {w["id"]: w for w in SC.withheld()}
check("platform_rule is excluded from the presets",
      ECFG.RULE_STRATEGY_ID not in SC.ids()
      and not SC.is_preset(ECFG.RULE_STRATEGY_ID))
check("and is marked distinctly rather than hidden",
      _withheld.get(ECFG.RULE_STRATEGY_ID, {}).get("kind") == "rule_builder",
      str(_withheld.get(ECFG.RULE_STRATEGY_ID)))
check("grid and martingale are registered",
      {"grid", "martingale"} <= _registered)
check("and are withheld, each with the reason a client would be given",
      all(_withheld.get(sid, {}).get("reason") for sid in
          ("grid", "martingale")),
      str(sorted(_withheld)))
check("they cannot be chosen",
      not SC.is_preset("grid") and not SC.is_preset("martingale"))
check("the catalogue names the rule-builder id, so the UI does not keep its "
      "own copy of that string",
      SC.catalogue()["ruleBuilderId"] == ECFG.RULE_STRATEGY_ID)


print("\n[2b] a registry that cannot be read offers nothing")
_real_describe = SA.describe
SA.describe = lambda: (_ for _ in ()).throw(RuntimeError("registry is gone"))
check("describe() answers with an empty list rather than the table",
      SC.describe() == [] and SC.ids() == ())
check("is_preset says no to everything, so nothing can be activated",
      not SC.is_preset("momentum") and not SC.is_preset("auto"))
SA.describe = _real_describe
check("and it recovers when the registry can be read again",
      len(SC.describe()) == 15)


# ── [3] a preset is a RuleDoc ───────────────────────────────────────────────
print("\n[3] a chosen preset is wrapped in a RuleDoc, not a second shape")

_blank = RD.blank(user_id="u", account_id="901", symbols=["EURUSD"],
                  timeframe="1h")
check("a blank rule names no preset, so the default is still the client's "
      "own conditions",
      _blank.get("strategy") is None, repr(_blank.get("strategy")))
check("and without one, an entry condition is still required",
      RD.validate(_blank) == ["entry.conditions: at least one condition is "
                              "required"],
      str(RD.validate(_blank)))

_preset_doc = SC.apply_to(_blank, "trend")
check("wrapping does not mutate the draft the caller handed over",
      _blank.get("strategy") is None)
check("the wrapped document names the strategy",
      _preset_doc["strategy"] == "trend")
check("and carries no conditions, because the strategy decides its own",
      _preset_doc["entry"]["conditions"] == []
      and _preset_doc["exit"]["conditions"] == [])

# The blank already has no conditions, so clearing them there proves nothing.
# A client who built half a rule and then picked a preset is the case that
# matters: their conditions have to GO, or the rule page would show terms the
# engine never consults.
_half_built = dict(
    _blank,
    entry={"combine": "AND", "conditions": [{"id": "rsi", "params": {}}]},
    exit={"combine": "OR", "conditions": [{"id": "macd", "params": {}}]})
_converted = SC.apply_to(_half_built, "zscore")
check("conditions a client had already built are cleared by the wrap, not "
      "carried along as decoration",
      _converted["entry"]["conditions"] == []
      and _converted["exit"]["conditions"] == [],
      str(_converted["entry"]["conditions"]))
check("the combine choice survives, so switching back does not lose it",
      _converted["entry"]["combine"] == "AND"
      and _converted["exit"]["combine"] == "OR")
check("and the half-built draft itself is not mutated",
      len(_half_built["entry"]["conditions"]) == 1)
check("the converted document validates",
      RD.validate(_converted, known_strategy_ids=SC.ids()) == [],
      str(RD.validate(_converted, known_strategy_ids=SC.ids())))
check("it keeps every other term — these are what the risk gates read",
      all(_preset_doc[k] == _blank[k] for k in
          ("symbols", "timeframe", "sizing", "stopLoss", "takeProfit",
           "trailingStop", "breakEven", "limits", "schedule")))
check("and it validates, which is what makes it activatable",
      RD.validate(_preset_doc, known_strategy_ids=SC.ids()) == [],
      str(RD.validate(_preset_doc, known_strategy_ids=SC.ids())))

def _wrap_refused(sid):
    """True when apply_to refuses `sid`. A refusal is the only safe answer:
    the caller is about to write this onto an account."""
    try:
        SC.apply_to(_blank, sid)
        return False
    except SC.NotAPreset:
        return True


_unoffered = ("grid", "martingale", ECFG.RULE_STRATEGY_ID, "nonsense", "",
              None, "TREND")
check("wrapping refuses every strategy the platform does not offer",
      all(_wrap_refused(sid) for sid in _unoffered),
      str([sid for sid in _unoffered if not _wrap_refused(sid)]))


print("\n[3a] a preset document carrying conditions is refused")
_decorated = dict(_preset_doc,
                  entry={"combine": "AND",
                         "conditions": [{"id": "rsi", "params": {}}]})
_problems = RD.validate(_decorated, known_strategy_ids=SC.ids())
check("entry conditions on a preset rule are a validation error",
      any(p.startswith("entry.conditions:") for p in _problems),
      str(_problems))
check("and the message says what to do about it, both ways",
      any("remove these conditions" in p and "clear the strategy" in p
          for p in _problems), str(_problems))
_decorated_exit = dict(_preset_doc,
                       exit={"combine": "OR",
                             "conditions": [{"id": "rsi", "params": {}}]})
check("so are exit conditions",
      any(p.startswith("exit.conditions:")
          for p in RD.validate(_decorated_exit, known_strategy_ids=SC.ids())),
      str(RD.validate(_decorated_exit, known_strategy_ids=SC.ids())))


print("\n[3b] the field is checked at the boundary that makes a rule live")
for _bad in ("nonsense", "grid", ECFG.RULE_STRATEGY_ID):
    _p = RD.validate(dict(_preset_doc, strategy=_bad),
                     known_strategy_ids=SC.ids())
    check(f"{_bad!r} is refused when the offered list is supplied",
          any(p.startswith("strategy:") for p in _p), str(_p))
check("a blank string is not a way to mean 'no preset'",
      any(p.startswith("strategy:") for p in
          RD.validate(dict(_preset_doc, strategy="  "),
                      known_strategy_ids=SC.ids())))
check("and a non-string is refused",
      any(p.startswith("strategy:") for p in
          RD.validate(dict(_preset_doc, strategy=7),
                      known_strategy_ids=SC.ids())))

OWNER = "cccccccc-3333-4333-8333-cccccccccccc"
_live = ST.create(OWNER, dict(_preset_doc, ruleDocId="preset-ok"))
_frozen = ST.activate(OWNER, "preset-ok")
check("a preset rule activates and is frozen like any other",
      _frozen["state"] == RD.ACTIVE and _frozen["strategy"] == "trend")

ST.create(OWNER, dict(_preset_doc, ruleDocId="preset-bad", strategy="grid"))
try:
    ST.activate(OWNER, "preset-bad")
    check("activation refuses a withheld strategy", False,
          "'grid' was activated")
except RD.RuleDocInvalid as e:
    check("activation refuses a withheld strategy, naming the field",
          any(p.startswith("strategy:") for p in e.problems), str(e.problems))


# ── [4] the hole an empty condition block would have opened ─────────────────
print("\n[4] the evaluator refuses a preset instead of reading its empty "
      "conditions as satisfied")

_bars = [{"open": 1.0 + i / 1000, "high": 1.002 + i / 1000,
          "low": 0.998 + i / 1000, "close": 1.0 + i / 1000,
          "time": 1_700_000_000 + i * 3600} for i in range(60)]
_snap = SNAP.MarketSnapshot(symbol="EURUSD", timeframe="1h", candles=_bars,
                            price=1.06, ts=1_700_216_000, spread_pips=0.4,
                            open_positions=[], balance=10_000.0)

# `sides: BUY` is the dangerous shape. With BOTH, the direction check catches
# an empty entry block; with BUY there is nothing left to catch it.
_armed = dict(_preset_doc, ruleDocId="armed", state=RD.ACTIVE, sides="BUY")
_verdict = EV.evaluate(_armed, _snap)
check("an empty AND entry block on its own IS treated as satisfied — the "
      "hazard is real, not hypothetical",
      EV._eval_block({"combine": "AND", "conditions": []}, _snap)[1] is True,
      "if this ever becomes False the guard below is belt-and-braces; until "
      "then it is the only thing standing between a preset rule and a buy "
      "on every bar")
check("so a preset rule does NOT come back BUY",
      _verdict.verdict != D.BUY, f"verdict was {_verdict.verdict}")
check("it comes back REJECT",
      _verdict.verdict == D.REJECT, str(_verdict.verdict))
check("with a code that says the evaluator is not the decider",
      _verdict.refusal_code == D.PRESET_STRATEGY, str(_verdict.refusal_code))
check("and a reason naming the strategy that IS",
      "trend" in (_verdict.reason or ""), _verdict.reason)
check("the refusal is not executable, so nothing downstream can place it",
      not _verdict.executable)
check("the same is true with sides BOTH",
      EV.evaluate(dict(_armed, sides="BOTH"), _snap).refusal_code
      == D.PRESET_STRATEGY)
check("and while a position is open, so a preset cannot be closed by an "
      "empty exit block either",
      EV.evaluate(_armed, SNAP.MarketSnapshot(
          symbol="EURUSD", timeframe="1h", candles=_bars, price=1.06,
          ts=1_700_216_000, open_positions=[{"symbol": "EURUSD",
                                             "side": "BUY"}],
          balance=10_000.0)).refusal_code == D.PRESET_STRATEGY)

check("a rule built from conditions is untouched by the guard",
      EV.evaluate(
          dict(_blank, ruleDocId="plain", state=RD.ACTIVE, sides="BUY",
               entry={"combine": "AND",
                      "conditions": [{"id": "rsi",
                                      "params": {"period": 14,
                                                 "comparator": "below",
                                                 "value": 30}}]}),
          _snap).refusal_code != D.PRESET_STRATEGY)

check("PRESET_STRATEGY is not filed as a client-fixable config error",
      not D.is_config_error(D.PRESET_STRATEGY),
      "it would tell the client to fix a rule that is correct")
check("but it is declared in a group, so every code belongs to one",
      D.PRESET_STRATEGY in D.DELEGATED_CODES)


# ── [5] the route ───────────────────────────────────────────────────────────
print("\n[5] GET strategies serves the catalogue, to signed-in clients only")

_USER = {"id": OWNER, "email": "cat@example.com",
         "email_confirmed_at": "2026-01-01T00:00:00Z"}


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


requests.get = lambda url, **kw: _Resp(200, _USER)


def _call(method, path, headers=None):
    I.forget_all()
    h = {"Authorization": "Bearer token"} if headers is None else headers
    return A.handle(method, path, h, None)


_st, _body = _call("GET", "/api/v1/strategies")
check("it answers 200 for a signed-in client", _st == 200, str(_st))
check("with the whole catalogue",
      len(_body.get("strategies") or []) == 15,
      str(len(_body.get("strategies") or [])))
check("each entry carries what a client needs to read before choosing",
      all({"id", "label", "version", "family", "what", "decides", "refuses"}
          <= set(e) for e in _body["strategies"]))
check("the withheld ones are served too, with their reasons",
      {w["id"] for w in _body.get("withheld") or []}
      == {"grid", "martingale", ECFG.RULE_STRATEGY_ID},
      str([w["id"] for w in _body.get("withheld") or []]))
check("there is no drift key when there is no drift",
      "unclassified" not in _body)
check("the payload is JSON-serialisable, which is what the transport needs",
      isinstance(json.dumps(_body), str))

_st_anon, _body_anon = _call("GET", "/api/v1/strategies", headers={})
check("and it refuses an unauthenticated caller",
      _st_anon in (401, 403) and not _body_anon.get("ok"),
      f"{_st_anon} {_body_anon}")
_st_post, _ = _call("POST", "/api/v1/strategies")
check("POST is not a thing this route does",
      _st_post in (404, 405), str(_st_post))

# The route must not have eaten its neighbour.
_st_cond, _body_cond = _call("GET", "/api/v1/conditions")
check("the conditions route still answers beside it",
      _st_cond == 200 and len(_body_cond.get("conditions") or {}) == 12,
      f"{_st_cond} {len(_body_cond.get('conditions') or {})}")


shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All strategy-catalogue checks passed.")
