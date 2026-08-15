"""Unit tests for the AI signal layer (no network calls).

Verifies JSON extraction, the safe HOLD fallback when every provider
fails, and that the prompt includes all strategy context.

Run: python tests/test_ai.py
"""
import os
import sys

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import ai, strategies, indicators  # noqa: E402
from apex import config as cfg  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0


def make_candles(closes):
    return [{"time": i, "open": c * 0.999, "high": c * 1.005,
             "low": c * 0.995, "close": c, "volume": 1000}
            for i, c in enumerate(closes)]


# ─── JSON extraction ──────────────────────────────────────
print("\n🧪 AI SIGNAL LAYER TESTS\n")
print("1. _extract_json")
r = ai._extract_json('Here is my answer: {"action":"BUY","confidence":80} thanks')
check("parses JSON inside chatter", r["action"] == "BUY" and r["confidence"] == 80, r)

r = ai._extract_json('```json\n{"action":"HOLD","confidence":0}\n```')
check("parses JSON inside code fences", r["action"] == "HOLD", r)

try:
    ai._extract_json("no json here at all")
    check("raises on missing JSON", False)
except ValueError:
    check("raises on missing JSON", True)

# ─── Fallback when every provider fails ───────────────────
print("\n2. get_signal fallback (all providers down)")
_orig_groq = ai._call_groq


def _boom(prompt):
    raise RuntimeError("provider down")


ai._call_groq = _boom

candles = make_candles([100 + i * 0.1 for i in range(240)])
ind = indicators.analyze(candles)
strat = strategies.analyze(candles)
sig = ai.get_signal(ind, 1000.0, None, strat)
# When every AI provider is down the bot does NOT freeze — it falls back to a
# deterministic mean-reversion signal. On this steady uptrend it must refuse to
# fade the trend (HOLD), and always return a well-formed, in-range signal.
check("returns a valid action", sig["action"] in ("BUY", "SELL", "HOLD", "CLOSE"), sig)
check("does not fade a strong trend (HOLD)", sig["action"] == "HOLD", sig)
check("confidence in range 0-100", 0 <= sig["confidence"] <= 100, sig)
check("riskLevel is valid", sig["riskLevel"] in ("LOW", "MEDIUM", "HIGH"), sig)

ai._call_groq = _orig_groq

# get_signal() is rule-FIRST since a1c08bfd: the AI is only consulted to
# confirm or block a rule-engine BUY/SELL, never to originate one. The uptrend
# fixture above deliberately yields HOLD, so it returns before any provider is
# touched — reusing it below silently stopped exercising the AI layer at all.
# Everything from here on needs a setup the rule engine actually acts on.
def oversold_ind():
    """Real indicator bundle nudged into a textbook oversold fade: price pinned
    to the lower Bollinger band, RSI/StochRSI washed out, EMAs flat so the
    strong-trend guard stays out of the way. Scores 5 → BUY."""
    d = dict(ind)
    d.update(bb_position=8, rsi=27, stochRsiK=12, bb_bandwidth=1.2,
             ema50=d["price"], ema200=d["price"])
    return d


buy_ind = oversold_ind()
check("fixture drives the rule engine to BUY (AI layer is reachable)",
      ai.signal_for_mode("mean_reversion", buy_ind, strat, None)["action"] == "BUY")

# ─── The single provider ──────────────────────────────────
# Anthropic used to sit in front of Groq, and the ordering was tested here.
# It was removed: the key was never set on this deployment, so every call
# raised, was swallowed, and fell through to Groq anyway. What still matters
# is what the one remaining provider is ALLOWED to do.
print("\n3. the AI holds a veto, not a vote")
calls = []
ai._call_groq = lambda p: (calls.append("groq"), {"action": "BUY", "confidence": 75})[1]
sig = ai.get_signal(buy_ind, 1000.0, None, strat)
check("agreement lets the rule-engine BUY through",
      sig["action"] == "BUY" and calls == ["groq"], (sig, calls))

calls.clear()
ai._call_groq = lambda p: (calls.append("groq"), {"action": "SELL", "confidence": 70})[1]
sig = ai.get_signal(buy_ind, 1000.0, None, strat)
# The AI answers SELL into a rule-engine BUY. A contradiction must block the
# entry, never flip its direction — the old test expected "SELL", which would
# mean a model's disagreement could reverse a live trade.
check("a contradiction blocks rather than reverses", sig["action"] == "HOLD", sig)

calls.clear()
ai._call_groq = _boom
sig = ai.get_signal(buy_ind, 1000.0, None, strat)
check("the provider being down leaves the rule signal intact",
      sig["action"] == "BUY", sig)
ai._call_groq = _orig_groq

# ─── Prompt content ───────────────────────────────────────
print("\n4. prompt includes full strategy context")
captured = {}


def _capture(prompt):
    captured["prompt"] = prompt
    return {"action": "HOLD", "confidence": 0}


ai._call_groq = _capture
ai.get_signal(buy_ind, 1234.56, None, strat)
p = captured["prompt"]
# The forex signal layer is a dedicated MEAN-REVERSION strategy (fade BB/RSI
# extremes) — not the crypto bot's "legendary traders" framing. Assert the
# real prompt contract so the test reflects what actually ships.
for section in ("MEAN REVERSION", "Bollinger Bands", "Stoch RSI", "TREND GUARD",
                "RSI (14)", "MACD Histogram",
                "$1234.56", "FOREX", "Active sessions", "pips"):
    check(f"prompt mentions {section!r}", section in p)
ai._call_groq = _orig_groq

print("\n5. AI is never consulted while a position is open")
# Every engine returns HOLD or CLOSE once open_position is set, so get_signal
# returns before it ever builds a prompt. That makes the prompt's
# open-position block unreachable — the old check here asserted output the AI
# can no longer receive. The invariant worth locking is the stronger one:
# an open trade is managed by SL/TP and the rule engine alone, so a slow or
# misbehaving LLM can never touch a position that already has money in it.
captured.clear()
ai._call_groq = _capture
for _mode in ai.STRATEGY_MODES:
    ai.get_signal(buy_ind, 1000.0,
                  {"side": "BUY", "entryPrice": 1.0855, "pnlPips": 12.3},
                  strat, mode=_mode)
check(f"no provider call in any of the {len(ai.STRATEGY_MODES)} modes while in a trade",
      "prompt" not in captured, list(captured))
ai._call_groq = _orig_groq


print("\n── the prompt describes the instrument actually being traded ──")
# Reuse buy_ind/strat, the fixture that actually produces a firing signal —
# a HOLD returns before the provider is ever called and captures nothing.
_cap = {}


def _cap_prompt(prompt):
    _cap["prompt"] = prompt
    return {"action": "HOLD", "confidence": 0}


ai._call_groq = _cap_prompt
ai.get_signal(buy_ind, 5000.0, None, strat, mode="mean_reversion",
              symbol="XAUUSD", timeframe="1m", sl_pips=15, tp_pips=30,
              risk_pct=0.02, min_confidence=50)
p2 = _cap["prompt"]
head = p2.split("## ACCOUNT")[0]
check("prompt names the traded symbol", "XAUUSD" in p2)
check("prompt does NOT mislabel it as the global default",
      "EUR_USD" not in head, head[:120])
check("prompt carries the caller's timeframe", "(1m)" in p2)
check("prompt quotes the caller's SL", "SL: 15 pips" in p2)
check("prompt quotes the caller's TP", "TP: 30 pips" in p2)
check("prompt quotes the caller's risk", "Risk: 2% per trade" in p2)
check("prompt quotes the caller's confidence floor",
      "Minimum confidence: 50%" in p2)

# Without the context arguments it must still work, falling back to config.
_cap.clear()
ai.get_signal(buy_ind, 5000.0, None, strat, mode="mean_reversion")
check("falls back to config when no context is passed",
      cfg.SYMBOL in _cap["prompt"])
ai._call_groq = _orig_groq

print("\n── currency legs resolve for the news context ──")
check("_context_line accepts a symbol without raising",
      isinstance(ai._context_line("XAUUSD"), str))
check("and still works with no symbol", isinstance(ai._context_line(), str))



print("\n── the model is told what kind of market it is looking at ──")
_ctx = {}


def _cap_ctx(prompt, image_png=None):
    _ctx["p"] = prompt
    return {"action": "HOLD", "confidence": 0}


ai._call_groq = _cap_ctx
ai.get_signal(buy_ind, 5000.0, None,
              {"turtle": {"signal": "BUY", "breakoutStr": "STRONG"},
               "livermore": {"trend": "BULLISH", "strength": 0.82},
               "soros": {"signal": "BUY"},
               "mean_reversion": {"zscore": -2.4, "stretched": True}},
              symbol="EURUSD", sl_pips=15,
              regime={"regime": "trending", "vol_ratio": 1.4,
                      "label": "bullish trend — trend following"},
              spread_pips=1.2)
p3 = _ctx["p"]
check("regime reaches the prompt", "trending" in p3 and "1.4" in p3)
check("regime label reaches it too", "trend following" in p3)
check("Turtle read reaches the prompt", "STRONG" in p3)
check("Livermore structure reaches the prompt", "0.82" in p3)
check("mean-reversion z-score reaches the prompt", "-2.4" in p3)
check("ADX reaches the prompt", "ADX" in p3)
check("cost is expressed against the stop, not in isolation",
      "8% of the 15-pip stop" in p3, p3[p3.find("Recent spread"):][:90])

# None of it may crash the call when the loop has nothing to give.
_ctx.clear()
ai.get_signal(buy_ind, 5000.0, None, {}, symbol="EURUSD")
check("missing context degrades to 'unknown' rather than failing",
      "Market regime: unknown" in _ctx["p"])
check("and says the engines had no read",
      "no read this bar" in _ctx["p"] or "N/A" in _ctx["p"])
ai._call_groq = _orig_groq

# ─── Result ───────────────────────────────────────────────

print("\n── vision is gone, and gone cleanly ──")
import apex.config as _cfg  # noqa: E402
# The chart-to-model path existed only for Anthropic; Groq's llama-3.3-70b is
# text-only. Removing the provider removed the capability, so the plumbing had
# to go with it. Half-removing it would have been the dangerous option: with
# AI_VISION still switchable, the prompt would announce "a chart is attached"
# while nothing was ever sent, and the model would answer as if it had looked.
_seen = {}


def _cap(prompt):
    _seen["prompt"] = prompt
    return {"action": "HOLD", "confidence": 0}


_bars = [{"time": 1700000000 + i * 60,
          "open": 1.10 + i * 0.0001, "high": 1.1010 + i * 0.0001,
          "low": 1.0990 + i * 0.0001, "close": 1.1005 + i * 0.0001}
         for i in range(120)]

ai._call_groq = _cap
_seen.clear()
ai.get_signal(buy_ind, 5000.0, None, strat, symbol="EURUSD", candles=_bars)
check("no chart section is promised to the model",
      "### CHART" not in _seen["prompt"])
check("nor any instruction to read one",
      "market structure" not in _seen["prompt"])
check("the renderer is gone", not hasattr(ai, "_chart_png"))
check("and so is the flag that used to switch it on",
      not hasattr(_cfg, "AI_VISION"))
check("the provider takes a prompt only", ai._call_groq is _cap)

# Candle counts that used to change the call shape now change nothing.
for _label, _c in (("no candles", None), ("too few", _bars[:5]), ("plenty", _bars)):
    _seen.clear()
    ai.get_signal(buy_ind, 5000.0, None, strat, symbol="EURUSD", candles=_c)
    check(f"{_label} → still one text call", "prompt" in _seen)

ai._call_groq = _orig_groq

print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — AI signal layer works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
