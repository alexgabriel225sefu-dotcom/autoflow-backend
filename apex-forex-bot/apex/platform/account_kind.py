"""Which of the client's accounts are demo and which are live, and why.

The type is never decided here. cTrader reports a `live` flag per account and
`ctrader_link` records it as `mode`; this module only READS that record and says
it in words, with the one thing a client wants next to a live account: what
stands between it and a live order.

THREE KINDS, NEVER TWO

  demo        cTrader reported a demo account
  live        cTrader reported a live account
  unverified  anything else. Unknown is not folded into demo: a live account
              that looks like a demo one is the mistake this exists to prevent.

An unverified account is shown with the same "no live order" outcome as a live
one that is not enabled. Reading this never changes anything and never places
an order.
"""
from apex.platform import live_pilot as _pilot

DEMO, LIVE, UNVERIFIED = "demo", "live", "unverified"

_BASIS = {
    DEMO: "cTrader reported this as a demo account.",
    LIVE: "cTrader reported this as a live account.",
    UNVERIFIED: "cTrader did not say whether this is a live or a demo account.",
}


def kind_of(mode):
    m = str(mode or "").strip().lower()
    return m if m in (DEMO, LIVE) else UNVERIFIED


def _live_state(user_id, ctid, live_allowed):
    """(state, text) for an account that is, or may be, live."""
    if not live_allowed:
        return ("not_enabled", "Live accounts are not enabled on this deployment, "
                               "so no order is sent to this account.")
    refusal = _pilot.check_identity(user_id, ctid)
    if refusal is None:
        return ("in_pilot", "This account is in the live pilot. A live order "
                            "still needs the licence, your approval and the "
                            "release switch, and is limited in size.")
    code = refusal[0]
    if code == _pilot.PILOT_UNCONFIGURED:
        return ("pilot_unconfigured", "The live pilot is not set up, so no live "
                                      "order is sent to this account.")
    return ("not_in_pilot", "This account is not part of the live pilot, which "
                            "is limited to the operator's own account.")


def classify(user_id, status):
    """Per-account kinds from a `ctrader_link.public_status` dict."""
    if not isinstance(status, dict) or not status.get("connected"):
        return {"status": "ok", "connected": False, "accounts": [],
                "summary": {"demo": 0, "live": 0, "unverified": 0}}
    selected = (status.get("selected") or {}).get("ctid")
    live_allowed = bool(status.get("liveAllowed"))
    rows, counts = [], {DEMO: 0, LIVE: 0, UNVERIFIED: 0}
    for a in status.get("accounts") or []:
        if not isinstance(a, dict):
            continue
        kind = kind_of(a.get("mode"))
        counts[kind] += 1
        row = {"ctid": a.get("ctid"), "label": a.get("label"), "kind": kind,
               "basis": _BASIS[kind],
               "selected": selected is not None and str(selected) == str(a.get("ctid"))}
        if kind == DEMO:
            row["liveState"] = None
            row["liveText"] = "Demo account: automation can run here with no real money."
        elif kind == LIVE:
            row["liveState"], row["liveText"] = _live_state(user_id, a.get("ctid"), live_allowed)
        else:
            row["liveState"] = "unverified"
            row["liveText"] = ("Treated as live and closed: no order is sent "
                               "until cTrader reports the account type.")
        rows.append(row)
    return {"status": "ok", "connected": True, "accounts": rows,
            "summary": {"demo": counts[DEMO], "live": counts[LIVE],
                        "unverified": counts[UNVERIFIED]}}
