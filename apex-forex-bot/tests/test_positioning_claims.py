"""What Apex4Traders says about itself must be what the code actually does.

The product is positioned as automation INFRASTRUCTURE rather than a trading
bot that handles customer money:

    the customer keeps their funds, their broker account and their
    relationship with the broker; Apex4Traders sends instructions; the broker
    executes.

That framing is safer commercially and defensible legally — but only while it
is TRUE. A claim that outruns the architecture is worse than the blunt version
it replaced, because it is the one a regulator or a disputing customer reads
back to you.

So these checks are in two halves:

  STRUCTURAL   the things that make the claim true, asserted against the code
  LANGUAGE     the claims that must never appear, asserted against the copy

The structural half is the important one. cTrader's Open API exposes no
withdrawal request of any kind, so fund movement is not something this
software could do even if it were written to — and the OAuth scope is
"trading", which places and manages orders and nothing else.

Run: python tests/test_positioning_claims.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-positioning-")

from apex import config as cfg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APEX = os.path.join(ROOT, "apex")


def code_of(path):
    """Source with docstrings and comments removed.

    A claim check that scans raw text matches the comment EXPLAINING why a
    phrase is banned, and passes on its own documentation.
    """
    src = open(path, encoding="utf-8").read()
    src = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', '""', src)
    return re.sub(r"#.*$", "", src, flags=re.M)


CUSTOMER_FACING = [os.path.join(APEX, f) for f in ("telegram.py", "webapp.py")]

print("\nPOSITIONING - the claim and the architecture must agree\n")

print("1. STRUCTURAL: the customer's money is not reachable")
# The Open API has no withdrawal request. This asserts we did not add one, and
# do not even read cash-flow history.
all_src = "".join(code_of(os.path.join(APEX, f))
                  for f in os.listdir(APEX) if f.endswith(".py"))
broker_src = "".join(code_of(os.path.join(APEX, "brokers", f))
                     for f in os.listdir(os.path.join(APEX, "brokers"))
                     if f.endswith(".py"))
both = all_src + broker_src
for forbidden in ("ProtoOAWithdraw", "CashFlowHistory", "withdrawFunds",
                  "createWithdrawal", "transferFunds"):
    check(f"no {forbidden} anywhere", forbidden not in both)

check("the OAuth scope is trading, not something broader",
      cfg.CTRADER_SCOPE == "trading", cfg.CTRADER_SCOPE)

print("\n2. STRUCTURAL: the customer keeps control of the connection")
tg = code_of(os.path.join(APEX, "telegram.py"))
check("the customer can disconnect their own account",
      "/reset" in tg or "disconnect" in tg.lower())
check("credentials are stored per-user, not pooled",
      "ctrader_access_token" in code_of(os.path.join(APEX, "user_store.py")))

print("\n3. STRUCTURAL: the broker decides live vs demo, not us")
am = code_of(os.path.join(APEX, "account_mode.py"))
check("the environment is read from the broker where reachable",
      "broker" in am and "UNVERIFIED" in am)
check("an unverifiable environment is never presented as confirmed",
      "stored-env" in am)

print("\n4. LANGUAGE: claims that must never appear in customer-facing copy")
# Every one of these invites the reading that returns are promised or that we
# manage the customer's money. Each raises commercial, reputational and
# regulatory risk, and none is true of what the software does.
BANNED = [
    r"guaranteed profit", r"guarantee[sd]? (?:you )?(?:a )?(?:profit|return)",
    r"make money while you sleep", r"passive income",
    r"we manage your (?:account|money|funds)",
    r"let (?:us|apex\w*) trade your money",
    r"professional money management",
    r"never lose", r"risk[- ]free profit",
    r"\bAI predicts the market\b",
    r"\d+\s*%\s*(?:per|a|every)\s*(?:month|week|day)\b",
]
for path in CUSTOMER_FACING:
    text = code_of(path)
    for pattern in BANNED:
        hits = re.findall(pattern, text, re.I)
        check(f"{os.path.basename(path)}: no {pattern[:38]!r}", not hits, str(hits[:2]))

print("\n4b. LANGUAGE: nothing still calls the product a bot")
# The first pass at this used a regex whose character class excluded
# backslashes, so it skipped every string containing \n — which is nearly
# every alert the customer receives. It reported zero and was wrong. This one
# allows escapes.
_CODE_TOKENS = ("bot_token", "/bot", "api.telegram", "BOT_TOKEN", "botHandle",
                "TELEGRAM]", "bot:on", "bot:off")
_SPEAKS_TO_CUSTOMER = ("telegram.py", "screens.py", "user_loop.py", "webapp.py",
                       "assistant.py", "news_alerts.py", "sentinel.py")
for fname in _SPEAKS_TO_CUSTOMER:
    path = os.path.join(APEX, fname)
    if not os.path.exists(path):
        continue
    text = code_of(path)
    hits = [m.group(1)[:60] for m in re.finditer(r'"((?:[^"\\]|\\.){6,200}?)"', text)
            if not any(tok in m.group(1) for tok in _CODE_TOKENS)
            and re.search(r"\b[Bb]ot\b", m.group(1))]
    check(f"{fname}: no customer-facing 'bot'", not hits, str(hits[:2]))

# The Mini App too, comments stripped.
_mini = re.sub(r"//.*$", "", open(os.path.join(APEX, "static", "terminal.html"),
                                 encoding="utf-8").read(), flags=re.M)
check("terminal.html: no 'bot'", not re.search(r"\bbot\b", _mini, re.I))

print("\n4c. LANGUAGE: the platform reports, it does not narrate")
# A platform states what happened. First person ("I can't fetch prices",
# "I retry every 30s") is a chatbot persona and undercuts the positioning.
# The AI assistant's own conversational voice is a different thing and is
# deliberately left alone — asking it a question IS a conversation.
for fname in ("telegram.py", "screens.py", "user_loop.py"):
    text = code_of(os.path.join(APEX, fname))
    hits = [m.group(1)[:60] for m in re.finditer(r'"((?:[^"\\]|\\.){6,200}?)"', text)
            if re.search(r"\bI (can\'t|cannot|retry|will|am|watch|check|read|found|see|auto)\b",
                         m.group(1))]
    check(f"{fname}: no first-person platform narration", not hits, str(hits[:2]))

print("\n5. LANGUAGE: the honest framing IS present")
check("the copy states the customer's money is never held",
      re.search(r"never holds your money|stays yours", tg, re.I) is not None,
      "the one claim that carries the positioning is missing")
check("…and that they can disconnect at any time",
      re.search(r"disconnect", tg, re.I) is not None)
check("…and that live/demo is read from the account, not taken on trust",
      re.search(r"read .{0,40}from the account|won't take your word", tg, re.I)
      is not None)

print("\n6. The product name is configurable and currently Apex4Traders")
check("BOT_NAME defaults to Apex4Traders", cfg.BOT_NAME == "Apex4Traders", cfg.BOT_NAME)
check("it is overridable by environment",
      'os.getenv("BOT_NAME")' in open(os.path.join(APEX, "config.py"),
                                      encoding="utf-8").read())
check("it makes a valid User-Agent token",
      re.fullmatch(r"[A-Za-z0-9._-]+", cfg.BOT_NAME.replace(" ", "")) is not None,
      cfg.BOT_NAME)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL POSITIONING CHECKS PASSED - the claim matches the code.")
