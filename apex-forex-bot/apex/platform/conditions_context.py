"""Context conditions — time, and the state of the account.

Split from conditions.py for size, not for meaning: these register into the
same library through `_define` and are imported at the end of that module, so
`conditions.available()` lists them from the first import.

What separates them from the rest is their input. The others read candles;
these read `snapshot.ts`, `snapshot.open_positions` and `snapshot.spread_pips`.
None of them reads the clock - the timestamp is a captured field, which is
what lets a decision made on a Friday be replayed on a Monday and still say
Friday.
"""

from apex.platform.conditions import (
    P, ConditionMisconfigured, ConditionUnavailable, _define, _minutes, _utc)


# -- session ----------------------------------------------------------------
def _c_session(p, snap):
    cid = "session"
    from apex import market
    # snapshot.session is used when the edge captured one; otherwise it is
    # derived from the snapshot's own ts. Either way no clock is read here.
    if snap.session:
        active = [str(snap.session)] if isinstance(snap.session, str) \
            else list(snap.session)
    else:
        active = market.session(_utc(snap).hour)["active"]
    bad = [s for s in p["sessions"] if not isinstance(s, str)]
    if bad:
        raise ConditionMisconfigured(
            f"{cid}.sessions must be names, got {bad!r}")
    norm = {a.strip().lower().replace(" ", "") for a in active}
    # Both sides are lowercased. "London" from a form must match "london"
    # from the session table, or the condition would be permanently false and
    # look exactly like a quiet market.
    want = {s.strip().lower().replace("_", "").replace(" ", "")
            for s in p["sessions"]}
    if not want:
        raise ConditionMisconfigured(f"{cid}.sessions cannot be empty")
    unknown = sorted(want - {"london", "newyork", "tokyo", "sydney"})
    if unknown:
        raise ConditionMisconfigured(
            f"{cid}.sessions has unknown session(s): {', '.join(unknown)}")
    hit = want & norm
    return bool(hit), f"open: {', '.join(sorted(norm)) or 'none'}"


_define("session",
        params={"sessions": P(list, ("london",))},
        check=_c_session,
        bias=None,
        doc="Whether one of the named FX sessions is open on this bar.")


# -- time window ------------------------------------------------------------
def _c_time_window(p, snap):
    cid = "time_window"
    start = _minutes(p["from"], cid, "from")
    end = _minutes(p["to"], cid, "to")
    if start == end:
        raise ConditionMisconfigured(
            f"{cid}: 'from' and 'to' are both {p['from']} — an empty window "
            f"can never be satisfied, so the rule would never trade")
    now = (_utc(snap).hour * 60 + _utc(snap).minute
           + p["utc_offset_minutes"]) % 1440
    # A window ending before it starts wraps past midnight (22:00 -> 02:00).
    inside = start <= now < end if start < end else (now >= start or now < end)
    return inside, (f"{now // 60:02d}:{now % 60:02d} vs "
                    f"{p['from']}-{p['to']}")


_define("time_window",
        params={"from": P(str, "07:00"), "to": P(str, "16:00"),
                # An explicit offset, not a named zone: DST would silently
                # move the window by an hour twice a year, and a client who
                # backtested one window would then be trading another.
                "utc_offset_minutes": P(int, 0, min=-720, max=840)},
        check=_c_time_window,
        bias=None,
        doc="Whether the bar falls inside a time-of-day window.")


# -- weekday ----------------------------------------------------------------
def _c_weekday(p, snap):
    cid = "weekday"
    days = p["days"]
    if not days:
        raise ConditionMisconfigured(f"{cid}.days cannot be empty")
    bad = [d for d in days
           if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6]
    if bad:
        raise ConditionMisconfigured(
            f"{cid}.days must be whole numbers 0-6 (Monday=0), got {bad!r}")
    wd = _utc(snap).weekday()
    names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    return wd in days, f"{names[wd]} (allowed: " \
                       f"{', '.join(names[d] for d in sorted(set(days)))})"


_define("weekday",
        params={"days": P(list, (0, 1, 2, 3, 4))},
        check=_c_weekday,
        bias=None,
        doc="Whether the bar falls on an allowed weekday (Monday = 0, UTC).")


# -- max open positions -----------------------------------------------------
def _c_max_positions(p, snap):
    cid = "max_positions"
    n = len(snap.positions_for()) if p["scope"] == "symbol" \
        else snap.open_count
    return n < p["max"], (f"{n} open ({p['scope']}), limit {p['max']}")


_define("max_positions",
        params={"max": P(int, 1, min=1, max=1000),
                "scope": P(str, "symbol", choices=("symbol", "account"))},
        check=_c_max_positions,
        bias=None,
        doc="Passes while fewer than `max` positions are open.")


# -- spread limit -----------------------------------------------------------
def _c_spread_limit(p, snap):
    cid = "spread_limit"
    if snap.spread_pips is None:
        # Not a pass. A client who set a spread ceiling is protecting against
        # a cost they cannot see; treating "unknown" as "fine" removes the
        # protection exactly when the feed is degraded.
        raise ConditionUnavailable(
            f"{cid}: the snapshot carries no spread, so a spread ceiling "
            f"cannot be honoured")
    return snap.spread_pips <= p["max_pips"], \
        f"spread {snap.spread_pips:.1f} pips, limit {p['max_pips']:.1f}"


_define("spread_limit",
        params={"max_pips": P(float, 2.0, min=0)},
        check=_c_spread_limit,
        bias=None,
        doc="Passes while the spread is at or under a ceiling.")
