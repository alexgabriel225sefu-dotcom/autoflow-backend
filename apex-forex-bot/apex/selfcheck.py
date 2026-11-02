"""The platform checks its own engine and reports, so nobody has to ask it.

WHY THIS EXISTS

The APEX engine — scanner, ranking, decision, thesis — shipped while the market
was closed, so it had never run once against live conditions. The obvious way
to find out whether it works is for someone to read the logs when the market
reopens. That someone is a person with finite time and, in this case, a finite
token budget.

So the bot does it. This runs inside the process that already exists, on the
host that is already paid for, and sends the answer to Telegram. It costs
nothing to run and needs nobody awake at 22:00 on a Sunday.

WHAT IT REPORTS, AND WHY EACH LINE IS THERE

  * whether the scanner produced a ranked pass at all — the one thing that was
    genuinely unverified;
  * how many candidates it looked at, and how many it refused, because a
    scanner that ranks eight and proposes none is working, while one that
    ranks zero is not;
  * how far the EV calibration got, because that counter was stuck at 27/30
    from a persistence bug and this is how anyone finds out it moved;
  * whether any scan failed, quoted rather than summarised.

SILENCE IS NOT SUCCESS

The report is sent whether the news is good or bad. A self-check that only
speaks up when something is wrong is indistinguishable from one that crashed —
which is the same trap as a monitor that greps only for the success line.
"""

import time

# How far back to look for evidence of a pass. One hour covers a market open
# plus the first few scan cycles at the default cadence.
_WINDOW_S = 3600

# Journal event types this reads. Imported lazily so a missing module cannot
# stop the session watcher.
_WANT = ("candidates.ranked", "decision.recorded", "thesis.created",
         "management.shadow", "ai.rejected")


def _events(user_id, since_ts):
    """(events, ok). `ok` is False when the journal could not be read.

    The two are separate on purpose. An empty list and a failed read produce
    the same report otherwise — "no pass recorded" — and that sentence would
    then be printed every week whether the scanner was silent or the reader
    was broken. This module exists to answer a question; answering it wrongly
    and confidently is worse than saying it could not be answered.
    """
    from apex import trade_events as te
    try:
        # recent() returns {"events": [...], "total": n}. Iterating the dict
        # itself yields its KEYS — strings — which raises on .get and, with a
        # bare except, looked exactly like an empty journal.
        page = te.recent(user_id, limit=400, since_ts=since_ts) or {}
        rows = page.get("events") or []
        return [e for e in rows
                if isinstance(e, dict) and e.get("type") in _WANT], True
    except Exception as e:
        print(f"[SelfCheck:{user_id}] event read failed: {e}")
        return [], False


def _ev_progress(user_id):
    """(labelled, needed) or (None, None) when it cannot be read."""
    try:
        from apex import ev, user_store
        journal = user_store.load_trades(user_id) or []
        return ev.labelled_count(journal), 30
    except Exception as e:
        print(f"[SelfCheck:{user_id}] EV progress unreadable: {e}")
        return None, None


def build(user_id, *, since_ts=None, dash=None):
    """The report as a dict. Never raises; every field is measured or None."""
    since = since_ts or (time.time() - _WINDOW_S)
    evs, readable = _events(user_id, since)
    by_type = {}
    for e in evs:
        by_type[e.get("type")] = by_type.get(e.get("type"), 0) + 1

    decisions = [e for e in evs if e.get("type") == "decision.recorded"]
    actions = {}
    for d in decisions:
        a = ((d.get("payload") or {}).get("action")) or "?"
        actions[a] = actions.get(a, 0) + 1

    labelled, needed = _ev_progress(user_id)
    d = dash or {}
    return {
        "at": int(time.time()),
        "windowS": int(time.time() - since),
        "journalReadable": readable,
        # None, not False, when the journal could not be read: "the scanner
        # did not run" is a claim, and this is not the code that can make it.
        "scannerRan": (by_type.get("candidates.ranked", 0) > 0
                       if readable else None),
        "rankedPasses": by_type.get("candidates.ranked", 0),
        "decisions": len(decisions),
        "actions": actions,
        "thesesWritten": by_type.get("thesis.created", 0),
        "shadowProposals": by_type.get("management.shadow", 0),
        "aiRejections": by_type.get("ai.rejected", 0),
        "evLabelled": labelled,
        "evNeeded": needed,
        "balance": d.get("balance"),
        "equitySource": d.get("equitySource"),
        "openCount": d.get("openCount"),
    }


def format_report(r):
    """Telegram HTML. Reads the same whether the news is good or bad."""
    ok = r.get("scannerRan")
    if ok is None:
        return ("🔧 <b>APEX engine — status unavailable</b>\n\n"
                "The decision journal could not be read, so this report "
                "cannot say whether the scanner ran.\n\n"
                "<i>This is a reporting fault, not a trading one — execution "
                "and risk controls are unaffected.</i>")
    head = ("✅ <b>APEX engine — first live pass</b>" if ok
            else "⚠️ <b>APEX engine — no pass recorded yet</b>")

    lines = [head, ""]
    if ok:
        lines.append(f"Scanner ran <b>{r['rankedPasses']}</b> ranked pass(es) "
                     f"in the last {r['windowS'] // 60} min.")
        lines.append(f"Decisions recorded: <b>{r['decisions']}</b>")
        if r["actions"]:
            for a, n in sorted(r["actions"].items(), key=lambda x: -x[1]):
                lines.append(f"  • {a}: {n}")
        # A scanner that ranks and proposes nothing is working. Saying so stops
        # a quiet session reading as a broken one.
        if r["decisions"] and not r["actions"].get("ENTER_PROPOSED"):
            lines.append("\n<i>No entry proposed — the setups were looked at "
                         "and refused, which is the engine working.</i>")
    else:
        lines.append("The scanner has not recorded a ranked pass in the last "
                     f"{r['windowS'] // 60} min.")
        lines.append("\n<i>Expected while the market is closed or every "
                     "instrument is already open. If the market is open and "
                     "this persists, the logs will carry an "
                     "<code>APEX scan failed</code> line.</i>")

    if r.get("thesesWritten"):
        lines.append(f"\nTheses written at entry: <b>{r['thesesWritten']}</b>")
    if r.get("shadowProposals"):
        lines.append(f"Shadow exit proposals: <b>{r['shadowProposals']}</b> "
                     f"<i>(recorded only — nothing acted on them)</i>")
    if r.get("aiRejections"):
        lines.append(f"Model replies rejected by schema: "
                     f"<b>{r['aiRejections']}</b>")

    if r.get("evLabelled") is not None:
        n, need = r["evLabelled"], r["evNeeded"]
        lines.append(f"\n📊 Probability model: <b>{n}/{need}</b> labelled trades")
        if n >= need:
            lines.append("<i>Threshold reached — the win rate is now measured "
                         "rather than assumed.</i>")
        else:
            lines.append(f"<i>{need - n} more closed trade(s) to go.</i>")

    if r.get("balance") is not None:
        src = r.get("equitySource") or "unknown"
        lines.append(f"\nBalance <b>${r['balance']:,.2f}</b> · "
                     f"{r.get('openCount', 0)} open · equity from {src}")
    return "\n".join(lines)


def run(user_id, *, dash=None, send=None):
    """Build and send. Returns the report dict, or None if it could not build.

    `send` is injected so this module never imports Telegram — it is called
    from the session watcher, which already owns that dependency, and keeping
    it out means this can be tested without a bot token.
    """
    try:
        r = build(user_id, dash=dash)
    except Exception as e:
        print(f"[SelfCheck:{user_id}] report build failed: {e}")
        return None
    if send:
        try:
            send(user_id, format_report(r))
        except Exception as e:
            print(f"[SelfCheck:{user_id}] report send failed: {e}")
    return r
