"""Read-only operations view of APEX, for an external operator assistant.

APEX is the authority. This module is a window into it — every function here
reads and none of them decide anything. Trading, risk, execution, protection,
licensing and broker authentication stay where they are; nothing in this file
can start, stop, size or close a trade.

THE RULE THAT SHAPES THE WHOLE MODULE: never guess. An operations assistant
that reports "healthy" because it could not reach Redis is worse than one that
reports nothing, because the operator acts on it. So every check returns one
of three answers — a fact, `UNKNOWN`, or an explicit failure — and `UNKNOWN`
is never collapsed into the reassuring side. `_ok()` and `_unknown()` exist to
make that the path of least resistance.

Secrets never leave. Broker tokens, licence keys, API keys and anything else
credential-shaped are dropped at the boundary by `_redact`, not merely omitted
from the happy path, so a field added to the user record later cannot leak by
being forgotten.
"""
import time

from apex import access, ownership, user_loop, user_store

UNKNOWN = "UNKNOWN"

# Past this, the worker cache stops being reported as a position and starts
# being reported as UNKNOWN. Two full ticks plus margin: one missed tick is a
# slow broker read, three means the loop is not reconciling and whatever it
# last published may no longer resemble the account.
_STALE_AFTER_S = 900

# Named in every position response, because "positions: 2" reads as a fact
# about the account when it is a fact about a cache. The operator needs to know
# which one they are looking at before they act on it.
POSITION_SOURCE = "last_loop_state"

# Reconciliation verdicts. The broker is authoritative and local state is a
# snapshot, so the two disagreeing is a REPORTABLE condition — not something to
# normalise away by preferring whichever side is convenient.
RECONCILED = "RECONCILED"
EXTERNAL_OR_UNRECONCILED_POSITION = "EXTERNAL_OR_UNRECONCILED_POSITION"
LOCAL_POSITION_MISSING_AT_BROKER = "LOCAL_POSITION_MISSING_AT_BROKER"

# Statuses an investigation can conclude with. Deliberately includes UNKNOWN.
HEALTHY, DEGRADED, RECOVERY = "HEALTHY", "DEGRADED", "RECOVERY"
SAFE_MODE, BLOCKED = "SAFE_MODE", "BLOCKED"
BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
LICENSE_BLOCKED, RISK_BLOCKED = "LICENSE_BLOCKED", "RISK_BLOCKED"
OWNERSHIP_LOST_ST = "OWNERSHIP_LOST"

# Keys that must never appear in a response. Substring match on the key name so
# a later `ctrader_access_token_v2` is caught by the same rule.
_SECRET_HINTS = ("token", "secret", "key", "password", "passwd", "credential",
                 "auth", "cookie", "session", "private", "license")


def _redact(d):
    """A dict with every credential-shaped field removed, recursively."""
    if isinstance(d, list):
        return [_redact(x) for x in d]
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if any(h in str(k).lower() for h in _SECRET_HINTS):
            continue
        out[k] = _redact(v) if isinstance(v, (dict, list)) else v
    return out


def _ok(**kw):
    return {"status": "OK", **kw}


def _unknown(why, **kw):
    """A fact we could not establish. Never a default, always a report."""
    return {"status": UNKNOWN, "reason": str(why)[:200], **kw}


def _valid_user(user_id):
    """Normalise and sanity-check a user id. Cross-user access starts here.

    Returns (uid, error). Ids are opaque Telegram chat ids: digits, bounded
    length. Anything else is a caller mistake or an attempt to walk the
    namespace, and both get the same refusal.
    """
    uid = str(user_id or "").strip()
    if not uid:
        return None, "user_id is required"
    if not uid.isdigit() or len(uid) > 24:
        return None, "user_id must be a numeric account id"
    return uid, None


def _known(uid):
    try:
        return bool(user_store.load(uid))
    except Exception:
        return False


# ─── Level 1: per-user reads ──────────────────────────────
def user_license(user_id):
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    try:
        state = access.allowed_state(uid)
    except Exception as e:
        return _unknown(f"access store unreachable: {e}")
    try:
        has_key = bool((user_store.load(uid) or {}).get("license_key"))
    except Exception:
        has_key = False
    if state == "allowed":
        return _ok(license="ACTIVE", source="grant", has_key=has_key)
    if state == "denied":
        # A stored licence still counts — the grant store is wiped on redeploy
        # when it falls back to local JSON, and a paying client must not read
        # as revoked because of that.
        if has_key:
            return _ok(license="ACTIVE", source="license_key")
        return _ok(license="REVOKED", source="grant", has_key=False)
    return _unknown("access store returned unknown", has_key=has_key)


def user_broker_status(user_id):
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    try:
        u = user_store.load(uid) or {}
    except Exception as e:
        return _unknown(f"user store unreachable: {e}")
    if not u:
        return {"error": "no such user"}
    if not u.get("ctrader_access_token"):
        return _ok(broker="NOT_CONNECTED", account_linked=False)
    dash = user_loop.get_dash(uid) or {}
    health = dash.get("brokerHealth")
    last = dash.get("lastTickTs")
    age = int(time.time() - last) if isinstance(last, (int, float)) and last else None
    return _ok(
        broker="CONNECTED" if health == "ok" else (health or UNKNOWN),
        account_linked=bool(u.get("ctrader_account_id")),
        env=(u.get("ctrader_env") or UNKNOWN),
        last_sync_s=age if age is not None else UNKNOWN,
    )


def user_risk(user_id):
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    try:
        u = user_store.load(uid) or {}
    except Exception as e:
        return _unknown(f"user store unreachable: {e}")
    if not u:
        return {"error": "no such user"}
    dash = user_loop.get_dash(uid) or {}
    guard = dash.get("riskGuard")
    return _ok(
        risk_pct=u.get("risk"),
        max_dd_pct=u.get("max_dd_pct"),
        max_daily_loss_pct=u.get("max_daily_loss_pct"),
        max_positions=u.get("maxpos"),
        loss_streak=u.get("loss_streak"),
        mode="paper" if u.get("paper", True) else "live",
        guard=("HOLDING" if (guard or {}).get("halted")
               else "ACTIVE" if isinstance(guard, dict) else UNKNOWN),
        guard_reasons=(guard or {}).get("reasons") or [],
    )


def user_positions(user_id):
    """Open positions as the LOOP last saw them, with the read's age.

    Deliberately not a live broker call: this is an observability endpoint and
    must not add load to the broker connection the trading loop depends on, nor
    block on it. The age is returned so a stale answer is visible as stale
    rather than passed off as current.
    """
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not _known(uid):
        return {"error": "no such user"}
    dash = user_loop.get_dash(uid) or {}
    if not dash:
        return _unknown("no worker state published for this user")
    pos = dash.get("openPosition")
    last = dash.get("lastTickTs")
    unprotected = bool(pos and not (pos.get("stopLoss") or pos.get("sl")))
    age = int(time.time() - last) if isinstance(last, (int, float)) and last else None

    # An age alone is not enough. "as_of_seconds: 1284" reads as a detail next
    # to a position list, and the position list is what gets acted on — so past
    # the point where the data can still be trusted this stops presenting it as
    # current and says so in the status field, which nothing skims past.
    if age is None:
        return _unknown("the worker has published no tick timestamp, so the age "
                        "of this position data cannot be established",
                        positions=[_redact(pos)] if pos else [],
                        position_source=POSITION_SOURCE,
                        as_of_seconds=UNKNOWN, freshness=UNKNOWN,
                        protection=UNKNOWN, state=RECOVERY)
    if age > _STALE_AFTER_S:
        return _unknown(
            f"last broker sync was {age}s ago (> {_STALE_AFTER_S}s) — this is the "
            f"last state the loop published, not the broker's current position",
            positions=[_redact(pos)] if pos else [],
            open_count=dash.get("openCount", 1 if pos else 0),
            position_source=POSITION_SOURCE,
            as_of_seconds=age, freshness="STALE",
            protection=UNKNOWN,     # cannot vouch for a stop last seen long ago
            state=RECOVERY,
        )
    return _ok(
        open_count=dash.get("openCount", 1 if pos else 0),
        positions=[_redact(pos)] if pos else [],
        protection="MISSING_STOP" if unprotected else ("OK" if pos else "N/A"),
        position_source=POSITION_SOURCE,
        as_of_seconds=age, freshness="FRESH",
    )


def user_orders(user_id, limit=10):
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not _known(uid):
        return {"error": "no such user"}
    try:
        rows = user_store.load_trades(uid) or []
    except Exception as e:
        return _unknown(f"journal unreachable: {e}")
    n = max(1, min(int(limit or 10), 50))
    keep = ("time", "symbol", "side", "netPnl", "entry", "exit", "strategyId", "mode")
    return _ok(orders=[{k: r.get(k) for k in keep} for r in rows[-n:]][::-1],
               total=len(rows))


def user_worker_status(user_id):
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not _known(uid):
        return {"error": "no such user"}
    dash = user_loop.get_dash(uid) or {}
    last = dash.get("lastTickTs")
    age = int(time.time() - last) if isinstance(last, (int, float)) and last else None
    return _ok(
        running=user_loop.is_running(uid),
        last_tick_s=age if age is not None else UNKNOWN,
        symbol=dash.get("symbol") or UNKNOWN,
        balance=dash.get("balance"),
    )


def user_ownership(user_id):
    """Which instance owns this user's loop. UNKNOWN is a real answer here.

    Redis being unreachable means ownership cannot be established, and the one
    thing that must not happen is reporting that as owned — the whole point of
    the lease is that an unverified owner is not an owner.
    """
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not ownership.shared_backed():
        return _ok(lease="NOT_APPLICABLE",
                   detail="no shared backend; single instance is uncontended")
    if ownership.was_lost(uid):
        return _ok(lease=OWNERSHIP_LOST_ST, owner="another instance")
    held = ownership.holds(uid)
    if held is None:
        return _unknown("ownership backend unreachable", lease=UNKNOWN)
    return _ok(lease="ACTIVE" if held else "NOT_OWNED",
               owner=ownership.INSTANCE_ID if held else UNKNOWN)


def user_incidents(user_id, limit=20):
    return recent_errors(user_id, limit=limit)


def recent_errors(user_id=None, limit=20):
    """Recent events, optionally for one user. Errors and warnings first."""
    try:
        from apex import control
        import json as _j
        n = max(1, min(int(limit or 20), 100))
        raw = control._cmd("LRANGE", control.K_EVENTS, 0, 199) or []
    except Exception as e:
        return _unknown(f"event log unreachable: {e}")
    out = []
    uid = str(user_id) if user_id else None
    if uid:
        uid, err = _valid_user(uid)
        if err:
            return {"error": err}
    for r in raw:
        try:
            rec = _j.loads(r)
        except Exception:
            continue
        if uid and str(rec.get("user") or "") != uid:
            continue
        if rec.get("level") in ("error", "warn"):
            out.append(_redact(rec))
    return _ok(errors=out[:n], scanned=len(raw))


def broker_reconcile(user_id):
    """Compare the broker against local state. The broker wins, always.

    A read-only diagnostic that actually asks the broker, unlike
    `user_positions`, which deliberately serves the worker cache. It exists
    because the two CAN disagree and each direction means something different:

      broker has a position, local does not
          -> EXTERNAL_OR_UNRECONCILED_POSITION. Opened by hand in cTrader, or
             opened by this bot and lost from local state. Either way something
             is live on the account that the loop is not managing.

      local has a position, broker does not
          -> LOCAL_POSITION_MISSING_AT_BROKER. It closed while nothing was
             watching, or was never really opened.

    Neither is normalised away. Silently preferring local state hides a real
    position; silently preferring the broker discards the only record of why a
    trade was taken. The operator is told which one it is, and nothing here
    changes either side — this diagnoses, the loop reconciles.
    """
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    try:
        u = user_store.load(uid) or {}
    except Exception as e:
        return _unknown(f"user store unreachable: {e}")
    if not u:
        return {"error": "no such user"}
    if not u.get("ctrader_access_token"):
        return _ok(reconciliation="NO_BROKER", detail="no broker connected")

    try:
        broker, _bcfg = user_loop._make_broker(u)
        remote = broker.get_all_positions() or []
    except Exception as e:
        # The authoritative side is the one we could not read. Saying anything
        # about the account now would be inventing it.
        return _unknown(f"broker unreachable: {str(e)[:120]}",
                        reconciliation=UNKNOWN, authority="broker")

    dash = user_loop.get_dash(uid) or {}
    local_pos = dash.get("openPosition")
    local_syms = {str((local_pos or {}).get("symbol") or "").upper()} - {""}
    remote_syms = {str(p.get("symbol") or "").upper() for p in remote} - {""}

    findings = []
    for sym in sorted(remote_syms - local_syms):
        findings.append({"symbol": sym,
                         "verdict": EXTERNAL_OR_UNRECONCILED_POSITION,
                         "detail": "open at the broker, not tracked locally"})
    for sym in sorted(local_syms - remote_syms):
        findings.append({"symbol": sym,
                         "verdict": LOCAL_POSITION_MISSING_AT_BROKER,
                         "detail": "tracked locally, not open at the broker"})

    return _ok(
        reconciliation=RECONCILED if not findings else "MISMATCH",
        authority="broker",
        broker_positions=len(remote),
        broker_symbols=sorted(remote_syms),
        local_symbols=sorted(local_syms),
        findings=findings,
        action_taken="none — this is a diagnostic, the trading loop reconciles",
    )


def reconcile_status(user_id):
    """Whether the loop has reconciled against the broker, and how long ago."""
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not _known(uid):
        return {"error": "no such user"}
    dash = user_loop.get_dash(uid) or {}
    if not dash:
        return _unknown("worker has published no state — reconciliation status "
                        "cannot be established")
    last = dash.get("lastTickTs")
    if not isinstance(last, (int, float)) or not last:
        return _unknown("no broker sync timestamp published")
    age = int(time.time() - last)
    # A tick is 5 minutes; three missed ticks means the loop is not reconciling.
    return _ok(last_broker_sync_s=age,
               state="OK" if age < 900 else RECOVERY,
               broker_health=dash.get("brokerHealth") or UNKNOWN)


# ─── Level 1: aggregate reads ─────────────────────────────
def system_health():
    """Fleet-wide state. Never reports healthy for something it could not read."""
    out = {"ts": int(time.time())}
    try:
        uids = user_store.all_active() or []
        out["active_users"] = len(uids)
        out["store"] = "HEALTHY"
    except Exception as e:
        uids = []
        out["active_users"] = UNKNOWN
        out["store"] = UNKNOWN
        out["store_reason"] = str(e)[:120]

    running = sum(1 for u in uids if user_loop.is_running(u))
    out["workers"] = f"{running}/{len(uids)}" if uids else "0/0"

    connected = 0
    unknown_brokers = 0
    for u in uids:
        b = user_broker_status(u)
        if b.get("status") == UNKNOWN:
            unknown_brokers += 1
        elif b.get("broker") == "CONNECTED":
            connected += 1
    out["broker_connections"] = f"{connected}/{len(uids)}" if uids else "0/0"
    if unknown_brokers:
        out["broker_unknown"] = unknown_brokers

    # A REAL probe, not a configuration flag. `_USE_REDIS` answers "was a
    # backend configured", which stays True through an outage — so a backend
    # that died at 03:00 reported HEALTHY until someone noticed by other means.
    try:
        rh = user_store.redis_health()
    except Exception as e:
        rh = {"status": UNKNOWN, "detail": str(e)[:120], "reachable": False,
              "configured": bool(getattr(user_store, "_USE_REDIS", False))}
    out["redis"] = rh.get("status", UNKNOWN)
    out["redis_detail"] = {k: rh.get(k) for k in
                           ("configured", "reachable", "latency_ms",
                            "last_success", "failure_count", "detail")
                           if rh.get(k) is not None}
    # Ownership rides the same backend, so it cannot be healthier than Redis is.
    if not ownership.shared_backed():
        out["ownership_backend"] = "NOT_CONFIGURED"
    elif rh.get("status") in ("DOWN", UNKNOWN):
        out["ownership_backend"] = rh.get("status")
    else:
        out["ownership_backend"] = rh.get("status", UNKNOWN)
    errs = recent_errors(limit=50)
    out["recent_errors"] = (len(errs.get("errors", []))
                            if errs.get("status") == "OK" else UNKNOWN)

    # A backend that is DOWN is not a degraded system, it is a system whose
    # coordination is gone — entitlement, ownership and order idempotency all
    # ride on it. It outranks every other signal here.
    if out["redis"] == "DOWN":
        out["overall"] = "DOWN"
    elif out["store"] == UNKNOWN or out["redis"] == UNKNOWN \
            or out["recent_errors"] == UNKNOWN:
        out["overall"] = UNKNOWN
    elif out["redis"] == "DEGRADED" or (uids and running < len(uids)):
        out["overall"] = DEGRADED
    else:
        out["overall"] = HEALTHY
    return out


def degraded_users(limit=50):
    """Users whose worker is down, lease is lost, or broker is disconnected."""
    try:
        uids = user_store.all_active() or []
    except Exception as e:
        return _unknown(f"user store unreachable: {e}")
    rows = []
    for u in uids[:max(1, min(int(limit or 50), 200))]:
        w = user_worker_status(u)
        o = user_ownership(u)
        b = user_broker_status(u)
        why = []
        if w.get("running") is False:
            why.append("worker not running")
        if o.get("lease") in (OWNERSHIP_LOST_ST, "NOT_OWNED"):
            why.append(f"lease {o.get('lease')}")
        if o.get("status") == UNKNOWN:
            why.append("lease UNKNOWN")
        if b.get("broker") not in ("CONNECTED", "NOT_CONNECTED", None):
            why.append(f"broker {b.get('broker')}")
        if why:
            rows.append({"user": u, "reasons": why})
    return _ok(degraded=rows, checked=len(uids))


def unprotected_positions(limit=50):
    """Open positions with no stop attached. P0 if any are on a live account."""
    try:
        uids = user_store.all_active() or []
    except Exception as e:
        return _unknown(f"user store unreachable: {e}")
    rows = []
    for u in uids[:max(1, min(int(limit or 50), 200))]:
        p = user_positions(u)
        if p.get("protection") == "MISSING_STOP":
            r = user_risk(u)
            rows.append({"user": u, "mode": r.get("mode", UNKNOWN),
                         "positions": p.get("positions", [])})
    return _ok(unprotected=rows, checked=len(uids))


# ─── Level 1: composed views ──────────────────────────────
def user_health(user_id):
    """Everything about one client, on one screen. Reads only."""
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not _known(uid):
        return {"error": "no such user"}
    parts = {
        "license": user_license(uid),
        "broker": user_broker_status(uid),
        "risk": user_risk(uid),
        "worker": user_worker_status(uid),
        "ownership": user_ownership(uid),
        "positions": user_positions(uid),
        "reconcile": reconcile_status(uid),
        "errors": recent_errors(uid, limit=10),
    }
    st, _cause, _blocked = _classify(parts)
    return {"user": uid, "overall": st, **parts}


def _classify(p):
    """(status, cause, trading_blocked) from the gathered parts.

    Order matters: the most specific blocking condition wins, and UNKNOWN beats
    HEALTHY. A client whose lease cannot be read is not healthy, they are
    unverifiable, and the operator needs to be told which.
    """
    if p["license"].get("license") == "REVOKED":
        return LICENSE_BLOCKED, "licence revoked", True
    if p["ownership"].get("lease") == OWNERSHIP_LOST_ST:
        return OWNERSHIP_LOST_ST, "another instance took over the account", True
    if p["risk"].get("guard") == "HOLDING":
        return RISK_BLOCKED, "; ".join(p["risk"].get("guard_reasons") or
                                       ["risk limit hit"]), True
    if p["broker"].get("broker") == "NOT_CONNECTED":
        return BROKER_DISCONNECTED, "no broker connected", True
    if p["positions"].get("protection") == "MISSING_STOP":
        return SAFE_MODE, "an open position has no stop attached", True
    if any(x.get("status") == UNKNOWN for x in p.values()):
        unknowns = [k for k, v in p.items() if v.get("status") == UNKNOWN]
        return UNKNOWN, f"could not verify: {', '.join(unknowns)}", True
    if p["worker"].get("running") is False:
        return DEGRADED, "worker is not running", True
    if p["reconcile"].get("state") == RECOVERY:
        return RECOVERY, "broker sync is stale", True
    return HEALTHY, "", False


def investigate(user_id):
    """Why is this client not trading? Diagnosis only — changes nothing."""
    uid, err = _valid_user(user_id)
    if err:
        return {"error": err}
    if not _known(uid):
        return {"error": "no such user"}
    parts = {
        "license": user_license(uid),
        "broker": user_broker_status(uid),
        "risk": user_risk(uid),
        "worker": user_worker_status(uid),
        "ownership": user_ownership(uid),
        "positions": user_positions(uid),
        "reconcile": reconcile_status(uid),
        "errors": recent_errors(uid, limit=10),
    }
    st, cause, blocked = _classify(parts)
    return {
        "user": uid,
        "status": st,
        "cause": cause or "nothing is blocking new entries",
        "new_entries": "BLOCKED" if blocked else "ALLOWED",
        "open_positions": parts["positions"].get("open_count", UNKNOWN),
        "protection": parts["positions"].get("protection", UNKNOWN),
        "recommended_action": _advice(st),
        "financial_action_taken": False,
        "evidence": parts,
    }


_ADVICE = {
    LICENSE_BLOCKED: "Restore the grant or licence, then restart the worker.",
    OWNERSHIP_LOST_ST: "Expected during a deploy. If it persists, check whether "
                       "two instances are running.",
    RISK_BLOCKED: "Risk guard is holding by design. Review the limits before "
                  "overriding anything.",
    BROKER_DISCONNECTED: "Ask the client to reconnect via /ctrader.",
    SAFE_MODE: "An open position has no stop. Attend to it before anything else.",
    DEGRADED: "Restart the worker (level 2, needs confirmation).",
    RECOVERY: "Broker sync is stale; wait one tick, then re-check.",
    UNKNOWN: "Do not act on this report. Re-run once the unreadable "
             "subsystem recovers.",
}


def _advice(status):
    return _ADVICE.get(status, "No action needed.")
