"""Real-money trading must not start on one mistyped word.

`/paper off` flipped a live cTrader account straight into sending real orders.
The only thing in front of it was a risk acceptance clicked once — for this
account, a month earlier. So one wrong command, one fat finger, or one
Telegram session in the wrong hands was enough to start trading real funds.

The audit asks for: request → show account + risk summary → explicit
confirmation token → hard initial risk cap → log the activation.

The demo path keeps its single step on purpose. Friction there protects
nothing and teaches people to click through warnings.

Run: python tests/test_live_activation.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from apex import telegram as tg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# ── stand-ins for Telegram, the store and the loop ──
sent = []
store = {}
restarts = []
audits = []

tg.send_to = lambda cid, text, **kw: sent.append(text) or text
tg.user_store.load = lambda cid: dict(store)
tg.user_store.update = lambda cid, d: store.update(d)
tg._restart_user_loop = lambda cid: restarts.append(cid)
tg.access.is_admin = lambda cid: False
tg.user_loop.get_dash = lambda cid: {"balance": 5000.0}

from apex import control  # noqa: E402
control._audit = lambda e: audits.append(e)


def reset(**over):
    sent.clear(); restarts.clear(); audits.clear()
    store.clear()
    store.update({
        "risk_accepted": "2026-07-17T05:57:35",
        "ctrader_env": "live",
        "ctrader_account_id": 47765456,
        "risk": 0.02, "paper": True,
        "sl_pips": 35.0, "tp_pips": 70.0,
        "max_trades_day": 15, "max_daily_loss_pct": 6, "max_dd_pct": 25,
    })
    store.update(over)


print("\n── a bare `/paper off` on a LIVE account does NOT go live ──")
reset()
tg._handle_paper("111", "off")
check("paper mode is unchanged", store.get("paper") is True, str(store.get("paper")))
check("the loop was not restarted into live", restarts == [], str(restarts))
check("a confirmation was demanded", any("REAL MONEY" in s for s in sent), str(sent)[:200])

print("\n── the summary shows what will actually trade ──")
msg = sent[-1]
check("the account id", "47765456" in msg)
check("the balance", "5000" in msg)
check("the stop and target", "35" in msg and "70" in msg)
check("the daily loss cap", "6" in msg)
check("it says losses are real", "real" in msg.lower())
check("it gives an exact command to send", "/paper off" in msg)
check("and a token was stored", bool((store.get("live_confirm") or {}).get("token")))

print("\n── the wrong token does not activate ──")
tok = store["live_confirm"]["token"]
sent.clear()
tg._handle_paper("111", "off WRONG1")
check("still simulating", store.get("paper") is True)
check("and it re-asks", any("REAL MONEY" in s for s in sent))

print("\n── the right token activates ──")
reset()
tg._handle_paper("111", "off")
tok = store["live_confirm"]["token"]
sent.clear()
tg._handle_paper("111", f"off {tok}")
check("paper mode is now OFF", store.get("paper") is False, str(store.get("paper")))
check("the loop restarted", restarts != [])
check("the user is told orders are live",
      any("LIVE" in s for s in sent), str(sent)[-1:])

print("\n── activation caps risk, whatever it was set to ──")
check(f"risk clamped to {tg._LIVE_INITIAL_RISK_CAP:.0%}",
      store["risk"] == tg._LIVE_INITIAL_RISK_CAP, str(store["risk"]))
reset(risk=0.005)
tg._handle_paper("111", "off")
tg._handle_paper("111", f"off {store['live_confirm']['token']}")
check("a risk already below the cap is left alone", store["risk"] == 0.005,
      str(store["risk"]))

print("\n── the token is single-use and time-bounded ──")
reset()
tg._handle_paper("111", "off")
tok = store["live_confirm"]["token"]
tg._handle_paper("111", f"off {tok}")
check("the token was burned after use", not store.get("live_confirm"),
      str(store.get("live_confirm")))
reset()
tg._handle_paper("111", "off")
tok = store["live_confirm"]["token"]
store["live_confirm"]["ts"] = time.time() - (tg._LIVE_CONFIRM_TTL_S + 5)
sent.clear()
tg._handle_paper("111", f"off {tok}")
check("an expired token is refused", store.get("paper") is True)
check("and a fresh one is issued", store["live_confirm"]["token"] != tok)

print("\n── the activation is audited ──")
reset()
tg._handle_paper("111", "off")
tg._handle_paper("111", f"off {store['live_confirm']['token']}")
check("an audit record was written", len(audits) == 1, str(audits))
rec = audits[0] if audits else {}
check("it names the action", rec.get("action") == "live_trading_activated", str(rec))
check("it records the actor", rec.get("actor") == "111", str(rec))
check("it records the account", "47765456" in str(rec.get("account")), str(rec))
check("it records the risk it started at",
      rec.get("risk_per_trade") == tg._LIVE_INITIAL_RISK_CAP, str(rec))
check("no token leaks into the audit", "token" not in str(rec).lower(), str(rec))

print("\n── DEMO accounts keep the one-step path ──")
reset(ctrader_env="demo")
tg._handle_paper("222", "off")
check("demo goes straight to live-orders-in-demo", store.get("paper") is False)
check("no confirmation token was demanded",
      not any("REAL MONEY" in s for s in sent), str(sent)[:160])
check("no live-activation audit for a demo account", audits == [], str(audits))

print("\n── turning paper back ON is never gated ──")
reset(paper=False)
tg._handle_paper("111", "on")
check("simulation resumes immediately", store.get("paper") is True)

print("\n── risk acceptance is still required first ──")
reset()
store.pop("risk_accepted")
sent.clear()
tg._handle_paper("111", "off")
check("an unaccepted user is shown the risk text first",
      store.get("paper") is True and not store.get("live_confirm"),
      str(store.get("live_confirm")))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL LIVE-ACTIVATION CHECKS PASSED.")
