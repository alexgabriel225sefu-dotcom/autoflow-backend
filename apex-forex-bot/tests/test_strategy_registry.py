"""The strategy interface, the registry, and the one rule neither may break.

Three things are asserted here, all of them safety properties rather than
trading opinions:

  * A strategy can be ADDED without touching the engine. That is the whole
    point of the registry — a new module is a class plus a decorator, and the
    dispatch code above it never learns its name.

  * `risk()` is ADVISORY (blueprint §6/§16). A strategy module is untrusted
    input to the Risk Engine: it may be written by someone else, and its
    numbers may come from an AI context that has every reason to ask for more
    size. A module that returns 99, NaN, or a key called "override_risk" must
    not get any of it. The clamp is enforced twice on purpose — once for
    modules that extend the base class properly, once at the Risk Engine's own
    read, for a module that overrode `risk()` outright.

  * Every strategy carries a strategy_id and strategy_version (§14). Without
    both, a trade cannot be reproduced later, so the registry refuses to
    accept a module missing either one.

Run: python tests/test_strategy_registry.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import strategy_api  # noqa: E402

strategy_api.load_builtins()


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def candles(n=60, start=100.0):
    return [{"time": i, "open": start + i * 0.1, "high": start + i * 0.1 + 0.2,
             "low": start + i * 0.1 - 0.2, "close": start + i * 0.1,
             "volume": 1000} for i in range(n)]


CANDLES = candles()

print("\n🧪 STRATEGY INTERFACE + REGISTRY\n")

# ── 1. Interface conformance ──────────────────────────────────────
print("1. Every shipped module implements the blueprint interface")
for sid in strategy_api.available():
    mod = strategy_api.get(sid)
    have = all(callable(getattr(mod, m, None))
               for m in ("analyze", "signal", "risk", "exit"))
    check(f"{sid}: analyze/signal/risk/exit + id + version",
          have and bool(mod.strategy_id) and bool(mod.strategy_version)
          and bool(mod.label),
          {"id": mod.strategy_id, "ver": mod.strategy_version})

check(f"{len(strategy_api.available())} modules registered",
      len(strategy_api.available()) >= 10, strategy_api.available())
check("describe() reports id, version and label for each",
      all({"strategy_id", "strategy_version", "label"} == set(d)
          for d in strategy_api.describe()), strategy_api.describe()[:1])
check("get() returns a fresh instance each call (modules are stateless)",
      strategy_api.get("trend") is not strategy_api.get("trend"))
check("an unknown strategy is None, not a silent default",
      strategy_api.get("does_not_exist") is None)
check("provenance_for() on an unknown strategy is None",
      strategy_api.provenance_for("does_not_exist") is None)

# ── 2. Adding a strategy never touches the engine ─────────────────
print("\n2. A new strategy is added without touching the engine")
before = set(strategy_api.available())


@strategy_api.register
class _Probe(strategy_api.Strategy):
    strategy_id = "_probe"
    strategy_version = "0.1.0"
    label = "Test probe"

    def analyze(self, market):
        return self.stamp({"seen": len(market.candles)})

    def signal(self, market):
        return self.stamp({"action": "HOLD", "confidence": 1})

    def advise_risk(self, market):
        return {"multiplier": 1.1}

    def exit(self, market):
        return self.stamp({"exit": False, "action": "HOLD"})


mkt = strategy_api.Market(CANDLES, symbol="EURUSD")
check("it appears in the registry", "_probe" in strategy_api.available())
check("it is reachable by name", strategy_api.get("_probe") is not None)
check("its verdict carries its own provenance",
      strategy_api.get("_probe").signal(mkt)["strategy_id"] == "_probe")
check("its version is recorded separately from the shipped ones",
      strategy_api.provenance_for("_probe")["strategy_version"] == "0.1.0")
check("adding it changed nothing about the existing modules",
      before <= set(strategy_api.available())
      and strategy_api.provenance_for("trend")["strategy_id"] == "trend")

print("\n3. The registry refuses anything it could not reproduce later (§14)")


def rejects(label, define, want=Exception):
    try:
        define()
    except want as e:
        check(label, True, repr(e))
        return
    except Exception as e:
        check(label, False, f"wrong error: {e!r}")
        return
    check(label, False, "accepted")


def _no_id():
    class X(strategy_api.Strategy):
        strategy_version = "1.0.0"
    strategy_api.register(X)


def _no_version():
    class X(strategy_api.Strategy):
        strategy_id = "_x"
    strategy_api.register(X)


def _blank_id():
    class X(strategy_api.Strategy):
        strategy_id = "   "
        strategy_version = "1.0.0"
    strategy_api.register(X)


def _not_a_strategy():
    class X:
        strategy_id = "_x"
        strategy_version = "1.0.0"
    strategy_api.register(X)


def _duplicate():
    class X(strategy_api.Strategy):
        strategy_id = "trend"
        strategy_version = "9.9.9"
    strategy_api.register(X)


rejects("a module with no strategy_id", _no_id, ValueError)
rejects("a module with no strategy_version", _no_version, ValueError)
rejects("a whitespace-only strategy_id", _blank_id, ValueError)
rejects("something that is not a Strategy at all", _not_a_strategy, TypeError)
rejects("a second module claiming an existing id", _duplicate, ValueError)
check("the collision did not overwrite the real strategy",
      strategy_api.provenance_for("trend")["strategy_version"] == "1.0.0",
      strategy_api.provenance_for("trend"))

# ── 4. risk() is advisory — the AI can never size its own trade up ─
print("\n4. risk() is advisory: a module cannot inflate its own size")


class _Greedy(strategy_api.Strategy):
    strategy_id = "_greedy"
    strategy_version = "0.0.1"

    def analyze(self, market):
        return {}

    def signal(self, market):
        return {"action": "BUY"}

    def advise_risk(self, market):
        return {"multiplier": 99.0, "reason": "AI says this one is a lock"}

    def exit(self, market):
        return {"exit": False}


g = _Greedy()
adv = g.risk(mkt)
check("a 99x advisory is clamped to the existing cap",
      adv["multiplier"] == strategy_api.ADVISORY_MAX, adv)
check("...and the clamp is visible, not silent",
      adv.get("clamped_from") == 99.0, adv)
check("the advisory is labelled as advisory", adv["advisory"] is True, adv)


def advises(value):
    class _V(_Greedy):
        strategy_id = "_v"

        def advise_risk(self, market):
            return {"multiplier": value}
    return _V().risk(mkt)["multiplier"]


check("a 0x advisory cannot zero out a position either",
      advises(0.0) == strategy_api.ADVISORY_MIN, advises(0.0))
check("a negative advisory is clamped, not inverted",
      advises(-5.0) == strategy_api.ADVISORY_MIN, advises(-5.0))
check("NaN falls back to 1.0", advises(float("nan")) == 1.0, advises(float("nan")))
check("a string falls back to 1.0", advises("huge") == 1.0, advises("huge"))
check("None falls back to 1.0", advises(None) == 1.0, advises(None))
check("an in-band advisory passes through untouched", advises(0.8) == 0.8)


class _Sneaky(_Greedy):
    strategy_id = "_sneaky"

    def advise_risk(self, market):
        return {"multiplier": 1.0, "override_risk_engine": True,
                "bypass_daily_loss": True, "force_entry": True,
                "skip_drawdown_check": True, "allow_stacking": True,
                "basis": "legitimate field"}


sneaky = _Sneaky().risk(mkt)
check("an advisory cannot carry an instruction to the risk engine",
      not any(k for k in sneaky if any(w in k.lower() for w in
              ("override", "bypass", "force", "skip", "allow"))), sneaky)
check("...while ordinary fields still come through",
      sneaky.get("basis") == "legitimate field", sneaky)


class _Rogue(_Greedy):
    strategy_id = "_rogue"

    def risk(self, market):          # overrides the sanitising wrapper
        return {"multiplier": 500.0}


check("a module that overrides risk() is still clamped at the engine's read",
      strategy_api.advisory_multiplier(_Rogue(), mkt) == strategy_api.ADVISORY_MAX,
      strategy_api.advisory_multiplier(_Rogue(), mkt))


class _Broken(_Greedy):
    strategy_id = "_broken"

    def risk(self, market):
        raise RuntimeError("boom")


check("a module whose risk() raises yields 1.0, not an exception into the loop",
      strategy_api.advisory_multiplier(_Broken(), mkt) == 1.0)
check("the base class default is a neutral 1.0, not a free upsize",
      strategy_api.Strategy().risk(mkt)["multiplier"] == 1.0)

# ── 5. Market validates at the boundary ───────────────────────────
print("\n5. The market frame is validated where the data enters")


def bad(label, build, want=Exception):
    try:
        build()
    except want:
        check(label, True)
    except Exception as e:
        check(label, False, f"wrong error: {e!r}")
    else:
        check(label, False, "accepted")


bad("no candles at all", lambda: strategy_api.Market([]), ValueError)
bad("candles is not a list", lambda: strategy_api.Market("EURUSD"), TypeError)
bad("a candle that is not a dict", lambda: strategy_api.Market([1, 2, 3]), TypeError)
bad("a candle missing close",
    lambda: strategy_api.Market([{"open": 1, "high": 2, "low": 0}]), ValueError)
bad("a candle with a string price",
    lambda: strategy_api.Market([{"open": 1, "high": 2, "low": 0, "close": "x"}]),
    ValueError)
bad("a NaN price",
    lambda: strategy_api.Market([{"open": 1, "high": 2, "low": 0,
                                  "close": float("nan")}]), ValueError)
bad("an open position with no side",
    lambda: strategy_api.Market(CANDLES, open_position={"units": 1000}), ValueError)
bad("an open position with a nonsense side",
    lambda: strategy_api.Market(CANDLES, open_position={"side": "LONG"}), ValueError)
bad("indicators handed in as a list",
    lambda: strategy_api.Market(CANDLES, indicators=[1, 2]), TypeError)

ok = strategy_api.Market(CANDLES, open_position={"side": "BUY"})
check("a valid frame is accepted", ok.open_position["side"] == "BUY")
check("price defaults to the last close",
      ok.price == CANDLES[-1]["close"], ok.price)
check("indicators are computed lazily from the candles",
      isinstance(ok.indicators, dict) and "rsi" in ok.indicators)
check("the strategy bundle is computed lazily too",
      "turtle" in ok.strat and "livermore" in ok.strat)
check("regime is available on the frame", "regime" in ok.regime)

# ── 6. The loop IS wired to the registry — and keeps a way back ────
print("\n6. The live decision path goes through the registry")
_loop = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "apex", "user_loop.py")
with open(_loop, encoding="utf-8") as f:
    loop_src = f.read()
# This check used to assert the OPPOSITE — that the loop did not import the
# registry — because V1 shipped additive on purpose: prove equivalence first,
# switch second. That switch has now been made deliberately, so the guard is
# inverted rather than deleted. What it protects has changed shape, not
# disappeared: the registry is in the decision path, and every path through it
# still has a way back to the engine, because a registry problem must never
# stop a live account from trading.
check("user_loop.py imports the registry", "strategy_api" in loop_src)
check("and populates it, or every lookup would miss silently",
      "strategy_api.load_builtins()" in loop_src)
check("the rule verdict goes through the module",
      "_strategy.signal(_frame)" in loop_src)
check("with a fallback to the engine if the module is missing or raises",
      loop_src.count("ai.signal_for_mode(active_mode, ind, strat_data, open_pos)") >= 1)
check("the frame is NOT named `market` — that name is the apex.market module",
      "market = strategy_api.Market(" not in loop_src
      and "_frame = strategy_api.Market(" in loop_src)
check("§14: the signal is stamped with its strategy",
      "_provenance" in loop_src and "signal = {**signal, **_provenance}" in loop_src)
check("§14: the opening strategy is carried on the position",
      '"entryStrategyId"' in loop_src and '"entryStrategyVersion"' in loop_src)
check("§14: and reaches the closed-trade journal",
      '"strategyId":' in loop_src and '"strategyVersion":' in loop_src)
check("the entry snapshot survives a broker re-read",
      '"entryStrategyId", "entryStrategyVersion",' in loop_src)

strategy_api.unregister("_probe")
check("test strategies clean up after themselves",
      "_probe" not in strategy_api.available())

print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL REGISTRY + INTERFACE CHECKS PASSED.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
