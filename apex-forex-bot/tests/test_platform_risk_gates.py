"""The risk gates — §5 of docs/LIVE_EXECUTION_SPECIFICATION.md.

WHAT THESE CHECKS ARE FOR

§5 lists nine things that must hold before an order is built, and says of
three of them that they are "recorded in the RuleDoc today and not enforced by
any engine consumer". A limit that is recorded and not enforced is worse than
an absent one: the client reads it on their own rule page and believes it
protects them. So most of what follows is not "does the gate exist" but "does
the gate actually bite, at the exact number it claims".

That is why every limit here is tested at three points — under it, exactly on
it, and over it. An off-by-one in a cap is the failure mode this project has
already met once: the legacy bot's daily counter increments when a trade
CLOSES, so a loop could hold five open positions against a cap of four and the
log read `5/4`. A cap that counts wrong is not a cap, and the only way to know
which side of the boundary a comparison falls on is to test the boundary.

AND THE OTHER HALF: FAILING CLOSED

Every gate needs a fact — the live balance, the open positions, today's
realised loss. §5 says every gate must fail closed, which means a fact the
platform could not read is a refusal and not a pass. Section [10] asks every
gate that question in turn: with its fact removed, does it still refuse, and
with its own code? A gate that quietly passes when it cannot measure anything
is the most dangerous kind, because it passes most loudly on the worst day.

NO BROKER, NO NETWORK. The balance arrives through an injected callable, which
is also the point of the injection: §5 requires the balance to be read at
decision time and never cached, and a callable is the only shape that lets
section [3] prove the read happens on every single call.

Run: python3 tests/test_platform_risk_gates.py
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import forex                              # noqa: E402
from apex.platform import risk_gates as G           # noqa: E402
from apex.platform import ruledoc as R              # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


# ── fixtures ────────────────────────────────────────────────────────────────
# One account, one instrument, round numbers, so every expected figure below
# can be read off by hand rather than trusted:
#
#   balance 10,000   EUR_USD at 1.1000   stop 1.0975 = 25 pips
#   40,000 units × $0.0001 per pip per unit × 25 pips = $100 = 1.00% of balance
#
# 1.00% is also `ruledoc.blank()`'s own default risk and the legacy bot's
# live activation cap, so the default fixture sits exactly ON the ceiling. That
# is deliberate: it makes an off-by-one in the risk comparison fail here rather
# than in production.
BALANCE = 10000.0
ENTRY = 1.1000
STOP = 1.0975
UNITS = 40000.0


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out.get(k) or {}, v) if isinstance(v, dict) else v
    return out


def doc(**over):
    """An ACTIVE RuleDoc that `ruledoc.validate` accepts, with overrides."""
    d = R.blank(user_id="u-1", account_id="701", symbols=["EUR_USD"])
    d["state"] = R.ACTIVE
    d["name"] = "test rule"
    d["entry"] = {"combine": "AND",
                  "conditions": [{"id": "ema_cross", "params": {}}]}
    d["stopLoss"] = {"mode": "pips", "pips": 25.0, "atrMultiple": None}
    d["takeProfit"] = {"mode": "pips", "pips": 50.0, "rr": None}
    d["sizing"] = {"mode": R.SIZING_RISK, "riskPercent": 1.0,
                   "fixedVolume": None}
    return _merge(d, over)


def intent(**over):
    kw = dict(symbol="EUR_USD", side="BUY", entry_price=ENTRY,
              stop_price=STOP, volume=UNITS)
    kw.update(over)
    return G.OrderIntent(**kw)


def state(**over):
    """Every fact the gates need, all present and all within limits."""
    st = {"positions": [], "dailyRealisedPnl": 0.0, "dailyTradesOpened": 0,
          "peakBalance": BALANCE, "spreadPips": 0.8, "slippagePoints": 0.0}
    st.update(over)
    return st


def reader(value=BALANCE, log=None):
    """A stand-in for the broker balance read. Raises if given an exception."""
    def read():
        if log is not None:
            log.append(value)
        if isinstance(value, BaseException):
            raise value
        return value
    return read


def go(rule=None, it=None, *, mode="live", balance=BALANCE, st=None, **kw):
    return G.authorize(doc() if rule is None else rule,
                       intent() if it is None else it, mode=mode,
                       balance_reader=(balance if callable(balance)
                                       else reader(balance)),
                       state=state() if st is None else st, **kw)


def pos(symbol="GBP_USD", side="BUY", units=10000.0, entry=1.2500,
        stop=1.2450):
    """One open position in the shape `broker_read.positions()` returns."""
    return {"symbol": symbol, "side": side, "units": units,
            "entryPrice": entry, "stopLoss": stop, "positionId": 1}


print("\n[1] the happy path — every gate runs, and says so")
v = go()
check("an order inside every limit is authorised", v.allowed, v.code)
check("it is truthy, so a caller can write `if verdict:`", bool(v) is True)
check("every gate is accounted for",
      [c["gate"] for c in v.checks] == list(G.GATES),
      str([c["gate"] for c in v.checks]))
check("none of them was skipped",
      all(c["state"] != G.SKIPPED for c in v.checks),
      str([c for c in v.checks if c["state"] == G.SKIPPED]))
check("the live balance is recorded, because the refusals are read later",
      v.facts.get("balance") == BALANCE, str(v.facts.get("balance")))
check("so is the money actually at risk",
      v.facts.get("riskMoney") == 100.0, str(v.facts.get("riskMoney")))
check("and it round-trips to a dict for the journal",
      isinstance(v.as_dict(), dict)
      and v.as_dict()["code"] == v.code
      and v.as_dict()["mode"] == "live", str(v.as_dict())[:120])


print("\n[2] a stop exists — and this module agrees with ruledoc")
# `ruledoc` already refuses to ACTIVATE a rule with no stop: "a rule without a
# stop has no defined risk". §5 asks for the same thing at order time, because
# activation happened once and possibly months ago, and because the stop that
# matters is the price on this order rather than the mode on the document.
stopless = doc(stopLoss={"mode": None, "pips": None, "atrMultiple": None})
check("ruledoc refuses to activate it",
      any(p.startswith("stopLoss.mode") for p in R.validate(stopless)),
      str(R.validate(stopless)))
v = go(stopless)
check("and the risk gate refuses the order too", not v.allowed)
check("with its own code", v.code == "NO_STOP", v.code)
check("at the stop gate", v.gate == "stop", v.gate)

for name, kw, code in (
        ("a stop that is not a price", {"stop_price": None},
         "STOP_NOT_PRICED"),
        ("a stop sitting on the entry", {"stop_price": ENTRY},
         "STOP_AT_ENTRY"),
        ("a BUY stop ABOVE the entry", {"stop_price": ENTRY + 0.0025},
         "STOP_WRONG_SIDE"),
        ("no entry price to measure the stop against", {"entry_price": None},
         "NO_ENTRY_PRICE")):
    v = go(it=intent(**kw))
    check(f"{name} is refused", not v.allowed and v.code == code,
          f"{v.code} / {v.detail}")
v = go(it=intent(side="SELL", stop_price=STOP))
check("a SELL stop BELOW the entry is refused too",
      not v.allowed and v.code == "STOP_WRONG_SIDE", v.code)
check("while a SELL stop above it is fine",
      go(it=intent(side="SELL", stop_price=ENTRY + 0.0025)).allowed)


print("\n[3] the balance is read LIVE, at decision time, and never cached")
log = []
go(balance=reader(BALANCE, log))
check("the reader is called", len(log) == 1, str(len(log)))
log.clear()
go(balance=reader(BALANCE, log))
go(balance=reader(BALANCE, log))
check("twice, for two orders — nothing is memoised between calls",
      len(log) == 2, str(len(log)))

r = reader(BALANCE, log)
log.clear()
go(balance=r)
go(balance=r)
check("not even for the same reader object", len(log) == 2, str(len(log)))

check("there is no parameter that accepts a cached number",
      "balance" not in
      set(G.authorize.__code__.co_varnames[:G.authorize.__code__.co_argcount
                                           + G.authorize.__code__.co_kwonlyargcount]),
      "a plain `balance=` argument is how a stale figure gets in")

v = go(balance=reader(RuntimeError("cTrader timed out")))
check("a broker that will not answer refuses the order",
      not v.allowed and v.code == "BALANCE_UNAVAILABLE", v.code)
check("and the reason survives into the refusal",
      "cTrader timed out" in v.detail, v.detail)
for bad in (None, 0.0, -5.0, "10000"):
    v = go(balance=reader(bad))
    check(f"a balance of {bad!r} is not a balance",
          not v.allowed and v.code == "BALANCE_NOT_A_NUMBER", v.code)


print("\n[4] risk per trade, as a percentage of that live balance")
check("exactly 1.00% against a 1% rule passes", go().allowed)
# 40,400 units is 1.01% — a hundredth of a percent over, and still over.
v = go(it=intent(volume=40400.0))
check("1.01% against the same rule does not",
      not v.allowed and v.code == "RISK_OVER_RULE", f"{v.code} {v.detail}")
check("and the gate reports what it measured",
      v.facts.get("riskPercent") and v.facts["riskPercent"] > 1.0,
      str(v.facts.get("riskPercent")))

# The rule's own number is only half of it. §5: the legacy bot caps initial
# live risk at 1% whatever the account was configured with, and the platform
# needs the same idea — so a 3% rule is refused on live and allowed on demo.
three = doc(sizing={"riskPercent": 3.0})
big = intent(volume=UNITS * 3)
v = go(three, big, mode="live")
check("a 3% rule is refused on a LIVE account",
      not v.allowed and v.code == "RISK_OVER_PLATFORM_CAP",
      f"{v.code} {v.detail}")
check("and the cap that refused it is named",
      v.facts.get("riskCapPercent") == G.PLATFORM["maxRiskPercentLive"],
      str(v.facts.get("riskCapPercent")))
check("the same rule and order are allowed on DEMO",
      go(three, big, mode="demo").allowed,
      str(go(three, big, mode="demo").detail))
check("but a DEMO order over its own rule is still refused — the rule binds "
      "in both modes",
      not go(three, intent(volume=UNITS * 4), mode="demo").allowed)

v = go(it=intent(volume=None))
check("an order with no size has no measurable risk, so it is refused",
      not v.allowed and v.code == "RISK_UNSIZED", v.code)
# A fixed-volume rule states no percentage at all, so only the mode cap is
# left. On live that is 1%, and 40,000 units is exactly it.
fixed = doc(sizing={"mode": R.SIZING_FIXED, "riskPercent": None,
                    "fixedVolume": 0.4})
check("a fixed-volume rule is held to the platform cap", go(fixed).allowed)
check("...and refused above it", not go(fixed, intent(volume=40400.0)).allowed)


print("\n[5] maximum open positions")
d = doc(limits={"maxOpenPositions": 2})
check("one open position under a cap of two is fine",
      go(d, st=state(positions=[pos()])).allowed)
# The second position is a dollar LONG on purpose. Two dollar shorts plus a
# short-dollar order would also trip the correlated-exposure gate below, and
# then this check would pass whether the position cap worked or not.
v = go(d, st=state(positions=[pos(), pos(symbol="USD_CHF", side="BUY",
                                         entry=0.9000, stop=0.8950)]))
check("two is the cap, so the third order is refused",
      not v.allowed and v.code == "AT_POSITION_LIMIT", f"{v.code} {v.detail}")
check("and it says which gate", v.gate == "open_positions", v.gate)
v = go(doc(limits={"maxOpenPositions": None}))
check("a rule with no stated position cap is refused, not defaulted",
      not v.allowed and v.code == "MAX_POSITIONS_UNSTATED", v.code)


print("\n[6] maximum daily loss, which nothing enforced before this")
# These two sections move the BALANCE, which moves the risk percentage of a
# 40,000-unit order with it — and the risk gate runs first, so it would refuse
# before the daily-loss gate was ever reached. `tiny` is 4,000 units, $10 of
# risk, far inside every ceiling, so the only thing under test here is the
# limit this section is about.
tiny = intent(volume=4000.0)
# -$400 on a day that opened at $10,000 is -4.00%, which is the platform
# floor. "Reached" means stop: a limit that only bites once it is EXCEEDED
# lets the account through the number it promised to stop at.
v = go(it=tiny, balance=reader(9600.0), st=state(dailyRealisedPnl=-400.0))
check("a day exactly at the limit is halted",
      not v.allowed and v.code == "DAILY_LOSS_REACHED", f"{v.code} {v.detail}")
check("the day's opening balance is derived and reported",
      v.facts.get("dayStartBalance") == 10000.0,
      str(v.facts.get("dayStartBalance")))
check("a day just under it is not",
      go(it=tiny, balance=reader(9601.0),
         st=state(dailyRealisedPnl=-399.0)).allowed)
check("and a profitable day certainly is not",
      go(it=tiny, balance=reader(10400.0),
         st=state(dailyRealisedPnl=400.0)).allowed)
# A rule may ask for a tighter limit than the platform's. It may not ask for a
# looser one — the floor is not the client's to raise.
tight = doc(limits={"maxDailyLossPercent": 1.0})
check("a tighter limit on the rule is honoured",
      not go(tight, tiny, balance=reader(9900.0),
             st=state(dailyRealisedPnl=-100.0)).allowed)
loose = doc(limits={"maxDailyLossPercent": 90.0})
check("a looser one cannot raise the platform floor",
      not go(loose, tiny, balance=reader(9600.0),
             st=state(dailyRealisedPnl=-400.0)).allowed)


print("\n[7] maximum drawdown from peak — likewise unenforced before this")
v = go(it=tiny, balance=reader(7500.0), st=state(peakBalance=10000.0))
check("-25% from peak is the floor, and it halts",
      not v.allowed and v.code == "DRAWDOWN_REACHED", f"{v.code} {v.detail}")
check("-24% does not",
      go(it=tiny, balance=reader(7600.0),
         st=state(peakBalance=10000.0)).allowed)
check("a balance above the recorded peak is not a drawdown",
      go(it=tiny, balance=reader(12000.0),
         st=state(peakBalance=10000.0)).allowed)
check("and the gate does not move the peak it is checking",
      go(it=tiny, balance=reader(12000.0),
         st=state(peakBalance=10000.0)).facts.get("peakBalance") == 10000.0)


print("\n[8] maximum daily trades — counted on OPEN, not on close")
d = doc(limits={"maxDailyTrades": 4})
check("three opened under a cap of four is fine",
      go(d, st=state(dailyTradesOpened=3)).allowed)
v = go(d, st=state(dailyTradesOpened=4))
check("the fifth is refused — four means four",
      not v.allowed and v.code == "DAILY_TRADES_REACHED",
      f"{v.code} {v.detail}")
check("and a count already past the cap stays refused",
      not go(d, st=state(dailyTradesOpened=5)).allowed)
# This is the `5/4` the specification names. The legacy counter increments in
# `strategies.record_trade`, which runs when a trade CLOSES, so four open
# positions counted as zero and the loop opened a fifth. The fact this gate
# reads is `dailyTradesOpened`, and nothing else will do.
check("the fact is the number OPENED today",
      "dailyTradesOpened" in G.REQUIRED_FACTS["daily_trades"],
      str(G.REQUIRED_FACTS["daily_trades"]))
check("a cap left empty is no cap, as the rule form promises",
      go(doc(limits={"maxDailyTrades": None}),
         st=state(dailyTradesOpened=99)).allowed)


print("\n[9] exposure per instrument, and correlated exposure")
# Per instrument, measured in money at risk rather than notional: 40,000 units
# of EUR_USD is $44,000 notional and $100 of risk, and a client who writes
# "max exposure 2%" against a 10,000 account means the second number.
#
# `maxOpenPositions` is lifted out of the way in this section. It defaults to
# 1 in `ruledoc.blank()` and runs BEFORE these two gates, so leaving it would
# mean every check below refusing for the wrong reason.
d = doc(limits={"maxExposurePercent": 2.0, "maxOpenPositions": 9})
same = pos(symbol="EUR_USD", side="BUY", units=UNITS, entry=ENTRY, stop=STOP)
check("one $100 position plus a $100 order is 2% — exactly the cap",
      go(d, st=state(positions=[same])).allowed)
v = go(d, st=state(positions=[same, same]))
check("a third is over it and refused",
      not v.allowed and v.code == "INSTRUMENT_EXPOSURE_EXCEEDED",
      f"{v.code} {v.detail}")
# Two USD_JPY longs rather than two GBP_USD longs: a different instrument is
# what this check is about, and GBP_USD longs are short dollars like the
# EUR_USD order, so they would have been refused one gate later for being the
# same bet — a pass for the wrong reason is as useless as a fail.
other = pos(symbol="USD_JPY", side="BUY", units=10000.0, entry=150.0,
            stop=149.0)
check("exposure on a DIFFERENT instrument does not count",
      go(d, st=state(positions=[other, other])).allowed,
      str(go(d, st=state(positions=[other, other])).as_dict())[:160])
v = go(d, st=state(positions=[{"symbol": "EUR_USD", "side": "BUY",
                               "units": UNITS, "entryPrice": ENTRY,
                               "stopLoss": None}]))
check("a position with no stop has unmeasurable exposure, so the gate "
      "refuses rather than counting it as zero",
      not v.allowed and v.code == "EXPOSURE_UNKNOWN", f"{v.code} {v.detail}")

# Correlated: BUY EUR_USD and BUY GBP_USD are both short USD. The default cap
# is the legacy loop's own — two positions on one dollar side.
check("the platform cap is the legacy loop's number",
      G.PLATFORM["maxSameUsdSide"] == 2, str(G.PLATFORM["maxSameUsdSide"]))
shorts = [pos(symbol="GBP_USD", side="BUY"),
          pos(symbol="AUD_USD", side="BUY", entry=0.6500, stop=0.6450)]
check("the model is the dollar leg, shared with the legacy guard",
      forex.usd_exposure("EUR_USD", "BUY") ==
      forex.usd_exposure("GBP_USD", "BUY") == -1)
room = doc(limits={"maxOpenPositions": 9})
v = go(room, st=state(positions=shorts))
check("a third short-dollar order is refused",
      not v.allowed and v.code == "CORRELATED_EXPOSURE", f"{v.code} {v.detail}")
check("two is not", go(room, st=state(positions=shorts[:1])).allowed)
check("the other dollar side is a different bet and does not count",
      go(room, st=state(positions=[pos(symbol="USD_JPY", side="BUY",
                                       entry=150.0, stop=151.0),
                                   pos(symbol="USD_CHF", side="BUY",
                                       entry=0.9, stop=0.91)])).allowed)
check("and a rule may tighten it",
      not go(doc(limits={"maxSameUsdSide": 1, "maxOpenPositions": 9}),
             st=state(positions=shorts[:1])).allowed)


print("\n[10] spread and slippage ceilings")
d = doc(limits={"maxSpreadPips": 1.5})
check("a spread at the ceiling is allowed — the rule blocks a WIDER one",
      go(d, st=state(spreadPips=1.5)).allowed)
v = go(d, st=state(spreadPips=1.6))
check("wider is refused", not v.allowed and v.code == "SPREAD_TOO_WIDE",
      f"{v.code} {v.detail}")
check("no stated ceiling is no ceiling",
      go(doc(limits={"maxSpreadPips": None}), st=state(spreadPips=99.0)).allowed)

s = doc(order={"maxSlippagePoints": 2.0})
check("slippage at the ceiling passes", go(s, st=state(slippagePoints=2.0)).allowed)
v = go(s, st=state(slippagePoints=2.1))
check("over it is refused", not v.allowed and v.code == "SLIPPAGE_OVER_CEILING",
      f"{v.code} {v.detail}")


print("\n[11] an order type the connector can actually honour")
for bad in ("LIMIT", "STOP"):
    v = go(doc(order={"type": bad}))
    check(f"a {bad} rule is refused",
          not v.allowed and v.code == "ORDER_TYPE_UNSUPPORTED",
          f"{v.code} {v.detail}")
    check(f"...and the {bad} is named, so the client can fix the rule",
          bad in v.detail, v.detail)
v = go(doc(order={"type": None}))
check("a rule that does not say is refused, not assumed to mean MARKET",
      not v.allowed and v.code == "ORDER_TYPE_UNSTATED", v.code)
check("MARKET is the one that passes", go(doc(order={"type": "MARKET"})).allowed)
check("every type ruledoc accepts is either supported or refused here",
      set(R.ORDER_TYPES) >= set(G.SUPPORTED_ORDER_TYPES),
      f"{R.ORDER_TYPES} vs {sorted(G.SUPPORTED_ORDER_TYPES)}")

# The duplicated constant. `bridge` is imported by nothing in production and
# this module must not be the one that changes that, so the value is copied
# and the copy is checked against the original's SOURCE instead.
BRIDGE = os.path.join(ROOT, "apex", "platform", "bridge.py")
_tree = ast.parse(open(BRIDGE, encoding="utf-8").read())
_found = None
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SUPPORTED_ORDER_TYPES"
            for t in _n.targets):
        _found = {c.value for c in ast.walk(_n.value)
                  if isinstance(c, ast.Constant) and isinstance(c.value, str)}
check("bridge still declares SUPPORTED_ORDER_TYPES", _found is not None)
check("and the duplicate here agrees with it, character for character",
      _found == set(G.SUPPORTED_ORDER_TYPES),
      f"bridge={sorted(_found or [])} risk_gates={sorted(G.SUPPORTED_ORDER_TYPES)}")


print("\n[12] every gate fails CLOSED when its fact cannot be read")
# The whole of §5 rests on this. Each gate is asked its question with the one
# fact it needs removed, and must refuse. A gate missing from this loop is a
# gate nobody proved fails closed, so the loop is driven by the module's own
# declaration of what each gate needs.
_facts = state()
for gate, needs in G.REQUIRED_FACTS.items():
    for fact in needs:
        st = {k: v for k, v in _facts.items() if k != fact}
        v = go(doc(limits={"maxOpenPositions": 1, "maxDailyTrades": 4,
                           "maxExposurePercent": 50.0, "maxSpreadPips": 5.0},
                   order={"type": "MARKET", "maxSlippagePoints": 5.0}), st=st)
        check(f"{gate} refuses without {fact}", not v.allowed,
              f"it allowed the order with {fact} missing")
        check(f"...and the refusal names a gate and a code",
              bool(v.gate) and bool(v.code), str(v.as_dict())[:140])
check("no facts at all refuses", not go(st={}).allowed)
check("and `state=None` is not a pass either",
      not G.authorize(doc(), intent(), mode="live",
                      balance_reader=reader(), state=None).allowed)


print("\n[13] a gate that crashes refuses, with a code of its own")


class Exploding(dict):
    def get(self, *a, **kw):
        raise ZeroDivisionError("boom")


v = go(st=state(positions=[Exploding()]))
check("an unreadable position does not become an authorised order",
      not v.allowed, v.code)
check("the code says a check failed rather than naming a limit",
      v.code.endswith("_CHECK_FAILED"), v.code)
check("every gate has its own crash code",
      len(set(G.CHECK_FAILED.values())) == len(G.GATES),
      str(G.CHECK_FAILED))
check("and each one names its gate",
      all(g.upper() in c for g, c in G.CHECK_FAILED.items()),
      str(G.CHECK_FAILED))


print("\n[14] the inputs themselves are a gate")
for kw, code in ((dict(mode="paper"), "MODE_NOT_STATED"),
                 (dict(mode=None), "MODE_NOT_STATED")):
    v = go(**kw)
    check(f"mode {kw['mode']!r} is refused — an order's environment is never "
          f"assumed", not v.allowed and v.code == code, v.code)
v = G.authorize(doc(), intent(), mode="live", balance_reader=BALANCE,
                state=state())
check("a number where the balance reader belongs is refused",
      not v.allowed and v.code == "BALANCE_NOT_CALLABLE", v.code)
v = go(it=intent(side="HOLD"))
check("a side that is not BUY or SELL is refused",
      not v.allowed and v.code == "SIDE_NOT_TRADEABLE", v.code)
v = go(it=intent(symbol=""))
check("and so is an order with no instrument",
      not v.allowed and v.code == "NO_SYMBOL", v.code)
v = go(rule="not a document")
check("a rule document that is not a document is refused",
      not v.allowed and v.code == "NO_RULE", v.code)


print("\n[15] a refusal is readable, and the order of the gates is kept")
v = go(doc(order={"type": "LIMIT"}))
first = v.checks[0]["gate"]
check("the cheapest configuration check runs before anything reads a broker",
      [c["gate"] for c in v.checks].index("order_type")
      < [c["gate"] for c in v.checks].index("balance"),
      str([c["gate"] for c in v.checks]))
check("gates after the refusal are reported as skipped, not as passed",
      all(c["state"] == G.SKIPPED
          for c in v.checks[[c["gate"] for c in v.checks].index("order_type") + 1:]),
      str(v.checks))
check("the refusing gate is marked refused",
      next(c for c in v.checks if c["gate"] == "order_type")["state"]
      == G.REFUSED)
check("a limit the rule did not set is WAIVED, not silently passed",
      next(c for c in go(doc(limits={"maxSpreadPips": None})).checks
           if c["gate"] == "spread")["state"] == G.WAIVED)
check("every code this module can answer with is unique",
      len(G.CODES) == len(set(G.CODES)), str(G.CODES))
check("and every code the gates actually raised is declared",
      v.code in G.CODES, v.code)


print("\n[16] this module cannot reach the execution boundary")
SRC = open(os.path.join(ROOT, "apex", "platform", "risk_gates.py"),
           encoding="utf-8").read()
_imports = set()
for _n in ast.walk(ast.parse(SRC)):
    if isinstance(_n, ast.ImportFrom):
        _imports.add(_n.module or "")
        if (_n.module or "") == "apex.platform":
            _imports.update(f"apex.platform.{a.name}" for a in _n.names)
    elif isinstance(_n, ast.Import):
        _imports.update(a.name for a in _n.names)
for forbidden in ("apex.platform.bridge", "apex.platform.execution"):
    check(f"it does not import {forbidden}", forbidden not in _imports,
          str(sorted(_imports)))
# And nothing in the executable body names either one, so a deferred import
# inside a function cannot put the dependency back. Comments and docstrings
# are stripped first — the same trick `tests/test_no_remote_execution.py`
# uses, and for the same reason: scanning raw text finds the words in the
# prose that EXPLAINS the absence, which is how a check like this quietly
# starts passing on its own commentary.
_code = re.sub(r"#.*$", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', '""', SRC),
               flags=re.M)
for forbidden in ("bridge", "execution"):
    check(f"and no deferred import of `{forbidden}` either",
          forbidden not in _code, forbidden)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
