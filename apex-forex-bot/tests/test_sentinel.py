"""Permanent Market Sentinel — persistent, EXPIRING market state.

The spec's sharpest rule is that a signal must expire: "Nu se folosește ultimul
BUY/SELL la nesfârșit." A stale opinion is not a weaker opinion, it is a
different market.

The trap this test exists to guard: the spec's own example expires a signal 60
seconds after publication. That suits a one-second sentinel loop and is
catastrophic in this engine, which ticks every few minutes on a 15m chart — a
fixed 60s TTL leaves every signal stale on arrival, the gate refuses
everything, and the bot silently stops trading. TTL is derived from the candle.

Run: python tests/test_sentinel.py
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

from apex import sentinel as S  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


T0 = 1_786_500_000.0


def st(action="BUY", ttl=300, now=T0, **kw):
    return S.build_state("EURUSD", action, ttl_s=ttl, now=now, **kw)


print("\n── TTL comes from the chart, not a magic number ──")
check("1m → 60s", S.default_ttl("1m") == 60)
check("15m → 900s", S.default_ttl("15m") == 900)
check("1h is capped at 30min, not left open-ended", S.default_ttl("1h") == 1800)
check("a 1d chart is still capped", S.default_ttl("1d") == 1800)
check("unknown timeframe falls back to 5m", S.default_ttl("banana") == 300)
check("THE TRAP: a 15m signal does NOT die after 60s",
      S.default_ttl("15m") > 60)

print("\n── a signal expires ──")
s = st(ttl=300)
check("fresh at publication", S.valid_signal(s, T0)[0] is True)
check("fresh at 299s", S.valid_signal(s, T0 + 299)[0] is True)
check("DEAD at 300s", S.valid_signal(s, T0 + 300)[0] is False)
check("and the reason is typed",
      S.valid_signal(s, T0 + 300)[1] == S.NO_SIGNAL)
check("age is reported", abs(S.age(s, T0 + 42) - 42) < 0.01)

print("\n── malformed signals are never actionable ──")
check("None", S.valid_signal(None, T0)[0] is False)
check("empty dict", S.valid_signal({}, T0)[0] is False)
check("no expires_at", S.valid_signal({"action": "BUY"}, T0)[0] is False)
check("junk expires_at",
      S.valid_signal({"action": "BUY", "expires_at": "soon"}, T0)[0] is False)
check("an action outside BUY/SELL/HOLD is malformed, not a HOLD",
      S.valid_signal({"action": "MOON", "expires_at": T0 + 99}, T0)[0] is False)
check("build_state coerces a bad action to HOLD",
      st(action="MOON")["action"] == "HOLD")

print("\n── confidence: 0-100 and 0-1 both arrive in this codebase ──")
check("73 (engine score) → 0.73", st(confidence=73)["confidence"] == 0.73)
check("0.73 (spec contract) → 0.73", st(confidence=0.73)["confidence"] == 0.73)
check("100 → 1.0", st(confidence=100)["confidence"] == 1.0)
check("junk → None, not 0 (0 would silently fail every threshold)",
      st(confidence="high")["confidence"] is None)
check("missing → None", st()["confidence"] is None)

print("\n── the decision gate, with typed reasons ──")
fresh = st("BUY", confidence=80, expected_value_r=0.4)
check("agreement → approved", S.decide(fresh, "BUY", T0) == (True, S.APPROVED))
check("disagreement → AI_DISAGREES",
      S.decide(fresh, "SELL", T0) == (False, S.DISAGREES))
check("stale → NO_FRESH_AI_SIGNAL",
      S.decide(fresh, "BUY", T0 + 9999) == (False, S.NO_SIGNAL))
check("no signal at all → NO_FRESH_AI_SIGNAL",
      S.decide(None, "BUY", T0) == (False, S.NO_SIGNAL))
check("AI says HOLD → its own reason, not 'disagrees'",
      S.decide(st("HOLD"), "BUY", T0) == (False, S.HOLD_CALLED))
check("risk engine veto → RISK_BLOCK",
      S.decide(fresh, "BUY", T0, risk_ok=False) == (False, S.RISK_BLOCK))
check("confidence below the bar → LOW_CONFIDENCE",
      S.decide(fresh, "BUY", T0, min_confidence=0.9) == (False, S.LOW_CONF))
check("confidence at the bar passes",
      S.decide(fresh, "BUY", T0, min_confidence=0.8)[0] is True)
check("EV below the bar → LOW_EV",
      S.decide(fresh, "BUY", T0, min_ev_r=0.5) == (False, S.LOW_EV))

print("\n── an unconfigured threshold must never block ──")
bare = st("BUY")   # no confidence, no EV on the state at all
check("min_confidence=None is not enforced",
      S.decide(bare, "BUY", T0, min_confidence=None)[0] is True)
check("min_ev_r=None is not enforced",
      S.decide(bare, "BUY", T0, min_ev_r=None)[0] is True)
check("but a CONFIGURED threshold with no data refuses",
      S.decide(bare, "BUY", T0, min_confidence=0.5) == (False, S.LOW_CONF))

print("\n── should_refresh: pay for an AI call only when something changed ──")
base = {"price": 1.1000, "atr": 0.0010, "spread_pips": 0.8,
        "regime": "trending", "bar_time": 100, "expires_at": T0 + 300}
check("no state → refresh", S.should_refresh(None, base, T0)[0] is True)
check("nothing changed → no refresh",
      S.should_refresh(base, dict(base), T0) == (False, "unchanged"))
check("expired → refresh",
      S.should_refresh(base, dict(base), T0 + 301)[1] == "expired")
check("new candle → refresh",
      S.should_refresh(base, {**base, "bar_time": 101}, T0)[1] == "new_candle")
check("regime flip → refresh",
      S.should_refresh(base, {**base, "regime": "ranging"}, T0)[1]
      == "regime_change")
check("price moved half an ATR → refresh",
      S.should_refresh(base, {**base, "price": 1.1005}, T0)[1] == "price_moved")
check("price moved a tenth of an ATR → no refresh",
      S.should_refresh(base, {**base, "price": 1.1001}, T0)[0] is False)
check("spread blew out → refresh (it changes the EV cost side)",
      S.should_refresh(base, {**base, "spread_pips": 1.4}, T0)[1]
      == "spread_change")

print("\n── should_refresh fails toward refreshing, never toward staleness ──")
check("no expires_at → refresh",
      S.should_refresh({"price": 1.1}, base, T0)[1] == "no_expiry")
check("junk expires_at → refresh",
      S.should_refresh({"expires_at": "x"}, base, T0)[1] == "no_expiry")
check("unreadable prices do not claim 'unchanged' wrongly",
      S.should_refresh({**base, "price": "n/a"},
                       {**base, "price": "n/a"}, T0)[0] is False)

print("\n── the store ──")
store = S.SignalStore()
store.publish(st("BUY", ttl=300))
check("get returns it", store.get("EURUSD")["action"] == "BUY")
check("EUR_USD / eurusd / EURUSD are one symbol",
      store.get("eur_usd") is not None and store.get("eurusd") is not None)
check("fresh() returns it while valid", store.fresh("EURUSD", T0) is not None)
check("fresh() returns None once stale",
      store.fresh("EURUSD", T0 + 9999) is None)
check("get() still returns the stale one (for logging)",
      store.get("EURUSD") is not None)
check("unknown symbol → None", store.get("GBPUSD") is None)
store.publish(st("SELL", ttl=300))
check("republishing replaces, not appends",
      store.get("EURUSD")["action"] == "SELL")
store.drop("EURUSD")
check("drop removes it", store.get("EURUSD") is None)
check("publishing a symbol-less state is a no-op",
      store.publish({"action": "BUY"}) is not None and store.get("") is None)

print("\n── describe() is safe on anything ──")
check("no signal", S.describe(None) == "no AI signal")
d = S.describe(st("BUY", confidence=73, expected_value_r=0.4), T0 + 10)
check("renders action, confidence, EV and age",
      "BUY" in d and "73%" in d and "0.4R" in d and "10s old" in d, d)
check("a stale signal is labelled STALE",
      "STALE" in S.describe(st("BUY", ttl=60), T0 + 999))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL SENTINEL CHECKS PASSED.")
