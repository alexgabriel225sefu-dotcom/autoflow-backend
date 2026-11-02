"""Build and maintain a persistent OHLC corpus — the thing the bot has never had.

Every strategy question worth asking ("does this edge survive costs", "does it
hold out of sample", "which regime does it work in") needs price history. The
bot has none: it fetches a live window each tick, Twelve Data caps a request at
5000 bars and cTrader at 1000, and nothing is kept. So nothing can be measured,
only asserted.

This collects history once and keeps it. Runs are resumable and idempotent:
each run walks backwards from the oldest bar already stored, so stopping it
half way and re-running loses nothing and duplicates nothing.

    python scripts/collect_history.py --days 30
    python scripts/collect_history.py --symbols EURUSD,XAUUSD --interval 5min
    python scripts/collect_history.py --status

Free-tier Twelve Data allows 800 requests/day at 8/min, and one request returns
up to 5000 bars — about 3.5 trading days of M1. Eight symbols to 30 days of M1
is roughly 70 requests, so a full build fits comfortably inside one free day
and a daily top-up costs a handful.

Storage is CSV under data/history/, one file per symbol and interval, sorted
oldest-first and deduplicated on the bar timestamp. Plain text on purpose: it
survives a schema change, and it can be inspected without this script.
"""
import argparse
import calendar
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PAPER_TRADING", "true")

import requests  # noqa: E402
from apex import config as cfg  # noqa: E402

BASE_URL = "https://api.twelvedata.com"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "history")
FIELDS = ["time", "open", "high", "low", "close", "volume"]
MAX_BARS_PER_CALL = 5000
# Free tier is 8 requests/minute. 8.5s between calls keeps us just under it
# without burning the retry path, which costs far more wall-clock time.
MIN_CALL_INTERVAL_S = 8.5

_last_call = [0.0]


def _throttle():
    wait = MIN_CALL_INTERVAL_S - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def path_for(symbol, interval):
    safe = symbol.replace("/", "").replace("_", "").upper()
    return os.path.join(DATA_DIR, f"{safe}_{interval}.csv")


def load(symbol, interval):
    """Stored bars, oldest first. Missing file is simply an empty corpus."""
    p = path_for(symbol, interval)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append({
                    "time": int(row["time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"] or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue          # skip a torn line rather than lose the file
    out.sort(key=lambda c: c["time"])
    return out


def merge(existing, incoming):
    """Union of two bar lists, deduped on timestamp, oldest first.

    Later data wins on a collision: a bar can be revised by the provider after
    it first appears, and the newer version is the corrected one.
    """
    by_ts = {c["time"]: c for c in existing}
    by_ts.update({c["time"]: c for c in incoming})
    return [by_ts[t] for t in sorted(by_ts)]


def save(symbol, interval, bars):
    os.makedirs(DATA_DIR, exist_ok=True)
    p = path_for(symbol, interval)
    tmp = p + ".tmp"
    # Write to a temp file and rename: a run interrupted mid-write must not
    # leave a truncated corpus behind.
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for c in bars:
            w.writerow({k: c.get(k, "") for k in FIELDS})
    os.replace(tmp, p)
    return p


def _fetch(symbol, interval, end_dt, api_key):
    """One page of bars ending at end_dt, oldest first. [] when exhausted."""
    _throttle()
    params = {
        "symbol": symbol.replace("_", "/").upper(),
        "interval": interval,
        "outputsize": MAX_BARS_PER_CALL,
        "apikey": api_key,
        "order": "ASC",
        "end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "UTC",
    }
    r = requests.get(f"{BASE_URL}/time_series", params=params, timeout=30)
    data = r.json()
    if isinstance(data, dict) and data.get("code") == 429:
        print("    rate limited — waiting 65s")
        time.sleep(65)
        return _fetch(symbol, interval, end_dt, api_key)
    if "values" not in data:
        msg = data.get("message", data) if isinstance(data, dict) else data
        raise RuntimeError(f"{symbol}: {msg}")
    bars = []
    for row in data["values"]:
        try:
            ts = int(calendar.timegm(
                time.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")))
        except ValueError:
            ts = int(calendar.timegm(
                time.strptime(row["datetime"], "%Y-%m-%d")))
        bars.append({
            "time": ts,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume") or 0),
        })
    bars.sort(key=lambda c: c["time"])
    return bars


# ── cTrader source ───────────────────────────────────────────────────────
# Preferred over Twelve Data when an account is linked: the bars come from the
# same broker the bot executes on, so backtests price against the venue that
# will actually fill the orders, and no extra API key is involved. cTrader caps
# a single request at 1000 bars, so depth comes from paging rather than from
# one big response.
_CT_INTERVALS = {"1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m",
                 "1h": "1h", "4h": "4h", "1day": "1d"}


def _ctrader_broker(user_id=None):
    """A broker bound to a linked cTrader account, or None with a reason."""
    from apex import user_store, user_loop
    uid = user_id
    if not uid:
        actives = user_store.all_active() or []
        if not actives:
            return None, "no active user with a linked cTrader account"
        uid = actives[0]
    user = user_store.load(uid)
    if not user.get("ctrader_access_token"):
        return None, f"user {uid} has no cTrader token"
    broker, _cfg = user_loop._make_broker(user)
    return broker, str(uid)


def collect_ctrader(symbol, interval, days, broker, max_calls=40):
    """Extend the corpus backwards using the broker's own trendbars."""
    ct_interval = _CT_INTERVALS.get(interval)
    if not ct_interval:
        raise RuntimeError(f"cTrader has no period for interval {interval!r}")

    existing = load(symbol, interval)
    target_start = time.time() - days * 86400
    added = calls = 0

    # Recent end first — that is what a daily top-up needs.
    try:
        fresh = broker.get_candles(symbol, ct_interval, 1000)
        calls += 1
        before = len(existing)
        existing = merge(existing, fresh or [])
        added += len(existing) - before
    except Exception as e:
        print(f"  ! recent fetch failed: {e}")

    while calls < max_calls and existing:
        if existing[0]["time"] <= target_start:
            break
        try:
            page = broker.get_candles(symbol, ct_interval, 1000,
                                      to_ts=existing[0]["time"] - 1)
        except Exception as e:
            print(f"  ! backfill stopped: {e}")
            break
        calls += 1
        if not page:
            print("  broker returned no older bars — corpus is as deep as it goes")
            break
        before = len(existing)
        existing = merge(existing, page)
        gained = len(existing) - before
        added += gained
        if gained == 0:
            print("  no new bars in that page — reached the broker's limit")
            break
        print(f"    +{gained:,} bars, now back to "
              f"{datetime.fromtimestamp(existing[0]['time'], timezone.utc):%Y-%m-%d}")

    if existing:
        save(symbol, interval, existing)
    return {"symbol": symbol, "bars": len(existing), "added": added, "calls": calls}


def collect(symbol, interval, days, api_key, max_calls=40):
    """Extend the corpus backwards until it reaches `days` of history.

    Walks from the oldest bar already stored, so re-running only fetches what
    is missing. Stops early when the provider stops returning older data —
    the free tier does not serve unlimited M1 depth, and pretending otherwise
    would spin forever.
    """
    existing = load(symbol, interval)
    target_start = datetime.now(timezone.utc) - timedelta(days=days)

    if existing:
        oldest = datetime.fromtimestamp(existing[0]["time"], timezone.utc)
        newest = datetime.fromtimestamp(existing[-1]["time"], timezone.utc)
        print(f"  have {len(existing):,} bars  {oldest:%Y-%m-%d} → {newest:%Y-%m-%d}")
    else:
        oldest = None
        print("  no local history yet")

    # 1) Top up the recent end first — that is what a daily run needs.
    added = 0
    calls = 0
    try:
        fresh = _fetch(symbol, interval, datetime.now(timezone.utc), api_key)
        calls += 1
        before = len(existing)
        existing = merge(existing, fresh)
        added += len(existing) - before
    except Exception as e:
        print(f"  ! recent fetch failed: {e}")

    # 2) Then extend backwards toward the target start date.
    while calls < max_calls:
        if not existing:
            break
        oldest = datetime.fromtimestamp(existing[0]["time"], timezone.utc)
        if oldest <= target_start:
            break
        try:
            page = _fetch(symbol, interval, oldest - timedelta(seconds=1), api_key)
        except Exception as e:
            print(f"  ! backfill stopped: {e}")
            break
        calls += 1
        if not page:
            print("  provider returned no older data — corpus is as deep as it goes")
            break
        before = len(existing)
        existing = merge(existing, page)
        gained = len(existing) - before
        added += gained
        if gained == 0:
            print("  no new bars in that page — reached the provider's limit")
            break
        print(f"    +{gained:,} bars, now back to "
              f"{datetime.fromtimestamp(existing[0]['time'], timezone.utc):%Y-%m-%d}")

    if existing:
        save(symbol, interval, existing)
    return {"symbol": symbol, "bars": len(existing), "added": added, "calls": calls}


def status(symbols, interval):
    print(f"\n{'symbol':>10} {'bars':>10} {'from':>12} {'to':>12} {'gap %':>7}")
    print("-" * 56)
    for s in symbols:
        bars = load(s, interval)
        if not bars:
            print(f"{s:>10} {'—':>10} {'—':>12} {'—':>12} {'—':>7}")
            continue
        a = datetime.fromtimestamp(bars[0]["time"], timezone.utc)
        b = datetime.fromtimestamp(bars[-1]["time"], timezone.utc)
        # Expected bars assumes a 24/5 market; weekends are legitimate gaps.
        step = {"1min": 60, "5min": 300, "15min": 900, "30min": 1800,
                "1h": 3600, "4h": 14400, "1day": 86400}.get(interval, 60)
        span = bars[-1]["time"] - bars[0]["time"]
        expected = (span / step) * (5 / 7)
        gap = max(0.0, 1 - len(bars) / expected) * 100 if expected > 0 else 0
        print(f"{s:>10} {len(bars):>10,} {a:%Y-%m-%d:>12} {b:%Y-%m-%d:>12} {gap:>6.1f}%")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=",".join(cfg.AUTOPILOT_UNIVERSE[:8]),
                    help="comma-separated, e.g. EURUSD,XAUUSD")
    ap.add_argument("--interval", default="1min",
                    help="1min, 5min, 15min, 1h, 1day")
    ap.add_argument("--days", type=int, default=30,
                    help="how far back to reach")
    ap.add_argument("--max-calls", type=int, default=40,
                    help="request budget per symbol per run")
    ap.add_argument("--status", action="store_true",
                    help="report what is already stored and exit")
    ap.add_argument("--source", choices=("auto", "ctrader", "td"), default="auto",
                    help="auto prefers the linked cTrader account and falls "
                         "back to Twelve Data")
    ap.add_argument("--user", default=None,
                    help="cTrader account to borrow (defaults to the first "
                         "active user)")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if args.status:
        status(symbols, args.interval)
        return 0

    # Prefer the broker the bot actually trades on: same prices, same venue,
    # no extra API key. Twelve Data stays as the fallback for when no account
    # is linked.
    broker = None
    if args.source in ("auto", "ctrader"):
        broker, note = _ctrader_broker(args.user)
        if broker:
            print(f"Source: cTrader (account of user {note})")
        elif args.source == "ctrader":
            print(f"cTrader unavailable — {note}")
            return 1
        else:
            print(f"cTrader unavailable ({note}) — falling back to Twelve Data")

    key = cfg.TWELVE_DATA_KEY
    if not broker:
        if not key:
            print("No cTrader account linked and TWELVE_DATA_KEY is not set. "
                  "Either link a cTrader account (the bot already uses one to "
                  "trade) or add a free key from twelvedata.com to .env.")
            return 1
        print("Source: Twelve Data")

    print(f"\nCollecting {args.interval} history for {len(symbols)} symbols, "
          f"target {args.days} days\n")
    total_added = total_calls = 0
    for s in symbols:
        print(f"{s}")
        try:
            if broker:
                r = collect_ctrader(s, args.interval, args.days, broker,
                                    args.max_calls)
            else:
                r = collect(s, args.interval, args.days, key, args.max_calls)
        except Exception as e:
            print(f"  ! {e}\n")
            continue
        total_added += r["added"]
        total_calls += r["calls"]
        print(f"  → {r['bars']:,} bars stored (+{r['added']:,} this run, "
              f"{r['calls']} requests)\n")

    print(f"Done. {total_added:,} new bars, {total_calls} requests "
          f"(free tier allows 800/day).")
    status(symbols, args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
