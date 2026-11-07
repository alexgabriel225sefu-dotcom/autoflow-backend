"""Trades are not independent, and every path has to know it.

The position cap and the correlation guard were real, correct, and reachable
from exactly one place: the autonomous loop. An autonomous entry was checked
against exposure; a manual /buy from Telegram was not. §14 requires manual,
assisted, automatic and AI-proposed to route through the same risk engine, so
the logic moved to apex/portfolio.py and gates.authorize_order calls it.

The property that matters most is the ordering. A portfolio denial must not
burn an idempotency claim, and it must not outrank a halted account — "trading
is paused" is more useful to a client than "you already hold two dollar shorts".

§31's example is the point of the correlation check:

    EURUSD long + GBPUSD long + EURGBP short

is not three risks. Two of those are the same bet on the dollar.

Run: python tests/test_portfolio_gate.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex import portfolio  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


GATES = open(os.path.join(ROOT, "apex", "gates.py"), encoding="utf-8").read()
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

TWO_SHORT_USD = portfolio.state({
    "maxpos": 5,
    "positions": [{"symbol": "EURUSD", "side": "BUY"},     # short USD
                  {"symbol": "GBPUSD", "side": "BUY"}]})   # short USD

print("\n1. Exposure is read, never recomputed")
check("it comes from the dash's own positions list",
      TWO_SHORT_USD["openCount"] == 2
      and TWO_SHORT_USD["symbols"] == ["EURUSD", "GBPUSD"])
check("both are counted as the same dollar bet",
      TWO_SHORT_USD["usdShort"] == 2 and TWO_SHORT_USD["usdLong"] == 0)
_pf_src = open(os.path.join(ROOT, "apex", "portfolio.py"), encoding="utf-8").read()
check("the module makes no broker call",
      not any(x in _pf_src for x in ("get_all_positions", "_make_broker",
                                     "get_balance", "get_candles")),
      "a risk check must not depend on a network round trip")

print("\n2. Margin is reported unknown, not reconstructed")
check("marginKnown is False", TWO_SHORT_USD["marginKnown"] is False)
check("...and no number is offered", TWO_SHORT_USD["marginHeadroom"] is None,
      "ProtoOATrader carries balance and leverage, not free margin")
check("the summary says so",
      "not reported by the broker" in portfolio.summary(TWO_SHORT_USD))

print("\n3. Correlated exposure is refused, opposite exposure is not")
ok, code, why = portfolio.check("AUDUSD", "BUY", TWO_SHORT_USD,
                                limits={"max_positions": 5})
check("a third short-USD position is refused",
      not ok and code == portfolio.CORRELATED_EXPOSURE, f"{code} {why}")
ok, _, _ = portfolio.check("USDJPY", "BUY", TWO_SHORT_USD,
                           limits={"max_positions": 5})
check("a long-USD position is allowed", ok)
_gold = portfolio.state({"maxpos": 5, "positions": [
    {"symbol": "XAUUSD", "side": "BUY"}, {"symbol": "XAGUSD", "side": "BUY"}]})
ok, _, _ = portfolio.check("EURUSD", "BUY", _gold, limits={"max_positions": 5})
check("metals do not consume the dollar budget", ok,
      "they have no USD leg to stack")

print("\n4. The cheapest and most decisive checks come first")
ok, code, _ = portfolio.check("EUR_USD", "SELL", TWO_SHORT_USD,
                              limits={"max_positions": 5})
check("an instrument already held is refused before anything else",
      not ok and code == portfolio.SYMBOL_ALREADY_OPEN, code)
ok, code, why = portfolio.check("USDJPY", "BUY", TWO_SHORT_USD,
                                limits={"max_positions": 2})
check("the position cap is enforced",
      not ok and code == portfolio.AT_POSITION_LIMIT, f"{code} {why}")
ok, code, _ = portfolio.check("USDJPY", "BUY", TWO_SHORT_USD,
                              limits={"max_positions": 2,
                                      "max_data_age_s": 30}, data_age_s=120)
check("stale data outranks every other check",
      not ok and code == portfolio.MARKET_DATA_STALE, code,)
ok, _, _ = portfolio.check("USDJPY", "BUY", TWO_SHORT_USD,
                           limits={"max_positions": 5}, data_age_s=99999)
check("...but only when the operator configured a limit", ok,
      "no max_data_age_s means the check is off, not that everything is stale")

print("\n5. The risk engine calls it, in the right place")
check("gates imports portfolio", "from apex import account_mode, portfolio" in GATES)
check("...and calls the check", "portfolio.check(symbol, side" in GATES)
_p = GATES.index("portfolio.check(symbol, side")
check("the portfolio check runs AFTER the risk-guard check",
      GATES.index('guard.get("halted")') < _p,
      "a halted account is the more useful thing to tell a client")
check("...and BEFORE the idempotency claim",
      _p < GATES.index("ledger.claim("),
      "a denial must not burn a claim")
check("a failure in the check denies rather than allows",
      "PORTFOLIO_CHECK_FAILED" in GATES,
      "this is a risk gate; it fails closed like every other branch")

print("\n6. The loop no longer carries its own copy")
check("the inline correlation arithmetic is gone",
      "same_dir >= 2" not in LOOP,
      "one implementation, called from both places")
check("the loop calls the shared check", "_pf.check(" in LOOP)
check("...and still records the decline for the 'why not' screen",
      "_pf.deny_text(_pcode)" in LOOP,
      "gates is the authority; the loop's job here is the explanation")
check("an already-open instrument is not announced every tick",
      "_pcode != _pf.SYMBOL_ALREADY_OPEN" in LOOP,
      "that is an ordinary state, not a refusal worth reporting repeatedly")

print("\n7. The default is a move, not a policy change")
check("the same USD-side cap the loop used",
      portfolio.DEFAULT_MAX_SAME_USD_SIDE == 2,
      "the loop refused when same_dir >= 2")
_tree = ast.parse(_pf_src)
_nums = {n.value for n in ast.walk(_tree)
         if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
         and n.value not in (0, 1)}
check(f"no other magic financial constant ({sorted(_nums)})",
      _nums <= {2, 10},
      "limits arrive through `limits`, per §71")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL PORTFOLIO-GATE CHECKS PASSED - every path sees the same exposure.")
