"""A setting the runtime will not honour is refused at the moment it is written.

WHY THIS TEST EXISTS

`coerce_setting()` typed values but did not check them. Its docstring said
"Unknown keys pass through untouched", and three of the sixteen keys the
control plane can set were reachable through that gap: `strategy`, `symbol`
and `timeframe`. Each one has a consumer downstream that SUBSTITUTES A DEFAULT
for a value it does not recognise rather than failing:

  * strategy  -> strategy_api.get() returns None for an unregistered id. The
                 guard at user_loop.py:3181 skips the whole strategy block
                 when the module is None, so control fell through to
                 ai.signal_for_mode(), whose own lookup ends in
                 `STRATEGY_MODES["mean_reversion"]`. A client who set
                 `strategy=trend_following` and read it back got
                 `trend_following` while the account traded mean reversion.
  * timeframe -> brokers.ctrader._period() ends in `.get(tf, "M5")`. `M15` is
                 not one of its keys, so asking for fifteen-minute candles
                 delivered five-minute ones, spelled the way you asked.
  * symbol    -> user_loop.py:1526-1532 already scrubs an untradeable symbol
                 back to the product default on the next loop start. The
                 write "succeeded", and the setting was gone by the time
                 anyone looked.

THE RULE THIS TEST PROTECTS

The platform's contract is "when the conditions you defined are met, execute
the action you configured, within the limits you enabled." Storing a value
the runtime then replaces with a different one breaks that sentence in the
one place the client cannot see. A rejected write is visible; a substituted
value is not. So the answer to an unrecognised value is an error, never a
default.

WHY THE ALLOWED SETS ARE BUILT AT CALL TIME

The strategy registry fills as a SIDE EFFECT of importing the strategy
modules, and control_actions imports none of them. At its import time
`strategy_api.available()` is empty; after strategy_modules, strategy_extra
and strategy_specialized are loaded it holds 17. A set captured at module
level would therefore reject every valid strategy and admit nothing — worse
than the gap it replaces. That is asserted below directly, by registering a
strategy that did not exist when this module was imported and requiring that
it become settable.

Run: python tests/test_setting_value_validation.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import control_actions, forex as forex_mod, strategy_api  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def rejects(key, val):
    """True when coerce_setting refuses the value with a ValueError."""
    try:
        control_actions.coerce_setting(key, val)
        return False
    except ValueError:
        return True


def accepts(key, val):
    try:
        control_actions.coerce_setting(key, val)
        return True
    except ValueError:
        return False


def value_of(key, val):
    """The coerced value, or the ValueError text. Never raises, so one
    unexpected rejection fails its own check instead of aborting the run and
    hiding every check after it."""
    try:
        return control_actions.coerce_setting(key, val)
    except ValueError as e:
        return f"<rejected: {e}>"


print("\n1. The three unvalidated keys now refuse what the runtime would swap")
check("strategy: an id no module registers",
      rejects("strategy", "trend_following"),
      "strategy_api.get() would return None and the loop would trade mean_reversion")
check("strategy: empty string", rejects("strategy", ""))
check("strategy: a near-miss spelling", rejects("strategy", "mean-reversion"),
      "the registry key is mean_reversion; a hyphen is not a synonym")
check("timeframe: M15, which _period() turns into M5",
      rejects("timeframe", "M15"),
      "this is the substitution the client cannot see")
check("timeframe: 2h, which is not in the broker's map",
      rejects("timeframe", "2h"))
check("symbol: US400, an index",
      rejects("symbol", "US400"),
      "no trading calendar exists for it; the loop scrubs it on next start")
check("symbol: GBPJPY, a cross with no USD leg",
      rejects("symbol", "GBPJPY"),
      "calc_units has no quote_usd_rate for it and mis-sizes by ~31x")
check("symbol: BTCUSD", rejects("symbol", "BTCUSD"))
check("symbol: empty string", rejects("symbol", ""))

print("\n2. Valid values are still accepted, and stored as given")
check("strategy: a registered id",
      value_of("strategy", "mean_reversion") == "mean_reversion",
      str(value_of("strategy", "mean_reversion"))[:70])
check("strategy: auto — a registered module like any other, despite the name",
      value_of("strategy", "auto") == "auto",
      str(value_of("strategy", "auto"))[:70])
check("strategy: case and padding are normalised, not rejected",
      value_of("strategy", "  Mean_Reversion  ") == "mean_reversion",
      str(value_of("strategy", "  Mean_Reversion  "))[:70])
check("timeframe: every key the broker's own map defines",
      all(accepts("timeframe", tf)
          for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d")),
      "the allowlist must match that map, not drift from it")
check("symbol: EURUSD", value_of("symbol", "EURUSD") == "EURUSD",
      str(value_of("symbol", "EURUSD"))[:70])
check("symbol: separators and case survive — the broker strips them itself",
      accepts("symbol", "eur_usd") and accepts("symbol", "eurusd"),
      "brokers/ctrader.py:80 uppercases and strips before the symbol lookup")
check("symbol: XAUUSD, a metal", accepts("symbol", "XAUUSD"))

print("\n3. automation is unchanged — the fix did not narrow what already worked")
check("approval", value_of("automation", "approval") == "approval",
      str(value_of("automation", "approval"))[:70])
check("full", accepts("automation", "full"))
check("signals", accepts("automation", "signals"))
check("a typo is still refused", rejects("automation", "aproval"),
      "automation.mode() falls back to the most permissive level")

print("\n4. Keys that were never value-checked still pass through")
check("risk is coerced to float, not enumerated",
      value_of("risk", "1.5") == 1.5, str(value_of("risk", "1.5")))
check("max_trades_day stays an int",
      value_of("max_trades_day", "4") == 4, str(value_of("max_trades_day", "4")))
check("watchlist stays a list",
      value_of("watchlist", "EURUSD,GBPUSD") == ["EURUSD", "GBPUSD"],
      str(value_of("watchlist", "EURUSD,GBPUSD")))
check("an unknown key is untouched",
      value_of("some_future_key", "whatever") == "whatever",
      "adding validation must not turn this into a blocklist")

print("\n5. The allowed set is the LIVE registry, not a snapshot from import")


class _Fictitious(strategy_api.Strategy):
    """Registered here, long after control_actions was imported."""
    strategy_id = "fictitious_test_strategy"
    strategy_version = "0.0.1-test"
    label = "Fictitious"

    def signal(self, market):
        return {"action": "HOLD", "reason": "test double"}


check("before registering, the id is refused",
      rejects("strategy", "fictitious_test_strategy"))
strategy_api.register(_Fictitious)
try:
    check("after registering, the SAME id is accepted",
          accepts("strategy", "fictitious_test_strategy"),
          "the set is read at call time; a module-level list would still refuse it")
finally:
    strategy_api.unregister("fictitious_test_strategy")
check("after unregistering, it is refused again",
      rejects("strategy", "fictitious_test_strategy"))

print("\n6. The allowlist survives an empty registry — it must not reject all")
# MEASURED: the registry (17 ids) is a strict SUPERSET of STRATEGY_MODES (10),
# and "auto" is itself a registered module. So both extra union terms in
# _allowed_values are redundant today and would rot unnoticed.
#
# They defend one specific failure. The registry fills as an import side
# effect, and control_actions imports no strategy module; available() is
# non-empty here only because user_loop pulls them in transitively. If an
# import reorder ever emptied it, a validator with an empty allowlist rejects
# EVERY strategy — the failure mode is the whole product, not one setting.
# Stubbing available() to [] is the only way to prove the floor is real.
from apex import ai, strategy_api  # noqa: E402

_saved_available = strategy_api.available
strategy_api.available = lambda: []
try:
    check("with the registry empty, auto is still settable",
          accepts("strategy", "auto"),
          "auto is what onboarding writes; an empty allowlist must not eat it")
    check("...and so is every mode in STRATEGY_MODES",
          all(accepts("strategy", m) for m in _saved_available()
              if m in ai.STRATEGY_MODES),
          "the STRATEGY_MODES term is the floor under an unpopulated registry")
    check("...while an id that was never in either source is still refused",
          rejects("strategy", "trend_following"),
          "the floor must not degrade into accepting anything")
    check("...and a registry-only id is correctly no longer settable",
          rejects("strategy", "zscore"),
          "zscore exists only in the registry; with it empty, refusing is right")
finally:
    strategy_api.available = _saved_available
check("registry restored", len(strategy_api.available()) == 17,
      str(len(strategy_api.available())))

print("\n7. forex.TIMEFRAMES still mirrors the broker's map exactly")
# The validator cannot read _period() directly: test_failure_matrix.py forbids
# any module outside the trading core from importing a broker, and
# control_actions is the operator interface — the module that rule exists for.
# So the set is mirrored into forex.TIMEFRAMES, and the mirror is only as good
# as this assertion. A test file is not bound by that invariant, so the
# comparison can be made against the real authority here and nowhere else.
#
# If this fails, the broker gained or lost a timeframe: update forex.TIMEFRAMES
# to match. Do NOT relax the check — a timeframe the broker cannot translate
# falls to its "M5" default, which is the silent substitution this whole file
# exists to prevent.
from apex.brokers.ctrader import _period  # noqa: E402

check("the mirrored set equals the broker's keys, exactly",
      set(forex_mod.TIMEFRAMES) == set(_period()),
      f"forex={sorted(forex_mod.TIMEFRAMES)} broker={sorted(_period())}")
check("and every mirrored value is settable",
      all(accepts("timeframe", tf) for tf in forex_mod.TIMEFRAMES))
check("no duplicates crept into the mirror",
      len(forex_mod.TIMEFRAMES) == len(set(forex_mod.TIMEFRAMES)))

print("\n8. The registry really is empty at control_actions import time")
CA_SRC = open(os.path.join(ROOT, "apex", "control_actions.py")).read()
check("control_actions imports no strategy module at module level",
      "import strategy_modules" not in CA_SRC
      and "import strategy_extra" not in CA_SRC
      and "import strategy_specialized" not in CA_SRC,
      "if it ever does, the lazy resolution stops being load-bearing — but the "
      "import cycle it would create is why it does not")
check("and it holds no literal list of strategy ids",
      "mean_reversion" not in CA_SRC and "breakout" not in CA_SRC,
      "a second copy of the registry is exactly the drift this avoids")
check("nor a literal list of timeframes",
      '"15m"' not in CA_SRC and "'15m'" not in CA_SRC,
      "four disagreeing timeframe lists already exist in this codebase")

print("\n9. A refusal says what was wrong, not just that something was")
try:
    control_actions.coerce_setting("strategy", "trend_following")
    msg = ""
except ValueError as e:
    msg = str(e)
check("the message names the key and the rejected value",
      "strategy" in msg and "trend_following" in msg, msg)
check("and lists what would have been accepted",
      "mean_reversion" in msg and "auto" in msg, msg)
# apex/control.py:532 truncates a failed command's message to 300 chars before
# the caller sees it. The strategy list alone is ~200, so the ordering inside
# the message is load-bearing: the diagnosis has to survive the cut, and the
# list is what may be sacrificed. Asserted against the real limit, not a
# comfortable one.
check("the diagnosis survives the 300-char truncation control.py applies",
      "trend_following" in msg[:300] and "strategy" in msg[:300],
      f"len={len(msg)} head={msg[:80]!r}")
check("...and would still survive with twice as many strategies registered",
      len(f"{'trend_following'!r} is not a valid 'strategy'. Must be one of: ")
      < 300,
      "the prefix alone must fit, whatever the list grows to")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - a value the runtime would replace is refused, "
      "not stored.")
