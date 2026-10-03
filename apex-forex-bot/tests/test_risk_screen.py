"""The Risk Centre shows the risk engine. It must never become a second one.

Two failures would matter here, and neither is cosmetic.

The first is a screen that computes a limit. There is one risk engine, and a
UI that recalculates "am I within the daily loss" from numbers it happens to
have will eventually disagree with the thing that actually blocks orders —
and the client will believe the screen.

The second is RISK_UNKNOWN drawn as RISK_OK. A risk state we could not read
is not a risk state that is fine, and green is the one colour that must never
be borrowed for it.

There is a third, quieter one: strategies.should_stop() advances the peak
balance and the daily reset as a side effect. Calling it to draw a badge
would move the circuit breakers every time someone opened a screen.

Run: python tests/test_risk_screen.py
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
ROUTE = BOT[BOT.index('if self.path.startswith("/api/app/risk")'):]
ROUTE = ROUTE[:ROUTE.index('if self.path.startswith("/api/app/markets")')]
# Comments explain intent; they are not the behaviour. Strip them before
# asserting anything about what the code does.
CODE = "\n".join(l for l in ROUTE.splitlines() if not l.strip().startswith("#"))

print("\n1. The screen reads the engine, it does not run it")
check("should_stop is never called to draw a badge", "should_stop" not in CODE,
      "it advances peak balance and the daily reset as a side effect")
check("the verdict comes from the engine's published guard", "riskGuard" in CODE)
check("...and from ui_state's own resolution", "risk_state(chat_id)" in CODE)
check("no limit is enforced here", "authorize" not in CODE)
check("no order path is reachable from this route",
      "place_order" not in CODE and "close_position" not in CODE)

print("\n2. Unknown is a third answer")
check("the route reports the engine state verbatim", '"engine": _r_state' in CODE)
# do_GET is one long method and bot.py has a module-level `dash`. A route that
# binds a bare `dash`, `stats` or `state` makes that name local to the WHOLE
# method and breaks every branch above it — this exact bug shipped once and
# took out the dashboard session. Every local these routes introduce is
# prefixed, and that is checked rather than remembered.
_locals = set(re.findall(r'^\s+([a-z][\w]*)\s*=(?!=)', CODE, re.M))
_allowed = {"tg_user", "chat_id", "u"}   # already method-locals in every route
check(f"no route local can shadow the enclosing scope ({sorted(_locals - _allowed)})",
      not (_locals - _allowed),
      "prefix it: a bare name here is an UnboundLocalError somewhere else")
check("it says whether a guard was ever published", '"guardSeen"' in CODE)
check("the screen has a distinct class for unknown", "#rEngine.unk" in HTML)
check("...that is not the OK colour",
      HTML[HTML.index("#rEngine.unk"):HTML.index("#rEngine.unk") + 90].count("47,213,117") == 0,
      "green is reserved for a state we actually read")
check("unknown is worded as unread, not as fine",
      "Risk state could not be read" in HTML)
check("OK is only shown for RISK_OK",
      "d.engine==='RISK_OK' ? 'ok'" in HTML)
check("halted is only shown for RISK_HOLDING",
      "d.engine==='RISK_HOLDING' ? 'halt'" in HTML)

print("\n3. Limits are rendered, never derived")
for field in ("riskPerTradePct", "maxDailyLossPct", "maxDrawdownPct"):
    check(f"{field} comes from the backend", field in CODE and field in HTML)
check("the meter draws a percentage of a limit it was given",
      "function meter(label, used, limit, unit)" in HTML)
check("an unknown value renders as unknown, not as zero",
      "known ? Math.abs(used).toFixed(2)+unit+' / '+limit.toFixed(2)+unit : 'unknown'" in HTML)
check("a missing limit does not fill the bar",
      "const pct = known ? Math.max(0, Math.min(100, (Math.abs(used)/limit)*100)) : 0;" in HTML)

print("\n4. Exposure is real positions, not a guess")
check("it reads the dash's own positions", 'dash.get("positions")' in CODE)
check("USD bias comes from the correlation helper", "usd_exposure" in CODE)
check("a position with no P&L yet shows no number",
      "known?money(e.pnlUsd):'\\u2014'" in HTML or "known?money(e.pnlUsd):'—'" in HTML)
check("no exposure is stated as none, not as zero risk",
      "No open exposure." in HTML)

print("\n5. The route is scoped to an authenticated client")
check("identity is checked first",
      CODE.index("_telegram_identity") < CODE.index("get_dash"))
check("a denied caller is refused", "_telegram_denied" in CODE)
check("a chat id is never taken from the query string",
      "qs.get" not in CODE and "chat_id\"]" not in CODE)
check("the chat id is the one the signature proved",
      'chat_id = str(tg_user["id"])' in CODE)

print("\n6. It is reachable, and it loads when opened")
check("Risk is a navigation destination", 'data-s="risk"' in HTML)
check("...with a screen", 'id="s-risk"' in HTML and 'id="riskBody"' in HTML)
check("...that fetches when shown", "if(name==='risk') loadRisk(true);" in HTML)
check("an unreachable backend says so",
      "Risk state unavailable" in HTML)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL RISK-SCREEN CHECKS PASSED - it renders the engine and never replaces it.")
