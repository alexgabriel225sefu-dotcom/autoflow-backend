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
_orig_anthropic, _orig_groq = ai._call_anthropic, ai._call_groq


def _boom(prompt):
    raise RuntimeError("provider down")


ai._call_anthropic = _boom
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

ai._call_anthropic, ai._call_groq = _orig_anthropic, _orig_groq

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

# ─── Provider preference ──────────────────────────────────
print("\n3. provider order (Anthropic first, Groq fallback)")
calls = []
ai._call_anthropic = lambda p: (calls.append("anthropic"),
                                {"action": "BUY", "confidence": 75})[1]
ai._call_groq = lambda p: (calls.append("groq"), {"action": "SELL", "confidence": 70})[1]
sig = ai.get_signal(buy_ind, 1000.0, None, strat)
check("uses Anthropic when available", sig["action"] == "BUY" and calls == ["anthropic"], calls)

calls.clear()
ai._call_anthropic = _boom
sig = ai.get_signal(buy_ind, 1000.0, None, strat)
check("falls back to Groq when Anthropic fails", calls == ["groq"], calls)
# Groq answers SELL into a rule-engine BUY. The AI holds a veto, not a vote:
# a contradiction must block the entry, never flip its direction. (The old
# test expected sig["action"] == "SELL" — that would mean a provider outage
# could reverse a live trade's direction.)
check("AI contradiction blocks rather than reverses", sig["action"] == "HOLD", sig)
ai._call_anthropic, ai._call_groq = _orig_anthropic, _orig_groq

# ─── Prompt content ───────────────────────────────────────
print("\n4. prompt includes full strategy context")
captured = {}


def _capture(prompt):
    captured["prompt"] = prompt
    return {"action": "HOLD", "confidence": 0}


ai._call_anthropic = _capture
ai.get_signal(buy_ind, 1234.56, None, strat)
p = captured["prompt"]
# The forex signal layer is a dedicated MEAN-REVERSION strategy (fade BB/RSI
# extremes) — not the crypto bot's "legendary traders" framing. Assert the
# real prompt contract so the test reflects what actually ships.
for section in ("MEAN REVERSION", "Bollinger Bands", "Stoch RSI", "TREND GUARD",
                "RSI (14)", "MACD Histogram",
                "$1234.56", "FOREX", "Active sessions", "pips"):
    check(f"prompt mentions {section!r}", section in p)
ai._call_anthropic = _orig_anthropic

print("\n5. AI is never consulted while a position is open")
# Every engine returns HOLD or CLOSE once open_position is set, so get_signal
# returns before it ever builds a prompt. That makes the prompt's
# open-position block unreachable — the old check here asserted output the AI
# can no longer receive. The invariant worth locking is the stronger one:
# an open trade is managed by SL/TP and the rule engine alone, so a slow or
# misbehaving LLM can never touch a position that already has money in it.
captured.clear()
ai._call_anthropic = _capture
for _mode in ai.STRATEGY_MODES:
    ai.get_signal(buy_ind, 1000.0,
                  {"side": "BUY", "entryPrice": 1.0855, "pnlPips": 12.3},
                  strat, mode=_mode)
check(f"no provider call in any of the {len(ai.STRATEGY_MODES)} modes while in a trade",
      "prompt" not in captured, list(captured))
ai._call_anthropic = _orig_anthropic

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — AI signal layer works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
