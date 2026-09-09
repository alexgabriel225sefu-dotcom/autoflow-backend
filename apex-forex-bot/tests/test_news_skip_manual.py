"""A trade the client opened by hand is theirs to hold through a release.

THE RULE

The news flatten closes open positions ahead of a high-impact release. When
NEWS_EXIT_SKIP_MANUAL is on, it leaves alone the position the client opened
themselves with /buy or /sell.

This follows the line the loop already draws for strategy exits:

    elif action == "CLOSE" and open_pos and dash.get("manualHold"):
        # /buy - /sell trades belong to the USER: the strategy engine
        # must not close them ... SL/TP rule them.

WHAT THIS CAN AND CANNOT DO — READ BEFORE TRUSTING IT

`manualHold` is a single boolean on the dash meaning "the position this loop
is TRACKING was opened by hand". It is not a per-position marker, and it
cannot become one: the account-wide list comes from broker.get_all_positions()
and a broker does not record which software placed an order.

So the guarantee is exactly this and no more: the TRACKED position is skipped
while manualHold is set. A hand-opened position that is not the loop's current
focus is indistinguishable from a bot position and is still closed. That is a
real limit, not an oversight, and the test below pins it so nobody later reads
the setting as a promise it cannot keep.

WHY IT IS OFF BY DEFAULT

The weekend flatten — the precedent this exit was built on — closes every
position regardless of origin, because a gap does not care who opened the
trade. NFP does not either: the client's hand-opened XAUUSD is blown through
its stop the same way the bot's was on 2026-09-04 (-116.67, stop overshot by
11.1 pips). Protection is the safer default; skipping it is a deliberate
choice by someone who wants to hold their own trade through a print.

Run: python tests/test_news_skip_manual.py
"""
import ast
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PRODUCT", "forex")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-newsman-")

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


SRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
CFG = open(os.path.join(ROOT, "apex", "config.py"), encoding="utf-8").read()

print("\n1. The setting exists and can be changed without a deploy")
check("NEWS_EXIT_SKIP_MANUAL is read from the environment",
      'NEWS_EXIT_SKIP_MANUAL' in CFG and 'os.getenv("NEWS_EXIT_SKIP_MANUAL")' in CFG)
from apex import config as cfg_mod  # noqa: E402
check("it defaults to OFF — protection is the safer default",
      cfg_mod.NEWS_EXIT_SKIP_MANUAL is False,
      f"got {getattr(cfg_mod, 'NEWS_EXIT_SKIP_MANUAL', 'missing')!r}")

print("\n2. It reaches the loop, so the environment variable actually does something")
# The defect this guards: a key absent from _make_broker's per-user config means
# the loop reads the module default and the env var silently does nothing.
check("the key is in the per-user config the loop reads",
      "NEWS_EXIT_SKIP_MANUAL" in SRC.split("def _loop(")[0],
      "without this, setting it in Render would look like it worked and would not")

print("\n3. The filter is applied where the targets are chosen")
_blk = SRC[SRC.index("_news_targets = []"):]
_blk = _blk[:_blk.index("_news_user = user_store.load")]
_code = "\n".join(l.split("#")[0] for l in _blk.splitlines())
check("the loop calls the filter before the close loop",
      "_news_skip_manual(" in _code,
      "filtering must happen at target selection, not inside the close loop")
check("it passes the setting through",
      "NEWS_EXIT_SKIP_MANUAL" in _code)

print("\n4. Behaviour, against the REAL function the loop calls")
from apex.user_loop import _news_skip_manual as skip  # noqa: E402

def syms(*a):
    return [p["symbol"] for p in skip(*a)]

POS = [{"symbol": "XAUUSD"}, {"symbol": "EURUSD"}]
check("manual tracked position is skipped when the setting is on",
      syms(POS, "XAUUSD", True, True) == ["EURUSD"])
check("the bot's other position is still protected",
      "EURUSD" in syms(POS, "XAUUSD", True, True))
check("nothing is skipped when the setting is off",
      syms(POS, "XAUUSD", True, False) == ["XAUUSD", "EURUSD"])
check("nothing is skipped when the position is not manual",
      syms(POS, "XAUUSD", False, True) == ["XAUUSD", "EURUSD"])
check("it matches the way the rest of the loop matches symbols",
      syms([{"symbol": "eurusd"}], "EUR_USD", True, True) == []
      and syms([{"symbol": "EUR/USD"}], "EURUSD", True, True) == [],
      "_nrm folds case and the _ / - separators; using it here rather than a "
      "second rule keeps this comparison in step with startup recovery")
check("an unmatched symbol fails in the SAFE direction — it stays protected",
      syms([{"symbol": " xauusd "}], "XAUUSD", True, True) == [" xauusd "],
      "_nrm does not strip whitespace, so a stray space means the position is "
      "closed before the release rather than silently left exposed")
check("a malformed entry is kept, never dropped by accident",
      len(skip([{"nope": 1}], "XAUUSD", True, True)) == 1)
check("an empty list is safe", skip([], "XAUUSD", True, True) == [])
check("None is safe", skip(None, "XAUUSD", True, True) == [])

print("\n5. The limit is real — proven by behaviour, not by a comment")
check("a hand-opened position that is NOT tracked is still closed",
      syms([{"symbol": "GBPUSD"}], "XAUUSD", True, True) == ["GBPUSD"],
      "the broker list carries no origin; only the tracked one can be known")
check("with no tracked symbol nothing is skipped at all",
      syms(POS, None, True, True) == ["XAUUSD", "EURUSD"])

print("\n6. With the setting off — the shipped default — nothing changes")
check("the target list is returned untouched",
      skip(POS, "XAUUSD", True, False) is not POS
      and [p["symbol"] for p in skip(POS, "XAUUSD", True, False)]
      == [p["symbol"] for p in POS],
      "a copy, so the caller's list is never mutated, but the same contents")

print("\n7. It still cannot close anything by itself")
check("the filter only removes targets, never adds one",
      len(skip(POS, "XAUUSD", True, True)) <= len(POS)
      and all(p in POS for p in skip(POS, "XAUUSD", True, True)))

print("\n" + "=" * 62)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED — the tracked hand-opened trade is the client's to hold.")
