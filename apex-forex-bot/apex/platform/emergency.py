"""The stop that has to work on the worst day.

WHAT §8 OF THE LIVE-EXECUTION SPECIFICATION ASKS FOR, AND WHY IT IS AWKWARD

Three levels — per client, per instrument, and one global switch that halts
every live loop for every client. The global one carries two requirements that
pull in opposite directions:

    it must not depend on the shared backend being reachable
    it must not require a deploy

A Redis key satisfies the second and fails the first. An environment variable
satisfies the first and fails the second, because changing one on the host
restarts the service. Neither alone is the switch.

So there are TWO independent sources and the widest halt wins:

    A4T_EMERGENCY_HALT          read from the environment. Works when the
                                shared store is unreachable, gone, or
                                misconfigured. Costs a restart to change.
    {ns}:a4t:emergency          a record in the shared store. Changes in
                                seconds with no deploy and no restart. Costs
                                the store being up.

Either can halt. Neither can un-halt the other: `release()` clears the record
it owns, and a halt set in the environment stays until the environment
changes. Anything else would let the easier switch quietly cancel the harder
one, which is backwards — the harder switch is the one somebody reached for
when the easy one was not enough.

THE ASYMMETRY ON UNCERTAINTY, STATED RATHER THAN IMPLIED

§8 also says to halt on the platform's own uncertainty. Taken literally, a
Redis blip would stop every free demo client in the product. That is a worse
outcome than letting them continue: a demo loop risks nothing, and the reads
it depends on already refuse rather than guess.

So uncertainty halts LIVE and not DEMO. An unreachable store means we cannot
know whether somebody pressed the switch, and for real money "I cannot tell"
has to be read as "stop". For practice money it does not. That is a decision,
not an oversight, and `state()` reports `storeReachable: False` so a caller
can see which branch it took.

NOT AN ENDPOINT

`halt()` and `release()` are operator tooling, reached from a shell on the
service, for the same reason the waitlist's removal is: a route that can stop
every client in the product is a route worth attacking, and the one person who
needs it already has a shell. The API only ever READS this.
"""

import json
import os
import time

from apex import user_store
from apex.platform import store as _store

# Scopes, widest first. The order is load-bearing: `_widest` compares by index.
ALL = "all"
LIVE = "live"
NONE = "none"
SCOPES = (ALL, LIVE, NONE)

ENV_VAR = "A4T_EMERGENCY_HALT"


class _NotResolved:
    """Sentinel: the account mode has not been looked up yet.

    Distinct from `None`, which means "we looked and could not tell". See
    `check()` — conflating the two refused free demo clients under a halt
    aimed at live accounts.
    """

    def __repr__(self):
        return "NOT_RESOLVED"


NOT_RESOLVED = _NotResolved()

# Sources, named so a report can say which switch is holding the product down
# — the remedy is different for each.
SRC_ENV = "env"
SRC_STORE = "store"
SRC_UNCERTAIN = "store_unreachable"


class Halted(RuntimeError):
    """Refused because a stop is in force.

    `code` is what a caller branches on, `scope` is which switch, and
    `source` is where it came from — an operator reading a refusal needs to
    know whether to change an environment variable or a stored record.
    """

    def __init__(self, code, message, *, scope=None, source=None, reason=None):
        self.code = code
        self.scope = scope
        self.source = source
        self.reason = reason
        super().__init__(message)


def _k():
    return f"{_store.namespace_prefix()}emergency"


def _widest(a, b):
    """The more severe of two scopes. NONE is the least severe."""
    return a if SCOPES.index(a) <= SCOPES.index(b) else b


def _env_scope():
    """The scope the environment asks for, or NONE.

    An unrecognised value is treated as ALL rather than ignored. Somebody who
    sets this variable is trying to stop the product; a typo in that moment
    must not read as "carry on".
    """
    raw = (os.getenv(ENV_VAR) or "").strip().lower()
    if not raw or raw in ("0", "false", "off", "no", NONE):
        return NONE
    if raw == LIVE:
        return LIVE
    return ALL


def _read_record():
    """The stored halt record, or None. Raises if the store cannot be asked.

    A strict read on purpose: `_read` cannot tell "nothing is stored" from
    "the store did not answer", and those are the two cases this whole module
    turns on.
    """
    raw = _store.read_raw(_k())
    if not raw:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        # A record we cannot parse is not an absent one. Refusing to read it
        # as "no halt" is the same rule as everywhere else here.
        raise user_store.StoreUnavailable(
            "the emergency record is stored but unreadable")
    return rec if isinstance(rec, dict) else None


def state():
    """The whole picture, with no exception to catch.

    Returns:
        scope           the effective halt, widest of both sources
        source          which source produced it
        storeReachable  False when the stored switch could not be asked
        instruments     symbols halted individually
        users           clients halted individually
        reason / by / at  from the stored record, when there is one

    Never raises. A function whose job is to answer "are we stopped?" cannot
    be one that fails to answer.
    """
    env_scope = _env_scope()
    out = {
        "scope": env_scope,
        "source": SRC_ENV if env_scope != NONE else None,
        "storeReachable": True,
        "instruments": [],
        "users": [],
        "reason": None,
        "by": None,
        "at": None,
        "envScope": env_scope,
        "storeScope": NONE,
    }
    try:
        rec = _read_record()
    except Exception as e:                                  # noqa: BLE001
        # We cannot tell whether somebody pressed the switch. For real money
        # that reads as "stop"; for practice money it does not. See the module
        # docstring — this asymmetry is the decision, not an accident.
        out["storeReachable"] = False
        out["storeError"] = f"{type(e).__name__}: {e}"
        out["storeScope"] = LIVE
        out["scope"] = _widest(env_scope, LIVE)
        out["source"] = SRC_ENV if env_scope == ALL else SRC_UNCERTAIN
        return out
    if not rec:
        return out
    scope = rec.get("scope")
    scope = scope if scope in SCOPES else NONE
    out["storeScope"] = scope
    widest = _widest(env_scope, scope)
    out["scope"] = widest
    out["source"] = (SRC_ENV if widest == env_scope and env_scope != NONE
                     else SRC_STORE if widest != NONE else None)
    out["instruments"] = [str(s).upper() for s in (rec.get("instruments") or [])]
    out["users"] = [str(u) for u in (rec.get("users") or [])]
    out["reason"] = rec.get("reason")
    out["by"] = rec.get("by")
    out["at"] = rec.get("at")
    return out


def check(*, user_id=None, symbol=None, mode=NOT_RESOLVED, st=None):
    """Raise `Halted` if this action is stopped. Otherwise return the state.

    `mode` is the account mode — `demo`, `live`, or anything else, which is
    treated as not-demo. It decides whether a LIVE-scoped halt applies, so a
    caller that looked and could not tell gets the stricter answer.

    THREE STATES, NOT TWO. "We have not resolved the account yet" is not the
    same as "we looked and could not tell", and collapsing them cost a real
    defect: `automation._preflight` asks this question twice, once before the
    connection is resolved and once after, and the first call treating an
    absent mode as "unknown" refused every FREE DEMO CLIENT under a
    LIVE-scoped halt. Demo access is the product; a switch aimed at real money
    must not take it down.

    So `NOT_RESOLVED` — the default — skips the levels that need a mode, and
    anything else, `None` included, is judged strictly.
    """
    st = state() if st is None else st
    scope = st["scope"]
    mode_known = mode is not NOT_RESOLVED
    is_demo = str(mode) == "demo"

    if scope == LIVE and not mode_known:
        # Nothing to decide here yet. The caller asks again once it knows.
        scope = NONE

    if scope == ALL:
        raise Halted("HALTED_ALL",
                     "automation is stopped for every client by an emergency "
                     "switch", scope=ALL, source=st["source"],
                     reason=st.get("reason"))
    if scope == LIVE and not is_demo:
        if st["source"] == SRC_UNCERTAIN:
            raise Halted(
                "HALTED_UNCERTAIN",
                "the emergency switch could not be read, so a non-demo "
                "account is refused rather than assumed safe",
                scope=LIVE, source=SRC_UNCERTAIN, reason=st.get("storeError"))
        raise Halted("HALTED_LIVE",
                     "live accounts are stopped by an emergency switch",
                     scope=LIVE, source=st["source"], reason=st.get("reason"))

    if symbol and str(symbol).upper() in st["instruments"]:
        raise Halted("HALTED_INSTRUMENT",
                     f"{str(symbol).upper()} is stopped by an emergency "
                     f"switch", scope=st["scope"], source=SRC_STORE,
                     reason=st.get("reason"))
    if user_id is not None and str(user_id) in st["users"]:
        raise Halted("HALTED_CLIENT",
                     "automation is stopped for this account by an emergency "
                     "switch", scope=st["scope"], source=SRC_STORE,
                     reason=st.get("reason"))
    return st


# ── operator tooling ────────────────────────────────────────────────────────
def halt(scope=ALL, *, reason, by, instruments=None, users=None, now=None):
    """Press the switch. `reason` and `by` are required, not optional.

    An emergency stop with no recorded reason and no recorded actor is an
    outage whose cause nobody can reconstruct afterwards — and this is exactly
    the record somebody will be reading at the worst possible moment.
    """
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    if not str(reason or "").strip():
        raise ValueError("an emergency halt needs a reason")
    if not str(by or "").strip():
        raise ValueError("an emergency halt needs to record who pressed it")
    rec = {
        "scope": scope,
        "reason": str(reason).strip()[:500],
        "by": str(by).strip()[:120],
        "at": int(now if now is not None else time.time()),
        "instruments": sorted({str(s).upper() for s in (instruments or [])}),
        "users": sorted({str(u) for u in (users or [])}),
    }
    _store.write_raw(_k(), json.dumps(rec, separators=(",", ":")))
    # Read back. A halt that did not store is the one failure this function
    # cannot report as success — the operator would walk away believing the
    # product is stopped.
    back = _read_record()
    if not back or back.get("scope") != scope:
        raise user_store.StoreUnavailable(
            "the emergency halt did not read back — it is NOT in force")
    return state()


def release(*, by, now=None):
    """Clear the STORED switch. Does not touch the environment one.

    Deliberate: a halt set in the environment was set by somebody who either
    could not reach the store or did not trust it, and a stored release must
    not be able to overrule that. `state()` will keep reporting the
    environment's scope, and the remedy is named there.
    """
    if not str(by or "").strip():
        raise ValueError("a release needs to record who performed it")
    _store._delete(_k())
    st = state()
    st["releasedBy"] = str(by).strip()[:120]
    st["releasedAt"] = int(now if now is not None else time.time())
    return st
