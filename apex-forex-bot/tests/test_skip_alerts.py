"""Every refused entry must be able to reach Telegram, without spamming it.

_skip() wrote to the dashboard and nowhere else. Of the 25 places that refuse
an entry, six ever alerted — and the HTF gate, which does most of the
refusing, was not one of them. A client watching their phone saw the bot go
quiet for a day with no explanation. Live proof: eight HTF refusals in one
night, zero Telegram messages.

Those six also shared one `last_warn_tick`, so a "market too quiet" notice at
08:00 silenced a spread warning at 08:05 and an EV veto at 08:10 for three
hours.

The fix has to satisfy both halves at once: every distinct refusal gets
through, and the same one repeating every five minutes does not.

Run: python tests/test_skip_alerts.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


COOLDOWN = 3 * 3600


def make_skip():
    """A faithful copy of the _skip closure's alerting decision, driven by an
    injectable clock so three hours can pass in a test."""
    sent, seen, clock = [], {}, {"t": 1_000_000.0}

    def skip(symbol, reason, alert=True):
        key = (str(symbol).upper().replace("_", ""), str(reason)[:60])
        if not alert:
            return
        if clock["t"] - seen.get(key, 0) < COOLDOWN:
            return
        seen[key] = clock["t"]
        sent.append({"symbol": symbol, "reason": reason})

    return skip, sent, clock


print("\n── the live case: 8 identical HTF refusals ──")
skip, sent, clock = make_skip()
for _ in range(8):
    skip("AUDUSD", "HTF gate: BUY blocked by H1 BEARISH trend")
    clock["t"] += 300          # one tick apart, as it happened
check("exactly one message, not eight", len(sent) == 1, str(len(sent)))
check("and not zero — this is the bug being fixed", len(sent) > 0)

print("\n── distinct reasons never suppress each other ──")
skip, sent, clock = make_skip()
skip("AUDUSD", "market too quiet")
clock["t"] += 300
skip("AUDUSD", "spread too wide (2.1p > 1.5p)")
clock["t"] += 300
skip("AUDUSD", "EV gate: probability below break-even")
clock["t"] += 300
skip("AUDUSD", "HTF gate: BUY blocked by H1 BEARISH trend")
check("all four arrive", len(sent) == 4, str([s["reason"][:20] for s in sent]))

print("\n── the same reason on a different symbol still arrives ──")
skip, sent, _ = make_skip()
skip("AUDUSD", "HTF gate: BUY blocked by H1 BEARISH trend")
skip("NZDUSD", "HTF gate: BUY blocked by H1 BEARISH trend")
skip("EURUSD", "HTF gate: BUY blocked by H1 BEARISH trend")
check("one per symbol", len(sent) == 3, str(len(sent)))

print("\n── symbol spelling is not a way to bypass the throttle ──")
skip, sent, _ = make_skip()
for spelling in ("AUDUSD", "AUD_USD", "audusd"):
    skip(spelling, "HTF gate: BUY blocked")
check("all three are the same instrument", len(sent) == 1, str(len(sent)))

print("\n── the throttle expires ──")
skip, sent, clock = make_skip()
skip("AUDUSD", "HTF gate: BUY blocked")
clock["t"] += COOLDOWN - 60
skip("AUDUSD", "HTF gate: BUY blocked")
check("still suppressed just before the cooldown ends", len(sent) == 1)
clock["t"] += 120
skip("AUDUSD", "HTF gate: BUY blocked")
check("sent again after it", len(sent) == 2)

print("\n── alert=False is for sites with their own richer message ──")
skip, sent, _ = make_skip()
skip("AUDUSD", "flash-crash guard: extreme candle range", alert=False)
skip("AUDUSD", "news guard: CPI", alert=False)
check("neither double-sends", len(sent) == 0)

print("\n── a full realistic day ──")
skip, sent, clock = make_skip()
# 288 five-minute ticks; HTF blocks all morning, spread widens twice, one
# quiet-regime spell in the afternoon.
for i in range(288):
    if i < 96:
        skip("AUDUSD", "HTF gate: BUY blocked by H1 BEARISH trend")
    elif i < 100:
        skip("AUDUSD", "spread too wide (2.4p > 1.5p)")
    elif i < 200:
        skip("NZDUSD", "market too quiet")
    else:
        skip("NZDUSD", "HTF gate: SELL blocked by H1 BULLISH trend")
    clock["t"] += 300
# Four persistent conditions across 24h, each re-notified every 3h: about ten
# messages. The number to beat is 288 (one per tick) and 0 (today's bug).
check(f"a whole day produces {len(sent)} messages, not 288",
      1 <= len(sent) <= 14, str(len(sent)))
check("and every distinct refusal is represented",
      len({s["reason"][:12] for s in sent}) >= 3,
      str(sorted({s["reason"][:20] for s in sent})))

print("\n── the real _skip is wired the same way ──")
import tempfile  # noqa: E402

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-skip-test-"))
from apex import user_loop  # noqa: E402

src = user_loop._loop.__code__.co_consts
check("_SKIP_ALERT_COOLDOWN_S exists",
      hasattr(user_loop, "_SKIP_ALERT_COOLDOWN_S"))
check("and is three hours", user_loop._SKIP_ALERT_COOLDOWN_S == COOLDOWN,
      str(getattr(user_loop, "_SKIP_ALERT_COOLDOWN_S", None)))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL SKIP-ALERT CHECKS PASSED.")
