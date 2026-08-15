"""The floating P&L of an open position — the number that was always $0.00.

/status printed `PnL: +$0.00` for the entire life of every open trade, and the
web terminal showed "Floating +$0.00" beside it. Neither was a formatting
slip: they read `currentPnl` / `pnlUsd` off the dashboard's openPosition, and
the per-user loop that runs in production never wrote either one. `currentPnl`
in particular had two readers and, in the whole repo, zero writers — so the
`.get(key, 0)` default was the only value it ever had.

A live trade that reads exactly $0.00 while it is $22 down is worse than no
number at all: it looks like a bot that has stopped working, and it hides the
one figure a client watches while a position is open.

What is pinned here: the loop computes the number, /status shows it, and a
zero is never invented when the number genuinely isn't there yet.

Run: python tests/test_open_pnl.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-pnl-")

from apex import telegram as tg          # noqa: E402
from apex import user_loop               # noqa: E402
from apex import strategy_api            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# The position this shipped broken on: a real USDCHF long on the demo account,
# entry 0.81232, last price 0.81091, 13,000 units. 14.1 pips against, ≈ $22.60.
POS = {"symbol": "USDCHF", "side": "BUY", "units": 13000.0,
       "entryPrice": 0.81232, "stopLoss": 0.80913, "takeProfit": 0.81963}
PRICE = 0.81091


print("\n── the loop computes it ──")
priced = user_loop._price_open_position(POS, "USDCHF", PRICE)
check("pnlUsd is produced", priced.get("pnlUsd") is not None)
check("and it is the real loss, not zero",
      priced.get("pnlUsd") is not None and abs(priced["pnlUsd"] + 22.60) < 0.15,
      f"got {priced.get('pnlUsd')}")
check("pnlPips agrees with it",
      priced.get("pnlPips") is not None and abs(priced["pnlPips"] + 14.1) < 0.2,
      f"got {priced.get('pnlPips')}")
check("a SELL at the same prices is the mirror image",
      abs(user_loop._price_open_position({**POS, "side": "SELL"}, "USDCHF",
                                         PRICE)["pnlUsd"]
          - 22.60) < 0.15)
check("the broker's dict is not mutated", "pnlUsd" not in POS)

print("\n── and it never takes the trading loop down ──")
for bad, label in ((None, "no position"),
                   ({"symbol": "USDCHF"}, "no entry price"),
                   ({**POS, "entryPrice": None}, "null entry"),
                   ({**POS, "side": "?"}, "unknown side"),
                   ({**POS, "units": 0}, "zero units")):
    try:
        user_loop._price_open_position(bad, "USDCHF", PRICE)
        check(f"{label} → survives", True)
    except Exception as e:
        check(f"{label} → survives", False, f"raised {e!r}")
check("a null price survives too",
      user_loop._price_open_position(POS, "USDCHF", None) is not None)


print("\n── /status shows it ──")
DASH = {"broker": "cTrader (demo)", "mode": "🧪 Demo", "balance": 3008.05,
        "startBalance": 3011.25, "symbol": "USDCHF", "trades": [],
        "openPosition": priced, "openCount": 1, "maxpos": 1,
        "lastTickTs": None, "lastTick": "—"}
out = tg._build_status(DASH)
check("the loss appears in the message", "22.60" in out, out)
check("shown as a loss, not a gain", "−$22.60" in out or "-$22.60" in out, out)
check("pips are shown alongside", "-14.1 pips" in out, out)
check("no phantom +$0.00", "+$0.00" not in out, out)

print("\n── and an absent number is never rendered as a zero ──")
bare = dict(DASH, openPosition={k: v for k, v in POS.items()})
out_bare = tg._build_status(bare)
check("a position with no P&L yet does not claim $0.00",
      "$0.00" not in out_bare, out_bare)
check("it says so instead", "PnL" in out_bare and "…" in out_bare, out_bare)


print("\n── the key nothing ever wrote is gone ──")
readers = []
for sub in ("apex",):
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, sub)):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            for i, line in enumerate(open(path, encoding="utf-8"), 1):
                if "currentPnl" in line and not line.lstrip().startswith("#"):
                    readers.append(f"{fn}:{i}")
check("no code reads currentPnl any more", not readers, str(readers))


print("\n── the help copy counts the same methods /strategy offers ──")
strategy_api.load_builtins()
n = len(strategy_api.available())
controls = tg._with_counts(tg._CONTROLS_TEXT)
allcmds = tg._with_counts(tg._HELP_ADMIN)
check("the placeholder is filled in", "STRATCOUNT" not in controls + allcmds)
check(f"/controls names the real count ({n})", f"{n} available" in controls)
check(f"/allcommands names it too ({n})", f"{n} methods" in allcmds)
check("no hardcoded count survives in the source",
      not re.search(r"\(10 available", open(
          os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()))

print("\n── commands the help promises actually exist ──")
SRC = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
dispatch = SRC[SRC.index("def dispatch_command"):]
handled = set()
for m in re.finditer(r'cmd_l\s*(?:==|in)\s*(\("[^)]+\)|"[^"]+")', dispatch):
    handled.update(re.findall(r'"(/[a-z0-9]+)"', m.group(1)))
promised = set(re.findall(r"^/([a-z]+)", allcmds, re.M))
missing = sorted("/" + c for c in promised if "/" + c not in handled)
check("every command /allcommands lists is dispatched", not missing, str(missing))


print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — open positions report a real P&L.")
