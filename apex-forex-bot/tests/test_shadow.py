"""Tests for refused-setup tracking (apex/shadow.py).

The whole point is to answer "was blocking that trade right?" with a fact. So
these check the accounting is honest — especially that a phantom cannot flatter
itself when a single bar spans both its stop and its target.

Run: python tests/test_shadow.py
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

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-shadow-test-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import shadow, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


UID = "shadow-test"


def reset():
    shadow.clear(UID)


# BUY EURUSD @1.1000, stop 1.0985 (15p), target 1.1030 (30p) → 1R = 15 pips
def open_buy():
    return shadow.open_shadow(UID, "EURUSD", "BUY", 1.1000, 1.0985, 1.1030,
                              blocked_by="AI disagreed",
                              reasoning="structure looks weak", confidence=76)


print("\n── a refused setup is recorded once ──")
reset()
ph = open_buy()
check("phantom created", ph is not None and ph["side"] == "BUY")
check("levels stored", ph["sl"] == 1.0985 and ph["tp"] == 1.1030)
check("the reason is kept", "structure" in ph["reasoning"])
check("a second one on the same symbol is refused", open_buy() is None)
check("only one is open", len(shadow._load(UID)["open"]) == 1)

print("\n── it resolves as a win when target comes first ──")
reset()
open_buy()
evts = shadow.update(UID, "EURUSD", high=1.1032, low=1.0995, price=1.1030)
check("one event", len(evts) == 1, str(evts))
check("resolved", evts[0]["kind"] == "resolved")
p = evts[0]["phantom"]
check("outcome is target", p["outcome"] == "TAKE_PROFIT", p["outcome"])
check("+2R reported", abs(p["r"] - 2.0) < 0.05, str(p["r"]))
check("pips reported", abs(p["pips"] - 30) < 1, str(p["pips"]))
check("it leaves the open list", shadow._load(UID)["open"] == [])

print("\n── and as a loss when the stop comes first ──")
reset()
open_buy()
p = shadow.update(UID, "EURUSD", high=1.1005, low=1.0980, price=1.0985)[0]["phantom"]
check("outcome is stop", p["outcome"] == "STOP_LOSS", p["outcome"])
check("−1R reported", abs(p["r"] + 1.0) < 0.05, str(p["r"]))

print("\n── a bar spanning both is counted as the STOP ──")
# We cannot know the order within a bar. Assuming the good fill is how a
# phantom flatters itself, which would make the filter look worse than it is.
reset()
open_buy()
p = shadow.update(UID, "EURUSD", high=1.1040, low=1.0980, price=1.1010)[0]["phantom"]
check("pessimistic read wins", p["outcome"] == "STOP_LOSS", p["outcome"])

print("\n── SELL is mirrored correctly ──")
reset()
shadow.open_shadow(UID, "EURUSD", "SELL", 1.1000, 1.1015, 1.0970, "AI")
p = shadow.update(UID, "EURUSD", high=1.1005, low=1.0968, price=1.0970)[0]["phantom"]
check("a SELL reaching its lower target is a win",
      p["outcome"] == "TAKE_PROFIT" and p["r"] > 1.5, f"{p['outcome']} {p['r']}")

print("\n── progress is reported once per half-R step ──")
reset()
open_buy()
e1 = shadow.update(UID, "EURUSD", 1.1008, 1.0999, 1.1008)   # ~+0.5R
check("crossing +0.5R reports once", len(e1) == 1 and e1[0]["kind"] == "milestone",
      str(e1))
e2 = shadow.update(UID, "EURUSD", 1.1008, 1.1007, 1.1008)   # same step
check("staying at the same step is silent", e2 == [], str(e2))
e3 = shadow.update(UID, "EURUSD", 1.1016, 1.1008, 1.1016)   # ~+1R
check("a new step reports again", len(e3) == 1 and e3[0]["kind"] == "milestone")

print("\n── other symbols are untouched ──")
reset()
open_buy()
check("a bar for another pair resolves nothing",
      shadow.update(UID, "GBPUSD", 2.0, 0.5, 1.3) == [])
check("the EURUSD phantom is still open",
      len(shadow._load(UID)["open"]) == 1)

print("\n── the scoreboard answers the actual question ──")
reset()
# Three refused setups that would have lost (−1R each) and one that would have
# won (+2R): net −1R. Note two losses against one 2R win is exactly breakeven —
# the fixture needs a third loss for the sign to mean anything.
for sym in ("EURUSD", "GBPUSD", "AUDUSD"):
    shadow.open_shadow(UID, sym, "BUY", 1.1000, 1.0985, 1.1030, "AI")
    shadow.update(UID, sym, 1.1005, 1.0980, 1.0985)
shadow.open_shadow(UID, "USDJPY", "BUY", 1.1000, 1.0985, 1.1030, "AI")
shadow.update(UID, "USDJPY", 1.1032, 1.0995, 1.1030)

sc = shadow.scoreboard(UID)
check("all four counted", sc["n"] == 4, str(sc))
check("three would have lost", sc["wouldHaveLost"] == 3, str(sc))
check("one would have won", sc["wouldHaveWon"] == 1, str(sc))
check("net R is negative — the filter saved money",
      sc["filterCostR"] < 0, str(sc["filterCostR"]))
check("and the verdict says so", "earning its keep" in sc["verdict"], sc["verdict"])

print("\n── the sign is not faked when it is genuinely a tie ──")
reset()
for sym in ("EURUSD", "GBPUSD"):
    shadow.open_shadow(UID, sym, "BUY", 1.1000, 1.0985, 1.1030, "AI")
    shadow.update(UID, sym, 1.1005, 1.0980, 1.0985)          # two × −1R
shadow.open_shadow(UID, "USDJPY", "BUY", 1.1000, 1.0985, 1.1030, "AI")
shadow.update(UID, "USDJPY", 1.1032, 1.0995, 1.1030)          # one × +2R
tie = shadow.scoreboard(UID)
check("two 1R losses against one 2R win is a wash",
      abs(tie["filterCostR"]) < 0.1, str(tie["filterCostR"]))
check("and it says so rather than picking a side",
      "too close to call" in tie["verdict"], tie["verdict"])

print("\n── bad input is refused rather than half-recorded ──")
reset()
check("no price → nothing", shadow.open_shadow(UID, "EURUSD", "BUY", None,
                                               1.0, 1.2, "x") is None)
check("HOLD is not a direction", shadow.open_shadow(UID, "EURUSD", "HOLD",
                                                    1.1, 1.0, 1.2, "x") is None)
check("empty state scores nothing", shadow.scoreboard(UID)["n"] == 0)
check("update on an empty state is safe",
      shadow.update(UID, "EURUSD", 1.1, 1.0, 1.05) == [])

print("\n── state survives a restart ──")
reset()
open_buy()
check("the phantom is persisted on the user record",
      bool((user_store.load(UID) or {}).get("shadow_trades", {}).get("open")))

reset()

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL SHADOW-TRACKING CHECKS PASSED.")
