"""Market session watcher — the open/close edge, and the broker connection
across the weekend gap.

WHY THIS IS NOT IN THE TRADING LOOP: `user_loop` is gated behind
`forex.is_market_open()` — with the market shut it sleeps 60s and skips the
rest of the tick (user_loop.py:1514). Everything that has to happen BECAUSE the
market closed therefore cannot live there: the loop is asleep at exactly the
moment it would need to act. The existing weekend flatten works only because it
runs in the one-hour overlap where the close WINDOW has opened and the market
is still technically open — restart the process at 21:30 on a Friday and no
client is ever told the market shut.

WHAT IT DELIBERATELY DOES NOT DO: it does not trade, does not close positions,
does not touch strategy. Flattening before the weekend already happens in the
loop and stays there; a second writer racing over the same positions is how a
"safety" feature closes a trade twice.

RECONNECTION WAS ALREADY SELF-HEALING. The broker's read-only `_rpc` drops a
dead socket and retries once, so Monday's first candle fetch repairs the
connection on its own. What was missing is not the reconnect but the PROOF: if
the refresh token
expired over the weekend, nothing noticed until a trade silently failed to
happen. This module reconnects deliberately, reads the balance to prove the
account really answered, and says so loudly when it did not.
"""
import threading
import time
from datetime import datetime, timezone

from apex import forex, user_store

# The market moves once a week in each direction; polling every 30s puts the
# announcement within half a minute of the real edge without meaningful cost.
_POLL_S = 30

# Two instances run during a Render deploy and both would announce. The claim
# below makes the edge single-shot across processes. The TTL has to outlive a
# restart but expire before the SAME edge comes round again seven days later.
_CLAIM_TTL_S = 6 * 24 * 3600

_open_now = None          # last observed state; None until the first poll
_started = False
_lock = threading.Lock()


def _session_stamp(dt=None):
    """The trading week an edge belongs to.

    ISO weeks run Monday→Sunday, so Friday's close and the Sunday reopen that
    follows it share one stamp — which is what makes ("close", stamp) and
    ("open", stamp) two distinct, non-repeating keys per week.
    """
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%G-W%V")


def _edge_is_ours(edge):
    """True when THIS process should announce `edge`.

    `claim` is tri-state on purpose: None means "no shared store to ask", not
    "somebody else has it". A single-instance dev box must still announce, so
    None reads as yes.
    """
    try:
        got = user_store.claim(f"mktedge:{edge}:{_session_stamp()}",
                               ttl_s=_CLAIM_TTL_S)
    except Exception as e:
        print(f"[Session] claim failed ({e}) — announcing anyway")
        return True
    return True if got is None else bool(got)


def _active_users():
    """(user_id, record) for every active client, skipping unreadable ones."""
    out = []
    for uid in (user_store.all_active() or []):
        try:
            rec = user_store.load(uid)
        except Exception as e:
            print(f"[Session] could not load {uid}: {e}")
            continue
        if rec:
            out.append((uid, rec))
    return out


def _alert(uid, payload):
    try:
        from apex import telegram as _tg
        _tg._user_alert(uid, payload)
    except Exception as e:
        print(f"[Session] alert to {uid} failed: {e}")


# ── Close ────────────────────────────────────────────────────────────────────
def _disconnect(user):
    """Drop this account's pooled cTrader socket. True when one was dropped.

    Delegated to the trading core rather than done here: no module outside it
    may import a broker (tests/test_failure_matrix.py item 15), and that
    invariant is worth more than the two lines it saves.
    """
    from apex import user_loop as _ul
    return _ul.drop_broker_connection(user)


def _on_close(users):
    for uid, rec in users:
        dropped = False
        try:
            dropped = _disconnect(rec)
        except Exception as e:
            print(f"[Session] disconnect for {uid} failed: {e}")
        print(f"[Session] {uid}: market closed, "
              f"{'connection dropped' if dropped else 'nothing to drop'}")
        _alert(uid, {"action": "MARKET_CLOSE", "disconnected": dropped,
                     "symbol": rec.get("symbol", "")})


# ── Open ─────────────────────────────────────────────────────────────────────
def _reconnect(uid, user):
    """Re-authenticate and PROVE it worked. Returns (ok, detail).

    The balance read is the proof. A socket that connects but whose token the
    broker rejects is the failure mode this exists to catch, and only a real
    request can tell the two apart.
    """
    if user.get("paper"):
        return True, "paper account — no broker session needed"
    if not user.get("ctrader_account_id"):
        return False, "no cTrader account linked"

    from apex import user_loop as _ul
    try:
        broker, bcfg = _ul._make_broker(user)
    except Exception as e:
        return False, f"broker init failed: {e}"

    try:
        return True, f"balance ${float(broker.get_balance()):.2f}"
    except Exception as e:
        first = str(e)[:160]

    # One repair attempt. A token that was valid on Friday can be expired by
    # Sunday, and that is precisely the case worth healing without the client
    # having to re-link their account.
    try:
        refreshed = _ul._refresh_ctrader_token(uid, bcfg)
    except Exception as e:
        return False, f"{first} — and the token refresh failed: {str(e)[:120]}"
    if not refreshed:
        return False, first
    # The refresh worked; the account still has to answer. Reporting these two
    # separately matters — "refresh failed" and "refreshed but the account is
    # still unreachable" send the client to different places.
    try:
        return True, (f"balance ${float(broker.get_balance()):.2f} "
                      f"(access token refreshed)")
    except Exception as e:
        return False, (f"token refreshed, but the account still would not "
                       f"answer: {str(e)[:120]}")


def _on_open(users):
    for uid, rec in users:
        try:
            ok, detail = _reconnect(uid, rec)
        except Exception as e:
            ok, detail = False, f"unexpected error: {str(e)[:160]}"
        print(f"[Session] {uid}: market open, reconnect "
              f"{'OK' if ok else 'FAILED'} — {detail}")
        _alert(uid, {"action": "MARKET_OPEN", "ok": ok, "detail": detail,
                     "symbol": rec.get("symbol", "")})


# ── Watcher ──────────────────────────────────────────────────────────────────
def _run(poll_s):
    global _open_now
    _open_now = forex.is_market_open()
    print(f"[Session] watcher ON — market is currently "
          f"{'OPEN' if _open_now else 'CLOSED'}, polling every {poll_s}s")
    while True:
        time.sleep(poll_s)
        try:
            now_open = forex.is_market_open()
            if now_open == _open_now:
                continue
            edge = "open" if now_open else "close"
            # Record the new state BEFORE anything that can fail. Leaving it
            # unchanged on a failed claim would re-detect the same edge every
            # poll and hammer the store for the rest of the session.
            _open_now = now_open
            if not _edge_is_ours(edge):
                print(f"[Session] market {edge} already announced by another "
                      f"instance — standing down")
                continue
            users = _active_users()
            print(f"[Session] market {edge.upper()} — {len(users)} active user(s)")
            (_on_open if now_open else _on_close)(users)
        except Exception as e:
            print(f"[Session] watcher error: {e}")


def start(poll_s=_POLL_S):
    """Start the watcher once per process."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_run, args=(poll_s,), name="session-watch",
                     daemon=True).start()
    return True
