"""The rule layer reads a saved rule's own stop and risk.

On a real account `POST rule-layer` answered 400 UNREADABLE_INPUT for every
rule: it looked for `limits.stopPips` and `limits.riskFraction`, and a rule
keeps those under `stopLoss` and `sizing`.

Run: python3 tests/test_rule_layer_inputs.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apex.platform import rule_layer as R                      # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


# The shape the store returned for the rule that failed.
RULE = {
    "symbols": ["XAUUSD"],
    "sizing": {"mode": "risk_percent", "riskPercent": 5.0, "fixedVolume": None},
    "stopLoss": {"mode": "pips", "pips": 20.0, "atrMultiple": None},
    "limits": {"maxOpenPositions": 1, "maxDailyLossPercent": 2.0},
}

print("\n[1] a real rule's stop and risk are read")
stop, risk, missing = R.inputs_from_rule(RULE, {"price": 3943.97})
check("stop in pips", stop == 20.0, str(stop))
check("risk percent becomes a fraction", abs(risk - 0.05) < 1e-12, str(risk))
check("nothing missing", missing == [], str(missing))

print("\n[2] a value in the request wins")
stop, risk, missing = R.inputs_from_rule(RULE, {"stopPips": 35, "riskFraction": 0.01})
check("request stop", stop == 35.0)
check("request risk", risk == 0.01)

print("\n[3] nothing is guessed")
atr = dict(RULE, stopLoss={"mode": "atr", "pips": None, "atrMultiple": 2.0})
stop, risk, missing = R.inputs_from_rule(atr, {})
check("an ATR stop has no pips", stop is None and missing == ["a fixed stop distance in pips"], str(missing))
fixed = dict(RULE, sizing={"mode": "fixed_volume", "riskPercent": None, "fixedVolume": 0.1})
stop, risk, missing = R.inputs_from_rule(fixed, {})
check("a fixed volume has no percentage", risk is None and missing == ["a risk percentage per trade"], str(missing))
stale = dict(RULE, stopLoss={"mode": "atr", "pips": 20.0, "atrMultiple": 2.0})
check("pips left over under another mode are not used", R.inputs_from_rule(stale, {})[0] is None)
check("zero is not a stop", R.inputs_from_rule(dict(RULE, stopLoss={"mode": "pips", "pips": 0}), {})[0] is None)
stop, risk, missing = R.inputs_from_rule(None, None)
check("no rule names both", len(missing) == 2, str(missing))
check("a malformed rule does not raise", R.inputs_from_rule({"sizing": "x", "stopLoss": 3, "limits": []}, [])[2] != [])

print("\n[4] the values feed the calculation")
stop, risk, _ = R.inputs_from_rule(RULE, {})
out = R.risk_units(balance=4462.84, risk_fraction=risk, stop_pips=stop,
                   symbol="XAUUSD", price=3943.97, leverage=30)
check("a result comes back", isinstance(out, dict) and bool(out), str(out)[:200])

if _fails:
    print(f"\n{len(_fails)} FAILED:")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("\nall rule layer input checks passed")
