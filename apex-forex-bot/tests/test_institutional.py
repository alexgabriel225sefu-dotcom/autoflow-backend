"""Institutional State must never invent data.

The spec is explicit (section 7): "Dacă o sursă lipsește, scorul trebuie
degradat; nu se inventează date." A composite score is only as trustworthy as
its coverage, and a +0.58 built from two feeds must never be mistaken for a
+0.58 built from nine.

The trap this guards: imputing 0.0 for a missing source. It looks harmless —
0 is "neutral" — but it asserts as fact that positioning is balanced when the
truth is that nobody looked. It also drags every composite toward zero
whenever a feed dies, which reads as "the market calmed down".

Run: python tests/test_institutional.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

from apex import institutional as I  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


T0 = 1_786_500_000.0


def obs(f, v, src="test", conf=1.0, ttl=3600, now=T0):
    return I.observe(f, v, src, confidence=conf, ttl_s=ttl, now=now)


FULL = [obs(f, 0.5, src=f"src_{f}") for f in I.FEATURES]

print("\n── values are normalised and bad input becomes missing, not zero ──")
check("in-range value kept", I.observe("sentiment", 0.4, "x")["value"] == 0.4)
check("above range clamped", I.observe("sentiment", 9.0, "x")["value"] == 1.0)
check("below range clamped", I.observe("sentiment", -9.0, "x")["value"] == -1.0)
check("junk becomes None, NOT 0.0",
      I.observe("sentiment", "bullish", "x")["value"] is None)
check("None stays None", I.observe("sentiment", None, "x")["value"] is None)

print("\n── a full picture scores cleanly ──")
s = I.build("EURUSD", FULL, now=T0)
check("proxy is the weighted mean", abs(s["institutional_proxy"] - 0.5) < 1e-6,
      str(s["institutional_proxy"]))
check("data quality is 100%", s["data_quality"] == 1.0)
check("usable", s["usable"] is True)
check("nothing reported missing", s["missing"] == [])
check("all sources are named", len(s["sources"]) == len(I.FEATURES))

print("\n── THE TRAP: a missing source degrades quality, not the score ──")
partial = [o for o in FULL if o["feature"] in ("price_momentum", "sentiment")]
p = I.build("EURUSD", partial, now=T0)
check("the score stays +0.5 — the two feeds still say +0.5",
      abs(p["institutional_proxy"] - 0.5) < 1e-6, str(p["institutional_proxy"]))
check("but quality collapses", p["data_quality"] < 0.3, str(p["data_quality"]))
check("and the state is refused as too thin", p["usable"] is False)
check("with the reason spelled out", "data quality" in p["reason"], p["reason"])
check("the absent features are listed by name",
      "cot_bias" in p["missing"] and "rate_differential" in p["missing"])
check("a missing feature is NOT imputed into features{}",
      "cot_bias" not in p["features"])

print("\n── the same score from 2 feeds vs 9 is distinguishable ──")
check("two-feed +0.5 and nine-feed +0.5 differ in quality",
      p["institutional_proxy"] == s["institutional_proxy"]
      and p["data_quality"] != s["data_quality"])
check("and only one of them is usable",
      s["usable"] is True and p["usable"] is False)

print("\n── expired observations are missing, not merely old ──")
stale = [obs(f, 0.5, ttl=60) for f in I.FEATURES]
e = I.build("EURUSD", stale, now=T0 + 999)
check("everything expired → nothing usable", e["institutional_proxy"] is None)
check("quality is zero", e["data_quality"] == 0.0)
check("state refused", e["usable"] is False)
mixed = [obs("price_momentum", 0.8, ttl=99999), obs("sentiment", -0.9, ttl=60)]
m = I.build("EURUSD", mixed, now=T0 + 999)
check("the stale one is dropped, the fresh one survives",
      list(m["features"]) == ["price_momentum"], str(list(m["features"])))
check("and the dead feed does not drag the score",
      m["institutional_proxy"] == 0.8, str(m["institutional_proxy"]))

print("\n── critical sources are load-bearing ──")
no_price = [o for o in FULL if o["feature"] != "price_momentum"]
n = I.build("EURUSD", no_price, now=T0)
check("high quality but still unusable without price",
      n["data_quality"] > 0.8 and n["usable"] is False,
      f"q={n['data_quality']} usable={n['usable']}")
check("the reason names the critical gap",
      "critical" in n["reason"] and "price_momentum" in n["reason"], n["reason"])

print("\n── confidence weights a source down without silencing it ──")
sure = I.build("X", [obs("price_momentum", 1.0), obs("sentiment", -1.0)], now=T0)
unsure = I.build("X", [obs("price_momentum", 1.0),
                       obs("sentiment", -1.0, conf=0.1)], now=T0)
check("a low-confidence bearish read moves the score less",
      unsure["institutional_proxy"] > sure["institutional_proxy"],
      f"{unsure['institutional_proxy']} vs {sure['institutional_proxy']}")
check("but it still counts toward coverage",
      unsure["data_quality"] == sure["data_quality"])

print("\n── later observations of a feature win ──")
dup = [obs("price_momentum", -0.9, src="old", now=T0),
       obs("price_momentum", 0.9, src="new", now=T0 + 10)]
d = I.build("EURUSD", dup, now=T0 + 20)
check("newest wins", d["features"]["price_momentum"]["value"] == 0.9)
check("and its source is credited",
      d["features"]["price_momentum"]["source"] == "new")

print("\n── delta compares only what is present in BOTH states ──")
a = I.build("EURUSD", [obs("price_momentum", 0.2), obs("cot_bias", 0.1)], now=T0)
b = I.build("EURUSD", [obs("price_momentum", 0.6), obs("sentiment", 0.9)],
            now=T0 + 60)
dl = I.delta(a, b)
check("the shared feature is compared",
      abs(dl["per_feature"]["price_momentum"] - 0.4) < 1e-6)
check("a feature that just APPEARED has no delta invented",
      "sentiment" not in dl["per_feature"])
check("a feature that DISAPPEARED has no delta invented",
      "cot_bias" not in dl["per_feature"])
check("the count of what was actually compared is reported",
      dl["compared"] == 1)
check("no previous state → empty delta, not a fabricated one",
      I.delta(None, b)["composite"] is None)

print("\n── action_bias: not knowing is a reason to stand aside ──")
strong_up = I.build("EURUSD", [obs(f, 0.8) for f in I.FEATURES], now=T0)
strong_dn = I.build("EURUSD", [obs(f, -0.8) for f in I.FEATURES], now=T0)
flat = I.build("EURUSD", [obs(f, 0.05) for f in I.FEATURES], now=T0)
check("strongly positive → BUY", I.action_bias(strong_up) == "BUY")
check("strongly negative → SELL", I.action_bias(strong_dn) == "SELL")
check("near zero → HOLD", I.action_bias(flat) == "HOLD")
check("UNUSABLE state → HOLD, never a guess", I.action_bias(p) == "HOLD")
check("no state at all → HOLD", I.action_bias(None) == "HOLD")
check("a thin but strongly bullish state still HOLDs",
      I.action_bias(I.build("X", [obs("price_momentum", 1.0)], now=T0)) == "HOLD")

print("\n── describe() is honest about coverage ──")
txt = I.describe(s)
check("names the proxy and the quality",
      "+0.50" in txt and "100%" in txt, txt)
check("an unusable state is labelled", "UNUSABLE" in I.describe(p))
check("no state", I.describe(None) == "no institutional state")

print("\n── garbage in never raises ──")
check("empty list", I.build("X", [], now=T0)["usable"] is False)
check("None", I.build("X", None, now=T0)["usable"] is False)
check("unknown feature is ignored",
      "moon_phase" not in I.build("X", [obs("moon_phase", 1.0)],
                                  now=T0)["features"])
check("observation with a broken expiry is dropped",
      I.build("X", [{"feature": "price_momentum", "value": 0.5,
                     "source": "x", "confidence": 1.0, "ts": T0,
                     "expires_at": "never"}], now=T0)["usable"] is False)

print("\n── THE COLLECTOR MUST NOT PUBLISH A DEAD FEED AS A FACT ──")
# Caught live: the calendar provider returned 403, news.high_impact_window()
# fail-opened to None exactly as it does when no event is near, and the
# collector recorded +0.2 "nothing due". That is a dead feed asserting a fact,
# and it RAISED data_quality for a source that knew nothing.
import tempfile  # noqa: E402

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-inst-test-"))
from apex import news, user_loop  # noqa: E402

_IND = {"rsi": 66.9, "ema50": 0.8130, "ema200": 0.8100,
        "macd": 0.0004, "macdSignal": 0.0002, "atr": 0.0006}
_RG = {"regime": "ranging", "vol_ratio": 1.18}
_orig_load = news._load

news._load = lambda: []          # feed down / never fetched
dead = I.build("USDCHF", user_loop._institutional_observations(
    "USDCHF", _IND, _RG, 0.1))
check("a dead calendar contributes NO macro_risk observation",
      "macro_risk" not in dead["features"], str(sorted(dead["features"])))
check("and it is reported as missing", "macro_risk" in dead["missing"])

news._load = lambda: [{"impact": "High", "currency": "USD", "title": "CPI",
                       "time": "2026-09-01T12:00:00Z"}]
alive = I.build("USDCHF", user_loop._institutional_observations(
    "USDCHF", _IND, _RG, 0.1))
check("a live calendar does contribute one",
      "macro_risk" in alive["features"])
check("so a dead feed lowers data_quality instead of inflating it",
      dead["data_quality"] < alive["data_quality"],
      f"dead={dead['data_quality']} alive={alive['data_quality']}")
news._load = _orig_load


# ── describe() must name the features, not just count them ──────────────
# "4/9 features" cannot answer the only question the line is ever read for:
# WHICH four. Diagnosing a missing macro_risk meant reverse-engineering the
# count from the quality percentage against the weight table — twice, and
# wrongly. The names were already in the state.
print("\n── describe() names its coverage ──")

_now = 1000.0
_obs = [
    I.observe("price_momentum", 0.4, "indicators", now=_now),
    I.observe("volatility", -0.03, "regime", now=_now),
    I.observe("macro_risk", 0.2, "calendar", now=_now),
]
_line = I.describe(I.build("USDCHF", _obs, now=_now))
check("the count is still there", "3/9" in _line, _line)
for _f in ("price_momentum", "volatility", "macro_risk"):
    check(f"{_f} is named", _f in _line, _line)
check("an absent feature is not named", "cot_bias" not in _line, _line)
check("the symbol still leads", _line.startswith("USDCHF"), _line)
check("names are listed in FEATURES order",
      _line.index("price_momentum") < _line.index("volatility")
      < _line.index("macro_risk"), _line)

_empty = I.describe(I.build("EURUSD", [], now=_now))
check("no features reads as 'none', not an empty list", "0/9: none" in _empty,
      _empty)
check("and it is still flagged unusable", "UNUSABLE" in _empty, _empty)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL INSTITUTIONAL CHECKS PASSED.")
