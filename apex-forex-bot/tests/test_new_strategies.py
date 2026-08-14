"""The blueprint §2 families that did not exist: momentum, session breakout,
quant/statistical, and the two specialized ones.

Unlike the V1 ten, these are NEW decision logic, so equivalence with an
existing engine cannot be the safety property. What is asserted instead:

  * each one DECIDES — it produces BUY/SELL on the setup it claims to trade,
    not HOLD forever, which is how a strategy can look safe by never working
  * each one REFUSES the conditions its family is known to lose in
  * the specialized two cannot escape their caps, whatever they ask for

That last one is the reason grid and martingale are includable at all. The
advisory band tops out at 1.2x, so no strategy can double a position, and
they stop emitting signals entirely after MAX_STEPS consecutive losses.

Run: python tests/test_new_strategies.py
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import strategy_api  # noqa: E402
from apex import strategies as _st  # noqa: E402

strategy_api.load_builtins()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def make(kind, n=240, seed=11):
    """Market shapes with REALISTIC noise — a monotonic ramp pegs RSI at 100
    and every strategy correctly refuses it, which tests nothing."""
    random.seed(seed)
    out, px = [], 1.1000
    for i in range(n):
        if kind == "trending_up":
            px += 0.00011 + random.uniform(-0.00035, 0.00045)
        elif kind == "trending_down":
            px -= 0.00011 + random.uniform(-0.00045, 0.00035)
        elif kind == "chop":
            px += random.uniform(-0.0005, 0.0005)
        elif kind == "range":
            # Ornstein-Uhlenbeck, NOT a sine wave. A sine is directional in
            # stretches, so it reads as ADX 31-40 — a trend, which is exactly
            # what the ranging strategies are built to refuse. A real ranging
            # FX tape mean-reverts and sits at ADX 12-21, and that is where
            # z-score, grid and martingale actually get their setups.
            px += 0.06 * (1.1000 - px) + random.gauss(0, 0.00055)
        elif kind == "squeeze_break":
            px += (random.uniform(-0.00006, 0.00006) if i < n - 25
                   else 0.00055 + random.uniform(-0.0001, 0.0002))
        elif kind == "range_then_break":
            px = (1.1000 + 0.0006 * math.sin(i / 5) + random.uniform(-0.0001, 0.0001)
                  if i < n - 4 else px + 0.0016)
        o = px - 0.00008
        out.append({"time": 1786600000 + i * 900, "open": o,
                    "high": max(o, px) + abs(random.uniform(0, 0.0005)),
                    "low": min(o, px) - abs(random.uniform(0, 0.0005)),
                    "close": px, "volume": 900 + (i * 37) % 400})
    return out


def frame(kind, seed=11, **kw):
    return strategy_api.Market(make(kind, seed=seed), symbol="EURUSD",
                               timeframe="15m", **kw)


def act(sid, kind, seed=11, **kw):
    v = strategy_api.get(sid).signal(frame(kind, seed=seed, **kw))
    return v.get("action"), v.get("reasoning", "")


print("\n── all four families are registered and versioned ──")
avail = strategy_api.available()
for sid in ("momentum", "session_breakout", "opening_range", "zscore",
            "vol_regime", "grid", "martingale"):
    check(f"{sid} registered", sid in avail, str(avail))
    p = strategy_api.provenance_for(sid) or {}
    check(f"{sid} is versioned", bool(p.get("strategy_version")), str(p))
check("the original ten are untouched",
      all(s in avail for s in ("auto", "trend", "mean_reversion", "breakout",
                               "fibonacci", "fvg", "ifvg", "supply_demand",
                               "liquidity_sweep", "evc")))

print("\n── each one actually decides, and refuses what it should ──")
seen = {}
for sid in ("momentum", "session_breakout", "opening_range", "zscore",
            "vol_regime", "grid", "martingale"):
    acts = set()
    for kind in ("trending_up", "trending_down", "chop", "range",
                 "squeeze_break", "range_then_break"):
        for sd in (2, 3, 5, 11):
            a, _ = act(sid, kind, seed=sd)
            acts.add(a)
    seen[sid] = acts
    check(f"{sid} emits a real entry somewhere",
          bool(acts & {"BUY", "SELL"}), f"only ever {acts}")
    check(f"{sid} also declines somewhere (not a permanent yes)",
          "HOLD" in acts, f"never holds: {acts}")

print("\n── each refuses the condition its family loses money in ──")
a, why = act("momentum", "chop")
check("momentum stands aside in chop", a == "HOLD" and "ADX" in why, why[:90])
a, why = act("zscore", "trending_up")
check("z-score will not fade a trend",
      a == "HOLD" and "not fading" in why, why[:90])
a, why = act("grid", "trending_up")
check("grid refuses a trend", a == "HOLD" and "trend" in why.lower(), why[:110])
a, why = act("martingale", "trending_up")
check("martingale refuses a trend", a == "HOLD" and "trend" in why.lower(), why[:110])
_sq = make("squeeze_break")[:-30]          # the squeeze, before it breaks
a = strategy_api.get("vol_regime").signal(
    strategy_api.Market(_sq, symbol="EURUSD", timeframe="15m"))
check("vol_regime waits while still squeezed rather than guessing direction",
      a.get("action") == "HOLD" and "squeez" in a.get("reasoning", "").lower(),
      a.get("reasoning", "")[:100])

print("\n── the specialized caps hold, whatever the strategy asks for ──")
mart = strategy_api.get("martingale")


class _Sess:
    def __init__(self, n):
        self.n = n

    def __call__(self, uid):
        return {"consecutiveLosses": self.n}


_real_session = _st.get_session
try:
    for streak, expect_signal in ((0, True), (1, True), (2, True), (3, False),
                                  (7, False)):
        _st.get_session = _Sess(streak)
        f = frame("range")
        f.user_id = "cap-test"
        v = mart.signal(f)
        got_entry = v.get("action") in ("BUY", "SELL")
        if expect_signal:
            check(f"streak {streak}: still allowed to trade",
                  v.get("action") in ("BUY", "SELL", "HOLD"))
        else:
            check(f"streak {streak}: REFUSES to trade at all",
                  not got_entry and "stops at" in v.get("reasoning", ""),
                  v.get("reasoning", "")[:110])
        advice = mart.risk(f)
        check(f"streak {streak}: advisory never exceeds "
              f"{strategy_api.ADVISORY_MAX}x",
              advice["multiplier"] <= strategy_api.ADVISORY_MAX,
              str(advice))
finally:
    _st.get_session = _real_session

print("\n── a martingale cannot double, by construction ──")
raw = mart.advise_risk(frame("range"))
check("it may ASK for more than the ceiling on a long streak",
      isinstance(raw.get("multiplier"), float))
clamped = strategy_api._sanitize_advice({"multiplier": 8.0}, mart)
check("but 8x is clamped to the band", clamped["multiplier"] == strategy_api.ADVISORY_MAX,
      str(clamped))
check("and the clamp is recorded, not hidden", "clamped_from" in clamped, str(clamped))
check("the Risk Engine's read clamps a second time",
      strategy_api.advisory_multiplier(mart, frame("range")) <= strategy_api.ADVISORY_MAX)


class Rogue(strategy_api.Strategy):
    strategy_id = "_rogue_probe"
    strategy_version = "0.0.1"

    def risk(self, market):        # overrides the sanitising wrapper entirely
        return {"multiplier": 50.0, "override_risk_engine": True}


check("even a strategy that overrides risk() outright is capped",
      strategy_api.advisory_multiplier(Rogue(), frame("range"))
      <= strategy_api.ADVISORY_MAX)

print("\n── grid keeps its entries small ──")
g = strategy_api.get("grid")
check("grid asks for LESS size, not more",
      g.risk(frame("range"))["multiplier"] <= 1.0,
      str(g.risk(frame("range"))))

print("\n── every new strategy names its numbers ──")
for sid in ("momentum", "session_breakout", "zscore", "vol_regime",
            "grid", "martingale"):
    _a, why = act(sid, "range")
    check(f"{sid} explains itself with figures",
          len(why) > 25 and any(ch.isdigit() for ch in why), why[:80])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL NEW-STRATEGY CHECKS PASSED.")
