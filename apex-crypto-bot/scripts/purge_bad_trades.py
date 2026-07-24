"""One-off fix: purge the corrupted phantom trade record(s) from a user's
tax journal (the six-figure netPnl produced by the stale-price-on-symbol-
switch bug, fixed in commit 9a25046b — this only cleans up data logged
BEFORE that fix, it doesn't need to run again after).

Safe by default: prints what it WOULD remove and does nothing else. Pass
--apply to actually overwrite the journal in Redis.

Run from apex-crypto-bot/ (needs the same env vars as the running bot —
REDIS_URL or UPSTASH_REDIS_REST_URL/TOKEN, and PRODUCT):

    python3 scripts/purge_bad_trades.py <user_id> [--apply] [--threshold 50000]
"""
import json
import sys

sys.path.insert(0, ".")
from apex import user_store  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python3 scripts/purge_bad_trades.py <user_id> [--apply] [--threshold N]")
        sys.exit(1)
    user_id = args[0]
    apply = "--apply" in sys.argv
    threshold = 50000.0
    if "--threshold" in sys.argv:
        threshold = float(sys.argv[sys.argv.index("--threshold") + 1])

    trades = user_store.load_trades(user_id)
    print(f"Loaded {len(trades)} trade records for user {user_id}.")

    bad = [t for t in trades if abs(t.get("netPnl") or 0) > threshold
           or abs(t.get("grossPnl") or 0) > threshold]
    good = [t for t in trades if t not in bad]

    if not bad:
        print(f"Nothing found above the ${threshold:,.0f} sanity threshold — journal looks clean.")
        return

    print(f"\nFound {len(bad)} corrupted record(s):")
    for t in bad:
        print(f"  {t.get('time')}  {t.get('symbol')}  entry={t.get('entry')}  "
              f"exit={t.get('exit')}  netPnl={t.get('netPnl')}")

    if not apply:
        print(f"\nDry run only — nothing changed. Re-run with --apply to remove "
              f"the {len(bad)} record(s) above and keep the remaining {len(good)}.")
        return

    key = f"{user_store._NS}:trades:{user_id}"
    payload = json.dumps(good)
    if user_store._USE_REDIS:
        user_store._redis_set(key, payload)
    else:
        with open(user_store._path(user_id) + ".trades", "w") as f:
            f.write(payload)
    print(f"\nDone — removed {len(bad)} record(s), {len(good)} remain in the journal.")


if __name__ == "__main__":
    main()
