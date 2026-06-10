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
check("returns HOLD", sig["action"] == "HOLD", sig)
check("confidence 0 (never trades on error)", sig["confidence"] == 0, sig)
check("riskLevel HIGH", sig["riskLevel"] == "HIGH", sig)

ai._call_anthropic, ai._call_groq = _orig_anthropic, _orig_groq

# ─── Provider preference ──────────────────────────────────
print("\n3. provider order (Anthropic first, Groq fallback)")
calls = []
ai._call_anthropic = lambda p: (calls.append("anthropic"),
                                {"action": "BUY", "confidence": 75})[1]
ai._call_groq = lambda p: (calls.append("groq"), {"action": "SELL", "confidence": 70})[1]
sig = ai.get_signal(ind, 1000.0, None, strat)
check("uses Anthropic when available", sig["action"] == "BUY" and calls == ["anthropic"], calls)

calls.clear()
ai._call_anthropic = _boom
sig = ai.get_signal(ind, 1000.0, None, strat)
check("falls back to Groq when Anthropic fails", sig["action"] == "SELL" and calls == ["groq"], calls)
ai._call_anthropic, ai._call_groq = _orig_anthropic, _orig_groq

# ─── Prompt content ───────────────────────────────────────
print("\n4. prompt includes full strategy context")
captured = {}


def _capture(prompt):
    captured["prompt"] = prompt
    return {"action": "HOLD", "confidence": 0}


ai._call_anthropic = _capture
ai.get_signal(ind, 1234.56, None, strat)
p = captured["prompt"]
for section in ("Turtle Trading", "Jesse Livermore", "George Soros",
                "Mean Reversion", "Ed Seykota", "RSI (14)", "MACD Histogram",
                "$1234.56"):
    check(f"prompt mentions {section!r}", section in p)
ai._call_anthropic = _orig_anthropic

print("\n5. prompt shows open position")
ai._call_anthropic = _capture
ai.get_signal(ind, 1000.0,
              {"side": "BUY", "entryPrice": 95.5, "pnlPct": 2.34}, strat)
check("position rendered in prompt", "BUY @ $95.5" in captured["prompt"]
      and "2.34%" in captured["prompt"])
ai._call_anthropic = _orig_anthropic

# ─── Legendary section robustness ─────────────────────────
print("\n6. _legendary_section edge cases")
check("empty strategy data → empty string", ai._legendary_section(None) == "")
sec = ai._legendary_section(strat)
check("renders without crashing", "LEGENDARY TRADERS ANALYSIS" in sec)

# ─── Result ───────────────────────────────────────────────
print("\n" + "=" * 50)
if check.failed == 0:
    print("✅ ALL TESTS PASSED — AI signal layer works.")
    sys.exit(0)
print(f"❌ {check.failed} CHECK(S) FAILED.")
sys.exit(1)
