"""DEMO must never read as LIVE, and LIVE must never read as DEMO.

That is the whole of this file. Everything else it checks — switching,
refreshing, activating — exists because each is a moment where the two can be
confused, and the confusion is only expensive in one direction.

The bug this replaces: the environment came from `user["ctrader_env"]`, a flag
written at connect time and writable afterwards by a command. A client who
switched accounts at their broker, or whose record was written before the
account list existed, was shown yesterday's answer next to today's balance.

Scenarios covered here (of the 30): new user · existing user · demo · live ·
demo→live switch · live→demo switch · unknown environment · disconnected demo ·
disconnected live · live activation · failed activation · account refresh ·
broker timeout.

Run: python tests/test_ux_environment.py
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
from apex import telegram as tg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} — {detail}")
        failures.append(name)


LIVE_ACC = {"ctrader_access_token": "t", "ctrader_account_id": 900001,
            "ctrader_accounts": [{"ctid": 900001, "live": True}],
            "paper": False}
DEMO_ACC = {"ctrader_access_token": "t", "ctrader_account_id": 900002,
            "ctrader_accounts": [{"ctid": 900002, "live": False}],
            "paper": True}
BOTH = {"ctrader_access_token": "t", "ctrader_account_id": 900002,
        "ctrader_accounts": [{"ctid": 900001, "live": True},
                             {"ctid": 900002, "live": False}]}


def says_live(text):
    return "🔴 LIVE" in text or "LIVE" in text


def says_demo(text):
    return "🧪 DEMO" in text or "DEMO" in text


print("\n🧪 ENVIRONMENT — the connected account decides, nothing else\n")

print("1. Scenario: a brand-new user, nothing connected")
env, proven, why = U.environment({})
check("a blank record is NOT demo", env != U.DEMO, env)
check("a blank record is NOT live", env != U.LIVE, env)
check("it reads as not connected", env == U.DISCONNECTED, env)
check("and the badge says so", "NOT CONNECTED" in U.badge(env, proven),
      U.badge(env, proven))

print("\n2. Scenario: an existing, fully connected DEMO user")
env, proven, why = U.environment(DEMO_ACC)
check("environment is demo", env == U.DEMO, env)
check("and it is proven by the account, not by a flag", proven is True, why)
check("the badge is the required 🧪 DEMO", U.badge(env, proven) == "🧪 DEMO",
      U.badge(env, proven))
check("a demo account is never badged LIVE",
      "🔴 LIVE" not in U.badge(env, proven), U.badge(env, proven))

print("\n3. Scenario: an existing, fully connected LIVE user")
env, proven, why = U.environment(LIVE_ACC)
check("environment is live", env == U.LIVE, env)
check("proven by the account", proven is True, why)
check("the badge is the required 🔴 LIVE", U.badge(env, proven) == "🔴 LIVE",
      U.badge(env, proven))
check("a live account is never badged DEMO",
      "DEMO" not in U.badge(env, proven), U.badge(env, proven))

print("\n4. The flag can lie; the account cannot")
# The exact production shape of the bug: a stale `ctrader_env` says demo while
# the connected account is live. Trusting the flag prints "🧪 DEMO" over real
# money.
lying = dict(LIVE_ACC, ctrader_env="demo")
env, proven, _ = U.environment(lying)
check("a stale demo flag does NOT turn a live account into demo",
      env == U.LIVE, env)
check("and the badge still reads LIVE", says_live(U.badge(env, proven)),
      U.badge(env, proven))
lying2 = dict(DEMO_ACC, ctrader_env="live")
env2, proven2, _ = U.environment(lying2)
check("a stale live flag does NOT turn a demo account into live",
      env2 == U.DEMO, env2)

print("\n5. Scenario: demo → live switch")
env, _, _ = U.environment(dict(BOTH, ctrader_account_id=900002))
check("bound to the demo account → demo", env == U.DEMO, env)
env, _, _ = U.environment(dict(BOTH, ctrader_account_id=900001))
check("bound to the live account → live", env == U.LIVE, env)

print("\n6. Scenario: live → demo switch")
check("switching back reads demo again",
      U.environment(dict(BOTH, ctrader_account_id=900002))[0] == U.DEMO)
check("the paper flag does not decide it either",
      U.environment(dict(BOTH, ctrader_account_id=900001, paper=True))[0] == U.LIVE)

print("\n7. Scenario: unknown environment")
# Connected, but the selected account is not in the broker's list — removed at
# the broker, or a record written before the list existed.
orphan = {"ctrader_access_token": "t", "ctrader_account_id": 777, "paper": True}
env, proven, why = U.environment(orphan)
check("an unprovable account is not silently called demo", env != U.DEMO, env)
check("it reads as unknown", env == U.UNKNOWN, env)
check("the badge is the required 🟠 VERIFICATION REQUIRED",
      U.badge(env, proven) == "🟠 VERIFICATION REQUIRED", U.badge(env, proven))
check("and it is never presented as proven", proven is False, str(proven))
env, proven, _ = U.environment(None)
check("an UNREADABLE record is unknown, not an empty demo account",
      env == U.UNKNOWN, env)

print("\n8. An unproven record resolves in the direction that cannot hurt")
# `paper: False` means real orders are intended and the record offers no
# evidence of where. Reading that as demo is the one reading that can cost
# somebody money.
env, proven, _ = U.environment({"ctrader_access_token": "t",
                                "ctrader_account_id": 5, "paper": False})
check("real-orders-intended with no evidence reads LIVE", env == U.LIVE, env)
check("and is flagged unverified rather than presented as confirmed",
      proven is False and "unverified" in U.badge(env, proven),
      U.badge(env, proven))

print("\n9. Scenario: disconnected demo and disconnected live")
st_demo = U.resolve("1", user={"paper": True})
check("disconnected demo → state F", st_demo.state == "F", st_demo.state)
st_live = U.resolve("1", user={"paper": False, "ctrader_env": "live"})
check("disconnected live → state E", st_live.state == "E", st_live.state)
for st, name in ((st_demo, "demo"), (st_live, "live")):
    body = screens.home(st)
    check(f"the disconnected {name} screen says it is not connected",
          "not connected" in body.lower(), body[:120])
    rows = screens.home_rows(st)
    flat = [c for row in rows for _l, c in row]
    check(f"the disconnected {name} screen offers a way to connect",
          "go:connect" in flat, str(flat))
    check(f"the disconnected {name} screen is not a dead end",
          any(c.startswith("nav:") for c in flat), str(flat))

print("\n10. Scenario: account refresh, and a broker that times out")
calls = {"n": 0}
saved = {}


class _Store:
    def load(self, uid):
        return dict(saved)

    def update(self, uid, d, **kw):
        saved.update(d)

    def claim(self, *a, **k):
        return True

    _USE_REDIS = False


_real_us = U.__dict__.get("user_store")
import apex.user_store as _us  # noqa: E402
_orig = (_us.load, _us.update)
_us.load = lambda uid: dict(saved)
_us.update = lambda uid, d, **kw: saved.update(d)

# The refresh must go THROUGH the trading core — `ui_state` is not allowed to
# import a broker itself (test_failure_matrix item 15 states that as a property
# of the import graph). So this stubs the core's accessor, which is also the
# proof that the accessor is the path being used.
import apex.user_loop as _ul  # noqa: E402
_ul_orig = _ul.list_broker_accounts


def _ok_list(user):
    calls["n"] += 1
    return [{"ctid": 900001, "live": True}]


def _timeout_list(user):
    calls["n"] += 1
    raise RuntimeError("timed out waiting for the broker")


try:
    saved.clear()
    saved.update({"ctrader_access_token": "t", "ctrader_account_id": 900001,
                  "ctrader_env": "demo"})
    _ul.list_broker_accounts = _ok_list
    u, refreshed, why = U.refresh("42", force=True)
    check("a refresh asks the broker", calls["n"] == 1, str(calls))
    check("it reports that it succeeded", refreshed is True, why)
    check("the stale demo flag is corrected to live",
          saved.get("ctrader_env") == "live", str(saved.get("ctrader_env")))
    check("and the environment now reads LIVE, proven",
          U.environment(u)[:2] == (U.LIVE, True), str(U.environment(u)[:2]))

    # Scenario: the broker times out. The screen must degrade, not lie.
    saved.clear()
    saved.update({"ctrader_access_token": "t", "ctrader_account_id": 900001})
    _ul.list_broker_accounts = _timeout_list
    u, refreshed, why = U.refresh("42", force=True)
    check("a broker timeout does not raise into the screen", u is not None)
    check("it reports that it did NOT confirm", refreshed is False, why)
    check("the wording is customer language, not a traceback",
          "timed out" not in why.lower() and "traceback" not in why.lower(), why)
    check("and the environment stays unknown rather than becoming demo",
          U.environment(u)[0] == U.UNKNOWN, str(U.environment(u)[0]))
finally:
    _ul.list_broker_accounts = _ul_orig
    _us.load, _us.update = _orig

print("\n10b. The UI layer does not reach a broker itself")
for _mod in ("ui_state.py", "screens.py", "callback_guard.py"):
    _src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "apex", _mod), encoding="utf-8").read()
    check(f"{_mod} imports no broker",
          "brokers.ctrader" not in _src and "CtraderBroker" not in _src
          and "from apex.brokers" not in _src, _mod)
check("the refresh goes through the trading core",
      "user_loop.list_broker_accounts" in open(os.path.join(
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
          "apex", "ui_state.py"), encoding="utf-8").read())

print("\n11. Scenario: live activation and a failed activation")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "telegram.py"), encoding="utf-8").read()
act = SRC[SRC.index("def _handle_paper"):SRC.index("# Risk tiers for the")]
check("activation asks ui_state for the environment, not ctrader_env",
      "_uis.environment(" in act and '"ctrader_env"' not in act, act[:200])
check("activation re-reads the account from the broker first",
      "_uis.refresh(" in act)
check("only a confirmed LIVE environment takes the confirmation path",
      "_env == _uis.LIVE" in act)
check("a failed/unconfirmed activation cannot skip the token",
      "consume_live_confirm" in act)
scr = SRC[SRC.index("def _screen_live_activation"):SRC.index("def _handle_terminal")]
check("the activation screen refuses a non-live environment",
      "st.env != ui_state.LIVE" in scr)
check("it re-checks with the broker before offering activation",
      "refresh=True, force=True" in scr)

print("\n12. The one-bot rule: no screen is built for 'the demo bot'")
check("there is exactly one status handler", SRC.count("def _handle_status(") == 1)
check("there is exactly one home screen", SRC.count("def _screen_home(") == 1)
check("there is exactly one account screen", SRC.count("def _screen_account(") == 1)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ENVIRONMENT DETECTION IS AUTHORITATIVE — demo is never live, live is never demo.")
