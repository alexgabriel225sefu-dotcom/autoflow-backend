"""A strategy module must decide EXACTLY what the live bot decides today.

This is a refactor into a module shape, not a change of mind about trading.
The account is real, so the only acceptable proof is a direct comparison: for
every registered module, on a spread of market shapes, with and without an
open position, the module's verdict must equal the verdict of the call the
live loop actually makes —

    apex/user_loop.py:2147 / 2185 / 2195
        ai.signal_for_mode(active_mode, ind, strat_data, open_pos)
    apex/user_loop.py:2749
        strategies.druckenmiller_multiplier(confidence, criteriaScore,
                                            strat_data["livermore"],
                                            strat_data["turtle"])

— key for key, with nothing added but the strategy_id / strategy_version that
blueprint §14 requires be recorded per trade. If a module ever drifts from the
engine it wraps, this file fails before the drift can reach the account.

Every call is made on its own deepcopy of the inputs, so an engine that
mutated what it was handed could not hide behind a second identical call.

Run: python tests/test_strategy_equivalence.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import ai, indicators, strategies, strategy_api  # noqa: E402

strategy_api.load_builtins()

PROVENANCE = ("strategy_id", "strategy_version")


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0
comparisons = 0


def frame(closes, wick=0.0015, vol=1000):
    """OHLC candles from a close series, wicks proportional to price."""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        w = abs(c) * wick
        out.append({"time": 1_700_000_000 + i * 300, "open": prev,
                    "high": max(prev, c) + w, "low": min(prev, c) - w,
                    "close": c, "volume": vol})
        prev = c
    return out


# ── A spread of market shapes: each one drives a different branch of the
#    engines (trend gates, band extremes, channel breaks, dead tape). ──
N = 260


def _base(v=100.0):
    return [v] * N


FIXTURES = {
    "strong uptrend": frame([100 + i * 0.35 for i in range(N)]),
    "strong downtrend": frame([200 - i * 0.35 for i in range(N)]),
    "tight range": frame([100 + (1.5 if i % 2 else -1.5) for i in range(N)]),
    "uptrend then oversold flush": frame(
        [100 + i * 0.2 for i in range(N - 6)] + [148, 143, 138, 132, 127, 122]),
    "downtrend then overbought spike": frame(
        [200 - i * 0.2 for i in range(N - 6)] + [152, 157, 162, 168, 173, 178]),
    "fresh 20-bar breakout up": frame(_base()[:N - 1] + [109.0]),
    "fresh 20-bar breakdown": frame(_base()[:N - 1] + [91.0]),
    "violent chop": frame([100 + (i % 7) * 2.5 - (i % 3) * 3.0 for i in range(N)],
                          wick=0.02),
    "dead flat tape": frame([100.0 + (0.001 if i % 2 else 0.0) for i in range(N)],
                            wick=0.00002),
    "short history (60 bars)": frame([100 + i * 0.3 for i in range(60)]),
}

POSITIONS = {
    "flat": None,
    "long open": {"side": "BUY", "entryPrice": 100.0, "units": 1000},
    "short open": {"side": "SELL", "entryPrice": 100.0, "units": 1000},
}

# Pre-compute the loop's own inputs once per fixture, exactly as user_loop does:
#   ind        = indicators.analyze(candles)
#   strat_data = strategies.analyze(candles)
INPUTS = {}
for _name, _candles in FIXTURES.items():
    INPUTS[_name] = (indicators.analyze(_candles), strategies.analyze(_candles))


def strip(verdict):
    return {k: v for k, v in verdict.items() if k not in PROVENANCE}


# Equivalence applies to the V1 ADAPTERS only — the ten modules that wrap an
# ai.py engine. Strategies added later (momentum, session breakout, z-score,
# volatility regime, grid, martingale) are NEW logic with no engine to be
# equivalent to; they are covered by tests/test_new_strategies.py, which
# asserts a different property: that each decides, and refuses what its
# family loses money in.
#
# This check used to be "no module invents a mode that does not exist in
# ai.py". It failed the moment a genuinely new strategy was added, which is
# what it was there to catch — inverted deliberately rather than deleted.
from apex import strategy_modules  # noqa: E402
_ADAPTERS = {cls.strategy_id for cls in vars(strategy_modules).values()
             if isinstance(cls, type)
             and issubclass(cls, strategy_api.Strategy)
             and getattr(cls, "strategy_id", "")}
registered = _ADAPTERS
modes = set(ai.STRATEGY_MODES)

print("\n🧪 STRATEGY MODULE ↔ LIVE ENGINE EQUIVALENCE\n")
print(f"  {len(FIXTURES)} market shapes × {len(POSITIONS)} position states "
      f"× {len(_ADAPTERS)} V1 adapter modules")

# ── 1. Every shipped engine has a module, and vice versa ──────────
print("\n1. The registry covers exactly the engines the bot ships")

check("every cfg.STRATEGY mode has a registered module",
      modes <= registered, sorted(modes - registered))
check("every V1 adapter maps to a real ai.py engine",
      registered <= modes, sorted(registered - modes))
check("and the new-logic strategies are registered but NOT claimed as adapters",
      {"momentum", "zscore", "grid", "martingale"} <= set(strategy_api.available())
      and not ({"momentum", "zscore", "grid", "martingale"} & registered))

# ── 2. signal() ═ ai.signal_for_mode(...) ─────────────────────────
print("\n2. signal() is the live call, verdict for verdict")
for sid in sorted(registered):
    mod = strategy_api.get(sid)
    mismatches, n = [], 0
    for fname, candles in FIXTURES.items():
        ind, strat = INPUTS[fname]
        for pname, pos in POSITIONS.items():
            expected = ai.signal_for_mode(sid, copy.deepcopy(ind),
                                          copy.deepcopy(strat),
                                          copy.deepcopy(pos))
            market = strategy_api.Market(candles,
                                         indicators=copy.deepcopy(ind),
                                         strat=copy.deepcopy(strat),
                                         open_position=copy.deepcopy(pos))
            got = mod.signal(market)
            n += 1
            if strip(got) != expected:
                mismatches.append((fname, pname, expected, strip(got)))
    comparisons += n
    check(f"{sid}: identical across all {n} frames", not mismatches,
          mismatches[:1])

# ── 3. Nothing but the §14 provenance is added ────────────────────
print("\n3. The only thing a module adds is the §14 trade record")
ind, strat = INPUTS["strong uptrend"]
mkt = strategy_api.Market(FIXTURES["strong uptrend"], indicators=ind, strat=strat)
sig = strategy_api.get("trend").signal(mkt)
raw = ai.signal_for_mode("trend", copy.deepcopy(ind), copy.deepcopy(strat), None)
check("added keys are exactly strategy_id + strategy_version",
      set(sig) - set(raw) == set(PROVENANCE), sorted(set(sig) - set(raw)))
check("no key of the engine's verdict is dropped",
      set(raw) - set(sig) == set(), sorted(set(raw) - set(sig)))
check("strategy_id is the registered name", sig["strategy_id"] == "trend", sig)
check("strategy_version is recorded", bool(sig["strategy_version"]), sig)
check("registry reports the same provenance without instantiating",
      strategy_api.provenance_for("trend") ==
      {"strategy_id": "trend", "strategy_version": sig["strategy_version"]})

# ── 4. exit() is a view over the same call, never a second opinion ─
print("\n4. exit() reports the engine's own CLOSE verdict")
for sid in sorted(registered):
    mod = strategy_api.get(sid)
    bad, n = [], 0
    for fname, candles in FIXTURES.items():
        ind, strat = INPUTS[fname]
        for pname, pos in POSITIONS.items():
            if pos is None:
                continue
            expected = ai.signal_for_mode(sid, copy.deepcopy(ind),
                                          copy.deepcopy(strat),
                                          copy.deepcopy(pos))
            market = strategy_api.Market(candles,
                                         indicators=copy.deepcopy(ind),
                                         strat=copy.deepcopy(strat),
                                         open_position=copy.deepcopy(pos))
            got = mod.exit(market)
            n += 1
            if (got["action"] != expected.get("action", "HOLD")
                    or got["exit"] is not (expected.get("action") == "CLOSE")
                    or got["verdict"] != expected):
                bad.append((fname, pname, expected, got))
    comparisons += n
    check(f"{sid}: exit matches the engine across all {n} open positions",
          not bad, bad[:1])

flat_mkt = strategy_api.Market(FIXTURES["strong uptrend"],
                               indicators=INPUTS["strong uptrend"][0],
                               strat=INPUTS["strong uptrend"][1])
ex = strategy_api.get("trend").exit(flat_mkt)
check("with no position open, exit() is a no-op, not a CLOSE",
      ex["exit"] is False and ex["action"] == "HOLD", ex)

# ── 5. analyze() is the loop's own market read ────────────────────
print("\n5. analyze() reproduces the loop's market read exactly")
for fname, candles in FIXTURES.items():
    mod = strategy_api.get("auto")
    market = strategy_api.Market(candles)   # lazy path: computed from candles
    out = mod.analyze(market)
    comparisons += 4
    ok = (out["strat"] == strategies.analyze(candles)
          and out["indicators"] == indicators.analyze(candles)
          and out["regime"] == strategies.detect_regime(candles)
          and out["htfTrend"] == strategies.htf_trend(candles))
    check(f"{fname}: strat + indicators + regime + HTF all match", ok,
          {k: out.get(k) for k in ("regime", "htfTrend")})

print("\n6. analyze() does not mutate the frame it was handed")
ind, strat = INPUTS["violent chop"]
before_i, before_s = copy.deepcopy(ind), copy.deepcopy(strat)
market = strategy_api.Market(FIXTURES["violent chop"], indicators=ind, strat=strat)
strategy_api.get("auto").analyze(market)
strategy_api.get("auto").signal(market)
strategy_api.get("auto").risk(market)
check("indicators unchanged after analyze/signal/risk", ind == before_i)
check("strategy bundle unchanged after analyze/signal/risk", strat == before_s)

# ── 7. risk() is the loop's druckenmiller call, and nothing more ──
print("\n7. risk() is the live sizing multiplier (advisory)")
for fname, candles in FIXTURES.items():
    ind, strat = INPUTS[fname]
    bad = []
    for sid in sorted(registered):
        mod = strategy_api.get(sid)
        own = ai.signal_for_mode(sid, copy.deepcopy(ind), copy.deepcopy(strat), None)
        expected = strategies.druckenmiller_multiplier(
            own.get("confidence", 0), own.get("criteriaScore", 0),
            strat.get("livermore"), strat.get("turtle"))
        market = strategy_api.Market(candles, indicators=copy.deepcopy(ind),
                                     strat=copy.deepcopy(strat))
        got = mod.risk(market)
        comparisons += 1
        if got["multiplier"] != expected:
            bad.append((sid, expected, got))
    check(f"{fname}: all {len(registered)} modules match "
          f"druckenmiller_multiplier", not bad, bad[:1])

# The loop feeds the POST-AI confidence into the multiplier, not the rule
# engine's own — a module must use the caller's number when it is given one,
# or AI confirmation would silently stop affecting position size.
print("\n8. The caller's post-AI confidence drives sizing, as in the loop")
ind, strat = INPUTS["strong uptrend"]
for conf, crit in ((90, 5), (82, 4), (60, 1), (78, 3)):
    market = strategy_api.Market(FIXTURES["strong uptrend"],
                                 indicators=copy.deepcopy(ind),
                                 strat=copy.deepcopy(strat),
                                 confidence=conf, criteria_score=crit)
    expected = strategies.druckenmiller_multiplier(
        conf, crit, strat.get("livermore"), strat.get("turtle"))
    got = strategy_api.get("trend").risk(market)["multiplier"]
    comparisons += 1
    check(f"confidence {conf} / criteria {crit} → {expected}", got == expected, got)

print("\n" + "=" * 50)
print(f"{comparisons} module-vs-engine comparisons made.")
if check.failed == 0:
    print("✅ ALL EQUIVALENCE CHECKS PASSED — modules decide what the bot decides.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
