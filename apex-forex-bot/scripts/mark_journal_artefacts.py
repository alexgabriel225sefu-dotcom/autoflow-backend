"""Mark journal rows that are not this account's trades. Never deletes.

WHY

A backfill wrote rows from a different cTrader account into user
7585109158's journal. Four carry balance 470,586.42 on an account that held
3,002.96 that day; one of those is US400, an index this platform cannot trade.
A fifth is XAUUSD -779.74 against balance 3,002.96 — 26% of the account in one
trade, where the sizing cap (max_total_risk / maxpos) makes 2.5% the ceiling.

Together they are -27,365 against +264 of real trading, so /report told the
client their net P&L was -$27,052.

WHY MARK AND NOT DELETE

The journal is the one record a client cannot reconstruct, and the tax export
reads it. A row that is wrong is still evidence that something wrote it. Each
row gets an `artefact` field naming the reason; user_store.load_trades()
excludes marked rows from every total by default.

THE RULES, AND WHY THEY ARE THESE

Deliberately conservative and each independently checkable against the row
itself, so a reader can audit a decision without trusting this script:

  foreign_account     balance more than 10x the journal's median balance.
                      An account does not gain two orders of magnitude and
                      come back.
  foreign_instrument  a symbol forex.is_tradeable() rejects. The platform is
                      forex + metals on a positive allowlist; anything else
                      cannot have been opened here.
  impossible_size     |netPnl| above 20% of the row's own balance. The cap is
                      2.5% per trade; 20% is eight times that, so this cannot
                      fire on a real trade even with slippage and a gap.

The 20% threshold was checked against this journal: the largest genuine loss
is 4.46% of its balance, so there is a factor of four between the worst real
row and the rule.

USAGE

Dry run (prints what it would mark, changes nothing):
    python3 scripts/mark_journal_artefacts.py <user_id>

Apply:
    python3 scripts/mark_journal_artefacts.py <user_id> --apply

Idempotent: a row already marked is left alone and reported as such.
"""
import sys

sys.path.insert(0, ".")
from apex import journal_audit, user_store  # noqa: E402

FOREIGN_BALANCE_MULTIPLE = journal_audit.FOREIGN_BALANCE_MULTIPLE
IMPOSSIBLE_PNL_FRACTION = journal_audit.IMPOSSIBLE_PNL_FRACTION
classify = journal_audit.classify


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().split("USAGE")[-1])
        sys.exit(1)
    uid = args[0]
    apply = "--apply" in sys.argv

    rows = user_store.load_trades(uid, include_artefacts=True)
    if not rows:
        print(f"No journal for {uid}.")
        return
    print(f"Loaded {len(rows)} rows for {uid}.")

    out, newly, already, med = journal_audit.plan(rows)
    print(f"Median balance: {med:,.2f}  "
          f"(foreign above {med * FOREIGN_BALANCE_MULTIPLE:,.2f})\n")

    if already:
        print(f"{len(already)} row(s) already marked, left alone:")
        for r in already:
            print(f"   {r.get('time')}  {r.get('symbol'):<7} "
                  f"{r.get(user_store.ARTEFACT_FIELD)}")
        print()

    if not newly:
        print("Nothing new to mark.")
        return

    print(f"Would mark {len(newly)} row(s):")
    total = 0.0
    for r in newly:
        pnl = r.get("netPnl") or 0.0
        total += float(pnl)
        print(f"   {r.get('time')}  {r.get('symbol'):<7} "
              f"net={float(pnl):>12,.2f}  balance={float(r.get('balance') or 0):>12,.2f}"
              f"  -> {r[user_store.ARTEFACT_FIELD]}")
    print(f"\n   removed from the account's totals: {total:>+,.2f}")
    real = [r for r in out if not user_store.is_artefact(r)]
    real_net = sum(float(r.get("netPnl") or 0) for r in real)
    print(f"   {len(real)} real trades remain, net {real_net:>+,.2f}")

    if not apply:
        print("\nDry run — nothing written. Re-run with --apply.")
        return

    user_store.save_trades(uid, out)
    back = user_store.load_trades(uid, include_artefacts=True)
    print(f"\nWritten. {len(back)} rows stored, "
          f"{sum(1 for r in back if user_store.is_artefact(r))} marked, "
          f"{len(user_store.load_trades(uid))} visible to totals.")


if __name__ == "__main__":
    main()
