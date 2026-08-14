"""Reconnecting a broker must not look like the bot forgot everything.

The OAuth callback called onboard_start() unconditionally, so re-authorising
cTrader — a token refresh, a re-link, tapping /ctrader again — threw an
already-configured client back into "Setup 1/2 — what do you want to trade?".

Nothing was ever actually lost: the settings and the open position stayed in
the store the whole time. But from the client's side that is indistinguishable
from the bot resetting itself and abandoning an open trade, which is a support
ticket every time and alarming on a live account. Reported from production
with a position open.

The same callback also notified twice. It is a browser redirect target, so a
reload, a prefetch or a double tap replays it — and during a deploy two
instances are live and both poll the same bot token.

Run: python tests/test_reconnect_no_reonboard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "ctrader_oauth.py")).read()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def is_set_up(user):
    """The condition the callback uses to tell a reconnect from a first run."""
    return bool(user.get("symbol") and user.get("strategy"))


print("\n── who counts as already set up ──")
returning = {"symbol": "EURUSD", "strategy": "mean_reversion", "autopilot": True,
             "risk": 0.02}
check("a configured client is recognised", is_set_up(returning) is True)
check("a client mid-onboarding is not",
      is_set_up({"ctrader_account_id": 123}) is False)
check("symbol without a strategy is not enough",
      is_set_up({"symbol": "EURUSD"}) is False)
check("strategy without a symbol is not enough",
      is_set_up({"strategy": "trend"}) is False)
check("an empty record is a first run", is_set_up({}) is False)

print("\n── the callback branches on it ──")
block = SRC[SRC.index("elif len(accounts) == 1:"):SRC.index("elif accounts:")]
check("onboarding is now conditional",
      "if not already_set_up:" in block, block[:200])
check("and gated on symbol AND strategy",
      'u_now.get("symbol") and u_now.get("strategy")' in block)
check("onboard_start is inside the first-run branch",
      block.index("if not already_set_up:") < block.index("tg.onboard_start(chat_id)"))
check("a returning client gets a different headline",
      "cTrader reconnected!" in block)
check("...and is told nothing was reset",
      "Nothing was reset" in block, block[-400:])

print("\n── the reconnect message answers 'did it lose my trade?' ──")
check("it reads the persisted position snapshot",
      'u_now.get("open_position_snapshot")' in block)
check("it names the side and symbol", "Open position kept" in block)
check("it shows the stop and target", "SL {pos.get('sl')}" in block)
check("and says so explicitly when there is none",
      "No open position" in block)
check("it restates the live settings rather than asking again",
      "Your setup is unchanged" in block)

print("\n── a first run still onboards exactly as before ──")
check("the original headline is kept for new clients",
      "cTrader connected!" in block)
check("onboard_start is still called", "tg.onboard_start(chat_id)" in block)

print("\n── a replayed callback must not notify twice ──")
head = SRC[SRC.index("# Notify the client in Telegram"):SRC.index("elif len(accounts) == 1:")]
check("a claim guards the notification", "user_store.claim(" in head, head[:200])
check("keyed per account, so linking a different one still notifies",
      "ctrader_account_id" in head)
check("a losing caller returns without messaging",
      "is False:" in head and "return 200" in head)
check("it is a short burst guard, not a permanent lock",
      "ttl_s=90" in head)
check("an unreachable store does not silence the message "
      "(claim returns None, not False)",
      "claim(_notify_key, ttl_s=90) is False" in head)

print("\n── the page still confirms success to the browser either way ──")
check("the duplicate path still renders Connected",
      head.count("Connected") >= 1)


# ── balance: retry, then fall back to what we already know ─────────────
# "⚠️ Balance unavailable: timed out" reached a client. account_balance
# already retries once internally, so that message means TWO attempts failed
# — the cold TLS session right after OAuth (connect + app auth + account auth
# + request) does not always finish inside the window, while the trading loop
# reads the same balance fine seconds later.
print("\n── the balance fetch retries before giving up ──")
_bal = SRC[SRC.index("if not gate_reason:"):SRC.index("user_store.update(chat_id, updates)")]
check("there is a retry loop", "for _attempt in (1, 2):" in _bal, _bal[:200])
check("it pauses between attempts", "time.sleep(2)" in _bal)
check("it does not pause after the last attempt",
      "if _attempt == 1:" in _bal, _bal[-300:])
check("a success clears the earlier error", "bal_err = None" in _bal)
check("and stops retrying", "break" in _bal)
check("each failure is logged with its attempt number",
      "balance attempt {_attempt} failed" in _bal)

print("\n── a still-failing balance shows a number, not an alarm ──")
_msg = SRC[SRC.index("if bal is not None:"):SRC.index("# A RECONNECT is not a first run.")]
check("the last known balance is used as a fallback",
      'user_store.load(chat_id).get("paper_balance")' in _msg, _msg[:200])
check("and is labelled as last known, not passed off as live",
      "last known" in _msg)
# Scoped to the message-building code: the phrase also appears in a comment
# that documents what the client used to see.
_TG = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "telegram.py")).read()
check("the scary wording is gone from the OAuth message",
      "Balance unavailable" not in _msg)
check("and from the /ctaccount path, which had the same bug",
      'bal_line = f"⚠️ Balance unavailable' not in _TG)
check("/ctaccount also stopped re-onboarding a configured client",
      'user.get("symbol") and user.get("strategy")' in _TG)
check("/ctaccount retries the balance too",
      _TG.count("for _attempt in (1, 2):") >= 1)
check("a client with no known balance sees 'loading', not an error",
      "Balance loading" in _msg)
check("a real number is still preferred when the call works",
      "${bal:,.2f}" in _msg)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL RECONNECT + BALANCE CHECKS PASSED.")
