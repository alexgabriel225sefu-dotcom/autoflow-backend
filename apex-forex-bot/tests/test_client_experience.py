"""A beginner must be able to work the bot alone, without being buried.

The bot grew 22 notification types and sent all of them to everyone. Most are
diagnostics written for whoever is debugging it, not for the person whose
money is in it — and the volume is the problem by itself. A trailing stop
that moves nine times on one trade produced nine near-identical "stop moved"
messages, which teaches a client to stop reading the channel, including the
two messages that mattered.

Also covered here: the three things a simulated ideal conversation promised
that the real bot could not do — /resume, an R figure on a closed trade, and
an end-of-day summary — plus plain-language strategy names, because someone
who just connected an account does not know what an Inverse Fair Value Gap
is.

Run: python tests/test_client_experience.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-ux-")

from apex import alert_policy, telegram as tg, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


QUIET = {}
LOUD = {"verbose_alerts": True}

print("\n── a beginner still sees everything about their money ──")
for a in ("BUY", "SELL", "CLOSE", "BROKER_CLOSE", "BROKER_CLOSE_MULTI",
          "STOP", "WEEKEND_CLOSE", "WEEKEND_REOPEN", "DAILY_SUMMARY",
          "STOP_BREAKEVEN"):
    check(f"{a} reaches a quiet client", alert_policy.allowed(a, QUIET))

print("\n── and anything they might need to act on ──")
for a in ("NEWS_WARN", "FLASH_WARN", "BROKER_HEALTH", "SUGGEST"):
    check(f"{a} reaches a quiet client", alert_policy.allowed(a, QUIET))

print("\n── the diagnostics are hidden until asked for ──")
for a in ("STOP_MOVED", "SKIP_WARN", "MARKET_PULSE", "HEARTBEAT",
          "SENTINEL_BLOCK", "SENTINEL_FLIP", "SHADOW_OPEN", "SHADOW_MOVE",
          "SHADOW_RESULT", "AI_ERROR", "DATA_ERROR"):
    check(f"{a} is quiet by default", not alert_policy.allowed(a, QUIET))
    check(f"{a} appears with /verbose", alert_policy.allowed(a, LOUD))

print("\n── the nine-messages-per-trade case ──")
check("every trail after the first is silent by default",
      not alert_policy.allowed("STOP_MOVED", QUIET))
check("but the one that makes the trade risk-free is not",
      alert_policy.allowed("STOP_BREAKEVEN", QUIET))
check("they are different alert types, so one cannot swallow the other",
      "STOP_BREAKEVEN" in alert_policy.ESSENTIAL
      and "STOP_MOVED" in alert_policy.DIAGNOSTIC)

LOOP = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "user_loop.py")).read()
check("the loop only announces breakeven once",
      'open_pos.get("breakevenAnnounced")' in LOOP)
_meta_block = LOOP.split("_ENTRY_META_KEYS = (")[1]
_meta_block = _meta_block[:_meta_block.index("\n)")]
check("and the flag survives the broker re-read that happens every tick",
      '"breakevenAnnounced"' in _meta_block,
      "not in _ENTRY_META_KEYS — the message would repeat every tick")

print("\n── an unclassified alert is sent, not silently swallowed ──")
check("an unknown action still reaches the client",
      alert_policy.allowed("SOME_NEW_THING", QUIET))
check("and is reported as unclassified",
      alert_policy.tier("SOME_NEW_THING") == "unclassified")

print("\n── the result is stated in R, not only dollars ──")
line = tg._r_multiple_line({"entryPrice": 1.1000, "initialStop": 1.0980,
                            "price": 1.1024, "side": "BUY"})
check("a winner reads as a positive R", "+1.20R" in line, line)
line = tg._r_multiple_line({"entryPrice": 1.1000, "initialStop": 1.0980,
                            "price": 1.0990, "side": "BUY"})
check("a loser reads as a negative R", "-0.50R" in line, line)
line = tg._r_multiple_line({"entryPrice": 1.1000, "initialStop": 1.1020,
                            "price": 1.0976, "side": "SELL"})
check("a short is measured the right way round", "+1.20R" in line, line)
check("no risk known → no R invented",
      tg._r_multiple_line({"price": 1.1}) == "")
check("a zero-width stop does not divide by zero",
      tg._r_multiple_line({"entryPrice": 1.1, "initialStop": 1.1,
                           "price": 1.2, "side": "BUY"}) == "")

print("\n── the daily summary reports the day, or says nothing ──")
uid = "ux-test-1"
user_store.clear_trades(uid)
check("a day with no closed trades produces NO message",
      tg.daily_summary_text(uid) is None)

from datetime import datetime  # noqa: E402
today = datetime.now().strftime("%Y-%m-%d")
for t, net, bal, sid in ((f"{today} 08:00:00", 24.0, 3024.0, "mean_reversion"),
                         (f"{today} 10:00:00", -6.0, 3018.0, "mean_reversion"),
                         (f"{today} 12:00:00", 12.0, 3030.0, "momentum")):
    user_store.append_trade(uid, {"time": t, "symbol": "EURUSD", "netPnl": net,
                                  "balance": bal, "strategyId": sid,
                                  "strategyVersion": "1.0.0"})
user_store.append_trade(uid, {"time": "2020-01-01 09:00:00", "symbol": "EURUSD",
                              "netPnl": 999.0, "balance": 1.0})
txt = tg.daily_summary_text(uid)
check("it counts only today's trades", "3</b> (2 won, 1 lost)" in txt, txt)
check("it nets them correctly", "+$30.00" in txt, txt)
check("it shows the closing balance", "3030.00" in txt, txt)
check("yesterday's outlier is excluded", "999" not in txt, txt)
check("it names the strategies in plain language",
      "Bounce Trader" in txt and "Momentum" in txt, txt)
check("it carries the honesty line",
      "does not guarantee" in txt, txt[-160:])

print("\n── plain-language names, with the technical id kept ──")
for key, expect in (("mean_reversion", "Bounce Trader"),
                    ("ifvg", "Reverse Gap"),
                    ("liquidity_sweep", "Stop Hunt"),
                    ("evc", "Volume Balance"),
                    ("martingale", "Martingale")):
    nice, tech = tg.friendly_strategy(key)
    check(f"{key} reads as '{expect}'", expect in nice, nice)
    check(f"{key} keeps its id for /strategy", tech == key)
check("the two risky ones are flagged in their own name",
      "⚠️" in tg.friendly_strategy("grid")[0]
      and "⚠️" in tg.friendly_strategy("martingale")[0])
nice, _ = tg.friendly_strategy("_not_a_strategy")
check("an unknown key does not crash the picker", isinstance(nice, str))

print("\n── the commands the copy promises actually exist ──")
TG = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "telegram.py")).read()
for cmd in ("/resume", "/settings", "/verbose", "/summary"):
    check(f"{cmd} is handled", f'"{cmd}"' in TG, "promised but missing")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL CLIENT-EXPERIENCE CHECKS PASSED.")
