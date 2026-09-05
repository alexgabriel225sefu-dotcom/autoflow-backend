"""What a client asks most often, answered without spending AI quota.

Every provider in the chat chain draws on one free-tier quota shared by every
client, and the trading signal draws on the same one. Measured over the
phrases a beginner actually types, 35 of 54 went to a language model — and
most were lookups the dashboard could already answer.

The risk of a table like this is not that it misses. It is that it MATCHES
TOO MUCH: a real question answered with a canned balance line is worse than
the API call it saved. So the negative half of this file matters more than the
positive half, and both directions are asserted.

Run: python tests/test_quick_answers.py
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
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-qa-")

from apex import quick_answers as qa  # noqa: E402
from apex import telegram as tg       # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


LOOKUPS = {
    # the account
    "cat am in cont": "status", "what is my balance": "status",
    "care e soldul": "status", "how am i doing": "status",
    "sunt in profit?": "status", "ce face botul": "status",
    "esti pornit?": "status", "is it running": "status", "cum merge": "status",
    # the anxious one
    "de ce nu tranzactioneaza": "why_no_trade",
    "why isn't it trading": "why_no_trade",
    "de ce nu deschide": "why_no_trade", "not trading": "why_no_trade",
    # settings
    "care e strategia mea": "strategy", "what strategy am i using": "strategy",
    "ce metoda folosesti": "strategy",
    "ce risc am": "risk", "what is my risk": "risk", "riscul meu": "risk",
    # context
    "ce stiri sunt azi": "news", "any news today": "news",
    "e piata deschisa": "market", "is the market open": "market",
    "cate tranzactii am facut azi": "summary", "cum a fost ziua azi": "summary",
    "rezultate azi": "summary",
    # onboarding
    "cum functioneaza": "help", "how does this work": "help",
    "ajutor": "help", "ce poti face": "help",
    "salut": "greeting", "hello": "greeting", "buna": "greeting",
    "multumesc": "thanks", "thanks": "thanks", "ok": "thanks",
}

print("\n── plain lookups are answered locally ──")
for _t, _want in LOOKUPS.items():
    _got = qa.resolve(_t)
    check(f"'{_t}' → {_want}", _got == _want, f"got {_got}")

# Anything needing judgement, comparison, explanation or an opinion. A canned
# reply here is a downgrade, not a saving.
REAL_QUESTIONS = [
    "de ce am pierdut azi la eurusd si ce ar trebui sa schimb",
    "explica-mi ce inseamna R multiple si cum se calculeaza",
    "crezi ca ar trebui sa cresc riscul acum ca sunt pe profit?",
    "what does ADX mean and why does it block my trades",
    "should i switch strategy given the last three losses",
    "ce parere ai despre piata de azi",
    "is momentum better than mean reversion for this pair right now",
    "?",
]

print("\n── real questions still reach the assistant ──")
for _t in REAL_QUESTIONS:
    check(f"'{_t[:46]}' → AI", qa.resolve(_t) is None, f"got {qa.resolve(_t)}")

print("\n── and the trade layer keeps priority ──")
# quick_answers runs AFTER trade intent, so these never reach it in the bot.
# Asserted anyway: if it ever claimed one, an order would become a status card.
for _t in ("cumpara EURUSD", "close it", "sell usdcad", "all in"):
    check(f"'{_t}' is not claimed as a lookup", qa.resolve(_t) is None,
          f"got {qa.resolve(_t)}")
check("a slash command is never claimed", qa.resolve("/status") is None)
check("empty input is never claimed", qa.resolve("") is None)
check("None is safe", qa.resolve(None) is None)

print("\n── every key routes to a handler that exists ──")
for _key in set(LOOKUPS.values()):
    check(f"'{_key}' is routed", _key in tg._QUICK_ROUTES)
for _key, _fn in tg._QUICK_ROUTES.items():
    check(f"'{_key}' is callable", callable(_fn))
check("the resolver's keys and the routes agree",
      {k for k, _ in qa._INTENTS} | {"thanks"} == set(tg._QUICK_ROUTES),
      f"{ {k for k, _ in qa._INTENTS} | {'thanks'} } vs { set(tg._QUICK_ROUTES) }")

print("\n── a long message is a conversation, not a lookup ──")
_long = "cat am in cont " + "si ".join(["ce ar trebui sa fac"] * 3)
check("past the word limit it goes to the assistant",
      qa.resolve(_long) is None, f"got {qa.resolve(_long)}")
check("the limit is where the module says it is",
      len("cat am in cont".split()) <= qa.MAX_WORDS < len(_long.split()))

print("\n── a failing handler falls back instead of eating the message ──")
_orig = tg._QUICK_ROUTES.get("status")
try:
    def _boom(_cid):
        raise RuntimeError("handler exploded")
    tg._QUICK_ROUTES["status"] = _boom
    check("a raising route returns False, so the AI still answers",
          tg._handle_quick_answer("1", "cat am in cont") is False)
finally:
    tg._QUICK_ROUTES["status"] = _orig

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — common questions cost no quota.")
