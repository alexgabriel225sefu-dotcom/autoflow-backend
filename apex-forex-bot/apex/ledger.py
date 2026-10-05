"""Order idempotency — the same intent must not become two positions.

Acceptance criterion 7 of the Guardian blueprint, and the only one on that
list that loses money directly. Nothing in this bot prevented it: every path
into `broker.place_order` sent the request and hoped.

Two ways it actually happens here, both observed rather than imagined:

  * TWO INSTANCES. Render's zero-downtime deploy overlaps the old and new
    containers. In today's logs instance 6n5hh was still running tick 101 at
    18:21:07 while vvlq4 had already started its loop at 18:21:00 — both
    driving the same cTrader account. The loop's generation token stops two
    threads inside ONE process from fighting; it cannot see another container.
  * A TIMED-OUT SUBMIT. "positions read: timed out" shows up in these logs
    already. A request that times out has not necessarily failed — the broker
    may have filled it — and a retry then opens a second position at double
    the intended risk.

The claim is keyed on the INTENT, not on a generated id: same account, same
symbol, same side, same size, same stop and target, inside a short window. Two
processes computing the intent independently arrive at the same key, which is
what makes the claim work across containers at all.

Fail policy. A shared backend that cannot be reached returns "unknown", and
unknown falls back to the in-process ledger and ALLOWS the order. Blocking
instead would mean a Redis hiccup silently halts all trading — the same denial
of service dressed as caution that the access gate had to avoid. The residual
exposure is bounded: the loop re-reads open positions from the broker on the
next tick and maxpos still applies, so a duplicate that slips through is
visible within one cycle rather than compounding.
"""
import hashlib
import threading
import time

from apex import user_store

# Two identical intents inside this window are the same trade. Wide enough to
# cover a deploy overlap (seconds) and a submit retry; far below the loop's
# post-close cooldown, so a genuine re-entry on the same pair is never caught.
DEFAULT_WINDOW_S = 120

_local = {}          # request_id -> {"ts", "result"}
_local_lock = threading.Lock()
_LOCAL_KEEP = 500


def _round(v, dp=6):
    try:
        return round(float(v), dp)
    except (TypeError, ValueError):
        return None


def request_id(user_id, symbol, side, units, sl=None, tp=None,
               window_s=DEFAULT_WINDOW_S, now=None):
    """Deterministic id for one trading intent inside a time bucket.

    Bucketed rather than timestamped so two processes a few seconds apart
    still agree. Buckets are half-open windows, so an intent near a boundary
    is checked against BOTH its own bucket and the previous one by the caller
    (see `claim`) — otherwise two instances either side of a boundary would
    compute different ids and both trade.
    """
    now = time.time() if now is None else float(now)
    bucket = int(now // max(1, int(window_s)))
    raw = "|".join(str(x) for x in (
        user_id, str(symbol or "").upper().replace("_", "").replace("/", ""),
        str(side or "").upper(), _round(units, 2),
        _round(sl), _round(tp), bucket))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _field(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _safe_part(value):
    text = str(value or "").strip()
    out = []
    for ch in text:
        out.append(ch if ch.isalnum() or ch in ("-", "_") else "-")
    return "".join(out).strip("-") or "unknown"


def _symbol_part(value):
    return str(value or "").upper().replace("_", "").replace("/", "")


def setup_key_from_decision(decision, *, strategy_id=None, bar=None):
    """Live idempotency key derived from the decision, never from wall time.

    Shape mirrors the legacy setup key: SYMBOL:SIDE:strategy:bar. The platform
    RuleDecision does not have a strategy id, so the default strategy component
    is the frozen RuleDoc id and version. A future live path may pass a more
    specific strategy id, but it still has to be a decision fact.
    """
    symbol = _symbol_part(_field(decision, "symbol"))
    side = str(_field(decision, "side") or _field(decision, "verdict")
               or "").upper()
    if not symbol:
        raise ValueError("decision needs a symbol for live idempotency")
    if side not in ("BUY", "SELL"):
        raise ValueError("decision needs BUY or SELL for live idempotency")

    if strategy_id is None:
        rid = _field(decision, "rule_doc_id", _field(decision, "ruleDocId"))
        ver = _field(decision, "rule_doc_version",
                     _field(decision, "ruleDocVersion"))
        strategy_id = f"{rid}-v{ver}"
    if bar is None:
        bar = _field(decision, "snapshot_ts", _field(decision, "snapshotTs"))
    if bar is None:
        raise ValueError("decision needs a snapshot bar for live idempotency")
    try:
        bar = int(float(bar))
    except (TypeError, ValueError) as e:
        raise ValueError("decision snapshot bar must be numeric") from e
    return f"{symbol}:{side}:{_safe_part(strategy_id)}:{bar}"


def live_claim_key(user_id, account_id, setup_key):
    """Shared-store key for one client's one live setup.

    The setup key itself is intentionally human-readable and decision-shaped;
    the Redis key namespaces it by user/account so two clients can take the same
    market setup independently.
    """
    if not user_id:
        raise ValueError("live order claim needs a user_id")
    if not account_id:
        raise ValueError("live order claim needs an account_id")
    digest = hashlib.sha256(str(setup_key).encode()).hexdigest()[:32]
    return f"live_order:{_safe_part(user_id)}:{_safe_part(account_id)}:{digest}"


def _shared_backend_ready():
    if not shared_backed():
        return False, "SHARED_BACKEND_REQUIRED", "no shared backend configured"
    health = user_store.redis_health()
    if not health.get("reachable"):
        return False, "COORDINATION_UNAVAILABLE", (
            health.get("status") or "shared backend is not reachable")
    return True, "OK", "shared backend reachable"


def claim_live_order(user_id, account_id, decision, *, strategy_id=None,
                     ttl_s=900):
    """Claim a future live order before any broker call can be made.

    This does not place an order and imports no execution primitive. It is the
    live-only idempotency contract from the specification: a shared backend is
    mandatory, the key is derived from the decision, and an unknown shared-store
    answer refuses rather than falling back to process memory.
    """
    setup_key = setup_key_from_decision(decision, strategy_id=strategy_id)
    claim_key = live_claim_key(user_id, account_id, setup_key)
    ready, code, detail = _shared_backend_ready()
    if not ready:
        return {"ok": False, "code": code, "detail": detail,
                "setupKey": setup_key, "claimKey": claim_key}

    won = user_store.claim(claim_key, ttl_s=int(ttl_s))
    if won is True:
        with _local_lock:
            _local[claim_key] = {"ts": time.time(), "result": None,
                                 "setupKey": setup_key, "live": True}
        return {"ok": True, "code": "CLAIMED", "setupKey": setup_key,
                "claimKey": claim_key}
    if won is False:
        return {"ok": False, "code": "DUPLICATE_LIVE_ORDER",
                "detail": "a live order for this setup is already claimed",
                "setupKey": setup_key, "claimKey": claim_key}
    return {"ok": False, "code": "COORDINATION_UNAVAILABLE",
            "detail": "shared backend could not confirm the live order claim",
            "setupKey": setup_key, "claimKey": claim_key}


def record_live_order_outcome(claim, result, *, confirmed):
    """Record a live claim outcome without reopening an unknown claim.

    A confirmed broker answer can be recorded. An exception or timeout is not a
    confirmed outcome, so the claim stays occupied until its shared TTL expires;
    releasing it here would turn one uncertain order into two.
    """
    key = (claim or {}).get("claimKey")
    if not key:
        raise ValueError("live outcome needs a claimKey")
    with _local_lock:
        entry = _local.setdefault(key, {"ts": time.time(), "live": True})
        entry["result"] = result
        entry["confirmed"] = bool(confirmed)
    if not confirmed:
        return {"ok": False, "code": "OUTCOME_UNKNOWN_CLAIM_HELD",
                "claimKey": key}
    return {"ok": True, "code": "RECORDED", "claimKey": key}


def _local_claim(rid, now):
    with _local_lock:
        hit = _local.get(rid)
        if hit:
            return False
        _local[rid] = {"ts": now, "result": None}
        if len(_local) > _LOCAL_KEEP:
            for k in sorted(_local, key=lambda k: _local[k]["ts"])[:100]:
                _local.pop(k, None)
        return True


def claim(user_id, symbol, side, units, sl=None, tp=None,
          window_s=DEFAULT_WINDOW_S, now=None, fail_closed=False):
    """Claim the right to send this order. Returns (ok, reason, request_id).

    ok=False means an identical order is already in flight or was just sent —
    the caller must NOT submit.

    `fail_closed` overrides the module's default fail-open policy for the case
    the policy was never meant to cover: a REAL-MONEY account whose shared
    backend is unreachable. The docstring above argues, correctly, that halting
    all trading on a Redis hiccup is its own denial of service — but that
    argument is about a simulation losing a signal, not about a live account
    opening a second position at double risk with no cross-container check
    left standing. Demo keeps the permissive default; live fails closed.
    """
    now = time.time() if now is None else float(now)
    rid = request_id(user_id, symbol, side, units, sl, tp, window_s, now)

    # Straddle the bucket boundary: an intent 1s after a boundary and one 1s
    # before it are the same trade, but land in different buckets. Checking the
    # previous bucket too costs one extra lookup and closes the seam that would
    # otherwise let exactly the deploy-overlap case through.
    prev = request_id(user_id, symbol, side, units, sl, tp, window_s,
                      now - window_s)

    taken = []
    for candidate in (prev, rid):
        shared = user_store.claim(f"order:{candidate}", ttl_s=int(window_s * 2))
        if shared is False:
            return False, "DUPLICATE_ORDER", rid
        if shared is None:
            # No shared backend, or it errored. The in-process ledger still
            # catches a retry inside this container; cross-container duplicates
            # are not detectable in this mode and the caller is told so.
            if fail_closed and shared_backed():
                # Configured but unreachable, on a live account. There is no
                # cross-container duplicate check left, so do not open a real
                # position on trust. (A backend that is not configured at all
                # is a different case: nothing to be unreachable, and the
                # single-instance setup it implies has no second writer.)
                return False, "COORDINATION_UNAVAILABLE", rid
            if not _local_claim(candidate, now):
                return False, "DUPLICATE_ORDER_LOCAL", rid
            taken.append(candidate)

    # A claim occupies BOTH bucket keys, so release() has to know about both.
    # Recording only the returned id left the previous-bucket key held, and a
    # legitimate retry after an explicit release was refused by the half nobody
    # remembered.
    with _local_lock:
        _local.setdefault(rid, {"ts": now, "result": None})["keys"] = taken
    return True, "CLAIMED", rid


def record(rid, result):
    """Store what the broker returned, so a duplicate can be answered with the
    original outcome instead of a bare refusal."""
    with _local_lock:
        _local.setdefault(rid, {"ts": time.time()})["result"] = result
    return result


def result_for(rid):
    with _local_lock:
        return (_local.get(rid) or {}).get("result")


def release(rid):
    """Drop a claim that never became an order (a broker rejection before the
    request left). Only the local half — the shared key expires on its own,
    and deleting it would reopen the window for a genuine duplicate."""
    with _local_lock:
        entry = _local.pop(rid, None) or {}
        for k in entry.get("keys") or ():
            _local.pop(k, None)


def shared_backed():
    """True when claims are visible to other instances. False means duplicate
    protection is per-process only — worth surfacing rather than assuming."""
    return bool(getattr(user_store, "_USE_REDIS", False))
