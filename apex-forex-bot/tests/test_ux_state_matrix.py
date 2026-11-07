"""Eight states, one bot, and nothing invented to fill a gap.

The screens used to answer "what is going on" from whatever happened to be in
the record: a balance key that was never written printed $0.00, a risk guard
that had not reported printed nothing at all, and Full Automation was drawn as
running on an account whose entitlement could not be read — where the gate was
about to refuse every order it produced.

What this pins:

  * each of the eight states A–H resolves to itself and to its own screen;
  * a live account missing a critical prerequisite does not offer new live
    orders, and says why in words a client can act on;
  * "🟢/🚀 Full Automation" is never rendered as active while entitlement is
    unknown — the setting is shown, the claim is not;
  * a missing number is a blank, never a zero;
  * no screen leaks `entitlement`, `oauth_state`, `redis`, `None` or a
    traceback into a client's chat.

Scenarios covered here (of the 30): unknown entitlement · risk unavailable ·
paused · emergency · the three automation modes · missing financial data ·
navigation and back.

Run: python tests/test_ux_state_matrix.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from apex import screens, ui_state as U  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} — {detail}")
        failures.append(name)


def state(**over):
    """A UiState built directly, so every combination is reachable."""
    base = dict(chat_id="1", user={}, env=U.DEMO, proven=True,
                env_detail="confirmed by the account you connected",
                connected=True, simulating=True, entitlement="allowed",
                entitlement_why="granted", risk=U.RISK_OK, risk_reasons=[],
                running=True, emergency=False, automation="approval")
    base.update(over)
    return U.UiState(**base)


LIVE = dict(env=U.LIVE, simulating=False)

print("\n🧪 STATE MATRIX — eight states, and no comfortable defaults\n")

print("1. Every state resolves to itself")
cases = [
    ("A", state()),
    ("B", state(**LIVE)),
    ("C", state(entitlement="unknown", **LIVE)),
    ("D", state(risk=U.RISK_UNKNOWN, **LIVE)),
    ("E", state(connected=False, **LIVE)),
    ("F", state(connected=False)),
    ("G", state(running=False)),
    ("H", state(emergency=True)),
]
for want, st in cases:
    check(f"state {want}", st.state == want, st.state)

print("\n2. Every state has a header block and a way out")
for want, st in cases:
    title, body = screens.home_head(st)
    check(f"state {want} has a title", bool(title.strip()), repr(title))
    check(f"state {want} has a body", len(body) > 40, repr(body[:60]))
    rows = screens.home_rows(st)
    flat = [c for row in rows for _l, c in row]
    check(f"state {want} has ← Back or ☰ Menu",
          any(c in ("nav:menu", "nav:home") or c.startswith("nav:") for c in flat),
          str(flat))
    check(f"state {want} shows the environment badge",
          st.env_badge in screens.home(st), screens.home(st)[:100])

print("\n3. Scenario: LIVE + entitlement unknown (state C)")
c = state(entitlement="unknown", **LIVE)
check("new live orders are NOT offered", c.live_orders_offered is False)
body = screens.home(c)
check("the screen says new real-money trades are switched off",
      "switched off" in body, body[-300:])
check("it never prints the word 'entitlement'", "entitlement" not in body.lower(),
      body)
check("it never prints UNKNOWN as a token", "UNKNOWN" not in body, body)
check("it offers a re-check button",
      "acct:recheck" in [x for r in screens.home_rows(c) for _l, x in r])
check("a demo account with the same unknown is unaffected",
      state(entitlement="unknown").state == "A")

print("\n3b. An UNIDENTIFIED account never falls through to the demo screen")
# Found by driving the real screen rather than the state object: an account
# badged 🟠 VERIFICATION REQUIRED resolved to state A and was handed the demo
# header — "nothing here can cost you anything", written over an account we
# could not identify. That sentence is only true if it is a simulation, and
# not knowing is precisely the case where we cannot say so.
unk = state(env=U.UNKNOWN, proven=False,
            env_detail="your broker has not confirmed this account")
check("an unknown environment is not state A", unk.state != "A", unk.state)
check("it is the verification state", unk.state == "C", unk.state)
title, body = screens.home_head(unk)
check("its header does not say Demo trading", "Demo trading" not in title, title)
check("and does not promise nothing can be lost",
      "cost you anything" not in body, body)
check("it says we could not confirm demo or real money",
      "demo or real money" in body, body)
full = screens.home(unk)
check("the screen still warns that new positions are switched off",
      "switched off" in full, full[-300:])

print("\n4. Scenario: LIVE + risk unavailable (state D)")
d = state(risk=U.RISK_UNKNOWN, **LIVE)
check("new live orders are NOT offered", d.live_orders_offered is False)
check("the risk line does not claim the guard is active",
      "active" not in screens.banner(d), screens.banner(d))
check("it says no report yet instead", "no report yet" in screens.banner(d),
      screens.banner(d))
check("a HOLDING guard keeps its reason",
      "daily loss cap" in screens.banner(
          state(risk=U.RISK_HOLDING, risk_reasons=["daily loss cap"], **LIVE)))

print("\n5. The critical rule: unknown live state disables new live orders")
for label, st in (("entitlement unknown", state(entitlement="unknown", **LIVE)),
                  ("entitlement denied", state(entitlement="denied", **LIVE)),
                  ("risk not reported", state(risk=U.RISK_UNKNOWN, **LIVE)),
                  ("risk holding", state(risk=U.RISK_HOLDING, **LIVE)),
                  ("account unproven", state(proven=False, **LIVE)),
                  ("environment unknown", state(env=U.UNKNOWN, proven=False)),
                  ("disconnected", state(connected=False, **LIVE)),
                  ("emergency hold", state(emergency=True, **LIVE))):
    check(f"{label} → live orders not offered", st.live_orders_offered is False)
check("a fully known, entitled, connected live account DOES offer them",
      state(**LIVE).live_orders_offered is True)

print("\n6. Full Automation is never rendered as running while a fact is missing")
for label, st in (("entitlement unknown",
                   state(automation="full", entitlement="unknown", **LIVE)),
                  ("risk not reported",
                   state(automation="full", risk=U.RISK_UNKNOWN, **LIVE)),
                  ("emergency", state(automation="full", emergency=True, **LIVE)),
                  ("bot off", state(automation="full", running=False, **LIVE))):
    lbl = U.automation_label(st)
    check(f"{label}: the level is still shown", "Full Automation" in lbl, lbl)
    check(f"{label}: but it is marked held", "⏸" in lbl, lbl)
ok = U.automation_label(state(automation="full", **LIVE))
check("an entitled, known live account shows it plainly", "⏸" not in ok, ok)
check("and a connected demo account does too",
      "⏸" not in U.automation_label(state(automation="full")),
      U.automation_label(state(automation="full")))

print("\n7. The three automation modes each say what they do")
from apex import automation  # noqa: E402
for m in automation.MODES:
    lbl = U.automation_label(state(automation=m))
    check(f"{m} renders", bool(lbl.strip()), lbl)
check("signals says it places nothing",
      "place" in automation.BLURB["signals"].lower())
check("approval says nothing opens without a tap",
      "approve" in automation.BLURB["approval"].lower())
check("full says it opens on its own", "own" in automation.BLURB["full"].lower())
check("only full actually executes",
      automation.EXECUTES == {"signals": False, "approval": False, "full": True},
      str(automation.EXECUTES))

print("\n8. Scenario: paused (G) and emergency (H) are different screens")
g_title, g_body = screens.home_head(state(running=False))
h_title, h_body = screens.home_head(state(emergency=True))
check("they do not share a title", g_title != h_title, g_title)
check("paused says open positions keep their stops",
      "stop" in g_body.lower(), g_body)
check("emergency says nothing new will open",
      "no new positions" in h_body.lower(), h_body)
check("both offer Resume",
      "nav:resume" in [c for r in screens.home_rows(state(running=False)) for _l, c in r]
      and "nav:resume" in [c for r in screens.home_rows(state(emergency=True)) for _l, c in r])

print("\n9. Scenario: missing financial data is a blank, never a zero")
check("a missing balance is not $0.00",
      "0.00" not in screens._fmt_money(None), screens._fmt_money(None))
check("it says not available", "not available" in screens._fmt_money(None))
check("a real zero balance still prints",
      screens._fmt_money(0.0) == "$0.00", screens._fmt_money(0.0))
check("a string balance is refused rather than formatted",
      "not available" in screens._fmt_money("—"))
body = screens.home(state(), balance=None, open_count=None)
check("an unreported position count is not shown as 0",
      "Open positions: <b>0</b>" not in body, body)
check("it says not reported yet", "not reported yet" in body, body)
u = screens.unavailable(state(), "Performance")
check("the unavailable screen refuses to invent a figure",
      "made-up" in u, u)

print("\n10. Customer language only — no internals reach a chat")
BANNED = ("entitlement", "oauth", "redis", "traceback", "Exception",
          "NoneType", "user_store", "authorize_order", "riskGuard")
texts = []
for _w, st in cases:
    texts += [screens.home(st), screens.banner(st), screens.account(st),
              screens.order_unknown(st), screens.close_unknown(st),
              screens.close_confirm(st, "EUR_USD"),
              screens.position_detail(st, {"symbol": "EUR_USD", "side": "BUY"}),
              screens.unavailable(st, "Performance"), screens.stale_action()]
for t in texts:
    for word in BANNED:
        if word.lower() in t.lower():
            check(f"no '{word}' in a client-facing screen", False, t[:160])
            break
    else:
        continue
    break
else:
    check("no internal vocabulary in any of the screens", True)
check("no bare 'None' rendered into a screen",
      not any(">None<" in t or " None " in t for t in texts))

print("\n11. Navigation: no screen is a dead end")
row_sets = [screens.home_rows(st) for _w, st in cases]
row_sets += [screens.account_rows(state()), screens.order_unknown_rows(),
             screens.close_confirm_rows("ABC123"),
             screens.account_switch([{"ctid": 1, "live": True}], 1)[1]]
for rows in row_sets:
    flat = [c for row in rows for _l, c in row]
    check("has a Menu or Back", any(c in ("nav:menu", "nav:acct", "nav:pos")
                                    for c in flat), str(flat))
    check("every callback is well-formed",
          all(":" in c and len(c) <= 64 for c in flat), str(flat))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ STATE MATRIX HOLDS — unknown is never rendered as fine.")
