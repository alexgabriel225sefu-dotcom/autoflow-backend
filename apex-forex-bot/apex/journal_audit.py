"""Which journal rows are not this account's trades, and why.

One place for the rules, because two callers apply them: the migration script
and the Telegram admin command. A second copy would be free to drift, and the
two would then disagree about a client's money.

The rules are deliberately conservative and each is checkable against the row
itself, so a decision can be audited without trusting this code:

  foreign_account     balance above 10x the journal's median. An account does
                      not gain two orders of magnitude and come back.
  foreign_instrument  a symbol forex.is_tradeable() rejects. The platform is
                      forex plus metals on a positive allowlist, so anything
                      else cannot have been opened here.
  impossible_size     |netPnl| above 20% of the row's own balance. Sizing caps
                      a trade at max_total_risk / maxpos — 2.5% by default — so
                      20% is eight times a full-risk loss.

Measured against the journal these were written for: the worst genuine row is
4.46% of its balance, a factor of four below the 20% rule.
"""
import statistics

from apex import forex, user_store

FOREIGN_BALANCE_MULTIPLE = 10.0
IMPOSSIBLE_PNL_FRACTION = 0.20


def _pnl(row):
    v = row.get("netPnl")
    return row.get("grossPnl") if v is None else v


def classify(row, median_balance):
    """Return the reason this row is not a real trade, or None."""
    bal, sym, pnl = row.get("balance"), row.get("symbol"), _pnl(row)

    try:
        if bal and median_balance and float(bal) > median_balance * FOREIGN_BALANCE_MULTIPLE:
            return "foreign_account"
    except (TypeError, ValueError):
        pass

    if sym and not forex.is_tradeable(str(sym)):
        return "foreign_instrument"

    try:
        if bal and pnl is not None and float(bal) > 0:
            if abs(float(pnl)) > float(bal) * IMPOSSIBLE_PNL_FRACTION:
                return "impossible_size"
    except (TypeError, ValueError):
        pass
    return None


def median_balance(rows):
    vals = []
    for r in rows:
        try:
            b = r.get("balance")
            if b not in (None, ""):
                vals.append(float(b))
        except (TypeError, ValueError):
            continue
    return statistics.median(vals) if vals else 0.0


def plan(rows):
    """(all_rows_after, newly_flagged, already_marked, median).

    Pure: returns what the journal WOULD become and never writes. Rows already
    marked keep their existing reason — re-running must not re-decide, or a
    rule change would silently relabel history.
    """
    med = median_balance(rows)
    out, newly, already = [], [], []
    for r in rows:
        if user_store.is_artefact(r):
            already.append(r)
            out.append(r)
            continue
        reason = classify(r, med)
        if reason:
            marked = {**r, user_store.ARTEFACT_FIELD: reason}
            out.append(marked)
            newly.append(marked)
        else:
            out.append(r)
    return out, newly, already, med
