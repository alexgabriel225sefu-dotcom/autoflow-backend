"""Intelligence must not merge four different claims into one.

The brief is unusually specific about this, and it is specific because the
failure is subtle. A screen that shows "BULLISH" without saying whether that is

  what the market shows,        an observation
  what the strategy detected,   a signal
  whether trading is allowed,   a risk state
  or what APEX actually did,    a decision

lets a reader take the weakest of the four as the strongest. A market reading is
not a signal. A signal is not a decision. A decision that was never recorded is
not a decision that was never made.

The second failure guarded here is a fabricated number. A confidence score
rendered beside four real fields is indistinguishable from a fifth real field,
and the brief forbids presenting confidence as a probability of winning unless
a calibrated model exists. This platform's model is still collecting samples,
so no win probability may appear at all.

Run: python tests/test_intelligence_screen.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()
ROUTE = BOT[BOT.index('if self.path.startswith("/api/app/intelligence")'):]
ROUTE = ROUTE[:ROUTE.index('if self.path.startswith("/api/app/risk")')]
CODE = "\n".join(l for l in ROUTE.splitlines() if not l.strip().startswith("#"))

print("\n1. The four concepts stay apart")
for key in ('"market"', '"strategy"', '"risk"', '"decision"'):
    check(f"the payload has its own {key} block", key in CODE)
# Asserted as the rendered markup, not the bare phrase. A loose phrase can
# also occur in a Python comment somewhere in the package, which makes the
# assertion ambiguous about what it is checking — and test_prose_assertions
# is right to flag that.
for _label in ("Market observation", "Strategy observation",
               "Risk state", "APEX decision"):
    check(f"the screen renders a {_label!r} block",
          f">{_label}</div>" in HTML)

print("\n2. Nothing is computed for display")
check("no scoring happens in the route",
      not re.search(r"(score|confidence)\s*=", CODE, re.I),
      "a score invented here would be indistinguishable from a measured one")
check("market data is read, not derived", '_n_dash.get("market")' in CODE)
check("regime is read, not derived", '_n_dash.get("regime")' in CODE)
check("risk comes from the engine's own resolution", "risk_state(_n_chat)" in CODE)
check("should_stop is never called", "should_stop" not in CODE,
      "it advances the peak balance and daily reset as a side effect")
check("no order path is reachable",
      not any(x in CODE for x in ("place_order", "force_close", "authorize_order")))

print("\n3. A missing value says so")
check("null fields render as unavailable", 'class="na">Not available' in HTML)
check("no platform state is stated, not blanked", "NO_PLATFORM_STATE" in CODE)
check("...and the screen words it as unavailable",
      "APEX Intelligence is unavailable" in HTML)

print("\n4. Unrecorded is not the same as nothing happened")
check("the payload reports whether a decision was recorded", '"recorded": bool' in CODE)
check("refusals come from the decision log", "_n_te.declines(" in CODE)
check("an empty log is worded as unrecorded, not as no reason",
      "No recorded APEX decision for this instrument yet" in HTML)
check("...and says explanations are not reconstructed",
      "nothing is reconstructed afterwards" in HTML)
check("each recorded refusal shows the strategy version that refused",
      "ev.strategy_version" in HTML,
      "an explanation without its version cannot be trusted after a strategy change")

print("\n5. No win probability is claimed")
# Worded as the CLAIM, not as the words. The disclaimer this screen carries —
# "No win probability is shown until it is measured" — contains the same nouns
# as the thing being forbidden, so a phrase match flags the sentence that
# promises not to make the claim. What must not appear is a number presented
# as odds.
check("no number is presented as odds of winning",
      not re.search(r"\d\s*%?\s*(chance|probability) of (winning|profit)", HTML, re.I)
      and "chance of winning" not in HTML.lower())
check("...and confidence is never labelled a win rate",
      not re.search(r"confidence[^<]{0,20}(chance|odds)", HTML, re.I))
check("calibration state is surfaced instead", "evCalibration" in CODE and "evCalibration" in HTML)
check("...worded as still calibrating",
      "Probability model is still" in HTML and "No win probability is" in HTML)

print("\n6. A reading is never shown under the wrong symbol")
check("the route reports whether this is the watched instrument", '"isFocus"' in CODE)
check("...and the screen says so when it is not",
      "instrument the platform is currently watching" in HTML)

print("\n7. Scoped to the authenticated client")
check("identity is checked before any state read",
      CODE.index("_telegram_identity") < CODE.index("get_dash"))
check("a denied caller is refused", "_telegram_denied" in CODE)
check("the chat id is the one the signature proved",
      '_n_chat = str(_n_user["id"])' in CODE)
check("a symbol from the query is clamped, and is only a filter",
      '[:16]' in CODE and "chat" not in CODE.split("_n_sym =")[1].split("\n")[0])

print("\n8. Reachable, and no local can shadow the enclosing scope")
check("Insight is a navigation destination", 'data-s="intelligence"' in HTML)
check("...with a screen", 'id="s-intelligence"' in HTML and 'id="intelBody"' in HTML)
check("...that loads when opened", "if(name==='intelligence') loadIntel(true);" in HTML)
_locals = set(re.findall(r'^\s+([a-z][\w]*)\s*=(?!=)', CODE, re.M))
check(f"every route local is prefixed ({sorted(_locals)})", not _locals,
      "do_GET shares a scope; a bare name here breaks a branch elsewhere")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL INTELLIGENCE CHECKS PASSED - four claims, kept apart, none invented.")
