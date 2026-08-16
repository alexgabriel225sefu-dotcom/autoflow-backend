"""Button presses are untrusted input, and old buttons never go away.

A Telegram inline keyboard is permanent. Every button this bot has ever sent is
still sitting in somebody's chat history and is still pressable — months later,
by a different person on the same account, twice in the same second because the
network was slow and the client tapped again. `callback_data` also arrives
straight off the wire: it is whatever the client's app sent, which for anyone
willing to look is whatever they typed.

So three separate problems, deliberately kept separate:

  MALFORMED   data that is not a callback this bot issues. Rejected on shape
              before anything reads it, so a handler never parses hostile text.

  REPEATED    the same action twice. The authoritative duplicate-order defence
              is the ledger claim inside `gates.authorize_order` — this layer
              does not replace it and must not be mistaken for it. What this
              adds is the *interface* half: the second tap gets an answer that
              says nothing happened, instead of a second "opening…" message
              followed by silence.

  STALE       a confirmation that has expired or was already redeemed. These
              carry a token, and the token is burned in the shared store with
              SET NX, so two confirmations arriving together cannot both win.

WHAT THIS IS NOT. It is not a permission check and it is not a financial gate.
Nothing here decides whether an order may be placed; `gates` does, on every
origin. A guard that started making that decision would be the second gate the
architecture spends its effort not having.
"""
import re
import secrets
import time

# Every namespace this bot issues. An action that is not in here cannot be
# routed, which means a new button is a deliberate two-line change rather than
# something a caller can smuggle in as a string.
NAMESPACES = {
    "nav", "go", "am", "pf", "emg", "pos", "live", "acct", "bot", "ob",
    "bld", "risk", "reset", "cp", "purgebad", "tr", "strat", "sig", "ui",
    "notif",
}

# Actions that change money, settings or the account binding. Navigation is
# deliberately absent: a client re-opening a screen twice is not a problem to
# be solved, and rate-limiting it would make the bot feel broken.
ACTION_NAMESPACES = {
    "am", "emg", "pos", "live", "acct", "bot", "risk", "reset", "cp",
    "purgebad", "tr", "ob",
}

# Telegram caps callback_data at 64 bytes; anything longer did not come from a
# keyboard this bot drew.
MAX_LEN = 64
_SHAPE = re.compile(r"^[A-Za-z0-9_:.\-]{1,64}$")

_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_TTL_S = 300


def parse(data):
    """→ (namespace, rest) for data this bot could have issued, else None.

    Total. Every rejection path returns None rather than raising, because the
    caller is a poll loop handling somebody else's input and an exception there
    costs every other client in the batch their turn.
    """
    if not isinstance(data, str):
        return None
    if not data or len(data) > MAX_LEN:
        return None
    if not _SHAPE.match(data):
        return None
    ns, _, rest = data.partition(":")
    if ns not in NAMESPACES:
        return None
    return ns, rest


def is_action(data):
    p = parse(data)
    return bool(p) and p[0] in ACTION_NAMESPACES


def once(chat_id, data, ttl_s=8):
    """True the first time this exact button is pressed inside `ttl_s`.

    Deliberately permissive when the shared store cannot answer. Two things
    make that the right call: the real duplicate-execution defence is the
    ledger claim inside the gate, which fails CLOSED for live money; and a
    coordination outage that silently disabled every button would look exactly
    like a broken bot to a client who cannot see the cause.
    """
    from apex import user_store
    try:
        got = user_store.claim(f"cb:{chat_id}:{data}", ttl_s=max(1, int(ttl_s)))
    except Exception as e:
        print(f"[CallbackGuard] dedupe unavailable for {chat_id}: {e}")
        return True
    return got is not False


# ── Confirmations that must not be replayable ─────────────

def issue(chat_id, purpose, ttl_s=DEFAULT_TTL_S):
    """Mint a short single-use token for a two-step confirmation.

    Stored on the user record so it survives the client scrolling away and
    coming back, and time-stamped so an old screen cannot be resurrected.
    """
    from apex import user_store
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))
    try:
        user_store.update(chat_id, {f"confirm_{purpose}": {"token": token,
                                                           "ts": time.time(),
                                                           "ttl": int(ttl_s)}})
    except Exception as e:
        print(f"[CallbackGuard] could not store {purpose} token for {chat_id}: {e}")
        return None
    return token


def consume(chat_id, purpose, token, user=None):
    """Burn a confirmation token exactly once. False means do NOT proceed.

    Two independent conditions, both required:

      * the token matches the one this account was issued, and it has not
        expired — that is what makes a screen from an hour ago inert;
      * a SET NX claim on the token succeeds — that is what stops two taps
        arriving together from both being the first.

    An unreachable store is a refusal here, unlike `once()` above. This
    function guards steps that move money or switch an account to real funds,
    and a confirmation that cannot be proven unused is not a confirmation.
    """
    from apex import user_store
    if not token or not isinstance(token, str):
        return False
    try:
        u = user if user is not None else user_store.load(chat_id)
    except Exception as e:
        print(f"[CallbackGuard] user unreadable while confirming {purpose}: {e}")
        return False
    rec = (u or {}).get(f"confirm_{purpose}") or {}
    stored = str(rec.get("token") or "")
    if not stored or not secrets.compare_digest(token, stored):
        return False
    try:
        ttl = float(rec.get("ttl") or DEFAULT_TTL_S)
        age = time.time() - float(rec.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    if age > ttl:
        return False
    try:
        got = user_store.claim(f"uiconfirm:{chat_id}:{purpose}:{token}",
                               ttl_s=int(ttl) * 2)
    except Exception as e:
        print(f"[CallbackGuard] confirmation claim failed for {chat_id}: {e}")
        return False
    if got is False:
        return False
    if got is None and getattr(user_store, "_USE_REDIS", False):
        # A shared backend exists and did not answer. Another container may
        # have redeemed this token already and we cannot see it.
        print(f"[CallbackGuard] ⛔ cannot prove the {purpose} confirmation for "
              f"{chat_id} is unused — refusing")
        return False
    try:
        user_store.update(chat_id, {f"confirm_{purpose}": None})
    except Exception as e:
        print(f"[CallbackGuard] could not clear {purpose} token: {e}")
    return True
