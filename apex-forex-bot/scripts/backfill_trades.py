"""Fill the gaps in an existing trade journal from cTrader's own deal history.

WHY THIS EXISTS

The reconciliation path that journals positions the broker closed on its own —
where SL and TP hits land, so where most trades are recorded — was dropping the
exit price, the direction and the position id, and was writing the balance from
before each trade's own P&L. That is fixed going forward. This fills in what was
already written, so a client's history stops showing trades with no exit, no R
multiple, no duration, and a direction the screen had to guess at.

WHAT IT WILL AND WILL NOT DO

  * It only ever fills a field that is MISSING. A value already in the journal
    is never overwritten, even when the broker disagrees — a backfill that
    rewrites recorded history is worse than one that leaves gaps, because
    afterwards nobody can tell which rows were touched.
  * It never invents. No interpolation, no "close enough". A row the broker has
    nothing for is left exactly as it is.
  * It refuses ambiguity. A journal row with no position id is matched on
    symbol, net P&L to the cent, and close time — and if more than one deal
    fits, the row is skipped and reported, never assigned to a guess.
  * It is a DRY RUN unless you pass --apply. The dry run prints precisely what
    would change.
  * It is idempotent. Running it twice fills nothing the second time.

DIRECTION

The side is derived from arithmetic, not from the closing deal's own tradeSide:
a long is closed by a sell, so reading that field naively would invert every
historical direction. A position was long exactly when the exit price moved the
same way as the profit. Where entry, exit or gross is missing, the side is left
blank rather than guessed. See CtraderBroker.get_deal_history.

USAGE

    # see what would change, for one client
    python scripts/backfill_trades.py --user 7585109158

    # ...and for everyone
    python scripts/backfill_trades.py --all

    # write it
    python scripts/backfill_trades.py --user 7585109158 --apply

    # how far back to read (default 120 days)
    python scripts/backfill_trades.py --all --days 365 --apply

A backup of each journal is written before anything is changed.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Fields this tool is allowed to fill. Deliberately short: these are the ones
# the broker actually answers for. Anything else stays out of reach.
FILLABLE = ("exit", "side", "positionId", "balance", "grossPnl", "costUsd",
            "netPnl", "entry", "openedAt")

# How close a row's recorded time must be to the deal's close time before they
# are considered the same event, when there is no position id to match on. The
# journal stamps its own clock at reconciliation, which can trail the broker's
# close by a polling interval or two.
_TIME_SLACK_S = 90 * 60


def _ts(row):
    """The row's close time as a unix timestamp, or None."""
    raw = str(row.get("time") or "")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(raw, fmt).timestamp())
        except ValueError:
            continue
    return None


def _nrm(sym):
    return str(sym or "").replace("_", "").replace("/", "").upper()


def _money_eq(a, b):
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


def match(row, deals):
    """(deal, reason) for one journal row. deal is None when nothing applies.

    A position id is an exact key and is trusted outright. Without one, the row
    has to be identified by what it does carry, and the bar is deliberately
    high: same instrument, same net P&L to the cent, and a close time within
    the polling slack. Two candidates means we cannot tell them apart, and the
    row is left alone.
    """
    pid = row.get("positionId")
    if pid is not None and str(pid) in deals:
        return deals[str(pid)], "position id"
    if pid is not None:
        return None, "position id not in the broker's window"

    net, when = row.get("netPnl"), _ts(row)
    if net is None or when is None:
        return None, "no position id, and no net P&L or time to match on"

    hits = [d for d in deals.values()
            if _nrm(d["symbol"]) == _nrm(row.get("symbol"))
            and _money_eq(d["netPnl"], net)
            and abs(d["closedAt"] - when) <= _TIME_SLACK_S]
    if len(hits) == 1:
        return hits[0], "symbol + net P&L + time"
    if len(hits) > 1:
        return None, f"ambiguous — {len(hits)} deals fit equally well"
    return None, "no deal matches"


def plan_row(row, deal):
    """{field: new_value} for the gaps this deal can fill. Never overwrites."""
    src = {
        "exit": deal.get("exitPrice"),
        "entry": deal.get("entryPrice"),
        "side": deal.get("side"),
        "positionId": deal.get("positionId"),
        "balance": deal.get("balance"),
        "grossPnl": deal.get("grossPnl"),
        "costUsd": deal.get("commissionUsd"),
        "netPnl": deal.get("netPnl"),
        # Only where the opening leg was inside the window the broker was asked
        # for. A position opened before it has no recoverable start, and the
        # trade screen already says "Not recorded" for that.
        "openedAt": (datetime.utcfromtimestamp(deal["openedAt"])
                     .strftime("%Y-%m-%d %H:%M:%S")
                     if deal.get("openedAt") else None),
    }
    out = {}
    for k in FILLABLE:
        if row.get(k) is None and src.get(k) is not None:
            out[k] = src[k]
    return out


def run_user(uid, days, apply, out_dir):
    from apex import user_store, user_loop

    trades = user_store.load_trades(uid) or []
    gaps = [r for r in trades if any(r.get(k) is None for k in FILLABLE)]
    print(f"\n── {uid} ─────────────────────────────────────────")
    print(f"   {len(trades)} trades in the journal, {len(gaps)} with a gap")
    if not gaps:
        print("   nothing to do")
        return 0

    user = user_store.load(uid) or {}
    if user.get("paper", True) or not user.get("ctrader_access_token"):
        print("   skipped: no live cTrader account on this record")
        return 0

    broker = user_loop._make_broker(user)
    now = int(time.time())
    res = broker.get_deal_history(now - days * 86400, now)
    # An empty answer must never be read as "the broker has no deals" — that
    # would report every row as unmatchable and look like a clean run.
    if not res.get("ok"):
        print(f"   ABORTED: the broker's deal history could not be read "
              f"({res.get('error') or 'no answer'}). Nothing was changed.")
        return 1
    deals = res["deals"]
    print(f"   {len(deals)} closing deals from the broker over {days} days")

    filled, reasons = 0, {}
    for row in trades:
        if not any(row.get(k) is None for k in FILLABLE):
            continue
        deal, why = match(row, deals)
        if deal is None:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        patch = plan_row(row, deal)
        if not patch:
            continue
        filled += 1
        when = str(row.get("time") or "")[:16]
        print(f"   {when} {str(row.get('symbol') or '?'):8} "
              f"[{why}] " + ", ".join(f"{k}={v}" for k, v in patch.items()))
        if apply:
            row.update(patch)

    for why, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"   {n:3} left alone: {why}")

    if not apply:
        print(f"   DRY RUN — {filled} rows would be filled. "
              f"Re-run with --apply to write.")
        return 0
    if not filled:
        print("   nothing to write")
        return 0

    # The backup goes down BEFORE the write, and the write is refused if it
    # cannot be made. A journal is the one record a client cannot reconstruct.
    os.makedirs(out_dir, exist_ok=True)
    backup = os.path.join(out_dir, f"trades-{uid}-{int(time.time())}.json")
    try:
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(user_store.load_trades(uid) or [], f, indent=1)
    except Exception as e:
        print(f"   ABORTED: could not write the backup ({e}). Nothing changed.")
        return 1
    print(f"   backup: {backup}")

    user_store.save_trades(uid, trades)
    print(f"   WROTE {filled} rows")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--user", help="one Telegram chat id")
    ap.add_argument("--all", action="store_true", help="every active user")
    ap.add_argument("--days", type=int, default=120,
                    help="how far back to read the broker's deals (default 120)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without it this is a dry run")
    ap.add_argument("--backup-dir", default=os.path.join(ROOT, "backups"))
    a = ap.parse_args()

    if not a.user and not a.all:
        ap.error("pass --user <id> or --all")

    from apex import user_store
    # all_active() is the only enumeration the store offers. That is the right
    # set anyway: a client who is not active has no live broker link to read a
    # deal history through.
    ids = [a.user] if a.user else [str(u) for u in (user_store.all_active() or [])]
    if not ids:
        print("no users found")
        return 0

    print("APPLYING — journals will be written (a backup is taken first)."
          if a.apply else "DRY RUN — nothing will be written.")

    rc = 0
    for uid in ids:
        try:
            rc |= run_user(uid, a.days, a.apply, a.backup_dir)
        except Exception as e:
            print(f"\n── {uid} ── FAILED: {type(e).__name__}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
