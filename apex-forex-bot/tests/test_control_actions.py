"""Typing of remotely-set settings (apex/control_actions.coerce_setting).

The MCP control plane carries every value as a string, while the trading loop
reads settings with bool() and list() and never re-parses them. That mismatch
silently ignored every remote attempt to switch a boolean OFF — bool("false")
is True — and would have shredded a remotely-set watchlist into single
characters. These tests pin the coercion against how user_loop actually reads
each key.

Run: python tests/test_control_actions.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex.control_actions import (  # noqa: E402
    coerce_setting, _SETTABLE, _BOOL_KEYS, _LIST_KEYS, _INT_KEYS, _FLOAT_KEYS)


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0

print("\n🧪 CONTROL-PLANE SETTING COERCION\n")

print("1. Booleans survive a string transport")
for key in sorted(_BOOL_KEYS):
    off = coerce_setting(key, "false")
    on = coerce_setting(key, "true")
    check(f"{key}: 'false' → False, 'true' → True",
          off is False and on is True, (off, on))

print("\n2. Every falsey spelling an operator might type")
for raw in ("false", "False", "FALSE", " false ", "0", "no", "off", "none",
            "null", ""):
    check(f"{raw!r} → False", coerce_setting("trailing", raw) is False,
          coerce_setting("trailing", raw))
for raw in ("true", "True", "1", "yes", "on"):
    check(f"{raw!r} → True", coerce_setting("trailing", raw) is True,
          coerce_setting("trailing", raw))
check("real booleans pass through", coerce_setting("htf", False) is False)

print("\n3. The bug this fixes, stated directly")
# bool("false") is True — the loop reads htf as bool(user.get("htf", True)),
# so before this a remote "htf=false" left the filter ON.
check("bool('false') really is True (why the raw value was unusable)",
      bool("false") is True)
check("coerced value is safe for the loop's bool() read",
      bool(coerce_setting("htf", "false")) is False)

print("\n4. Lists are not shredded into characters")
check("single symbol → one-element list",
      coerce_setting("watchlist", "EURUSD") == ["EURUSD"],
      coerce_setting("watchlist", "EURUSD"))
check("list('EURUSD') would have given 6 letters — not any more",
      len(coerce_setting("watchlist", "EURUSD")) == 1)
check("comma separated", coerce_setting("watchlist", "EURUSD,GBPUSD") ==
      ["EURUSD", "GBPUSD"], coerce_setting("watchlist", "EURUSD,GBPUSD"))
check("spaces tolerated", coerce_setting("watchlist", " EURUSD , GBPUSD ") ==
      ["EURUSD", "GBPUSD"])
check("semicolons tolerated", coerce_setting("autopilot_universe",
      "EURUSD;GBPUSD") == ["EURUSD", "GBPUSD"])
check("JSON array", coerce_setting("watchlist", '["EURUSD","GBPUSD"]') ==
      ["EURUSD", "GBPUSD"], coerce_setting("watchlist", '["EURUSD","GBPUSD"]'))
check("real list passes through",
      coerce_setting("session_filter", ["London"]) == ["London"])
check("empty string → empty list, not ['']",
      coerce_setting("session_filter", "") == [])

print("\n5. Numbers are typed, not left as text")
check("risk '0.35' → 0.35 float", coerce_setting("risk", "0.35") == 0.35
      and isinstance(coerce_setting("risk", "0.35"), float))
check("min_confidence '60' → 60 int", coerce_setting("min_confidence", "60") == 60
      and isinstance(coerce_setting("min_confidence", "60"), int))
check("maxpos '3.0' → 3 int", coerce_setting("maxpos", "3.0") == 3)
check("max_dd_pct '20' → 20.0 float",
      isinstance(coerce_setting("max_dd_pct", "20"), float))

print("\n6. Strings and unknown keys are left alone")
check("strategy untouched", coerce_setting("strategy", "mean_reversion") ==
      "mean_reversion")
check("symbol untouched", coerce_setting("symbol", "EUR_USD") == "EUR_USD")
check("unknown key passes through", coerce_setting("not_a_key", "x") == "x")

print("\n7. Every settable key has a decided type")
typed = _BOOL_KEYS | _LIST_KEYS | _INT_KEYS | _FLOAT_KEYS
strings = {"strategy", "symbol", "timeframe", "exit_mode", "style", "confirm"}
unclassified = _SETTABLE - typed - strings
check("no settable key is silently untyped", not unclassified,
      sorted(unclassified))
check("no key claims two types",
      len(typed) == len(_BOOL_KEYS) + len(_LIST_KEYS) + len(_INT_KEYS)
      + len(_FLOAT_KEYS))

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — remote settings are typed correctly.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
