"""The AI's reply is a contract, and an unusable reply is not a decision.

`_extract_json` only guarantees the model's text contained *some* JSON object.
Everything after that was trusted, and two real ways a model breaks the
contract were being read as deliberate verdicts:

  * `{"action": "buy"}` — lowercase. It matched neither the rule action
    ("BUY") nor "HOLD", fell through to the contradiction branch, and BLOCKED
    the trade. The model agreed; the bot read agreement as a veto.
  * `{"reasoning": "..."}` with no action — `.get("action", "HOLD")` turned an
    unparseable answer into a confident neutral one, penalty included.

Run: python tests/test_ai_contract.py
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

from apex import ai  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


V = ai._validate_verdict

print("\n── a well-formed verdict passes through ──")
for a in ("BUY", "SELL", "HOLD"):
    check(f"{a} accepted", (V({"action": a}) or {}).get("action") == a)

print("\n── THE INVERSION: casing must not turn agreement into a veto ──")
for spelling in ("buy", "Buy", "BUY ", " buy\n", "bUy"):
    got = V({"action": spelling})
    check(f"{spelling!r} normalises to BUY",
          got is not None and got["action"] == "BUY", str(got))
check("sell likewise", (V({"action": "sell"}) or {})["action"] == "SELL")
check("hold likewise", (V({"action": "hold"}) or {})["action"] == "HOLD")

print("\n── a reply with no usable decision is None, NOT HOLD ──")
check("no action key", V({"reasoning": "looks choppy"}) is None)
check("action is null", V({"action": None}) is None)
check("action is a number", V({"action": 1}) is None)
check("action is a list", V({"action": ["BUY"]}) is None)
check("empty string", V({"action": ""}) is None)
check("a word that is not a decision", V({"action": "MAYBE"}) is None)
check("a sentence", V({"action": "I would buy here"}) is None)
check("empty object", V({}) is None)
check("not a dict at all", V("BUY") is None)
check("None", V(None) is None)
check("a list", V([{"action": "BUY"}]) is None)

print("\n── the distinction that matters ──")
check("an explicit HOLD IS a verdict",
      (V({"action": "HOLD"}) or {}).get("action") == "HOLD")
check("a missing action is NOT a verdict", V({"confidence": 0.9}) is None)
check("...and the two are distinguishable",
      V({"action": "HOLD"}) is not None and V({"confidence": 0.9}) is None)

print("\n── confidence is advisory: bad values drop, never fail the verdict ──")
check("0-1 scale is scaled up",
      V({"action": "BUY", "confidence": 0.8})["confidence"] == 80.0)
check("0-100 scale is kept",
      V({"action": "BUY", "confidence": 80})["confidence"] == 80.0)
check("junk confidence does not reject the verdict",
      V({"action": "BUY", "confidence": "high"})["action"] == "BUY")
check("...and simply carries no confidence",
      "confidence" not in V({"action": "BUY", "confidence": "high"}))
check("missing confidence is fine", V({"action": "BUY"})["action"] == "BUY")

print("\n── reasoning is captured and bounded ──")
check("carried through",
      V({"action": "BUY", "reasoning": "trend up"})["reasoning"] == "trend up")
check("a 5000-char essay is truncated",
      len(V({"action": "BUY", "reasoning": "x" * 5000})["reasoning"]) == 300)
check("non-string reasoning does not crash",
      V({"action": "BUY", "reasoning": {"a": 1}})["action"] == "BUY")

print("\n── the provider is skipped entirely when no key is configured ──")
# This block used to assert the same property for Anthropic. Anthropic was
# removed: its key was never set on this deployment, so every call raised and
# fell through to Groq anyway. Groq is now the only provider, and the property
# still has to hold — fail before the network, with a reason.
_orig = ai.cfg.GROQ_API_KEY
ai.cfg.GROQ_API_KEY = ""
try:
    ai._call_groq("hi")
    check("raises without a key", False, "no exception")
except RuntimeError as e:
    check("raises without a key", True)
    check("and says why, before any network attempt",
          "GROQ_API_KEY" in str(e), str(e))
except Exception as e:
    check("raises a RuntimeError, not an SDK error", False, repr(e))
ai.cfg.GROQ_API_KEY = _orig

print("\n── end to end through get_signal ──")
_calls = {"n": 0}


def fake_ai(prompt):
    _calls["n"] += 1
    return {"action": "buy", "reasoning": "agrees"}


_og = ai._call_groq
ai._call_groq = fake_ai
ai.cfg.GROQ_API_KEY = "test-key"

# Build the indicator bundle from the real analyzer rather than hand-rolling
# it: the prompt reads a couple of dozen keys and a literal dict silently rots
# every time one is added. Nudged into a textbook oversold fade so the rule
# engine produces BUY and the AI layer is actually reached.
from apex import indicators, strategies  # noqa: E402


def _candles(prices):
    out = []
    for i, p in enumerate(prices):
        out.append({"time": 1_700_000_000 + i * 900, "open": p, "high": p + 0.05,
                    "low": p - 0.05, "close": p, "volume": 1000})
    return out


_c = _candles([100 + i * 0.1 for i in range(240)])
IND = dict(indicators.analyze(_c))
STRAT = strategies.analyze(_c)
IND.update(bb_position=8, rsi=27, stochRsiK=12, bb_bandwidth=1.2,
           ema50=IND["price"], ema200=IND["price"])
check("fixture drives the rule engine to BUY (the AI layer is reachable)",
      ai.signal_for_mode("mean_reversion", IND, STRAT, None)["action"] == "BUY")

sig = ai.get_signal(IND, 3000.0, None, STRAT, mode="mean_reversion",
                    symbol="EURUSD", timeframe="15m")
check("a lowercase agreement is NOT treated as a block",
      "blockedAction" not in sig, str(sig.get("action")))
check("the AI was actually consulted", _calls["n"] > 0)


def junk_ai(prompt):
    return {"thoughts": "hmm"}


ai._call_groq = junk_ai
sig2 = ai.get_signal(IND, 3000.0, None, STRAT, mode="mean_reversion",
                     symbol="EURUSD", timeframe="15m")
check("a verdict-less reply does not silently become a block",
      "blockedAction" not in sig2, str(sig2.get("action")))
check("and does not earn an 'AI confirms' factor it never gave",
      "AI confirms" not in (sig2.get("keyFactors") or []))

ai._call_groq = _og
ai.cfg.GROQ_API_KEY = _orig

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL AI-CONTRACT CHECKS PASSED.")
