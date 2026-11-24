"""A healthy 1h feed must not be called frozen every 15 minutes.

The frozen-feed detector counted 3 ticks (~15 min) without a new closed candle.
On a 1h chart the newest closed bar changes hourly, so it fired constantly:
it dropped a good cTrader connection and spread-blocked the symbol.
"""
import os
import sys
import tempfile

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-stale-test-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apex import user_loop  # noqa: E402

failed = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        failed.append(name)


iv = user_loop._LOOP_INTERVAL
limit = user_loop._stale_tick_limit

check("1h feed is not frozen after 15 minutes", limit("1h") * iv > 3600 + 900)
check("1h feed counts as frozen once two bars and grace have passed",
      limit("1h") * iv >= 2 * 3600 + 600)
check("4h waits longer than 1h", limit("4h") > limit("1h"))
check("short timeframes stay close to the old 15-minute behaviour",
      limit("1m") == 3 and limit("5m") <= 4)
check("unknown timeframe never drops below the floor", limit(None) >= 3)

if failed:
    print("\nFAILED (%d):" % len(failed))
    for f in failed:
        print("  - " + f)
    sys.exit(1)
print("\nAll stale-feed checks passed.")
