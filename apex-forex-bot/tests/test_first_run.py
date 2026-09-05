"""A brand-new client, from the first message to the first trade.

Drives telegram.dispatch_command — the same function the poll loop calls — so
this is what a real person gets, not a paraphrase of it. Nothing is sent: the
Telegram transport is replaced with a sink that records every reply.

The point is not that each handler returns a string. It is that the JOURNEY
holds together: the bot never promises a command that does not exist, never
answers in a language the client did not choose, never shows a number it has
not got, and never leaves someone stuck with no next step. Every one of those
has shipped broken at least once — a promised /settings that was never
implemented, a Romanian reply on an English interface, `PnL: +$0.00` on a
position $22 down, a reconnect that re-ran onboarding from scratch.

Run: python tests/test_first_run.py
"""
import os
import re
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "900001")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-first-")

from apex import telegram as tg      # noqa: E402
from apex import user_store          # noqa: E402
from apex import user_loop           # noqa: E402
from apex import access              # noqa: E402
from apex import control             # noqa: E402

USER = "900001"
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# ── the world this client lives in ───────────────────────────
STATE = {"record": {}, "dash": {}}
SENT = []

tg._post_message = lambda cid, text, extra=None: SENT.append(
    {"text": text, "extra": extra})
tg._broker = None
control.event = lambda *a, **k: None
access.is_admin = lambda cid: False       # a CLIENT, not the owner
access.is_allowed = lambda cid: True
user_store.load = lambda cid: dict(STATE["record"])
user_store.get_user = lambda cid: dict(STATE["record"])
user_store.save = lambda cid, d: STATE["record"].update(d)
user_store.update = lambda cid, upd: STATE["record"].update(upd)
user_store.load_trades = lambda cid: list(STATE.get("trades", []))
user_loop.get_dash = lambda uid: dict(STATE["dash"])
user_loop.live_balance = lambda uid: None
user_loop.is_running = lambda uid: bool(STATE["record"].get("active"))
user_loop.restart = lambda *a, **k: None
tg._restart_user_loop = lambda *a, **k: True


def say(msg):
    """One client message. Returns (replies, traceback-or-None)."""
    del SENT[:]
    err = None
    try:
        tg.dispatch_command(USER, msg, msg_id=1)
    except Exception:
        err = traceback.format_exc()
    return list(SENT), err


def text_of(replies):
    return "\n".join(r["text"] for r in replies)


def buttons_of(replies):
    import json
    out = []
    for r in replies:
        ex = r.get("extra")
        if isinstance(ex, str):
            try:
                ex = json.loads(ex)
            except Exception:
                ex = {}
        mk = (ex or {}).get("reply_markup") if isinstance(ex, dict) else None
        if isinstance(mk, str):
            try:
                mk = json.loads(mk)
            except Exception:
                mk = {}
        for row in (mk or {}).get("inline_keyboard", []):
            out += [b.get("text", "") for b in row]
    return out


# Commands the bot actually dispatches — the ground truth for "does this exist".
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "telegram.py"), encoding="utf-8").read()
_DISPATCH = SRC[SRC.index("def dispatch_command"):]
HANDLED = set(re.findall(r'"(/[a-z0-9]+)"', _DISPATCH))


_TAGS = re.compile(r"</?[a-zA-Z][^>]*>")
_URLS = re.compile(r"https?://\S+|\b[\w.-]+\.(?:com|org|net|ai|io|space)\S*")


def promises_only_real_commands(label, body):
    """Every /command the copy shows a client must actually be dispatched.

    Strip HTML and URLs first: `</b>` and `console.groq.com/keys` are not
    promises, and counting them turns this into a test that cries wolf.
    """
    clean = _URLS.sub(" ", _TAGS.sub(" ", body))
    promised = set(re.findall(r"(?<![\w/])(/[a-z][a-z0-9]*)", clean))
    missing = sorted(c for c in promised if c not in HANDLED)
    check(f"{label}: every command it names exists", not missing, str(missing))


print("\n══ 1. the very first message, before anything is set up ══")
replies, err = say("/start")
check("/start does not raise", err is None, (err or "")[-300:])
check("it answers at all", bool(replies))
body = text_of(replies)
check("it does not show a balance it has not got", "$0.00" not in body, body[:120])
promises_only_real_commands("/start", body)
check("it gives the client a next step",
      bool(buttons_of(replies)) or "/" in body, body[:120])

print("\n══ 2. they ask what this thing is ══")
for msg in ("/help", "cum functioneaza", "what is this"):
    replies, err = say(msg)
    check(f"'{msg}' does not raise", err is None, (err or "")[-200:])
    check(f"'{msg}' answers", bool(replies))
    promises_only_real_commands(f"'{msg}'", text_of(replies))

print("\n══ 3. every command the help text advertises actually runs ══")
replies, _ = say("/allcommands")
advertised = sorted(set(re.findall(r"^(/[a-z]+)", text_of(replies), re.M)))
check("the list is not empty", len(advertised) > 5, str(advertised))
broken = []
for cmd in advertised:
    r, e = say(cmd)
    if e is not None:
        broken.append(f"{cmd}: {e.strip().splitlines()[-1][:60]}")
check("none of them raise", not broken, str(broken))

print("\n══ 4. they connect a broker, then look around ══")
STATE["record"] = {
    "active": True, "paper": False, "symbol": "EURUSD", "strategy": "momentum",
    "risk": 0.01, "sl_pips": 35.0, "tp_pips": 70.0, "timeframe": "15m",
    "broker": "ctrader", "ctrader_account_id": 47765456, "ctrader_env": "demo",
    "paper_balance": 3000.0, "max_trades_day": 15, "maxpos": 1,
    "_connected_ctrader": True, "verbose_alerts": False,
}
STATE["dash"] = {
    "broker": "cTrader (demo)", "mode": "🧪 Demo", "balance": 3000.0,
    "startBalance": 3000.0, "symbol": "EURUSD", "currentSymbol": "EURUSD",
    "strategy": "⚡ Momentum — joins a move already running",
    "trades": [], "openPosition": None, "openCount": 0, "maxpos": 1,
    "lastTickTs": None, "lastTick": "—", "currentPrice": 1.15800,
    "market": {"symbol": "EURUSD", "volatility": "calm 🟢", "momentum": "neutral",
               "trend": "BULLISH", "volume": "normal", "atrPct": 0.05, "rsi": 51.0},
    "regime": {"regime": "trending", "label": "trending market"},
    "skips": [], "skipsToday": 0,
}
for msg in ("/status", "/strategy", "/risk", "/settings", "/market", "/report",
            "/summary", "/news", "/verbose", "/resume"):
    r, e = say(msg)
    check(f"{msg} works for a connected client", e is None, (e or "")[-200:])
    check(f"{msg} replies", bool(r))

print("\n══ 5. the numbers shown are the numbers held ══")
r, _ = say("/status")
body = text_of(r)
check("the balance is the real one", "3000.00" in body, body[:160])
check("no position is reported when none is open",
      "No open position" in body, body[:200])
check("the method named is the one configured", "Momentum" in body, body[:200])

STATE["dash"]["openPosition"] = {
    "symbol": "EURUSD", "side": "BUY", "units": 17000.0, "entryPrice": 1.15808,
    "stopLoss": 1.15486, "takeProfit": 1.16536, "pnlUsd": -23.80, "pnlPips": -14.0,
}
STATE["dash"]["openCount"] = 1
r, _ = say("/status")
body = text_of(r)
check("an open position shows its REAL P&L, not zero",
      "23.80" in body and "+$0.00" not in body, body[:240])
check("and the pips alongside it", "-14.0 pips" in body, body[:240])

print("\n══ 6. they type in their own language, and get English back ══")
RO = re.compile(r"(?<![A-Za-z])(?:cu|și|si|pentru|acum|dar|tranzacție|tranzactie|"
                r"poziție|pozitie|deschid|închid|inchid|piața|piata|câștig|castig|"
                r"pierdere|bani|tău|tau|vinde|cumpără|cumpara|contul)(?![A-Za-z])",
                re.IGNORECASE)
for msg in ("cat am in cont", "care e strategia mea", "de ce nu tranzactioneaza",
            "ce risc am", "e piata deschisa", "salut", "multumesc"):
    r, e = say(msg)
    check(f"'{msg}' is understood", e is None and bool(r), (e or "")[-200:])
    ro = RO.findall(text_of(r))
    check(f"'{msg}' is answered in English", not ro, f"Romanian: {ro[:4]}")

print("\n══ 7. nothing dangerous happens by accident ══")
opened = []
user_loop.force_trade = lambda uid, side, sym=None, lots=None: (
    opened.append((side, sym)) or {"ok": True, "side": side, "symbol": sym,
                                   "price": 1.158, "units": 1000, "sl": 1.15,
                                   "tp": 1.17, "spread": 0.1})
for msg in ("cat am in cont", "how am i doing", "care e strategia mea",
            "de ce nu tranzactioneaza", "salut", "ce stiri sunt azi",
            "if i close now how much would i have", "daca inchid acum cat am"):
    del opened[:]
    say(msg)
    check(f"'{msg}' opens no trade", not opened, str(opened))

del opened[:]
say("cumpara EURUSD")
check("but an explicit order still opens one", opened == [("BUY", "EUR_USD")],
      str(opened))

print("\n══ 8. the unhappy paths ══")
for msg in ("", "   ", "?", "/nonexistent", "aaaaaaaa", "🙂", "/risk 999",
            "/risk abc", "/symbol NOTAPAIR", "/sl -5", "/tp 0"):
    r, e = say(msg)
    check(f"{msg!r} does not raise", e is None, (e or "")[-200:])

r, _ = say("/risk 999")
check("an out-of-range risk is refused, not applied",
      STATE["record"].get("risk") == 0.01, str(STATE["record"].get("risk")))

print("\n══ 9. a client with no broker is never left stuck ══")
STATE["record"] = {"active": False}
STATE["dash"] = {}
for msg in ("/status", "/report", "/summary", "cat am in cont", "/strategy"):
    r, e = say(msg)
    check(f"{msg} on an empty account does not raise", e is None, (e or "")[-200:])
    check(f"{msg} still says something", bool(r), "silence leaves them stuck")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    for f in failures[:25]:
        print(f"   • {f}")
    sys.exit(1)
print("✅ ALL TESTS PASSED — a first-time client gets a coherent journey.")
