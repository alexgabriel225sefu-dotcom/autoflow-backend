"""The account screen shows identity. It must never show credentials.

A broker access token on a screen is a token in a screenshot, and a screenshot
is the one place a client will share without thinking. So the account payload
carries what identifies the account and nothing that could be used to reach it.

The alerts screen has the opposite failure mode: it is assembled from the
decision log, and an empty log means nothing was RECORDED — not that nothing
happened. Rendering emptiness as "all quiet" would be the same fabrication the
Intelligence screen is forbidden to make.

Run: python tests/test_account_alerts.py
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
ACC = BOT[BOT.index('if self.path.startswith("/api/app/account")'):]
ACC = ACC[:ACC.index('if self.path.startswith("/api/app/alerts")')]
ALR = BOT[BOT.index('if self.path.startswith("/api/app/alerts")'):]
ALR = ALR[:ALR.index('if self.path.startswith("/api/app/stream")')]
ACCC = "\n".join(l for l in ACC.splitlines() if not l.strip().startswith("#"))
ALRC = "\n".join(l for l in ALR.splitlines() if not l.strip().startswith("#"))

print("\n1. No credential leaves the server")
for secret in ("ctrader_access_token", "ctrader_refresh_token", "access_token",
               "refresh_token", "ctrader_accounts", "groq_key", "gemini_key",
               "voice_token_hash", "TOKEN_ENCRYPTION_KEY"):
    check(f"{secret} is never sent", secret not in ACCC,
          "a token on a screen is a token in a screenshot")
check("the account number is masked, not sent whole",
      '"••••" + _c_num[-4:]' in ACCC,
      "enough to tell two accounts apart, and no more")
check("...and the mask keeps only four digits", "[-4:]" in ACCC)

print("\n2. The environment comes from the server's own resolution")
check("ui_state.environment resolves it", "_c_ui.environment(_c_rec)" in ACCC)
check("account_mode supplies the badge", "_c_am.badge(_c_mode, _c_src)" in ACCC)
check("whether it is proven is carried through", '"proven": bool(_c_proven)' in ACCC)
check("an unproven environment is stated on the screen",
      "could not be verified with your broker" in HTML)
check("...and says live orders are unavailable until it is",
      "New live orders are unavailable until" in HTML)
check("the screen renders the word, not only a colour",
      "(unconfirmed)" in HTML and "UNKNOWN" in HTML)

print("\n3. The screen tells the client where credentials live")
check("it says they never leave the server",
      HTML.count("never shown here and never leave the server") >= 1)
# The account screen now offers Refresh and Disconnect, and directs BOTH
# connecting and disconnecting to the chat — the broker's own sign-in runs
# there, and revoking a token must not be doable from a read-only screen.
check("connecting and disconnecting are directed to the chat",
      "happen in the chat" in HTML and "/ctrader" in HTML)
check("refresh is a real action on this screen", "acctRefresh" in HTML)
check("disconnect explains why it is not done here",
      "revokes a broker token" in HTML)

print("\n4. Alerts are recorded events, not generated ones")
check("events come from the decision log", "_l_te.recent(_l_chat" in ALRC)
check("the risk verdict comes from the engine", "_l_ui.risk_state(_l_chat)" in ALRC)
check("nothing is composed in the route",
      not re.search(r'"(message|headline|summary)"\s*:', ALRC),
      "an alert the platform did not record is an alert it did not have")
check("an empty log is worded as unrecorded",
      "Nothing recorded yet" in HTML)
check("...and explains when entries appear",
      "appear" in HTML and "as they happen" in HTML)
check("each entry shows its environment where known", "ev.environment" in HTML)

print("\n5. Both routes are scoped to the authenticated client")
for name, code in (("account", ACCC), ("alerts", ALRC)):
    check(f"{name}: a denied caller is refused", "_telegram_denied" in code)
    check(f"{name}: the chat id comes from the signature",
          '_c_chat = str(_c_user["id"])' in code or '_l_chat = str(_l_user["id"])' in code)
    check(f"{name}: nothing is read from the query string",
          "parse_qs" not in code and '"user_id"' not in code)
    check(f"{name}: no order path is reachable",
          not any(x in code for x in ("place_order", "force_close", "authorize_order")))

print("\n6. Failure is stated, not blanked")
check("account: an unreadable record answers a reason",
      "ACCOUNT_UNAVAILABLE" in ACCC)
check("alerts: an unreadable log answers a reason", "ALERTS_UNAVAILABLE" in ALRC)
for phrase in ("Your account could not be read just now",
               "Alerts are unavailable right now"):
    check(f"the screen says so: {phrase!r}", phrase in HTML)

print("\n7. Reachable, and no local can shadow the enclosing scope")
for sid in ("settings", "account", "alerts"):
    check(f"{sid} has a screen", f'id="s-{sid}"' in HTML)
check("Settings is a navigation destination", 'data-s="settings"' in HTML)
check("Settings links to the others",
      all(f'data-goto="{x}"' in HTML for x in ("account", "automation", "alerts", "risk")))
check("account loads when opened", "if(name==='account') loadAccount(true);" in HTML)
check("alerts loads when opened", "if(name==='alerts') loadAlerts(true);" in HTML)
RX = re.compile(r'^\s+([a-z][\w]*) = (?!=)', re.M)
for name, code in (("account", ACCC), ("alerts", ALRC)):
    bare = {m.group(1) for m in RX.finditer(code)}
    check(f"{name}: every local is prefixed ({sorted(bare)})", not bare)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL ACCOUNT/ALERTS CHECKS PASSED - identity without credentials, events without invention.")
