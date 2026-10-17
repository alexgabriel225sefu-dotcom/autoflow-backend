"""The ledger that stops one decision becoming two positions.

§6 of docs/LIVE_EXECUTION_SPECIFICATION.md names three ways a duplicate
happens — a retry, a redeploy, and two instances racing — and one shape of key
that catches all three. The assertions that matter here are not "does a claim
work" but:

  * THE KEY IS THE DECISION. Two instances that compute the same decision seven
    seconds apart must compute the SAME key. A key that reads the clock is the
    bug this file exists to catch, because it looks like it works: the first
    claim wins, and the second instance — the deploy overlap this project has
    in its own logs, seven seconds wide — sails straight through with a key
    nobody else is holding.
  * A CLAIM IS NOT RELEASED ON AN UNKNOWN OUTCOME. A timed-out submit may have
    filled. Releasing the claim there turns one uncertain order into two
    certain ones.
  * THE PROCESS REFUSES TO START with no shared backend. Not degrades, not
    warns — refuses, which is asserted in a real subprocess rather than by
    calling a function, because "the process must refuse to start" is a claim
    about a process.

The fake backend below is deliberately hostile: its NX is atomic, it offers a
GET, and it can be made to release every waiting thread at once. An
implementation that checked and then set would pass a sequential test and fail
this one, which is the whole point of writing it this way.

Run: python3 tests/test_platform_live_ledger.py
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-ledger-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("REDIS_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import user_store                             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def raised(exc, fn, *a, **kw):
    """The exception `fn` raised, or None. Anything else propagates."""
    try:
        fn(*a, **kw)
        return None
    except exc as e:
        return e


# ── a shared backend that behaves like one, and can be made hostile ─────────
class FakeShared:
    """SET NX, atomic, plus the GET a wrong implementation would reach for.

    The LATCH is the hazard, and WHERE it sits in each operation is the whole
    design. A claim is held BEFORE its atomic section, so every attempt is
    poised on the same key at once and the NX has to pick one. A read is held
    AFTER it has its answer, so every reader is holding "the key is free"
    before any writer acts — which is exactly the state two containers are in
    when both decide to trade, and it makes a check-then-set implementation
    produce eight winners every time rather than occasionally.

    A latch rather than a Barrier on purpose: a barrier fixes the number of
    waiters, so it deadlocks the moment the code under test makes one more
    call or one fewer, and a deadlock is an unreadable failure.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.calls = {"claim_value": 0, "release_claim": 0, "set_blob": 0,
                      "get_blob_strict": 0}
        self.released = []
        self.down = False
        self.latched = False
        self.arrived = 0
        self.go = threading.Event()

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        user_store.claim_value = self.claim_value
        user_store.release_claim = self.release_claim
        user_store.set_blob = self.set_blob
        user_store.get_blob_strict = self.get_blob_strict

    def arm_latch(self):
        self.latched = True
        self.arrived = 0
        self.go.clear()

    def release_latch(self, want, timeout=15.0):
        """Wait until `want` callers are held, then let them all go."""
        deadline = time.time() + timeout
        while self.arrived < want and time.time() < deadline:
            time.sleep(0.01)
        held = self.arrived
        self.latched = False
        self.go.set()
        return held

    def _gate(self):
        if not self.latched:
            return
        with self.lock:
            self.arrived += 1
        self.go.wait(timeout=20)

    def claim_value(self, key, value, ttl_s=120):
        self.calls["claim_value"] += 1
        if self.down:
            return None                 # could not ask — NOT "taken"
        self._gate()
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = str(value)
            return True

    def release_claim(self, key, value):
        self.calls["release_claim"] += 1
        if self.down:
            return None
        with self.lock:
            if self.data.get(key) != str(value):
                return False            # not ours — a Redlock release is scoped
            del self.data[key]
        self.released.append(key)
        return True

    def set_blob(self, key, value_str, ttl_s=None):
        self.calls["set_blob"] += 1
        if self.down:
            return False
        with self.lock:
            self.data[key] = value_str
        return True

    def get_blob_strict(self, key):
        self.calls["get_blob_strict"] += 1
        if self.down:
            raise user_store.StoreUnavailable("fake backend is unreachable")
        with self.lock:
            got = self.data.get(key)
        self._gate()            # held AFTER the read — see the class docstring
        return got


FAKE = FakeShared()
FAKE.install()

from apex.platform import live_ledger as L              # noqa: E402
from apex.platform import store as _store               # noqa: E402

# One decision, expressed the way the platform expresses one. 1 758 542 400 is
# inside the 1h bar that opens at 1 758 542 400 and closes an hour later, so a
# second reading a few seconds later is the SAME bar.
BAR_OPEN = 1_758_542_400
TF = "1h"


def decision(**over):
    d = {"symbol": "EUR_USD", "side": "BUY", "verdict": "BUY",
         "ruleDocId": "rule-7", "ruleDocVersion": 3,
         "snapshotTs": float(BAR_OPEN + 12)}
    d.update(over)
    return d


print("\n[1] the claim key is derived from the DECISION, not from the clock")
k_a = L.setup_key_for(decision(), timeframe=TF)
k_b = L.setup_key_for(decision(snapshotTs=float(BAR_OPEN + 19)), timeframe=TF)
check("the key has the SYMBOL:SIDE:strategy:bar shape",
      k_a == f"EURUSD:BUY:rule-7v3:{BAR_OPEN}", k_a)
check("the same decision seven seconds later gives the SAME key",
      k_a == k_b, f"{k_a} != {k_b} — this is the deploy-overlap duplicate")
check("a decision in the NEXT bar gives a different key",
      L.setup_key_for(decision(snapshotTs=float(BAR_OPEN + 3600)),
                      timeframe=TF) != k_a)
check("two different rules on one bar do not share a key",
      L.setup_key_for(decision(ruleDocId="rule-8"), timeframe=TF) != k_a)
check("two versions of one rule do not share a key",
      L.setup_key_for(decision(ruleDocVersion=4), timeframe=TF) != k_a)
check("the opposite side does not share a key",
      L.setup_key_for(decision(side="SELL", verdict="SELL"),
                      timeframe=TF) != k_a)
for spelling in ("EUR_USD", "eur/usd", "eurusd", "EURUSD"):
    check(f"{spelling} is the same instrument",
          L.setup_key_for(decision(symbol=spelling), timeframe=TF) == k_a)
check("an unknown timeframe is refused, not guessed",
      raised(ValueError, L.setup_key_for, decision(), timeframe="7s")
      is not None)
check("a decision with no tradable side is refused",
      raised(ValueError, L.setup_key_for, decision(side=None, verdict="HOLD"),
             timeframe=TF) is not None)
check("a decision with no snapshot is refused",
      raised(ValueError, L.setup_key_for, decision(snapshotTs=None),
             timeframe=TF) is not None)
check("the stored key lives under the platform namespace, so the backup "
      "covers it",
      L.claim_key("u1", "acc1", k_a).startswith(_store.namespace_prefix()),
      L.claim_key("u1", "acc1", k_a))
check("an identity carrying the key separator is refused rather than mangled",
      raised(ValueError, L.claim_key, "u1:evil", "acc1", k_a) is not None,
      "mangling two ids onto one key makes one client block another")


print("\n[2] two concurrent attempts on one key — exactly one proceeds")
FAKE.data.clear()
FAKE.calls["claim_value"] = 0
N = 8
won, refused_as_dupe, other = [], [], []


def attempt():
    try:
        won.append(L.claim(decision(), user_id="u1", account_id="acc1",
                           timeframe=TF))
    except L.AlreadyClaimed:
        refused_as_dupe.append(1)
    except BaseException as e:                          # noqa: BLE001
        other.append(f"{type(e).__name__}: {e}")


FAKE.arm_latch()
threads = [threading.Thread(target=attempt) for _ in range(N)]
for t in threads:
    t.start()
held = FAKE.release_latch(N)
for t in threads:
    t.join(timeout=30)
check("all eight attempts really were in flight at once", held == N,
      f"{held} of {N} were held at the latch")
check("exactly one of eight concurrent attempts proceeds", len(won) == 1,
      f"{len(won)} winners, {len(refused_as_dupe)} refused, other={other}")
check("the other seven are refused as already claimed",
      len(refused_as_dupe) == N - 1, str(len(refused_as_dupe)))
check("nothing failed for another reason", other == [], str(other))
check("the claim records WHO holds it, so only the holder can release it",
      len(won) == 1 and bool(getattr(won[0], "holder", None)),
      "claim_value carries the holder; claim() writes a bare 1 and cannot")
check("one shared-store claim per attempt — no pre-flight on the order path",
      FAKE.calls["claim_value"] == N, str(FAKE.calls))


print("\n[3] a store that cannot answer refuses — it does not claim")
FAKE.data.clear()
FAKE.down = True
err = raised(L.CoordinationUnavailable, L.claim, decision(), user_id="u1",
             account_id="acc1", timeframe=TF)
check("an unanswering store refuses rather than claiming", err is not None,
      "None from claim_value is 'I could not ask', never 'I won'")
check("and nothing was written", FAKE.data == {}, str(FAKE.data))
FAKE.down = False


print("\n[4] the claim is released only on a CONFIRMED outcome")
FAKE.data.clear()
FAKE.released.clear()
c = L.claim(decision(), user_id="u1", account_id="acc1", timeframe=TF)

unknown = L.abandon_unknown(c, detail="submit timed out; fill state unknown")
check("an unknown outcome is recorded as unknown",
      unknown["outcome"] == L.UNKNOWN, str(unknown))
check("an unknown outcome NEVER releases the claim", FAKE.released == [],
      "a claim released on an unknown result turns one uncertain order "
      "into two")
check("so the same decision is still refused afterwards",
      raised(L.AlreadyClaimed, L.claim, decision(), user_id="u1",
             account_id="acc1", timeframe=TF) is not None)

FAKE.data.clear()
FAKE.released.clear()
c2 = L.claim(decision(symbol="GBPUSD"), user_id="u1", account_id="acc1",
             timeframe=TF)
L.confirm_filled(c2, broker_reply={"ok": True, "positionId": "pos-1"},
                 position_id="pos-1")
check("a confirmed FILL does not release the claim either",
      FAKE.released == [],
      "the position exists; freeing its key is how the retry duplicates it")
check("so a retry of a filled decision is refused",
      raised(L.AlreadyClaimed, L.claim, decision(symbol="GBPUSD"),
             user_id="u1", account_id="acc1", timeframe=TF) is not None)

FAKE.data.clear()
FAKE.released.clear()
c3 = L.claim(decision(symbol="USDJPY"), user_id="u1", account_id="acc1",
             timeframe=TF)
L.confirm_rejected(c3, broker_reply={"ok": False}, code="MARKET_CLOSED")
check("a confirmed broker REJECTION does release the claim",
      FAKE.released == [c3.key], str(FAKE.released))
check("so the decision can be retried once the broker has said no",
      L.claim(decision(symbol="USDJPY"), user_id="u1", account_id="acc1",
              timeframe=TF) is not None)
check("the release is scoped to the holder token, not to the key",
      FAKE.calls["release_claim"] > 0
      and raised(L.NotTheHolder, L.confirm_rejected,
                 L.Claim(key=c3.key, setup_key=c3.setup_key,
                         holder="some-other-process", ttl_s=60),
                 broker_reply={"ok": False}, code="X") is not None,
      "a Redlock release that ignores the token frees another "
      "container's claim")


print("\n[5] the recorded outcome outlives this process")
FAKE.data.clear()
c4 = L.claim(decision(symbol="AUDUSD"), user_id="u1", account_id="acc1",
             timeframe=TF)
L.confirm_filled(c4, broker_reply={"ok": True, "positionId": "pos-9"},
                 position_id="pos-9")
check("the outcome is written to the SHARED store, not to process memory",
      FAKE.calls["set_blob"] > 0 and any(
          "outcome" in k for k in FAKE.data),
      str(sorted(FAKE.data)))
got = L.outcome_for(c4)
check("and a duplicate can be answered with the original outcome",
      got and got.get("positionId") == "pos-9", str(got))
FAKE.down = True
check("a store that cannot answer does not read as 'no outcome recorded'",
      raised(L.CoordinationUnavailable, L.outcome_for, c4) is not None,
      "an absent outcome and an unreachable store are different facts")
FAKE.down = False


print("\n[6] a shared backend is MANDATORY — the process refuses to start")
check("assert_shared_backend() raises rather than reporting degraded",
      (lambda: (setattr(user_store, "_USE_REDIS", False),
                raised(L.SharedBackendRequired, L.assert_shared_backend),
                setattr(user_store, "_USE_REDIS", True))[1])() is not None)

_child = (
    "import os, sys\n"
    f"sys.path.insert(0, {ROOT!r})\n"
    "from apex.platform import live_ledger\n"
    "print('IMPORTED')\n"
)
_env = dict(os.environ)
_env["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-ledger-child-")
for _k in ("REDIS_URL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    _env.pop(_k, None)
_r = subprocess.run([sys.executable, "-c", _child], capture_output=True,
                    text=True, env=_env, timeout=120)
check("importing it with no shared backend exits non-zero",
      _r.returncode != 0, f"rc={_r.returncode} out={_r.stdout.strip()!r}")
check("the module never finished importing", "IMPORTED" not in _r.stdout)
check("and the refusal names the shared backend",
      "shared" in (_r.stderr or "").lower()
      and "SharedBackendRequired" in (_r.stderr or ""),
      (_r.stderr or "")[-300:])


print("\n[7] the ledger stays outside the execution boundary")
_src = open(os.path.join(ROOT, "apex", "platform", "live_ledger.py"),
            encoding="utf-8").read()
check("it does not import the order-placing module",
      "import bridge" not in _src and "platform.bridge" not in _src)
check("and it does not import the execution controller",
      "import execution" not in _src and "platform.execution" not in _src)


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All live-ledger invariants hold.")
