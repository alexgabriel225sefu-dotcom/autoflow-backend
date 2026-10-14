"""A rule's entry and exit conditions decide what the RUNNING loop does.

WHAT WAS WRONG

A client built a rule — "RSI(14) below 30" to enter, "RSI(14) above 70" to
leave — activated it, pressed Start, and the engine chose entries with ITS OWN
strategies. `engine_config.translate` carried the stop, the target, the risk
percentage and the instrument across, and reported `entry` and `exit` to the
client as terms it would not act on. The conditions never reached the loop.

HOW IT IS FIXED, AND WHY IT IS THIS SHAPE

The loop already dispatches its decision through a registry:

    _strategy = strategy_api.get(active_mode)       # active_mode = cfg.STRATEGY
    ...
    return _strategy.signal(_frame)

`cfg.STRATEGY` is per-account (`user["strategy"]`), so `engine_config` can
point one account's loop at a strategy module that does nothing but ask the
PLATFORM EVALUATOR about that account's running rule. There is no second
implementation of "does this rule fire": `apex/platform/rule_strategy.py`
builds a MarketSnapshot and calls `evaluator.evaluate`, the same function the
rule preview screen calls. The check named "the strategy does not decide
anything itself" below proves that by replacing `evaluator.evaluate` and
watching the verdict change with it — a second path would survive that.

WHAT THIS FILE PINS THAT THE RATCHET CANNOT

`tests/test_rule_reaches_engine.py` measures a real start and asks which
engine SETTINGS changed. That is the right question for `sl_pips` and it is
the wrong question for a condition: nothing about `{"id": "rsi", "op":
"below"}` becomes a number in the account record. So this file drives the
strategy module directly, with candles built to satisfy and to fail each
condition, and asserts the verdict.

Run: python3 tests/test_rule_drives_loop.py
"""
import ast
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-drives-")
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

from apex import strategies as _engine_strategies      # noqa: E402
from apex import strategy_api                          # noqa: E402
from apex import user_store                            # noqa: E402
from apex.platform import automation as AU             # noqa: E402
from apex.platform import ctrader_link as CL           # noqa: E402
from apex.platform import engine_config as ECFG        # noqa: E402
from apex.platform import evaluator as EV              # noqa: E402
from apex.platform import ruledoc as RD                # noqa: E402
from apex.platform import store as STORE               # noqa: E402

from apex.brokers import ctrader as _ct_broker         # noqa: E402

_ct_broker.list_accounts = lambda token: [{"ctid": 902, "live": False}]

# Registering the shipped modules is what the loop does at import. The rule
# strategy has to arrive through that same call, or an account pointed at it
# would find an empty registry after any process restart.
strategy_api.load_builtins()

from apex.platform import rule_strategy as RS          # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── candles ─────────────────────────────────────────────────────────────────
# RSI is the condition under test throughout: a monotonically falling series
# puts Wilder's RSI at 0 and a rising one at 100, so "below 30" is satisfied or
# refused by the SHAPE of the series rather than by a tuned constant. A test
# that needed a hand-picked threshold would be measuring the fixture.

BAR = 3600          # the fixture's timeframe is 1h throughout
NOW = 1_700_000_000.0


def _bars(closes, *, last_bar_open=None, bar=BAR):
    """Candles ending with a bar that OPENED at `last_bar_open`.

    Default: the final bar closed exactly at NOW, so nothing is still forming.
    """
    if last_bar_open is None:
        last_bar_open = NOW - bar
    out = []
    n = len(closes)
    for i, c in enumerate(closes):
        t = last_bar_open - (n - 1 - i) * bar
        out.append({"time": t, "open": c, "high": c * 1.001,
                    "low": c * 0.999, "close": c})
    return out


FALLING = _bars([1.3000 - i * 0.0010 for i in range(40)])     # RSI -> 0
RISING = _bars([1.2000 + i * 0.0010 for i in range(40)])      # RSI -> 100


def frame(candles, **kw):
    kw.setdefault("symbol", "EURUSD")
    kw.setdefault("timeframe", "1h")
    kw.setdefault("user_id", USER)
    return strategy_api.Market(candles, **kw)


# ── a real account, with a real running rule ────────────────────────────────
USER = "dddd1111-2222-4333-8444-dddd55556666"

_begun = CL.begin(USER)
_state = _begun["authorizeUrl"].split("state=")[1].split("&")[0]
CL.handle_callback({"code": "c", "state": _state},
                   exchanger=lambda c, u: {"accessToken": "TOK",
                                           "refreshToken": "REF",
                                           "expiresIn": 2592000})
CL.complete(USER, _begun["nonce"], lister=lambda a: [{"ctid": 902,
                                                      "live": False}])
CL.select_account(USER, 902)

user_store.save(USER, {"symbol": "GBPUSD", "timeframe": "5m", "risk": 0.07,
                       "strategy": "fibonacci", "ai_confirm": True,
                       "min_confidence": 70, "htf": True, "autopilot": True,
                       "watchlist": ["USDJPY"], "session_filter": ["LONDON"]})


def build_rule(*, entry, exit_=None, sides="BOTH", symbols=("EURUSD",),
               timeframe="1h", schedule=None, limits=None):
    doc = RD.blank(user_id=USER, account_id="902", symbols=list(symbols),
                   timeframe=timeframe)
    doc["name"] = "driven rule"
    doc["entry"] = {"combine": "AND", "conditions": list(entry)}
    doc["exit"] = {"combine": "OR", "conditions": list(exit_ or [])}
    doc["sides"] = sides
    doc["stopLoss"] = {"mode": "pips", "atrMultiple": None, "pips": 20}
    doc["takeProfit"] = {"mode": "pips", "rr": None, "pips": 40}
    if schedule is not None:
        doc["schedule"] = schedule
    if limits is not None:
        doc["limits"] = dict(doc["limits"], **limits)
    return doc


def run(doc):
    """Store the rule, activate it, and start automation on it. Returns the
    frozen ACTIVE document the loop will be answering about."""
    try:
        AU.stop(USER, stopper=lambda uid: True)
    except Exception:
        pass
    if STORE.exists(USER, doc["ruleDocId"]):
        # A section below re-runs a rule an earlier one already activated.
        # Its frozen version cannot be rewritten — that refusal is the store
        # doing its job — and nothing about the document has changed, so the
        # stored ACTIVE version is already what the loop must answer about.
        live = STORE.get(USER, doc["ruleDocId"])
    else:
        STORE.create(USER, doc)
        live = STORE.activate(
            USER, doc["ruleDocId"],
            known_condition_ids=set(RS._condition_ids()))
    AU.start(USER, doc["ruleDocId"], starter=lambda uid: True)
    return live


RSI_LOW = {"id": "rsi", "params": {"period": 14, "op": "below", "value": 30}}
RSI_HIGH = {"id": "rsi", "params": {"period": 14, "op": "above", "value": 70}}

POS_BUY = {"side": "BUY", "entryPrice": 1.2500, "positionId": "p1",
           "units": 1000}


# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] the engine is told to ask the rule, and told nothing else")

check("engine_config names the strategy the loop must run",
      isinstance(getattr(ECFG, "RULE_STRATEGY_ID", None), str)
      and bool(ECFG.RULE_STRATEGY_ID),
      repr(getattr(ECFG, "RULE_STRATEGY_ID", None)))
check("and the strategy module answers to exactly that id",
      RS.STRATEGY_ID == ECFG.RULE_STRATEGY_ID,
      f"{RS.STRATEGY_ID!r} vs {ECFG.RULE_STRATEGY_ID!r}")
check("load_builtins() registers it, so a restart still finds it",
      ECFG.RULE_STRATEGY_ID in strategy_api.available(),
      str(strategy_api.available()))

_doc = build_rule(entry=[RSI_LOW], exit_=[RSI_HIGH])
_applied, _missed = ECFG.translate(_doc)
check("translate points the account's loop at it",
      _applied.get("strategy") == ECFG.RULE_STRATEGY_ID,
      str(_applied.get("strategy")))

# Each of these is a gate that would otherwise decide instead of the rule.
# `ai_confirm` is the loudest: with it on, the loop DISCARDS the strategy's
# BUY and calls ai.get_signal() for its own, which can hold or reverse it.
print("\n[2] the gates that would overrule the rule are switched off")
for key, want, why in (
    ("ai_confirm", False,
     "the AI replaces a BUY/SELL verdict with its own"),
    ("min_confidence", 0,
     "a rule has no probability score, so any threshold refuses it forever"),
    ("htf", False, "an H1-trend veto blocks entries the rule asked for"),
    ("autopilot", False, "the engine would pick its own instruments"),
):
    check(f"{key} is written as {want!r} ({why})",
          _applied.get(key) == want
          and isinstance(_applied.get(key), type(want)),
          f"got {_applied.get(key)!r}")
check("the engine's own instrument basket is cleared",
      _applied.get("watchlist") == [], str(_applied.get("watchlist")))

print("\n[3] every key translate writes is restored when the rule stops")
for key in ("strategy", "ai_confirm", "min_confidence", "htf", "autopilot",
            "watchlist", "session_filter"):
    check(f"{key} is an owned key", key in ECFG.OWNED_KEYS,
          "stopping would leave it on the account for whatever runs next")
check("translate writes nothing outside OWNED_KEYS",
      set(_applied) <= set(ECFG.OWNED_KEYS) | {"active"},
      str(sorted(set(_applied) - set(ECFG.OWNED_KEYS))))

# ═══════════════════════════════════════════════════════════════════════════
print("\n[4] the strategy does not decide anything itself")
# The point of the whole design: one implementation of "does this rule fire".
# Replacing the evaluator must change the verdict, because there is nothing
# else in the path that could have reached it.
_live = run(_doc)
_real_evaluate = EV.evaluate
try:
    import apex.platform.decision as _D
    EV.evaluate = lambda doc, snap: _D.reject(
        rule_doc_id="x", rule_doc_version=1, symbol=snap.symbol,
        snapshot_ts=snap.ts, code=_D.RULE_INVALID,
        reason="SUBSTITUTED EVALUATOR")
    _sub = RS.PlatformRuleStrategy().signal(frame(FALLING))
    check("replacing evaluator.evaluate changes the verdict",
          _sub.get("action") == "HOLD"
          and "SUBSTITUTED EVALUATOR" in _sub.get("reasoning", ""),
          f"{_sub.get('action')!r} / {_sub.get('reasoning')!r} — a second "
          f"evaluation path survived the substitution")
finally:
    EV.evaluate = _real_evaluate

_src = open(os.path.join(ROOT, "apex", "platform", "rule_strategy.py"),
            encoding="utf-8").read()
_names = {n.attr for n in ast.walk(ast.parse(_src))
          if isinstance(n, ast.Attribute)}
check("and it never evaluates a condition on its own",
      "evaluate_one" not in _names and "bias_of" not in _names,
      str(sorted(_names & {"evaluate_one", "bias_of"})))
check("it calls the evaluator", "evaluate" in _names, str(sorted(_names)[:12]))

# ═══════════════════════════════════════════════════════════════════════════
print("\n[5] the rule's ENTRY conditions decide the entry")
_sig = RS.PlatformRuleStrategy().signal(frame(FALLING))
check("RSI(14) below 30, satisfied -> the loop is told to BUY",
      _sig.get("action") == "BUY", str(_sig))
check("and the reason is the rule's own, naming the condition and its value",
      "rsi" in _sig.get("reasoning", "")
      and "RSI(14)" in _sig.get("reasoning", ""),
      str(_sig.get("reasoning")))
_sig_no = RS.PlatformRuleStrategy().signal(frame(RISING))
check("the same condition, unsatisfied -> HOLD, not a trade",
      _sig_no.get("action") == "HOLD", str(_sig_no))
check("and it says WHY nothing happened",
      "rsi" in _sig_no.get("reasoning", ""), str(_sig_no.get("reasoning")))

print("\n[6] the rule's SIDES is obeyed, not inferred")
_sell = build_rule(entry=[RSI_LOW], sides="SELL")
run(_sell)
_s = RS.PlatformRuleStrategy().signal(frame(FALLING))
check("a SELL-only rule sells on a condition that argues BUY",
      _s.get("action") == "SELL",
      f"{_s.get('action')!r} — the rule's own side must win outright")

print("\n[7] the rule's EXIT conditions close the position")
_doc2 = build_rule(entry=[RSI_LOW], exit_=[RSI_HIGH])
run(_doc2)
_ex = RS.PlatformRuleStrategy().signal(frame(RISING, open_position=POS_BUY,
                                             price=1.2600))
check("RSI(14) above 70, satisfied, with a position open -> CLOSE",
      _ex.get("action") == "CLOSE", str(_ex))
_hold = RS.PlatformRuleStrategy().signal(frame(FALLING, open_position=POS_BUY,
                                               price=1.2400))
check("unsatisfied, with the same position open -> the position is kept",
      _hold.get("action") == "HOLD", str(_hold))
check("an exit verdict is reported by exit() too, from the same evaluation",
      RS.PlatformRuleStrategy().exit(
          frame(RISING, open_position=POS_BUY))["exit"] is True
      and RS.PlatformRuleStrategy().exit(
          frame(FALLING, open_position=POS_BUY))["exit"] is False)

# ═══════════════════════════════════════════════════════════════════════════
print("\n[8] nothing trades without a rule to trade")
_doc3 = build_rule(entry=[RSI_LOW])
run(_doc3)
for name, f in (
    ("the loop did not identify the account",
     strategy_api.Market(FALLING, symbol="EURUSD", timeframe="1h")),
    ("the instrument is not one the rule names",
     frame(FALLING, symbol="USDJPY")),
    ("the timeframe is not the rule's",
     frame(FALLING, timeframe="5m")),
):
    v = RS.PlatformRuleStrategy().signal(f)
    check(f"HOLD when {name}", v.get("action") == "HOLD", str(v))
    check(f"   and it says so, rather than going quiet ({name})",
          len(v.get("reasoning", "")) > 20, str(v.get("reasoning")))

# PAUSED is the dangerous one. Stopping clears `ruleDocId` from the automation
# record, so "is a rule running" is answered by accident there — the rule id is
# simply gone. Pausing writes `dict(rec, state=PAUSED)` and KEEPS the id, so
# only the state says not to trade. automation.pause's own docstring calls a
# paused state that left a loop ticking "the most dangerous word on the
# screen", and the client is told no new positions will be opened until they
# resume. This is the check that the strategy keeps that promise.
AU.pause(USER, stopper=lambda uid: True)
_paused = RS.PlatformRuleStrategy().signal(frame(FALLING))
check("HOLD while automation is PAUSED, on a rule that would otherwise fire",
      _paused.get("action") == "HOLD",
      f"{_paused.get('action')!r} — the rule id is still on the record when "
      f"paused, so only the state can refuse this")
check("   and the reason says it is paused, not something vaguer",
      "paused" in _paused.get("reasoning", "").lower(),
      str(_paused.get("reasoning")))

AU.stop(USER, stopper=lambda uid: True)
_stopped = RS.PlatformRuleStrategy().signal(frame(FALLING))
check("HOLD once automation is stopped, even on a satisfied rule",
      _stopped.get("action") == "HOLD", str(_stopped))

# A legacy Telegram account has no platform rule at all. It can only reach
# this module by holding this strategy id, and if it ever does, the answer is
# no trade — never the engine's own strategies under a rule's name.
_unknown = RS.PlatformRuleStrategy().signal(
    strategy_api.Market(FALLING, symbol="EURUSD", timeframe="1h",
                        user_id="nobody-at-all"))
check("HOLD for an account with no rule of any kind",
      _unknown.get("action") == "HOLD", str(_unknown))

run(_doc3)   # back to a running rule for the sections below

# ═══════════════════════════════════════════════════════════════════════════
print("\n[9] the bar still forming is not what the rule is judged on")
# `evaluateOn` is "bar_close". The loop's last candle is the bar in progress,
# whose close is not the close. A rule judged on it can fire on a price the
# bar never closes at — and the opposite: a satisfied rule can be hidden by a
# single tick in the wrong direction.
_forming_up = FALLING[:-1] + [dict(FALLING[-1], time=NOW - 60,
                                   close=FALLING[-1]["close"] * 1.05,
                                   high=FALLING[-1]["close"] * 1.06)]
_d, _why = RS.decide(frame(_forming_up), now=NOW)
check("a spike on the unfinished bar does not hide a satisfied rule",
      _d is not None and _d.verdict == "BUY",
      f"{getattr(_d, 'verdict', None)!r} / {_why}")

_forming_down = RISING[:-1] + [dict(RISING[-1], time=NOW - 60,
                                    close=RISING[-1]["close"] * 0.95,
                                    low=RISING[-1]["close"] * 0.94)]
_d2, _why2 = RS.decide(frame(_forming_down), now=NOW)
check("and a dip on the unfinished bar does not manufacture one",
      _d2 is not None and _d2.verdict == "HOLD",
      f"{getattr(_d2, 'verdict', None)!r} / {_why2}")

_closed = _bars([1.3 - i * 0.001 for i in range(40)],
                last_bar_open=NOW - BAR)
_d3, _ = RS.decide(frame(_closed), now=NOW)
check("a bar that has closed IS judged",
      _d3 is not None and _d3.verdict == "BUY",
      str(getattr(_d3, "verdict", None)))

# The decision is stamped with the bar it was about, not the moment it ran.
# `_forming_up` is the frame that can tell the two apart: its last bar is
# still open, so the bar actually judged closed one BAR earlier than `now`.
# On a frame whose last bar closed exactly at `now` — every other fixture
# here — the two values are identical and a tick-stamped journal looks right.
_d4, _ = RS.decide(frame(_forming_up), now=NOW)
check("the decision is stamped with the closed bar, not the moment it ran",
      _d4 is not None and _d4.snapshot_ts == NOW - BAR,
      f"{getattr(_d4, 'snapshot_ts', None)!r}, expected {NOW - BAR!r} — a "
      f"journal stamped with the tick cannot say which bar was judged")

# ruledoc.validate only requires a timeframe to be NON-EMPTY, so a rule can be
# activated on one whose candle length nothing here knows. Reaching for a
# default length would then decide "has this bar closed?" with the wrong
# number and judge an unfinished bar, which section [9] exists to prevent.
_d5, _why5 = RS.decide(frame(FALLING, timeframe="7m"), now=NOW)
check("a timeframe whose length is unknown is refused, not assumed",
      _d5 is None and "7m" in _why5,
      f"{getattr(_d5, 'verdict', None)!r} / {_why5} — measuring an unknown "
      f"timeframe with a default candle length judges the wrong bar")

# ═══════════════════════════════════════════════════════════════════════════
print("\n[10] the verdict survives the loop's own gates on the way to an order")
_sig = RS.PlatformRuleStrategy().signal(frame(FALLING))
_app, _ = ECFG.translate(_doc3)
check("the signal clears the confidence gate the rule's own config sets",
      _sig.get("confidence", 0) >= _app.get("min_confidence", 70),
      f"confidence {_sig.get('confidence')!r} vs threshold "
      f"{_app.get('min_confidence')!r}")
# The size multiplier is the quiet one. druckenmiller_multiplier reads a
# confidence and a criteria count; a score-less verdict scored 0.6x there, so
# a client who set 1% risk would have been given 0.6% and nothing would have
# said so.
_mult = _engine_strategies.druckenmiller_multiplier(
    _sig.get("confidence", 0), _sig.get("criteriaScore", 0), None, None)
check("and the rule's risk percentage is not quietly scaled down",
      _mult == 1.0,
      f"the engine would size this entry at {_mult}x the rule's risk")

print("\n[11] §14: the verdict names what produced it")
check("the signal carries the strategy id",
      _sig.get("strategy_id") == ECFG.RULE_STRATEGY_ID,
      str(_sig.get("strategy_id")))
check("and a version", bool(_sig.get("strategy_version")),
      str(_sig.get("strategy_version")))
check("and the rule it answered for",
      _sig.get("ruleDocId") == _doc3["ruleDocId"], str(_sig.get("ruleDocId")))

# ═══════════════════════════════════════════════════════════════════════════
print("\n[12] the loop hands the strategy what it needs to find the rule")
_ul = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
_tree = ast.parse(_ul)
_market_calls = [n for n in ast.walk(_tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "Market"]
check("the loop builds exactly one market frame for its strategy",
      len(_market_calls) == 1, f"{len(_market_calls)} Market(...) calls")
if _market_calls:
    _kw = {k.arg for k in _market_calls[0].keywords}
    check("and passes the account id, so the rule can be found",
          "user_id" in _kw, str(sorted(_kw)))
    check("and the spread, so a rule's spread ceiling can be honoured",
          "spread_pips" in _kw, str(sorted(_kw)))
_m = strategy_api.Market(FALLING, symbol="EURUSD", timeframe="1h",
                         user_id="u1", spread_pips=1.4)
check("Market carries them through to the strategy",
      _m.user_id == "u1" and _m.spread_pips == 1.4,
      f"{getattr(_m, 'user_id', None)!r} / {getattr(_m, 'spread_pips', None)!r}")
check("and both are optional, so every existing caller is unchanged",
      strategy_api.Market(FALLING, symbol="EURUSD").user_id == ""
      and strategy_api.Market(FALLING, symbol="EURUSD").spread_pips is None)

print("\n[13] a rule's spread ceiling is answered, not guessed")
_capped = build_rule(entry=[RSI_LOW], limits={"maxSpreadPips": 1.0})
run(_capped)
_wide = RS.PlatformRuleStrategy().signal(frame(FALLING, spread_pips=4.0))
check("over the ceiling -> no entry", _wide.get("action") == "HOLD", str(_wide))
_tight = RS.PlatformRuleStrategy().signal(frame(FALLING, spread_pips=0.4))
check("under it -> the rule decides as normal",
      _tight.get("action") == "BUY", str(_tight))
_blind = RS.PlatformRuleStrategy().signal(frame(FALLING, spread_pips=None))
check("no spread in the frame -> refused, never treated as under the cap",
      _blind.get("action") == "HOLD", str(_blind))

# ═══════════════════════════════════════════════════════════════════════════
print("\n[14] what STILL does not reach the loop is named to the client")
_, _miss = ECFG.translate(build_rule(entry=[RSI_LOW], exit_=[RSI_HIGH]))
_terms = {m["term"] for m in _miss}
for gone in ("Entry conditions", "Exit conditions", "Sides"):
    check(f"{gone!r} is no longer reported as not applied",
          gone not in _terms, str(sorted(_terms)))
for named in ("Evaluation timing", "Exit timing", "Position size"):
    check(f"{named!r} IS named, because it is still not exact",
          named in _terms, str(sorted(_terms)))
check("every reported term says why, in words a client can read",
      all(len(m["why"]) > 40 for m in _miss),
      str([m["term"] for m in _miss if len(m["why"]) <= 40]))

print("\n[15] still demo only, and still no execution path")
check("the strategy module cannot reach the order bridge",
      "bridge" not in _names and "submit" not in _names,
      str(sorted(_names & {"bridge", "submit"})))
check("it names no broker-mutating operation",
      not ({"place_order", "close_position", "amend_sltp", "force_trade",
            "authorize_order", "authorize_close", "modify_position"}
           & ({n.id for n in ast.walk(ast.parse(_src))
               if isinstance(n, ast.Name)} | _names)))
check("automation still only ever starts a demo loop",
      AU.status(USER).get("mode") == "demo", str(AU.status(USER)))

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All rule-drives-loop checks passed.")
