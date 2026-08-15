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
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

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

print("\n── infrastructure events never reach a client at all ──")
# A client received `⚡ OWNERSHIP_LOST — EUR_USD` three times in twenty minutes.
# Nothing had happened to their money: each deploy hands the account to the new
# container and the retiring one stands down, which is the handover working.
# But it reads like a failure, names their instrument, and there is no action a
# client could take — the correct response is "the other container has it".
for a in ("OWNERSHIP_LOST", "OWNERSHIP_BLOCKED"):
    check(f"{a} is not sent to a quiet client", not alert_policy.allowed(a, QUIET))
    check(f"{a} is not sent with /verbose either",
          not alert_policy.allowed(a, LOUD),
          "OPERATOR is stronger than DIAGNOSTIC — not about them at all")
    check(f"{a} is classified, not merely unknown",
          alert_policy.tier(a) == "operator", alert_policy.tier(a))
check("operator events are a separate tier from diagnostics",
      not (alert_policy.OPERATOR & alert_policy.DIAGNOSTIC))
# The operator must still see them: the client gate runs AFTER the event log.
TG = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "telegram.py"), encoding="utf-8").read()
_alert_fn = TG[TG.index("def _user_alert"):TG.index("def _user_alert") + 1200]
check("the operator event log is written before the client gate",
      _alert_fn.index("event_from_alert") < _alert_fn.index("alert_policy.allowed"))
# An unclassified alert must still default to SENT — silence is the failure
# mode that is hard to notice, so this tier is opt-IN, never a new default.
check("an unknown alert type is still sent",
      alert_policy.allowed("SOME_NEW_ALERT", QUIET))

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


# ── one language, everywhere ────────────────────────────────────────────
# The bot's own messages were English while the AI assistant mirrored
# whatever the client wrote, so a single Telegram thread came out bilingual:
# an English "Position closed" answered in Romanian. Each message was
# individually well-matched and the conversation as a whole read as broken.
print("\n── the interface speaks one language ──")
import re as _re  # noqa: E402

_CLIENT_FACING = ("telegram.py", "ctrader_oauth.py", "assistant.py",
                  "chat_memory.py", "webapp.py")
_ROMANIAN = _re.compile(
    r'\b(nicio|deschis[ăa]|pentru a|folose[șs]te|închide|pre[țt] curent|'
    r'balan[țt][ăa]|tranzac[țt]i|riscul|apas[ăa]|momentan|a[șs]teapt[ăa])\b',
    _re.I)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for fname in _CLIENT_FACING:
    path = os.path.join(_root, "apex", fname)
    if not os.path.exists(path):
        continue
    hits = []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Raw strings here are INPUT patterns — the bot still understands
        # "închide" or "cumpără" typed by a client. Only its own OUTPUT has
        # to be English, so regex definitions are not a violation.
        if 'r"' in line or "r'" in line or "re.compile" in line:
            continue
        if _ROMANIAN.search(line):
            hits.append(f"{fname}:{i}")
    check(f"{fname} has no leftover Romanian in client text",
          not hits, ", ".join(hits[:4]))

ASSIST = open(os.path.join(_root, "apex", "assistant.py"), encoding="utf-8").read()
check("the assistant is pinned to English, not mirroring the client",
      "ALWAYS reply in English" in ASSIST)
check("and the old mirroring instruction is gone",
      "mirror whatever the user wrote" not in ASSIST)
check("it still understands other languages, it just answers in one",
      "understand it fully" in ASSIST)


print("\n── the copy does not promise a reply in the client's language ──")
TG2 = open(os.path.join(_root, "apex", "telegram.py"), encoding="utf-8").read()
check("no line still offers to talk 'in any language' unqualified",
      "talk to me in any language!" not in TG2
      and "any language — just type your question" not in TG2)
check("it says plainly which language the answer comes back in",
      TG2.count("reply in English") + TG2.count("I answer in English") >= 2, "")
check("and still invites other languages as INPUT",
      "any language" in TG2)

ASSIST2 = open(os.path.join(_root, "apex", "assistant.py"), encoding="utf-8").read()
check("the symbol is shown the same way in the status line as everywhere else",
      "symbol.replace(chr(95), '')" in ASSIST2,
      "status line would say EUR_USD next to a reply saying EURUSD")

# ── the two bugs the live screenshots caught ────────────────────────────
print("\n── /status must name the strategy that is actually running ──")
LOOP2 = open(os.path.join(_root, "apex", "user_loop.py"), encoding="utf-8").read()
check("the dash label no longer defaults through STRATEGY_MODES",
      'ai.STRATEGY_MODES.get(cfg.STRATEGY' not in LOOP2,
      "would report Mean Reversion for every post-V1 strategy")
check("it resolves through the registry instead",
      "_strategy_label(cfg.STRATEGY)" in LOOP2)
check("the auto-mode label uses it too",
      "_strategy_label(active_mode)" in LOOP2)

from apex import user_loop as _ul  # noqa: E402
check("a registry-only strategy resolves to its real name",
      "Momentum" in _ul._strategy_label("momentum"),
      _ul._strategy_label("momentum"))
check("a V1 strategy still resolves",
      _ul._strategy_label("mean_reversion") != "mean_reversion",
      _ul._strategy_label("mean_reversion"))
check("an unknown key degrades to the key, not to a wrong strategy",
      _ul._strategy_label("_nope") == "_nope", _ul._strategy_label("_nope"))

print("\n── a closed trade carries what the R figure needs ──")
_closes = LOOP2.count('"initialStop": open_pos.get("initialStop")')
check("every close payload passes the original stop", _closes >= 3, str(_closes))
check("and the side", LOOP2.count('"side": open_pos.get("entrySide")') >= 3,
      str(LOOP2.count('"side": open_pos.get("entrySide")')))
check("so the R line has its inputs",
      tg._r_multiple_line({"entryPrice": 1.15311, "initialStop": 1.15661,
                           "price": 1.15547, "side": "SELL"}) != "",
      "the live close showed dollars with no R")

print("\n── everything the client is shown is in English ──")
# The bot is asked in any language and answers in English. That was done once,
# and the natural-language trading path was missed: "⚡ Deschid BUY EURUSD…"
# went out in Romanian on a live account for weeks, right before an English
# confirmation. Understanding stays multilingual — only OUTPUT is pinned.
import re as _re  # noqa: E402

_RO_WORDS = _re.compile(
    r"(?<![A-Za-z])(?:cu|și|si|pentru|acum|dar|către|catre|tranzacție|"
    r"tranzactie|poziție|pozitie|deschid|închid|inchid|piața|piata|"
    r"câștig|castig|pierdere|bani|tău|tau|vinde|cumpără|cumpara|"
    r"contul|niciodată|niciodata)(?![A-Za-z])", _re.I)

_TG = TG   # telegram.py, already read above
_ro_out = []
for _i, _line in enumerate(_TG.split("\n"), 1):
    if _line.strip().startswith("#") or "send_to(" not in _line and "send(" not in _line:
        continue
    for _a, _b in _re.findall(r'"([^"\n]{8,})"|\'([^\'\n]{8,})\'', _line):
        _txt = _a or _b
        if _RO_WORDS.search(_txt):
            _ro_out.append(f"telegram.py:{_i} {_txt[:60]}")
            break
check("no Romanian in anything sent to a client", not _ro_out, str(_ro_out))
check("the trade acks are English",
      'f"⚡ Opening <b>BUY {sym}</b>…"' in _TG
      and 'f"⚡ Opening <b>SELL {sym}</b>…"' in _TG)
check("and the all-in ack too", '</b> with <b>${bal * 0.98:.0f}</b>' in _TG)

print("\n── but it still UNDERSTANDS other languages ──")
for _word, _rx, _lbl in (("cumpara", tg._RE_BUY_FX, "BUY"),
                         ("cumpără EURUSD", tg._RE_BUY_FX, "BUY"),
                         ("buy eurusd", tg._RE_BUY_FX, "BUY"),
                         ("intru long", tg._RE_BUY_FX, "BUY"),
                         ("vinde USDCAD", tg._RE_SELL_FX, "SELL"),
                         ("sell now", tg._RE_SELL_FX, "SELL"),
                         ("short it", tg._RE_SELL_FX, "SELL")):
    check(f"'{_word}' still reads as {_lbl}", bool(_rx.search(_word)))

print("\n── a free-text order names its own instrument ──")
# _RE_PAIR_FX wanted EUR/USD or a lone EUR. A bare six-letter pair has no word
# boundary in the middle, so "cumpara EURUSD" matched nothing and the order
# fell back to whatever Auto-Pilot was focused on — a real position on the
# wrong instrument, silently. It only looked correct in testing because focus
# and request happened to agree.
for _txt, _want in (("cumpara EURUSD", "EUR_USD"),
                    ("buy me some eurusd", "EUR_USD"),
                    ("long usdjpy", "USD_JPY"),
                    ("sell usdcad", "USD_CAD"),
                    ("short eurusd", "EUR_USD"),
                    ("intru pe gbpusd", "GBP_USD"),
                    ("buy EUR/USD", "EUR_USD"),
                    ("buy EUR_USD", "EUR_USD"),
                    ("buy gold", "XAU_USD"),
                    ("cumpara silver", "XAG_USD")):
    check(f"'{_txt}' → {_want}", tg._pair_from_text(_txt) == _want,
          f"got {tg._pair_from_text(_txt)}")
for _txt in ("cumpără", "vinde", "go short", "buy now", "close it",
             "buy usd", "sell me something"):
    check(f"'{_txt}' names no pair → keeps the current one",
          tg._pair_from_text(_txt) is None, f"got {tg._pair_from_text(_txt)}")

print("\n── asking about closing must not close ──")
# The close-math pattern needed a Romanian second half, so the English
# hypothetical fell through to the branch that actually shuts the position.
_math = lambda t: bool(  # noqa: E731  - mirrors the gate in _handle_trade_intent_fx
    tg._RE_CLOSE_MATH_FX.search(t)
    or (tg._RE_CLOSE_FX.search(t) and tg._RE_HYPOTHETICAL_FX.search(t)))
for _q in ("if i close now how much would i have",
           "how much if i close right now",
           "what would i get if i close",
           "daca inchid acum cat am?",
           "daca inchid cat pierd",
           "close?"):
    check(f"question: '{_q}' → preview, not a close", _math(_q))
for _o in ("close it", "close the trade", "inchide", "exit now",
           "iesi din tranzactie"):
    check(f"order: '{_o}' → still closes", not _math(_o))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL CLIENT-EXPERIENCE CHECKS PASSED.")
