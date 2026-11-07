"""Account erasure on the Redis backend, and which key kinds it knows about.

WHY THIS EXISTS

`tests/test_account_data.py` runs erasure on the file backend. Production runs
on Redis, where owned keys are found with `SCAN <ns>:*<id>*` and removed with
`DEL`, and where the engine's active-user set is a Redis set. That path had
only been argued from reading the code. These tests run the REAL `user_store`
functions (`scan_keys`, `del_blob`, `get_blobs_strict`, `_redis_srem`) against
a small in-memory stand-in for the redis-py client, so what is under test is
this repository's code and not the stand-in.

WHAT THESE TESTS WILL NOT ACCEPT

* a key of the caller's left behind after erasure, whatever its kind, or with
  a SCAN that returns its results over several pages;
* a key of another client removed, including a client whose id contains the
  caller's id as a substring (`alice-1` against `alice-10`);
* the caller left in the engine's active-user set, or another client removed
  from it;
* a payment-reference record that names the caller surviving, or one that
  names another client being removed;
* an unreachable store reported as "deleted", on the scan or on the delete;
* a second erasure that fails or reports anything but zeros;
* a new per-user key kind written under `a4t:` that nobody has decided about:
  every kind is either mapped to an erasure category or listed below as
  deliberately not per-user, with the reason.

Run: python3 tests/test_account_erasure_redis.py
"""
import fnmatch
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-erase-redis-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import user_store as U                             # noqa: E402
from apex.platform import account_data as AD                 # noqa: E402
from apex.platform import store as S                         # noqa: E402


class FakeRedis:
    """The redis-py calls `user_store` makes, over a dict.

    `scan` pages its answer (`page` keys per call) so the cursor loop in
    `scan_keys` is exercised, and `fail` names commands that raise.
    """

    def __init__(self, page=3):
        self.kv, self.sets, self.page, self.fail = {}, {}, page, set()

    def _go(self, op):
        if op in self.fail:
            raise ConnectionError(f"{op} unreachable")

    def get(self, key):
        self._go("get")
        return self.kv.get(key)

    def mget(self, keys):
        self._go("mget")
        return [self.kv.get(k) for k in keys]

    def set(self, key, value, ex=None, nx=False):
        self._go("set")
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    def delete(self, *keys):
        self._go("delete")
        n = 0
        for k in keys:
            n += (self.kv.pop(k, None) is not None) + (self.sets.pop(k, None) is not None)
        return n

    def type(self, key):
        self._go("type")
        return "set" if key in self.sets else ("string" if key in self.kv else "none")

    def scan(self, cursor=0, match="*", count=10):
        self._go("scan")
        keys = sorted(k for k in list(self.kv) + list(self.sets)
                      if fnmatch.fnmatchcase(k, match))
        nxt = int(cursor) + self.page
        return (nxt if nxt < len(keys) else 0), keys[int(cursor):nxt]

    def sadd(self, key, *members):
        self._go("sadd")
        self.sets.setdefault(key, set()).update(members)
        return len(members)

    def srem(self, key, *members):
        self._go("srem")
        s = self.sets.get(key, set())
        n = len(s & set(members))
        s.difference_update(members)
        return n

    def smembers(self, key):
        self._go("smembers")
        return set(self.sets.get(key, set()))


NS = U._NS or "apex"
ALICE, ALICE_TEN, BOB = "alice-1", "alice-10", "bob-2"


def doc(uid, **extra):
    return json.dumps({"userId": uid, **extra})


def seed(r, uid):
    """One key of every shape the platform writes for a user."""
    a = f"{NS}:a4t"
    keys = {
        f"{a}:rule:{uid}:r1": doc(uid),
        f"{a}:rulev:{uid}:r1:1": doc(uid),
        f"{a}:rules:{uid}": json.dumps(["r1"]),
        f"{a}:jentry:{uid}:e1": doc(uid),
        f"{a}:jindex:{uid}": json.dumps(["e1"]),
        f"{a}:jlock:{uid}": "1",
        f"{a}:notify:{uid}": json.dumps([{"userId": uid}]),
        f"{a}:notifylock:{uid}": "1",
        f"{a}:licence:{uid}": doc(uid, state="active"),
        f"{a}:ctrader:{uid}": "enc:ciphertext",
        f"{a}:ctlink:{uid}": doc(uid),
        f"{a}:automation:{uid}": doc(uid),
        f"{a}:autolock:{uid}": "1",
        f"{a}:suggestion:{uid}:s1": doc(uid),
        f"{a}:suggclaim:{uid}:s1": "1",
        f"{a}:audit:{uid}:1": doc(uid),
        f"{a}:referral:{uid}": doc(uid),
        f"{a}:livegate:{uid}": doc(uid),
        f"{a}:billing:intent:{uid}": doc(uid),
        f"{a}:orderrate:{uid}:1": "3",
        f"{a}:rl:user:emergency_user:{uid}:99": "2",
        f"{NS}:user:{uid}": doc(uid),
        f"{NS}:uver:{uid}": "4",
        f"{NS}:trades:{uid}": json.dumps([]),
        f"{NS}:tver:{uid}": "1",
    }
    r.kv.update(keys)
    r.kv[f"{a}:billing:ref:pay_{uid}"] = doc(uid, at=1)
    return set(keys) | {f"{a}:billing:ref:pay_{uid}"}


def mine(r, uid):
    return {k for k in r.kv if uid in k.split(":")}


def stop_ok(uid):
    return {"stopped": True}


saved = (U._BACKEND, U._USE_REDIS, getattr(U, "_r", None))


def install(r):
    U._BACKEND, U._USE_REDIS, U._r = "redis", True, r


def restore():
    U._BACKEND, U._USE_REDIS, U._r = saved


print("\n[1] erasure on the Redis backend removes the caller's keys and only those")
try:
    r = FakeRedis(page=3)
    install(r)
    alice = seed(r, ALICE)
    ten = seed(r, ALICE_TEN)
    bob = seed(r, BOB)
    r.sadd(U._ACTIVE_SET, ALICE, ALICE_TEN, BOB)
    before_others = {k: r.kv[k] for k in ten | bob}
    check("the seed covers more keys than one SCAN page", len(alice) > r.page * 3)

    owned = {k for k, _c, _kind in AD.owned_keys(ALICE)}
    check("owned_keys finds every key through a paged SCAN",
          owned == alice - {k for k in alice if "billing:ref:" in k}, str(sorted(
              (alice - {k for k in alice if 'billing:ref:' in k}) ^ owned)))
    check("and not a key of the id that merely contains it",
          not (owned & ten))

    os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-only-not-a-real-key"
    out = AD.delete(ALICE, {"confirm": "DELETE"}, stop_automation=stop_ok,
                    auth_deleter=lambda *a: 204)
    check("no key of the caller is left", not mine(r, ALICE), str(sorted(mine(r, ALICE))))
    check("her payment reference is gone", f"{NS}:a4t:billing:ref:pay_{ALICE}" not in r.kv)
    check("another client's keys are untouched, value for value",
          all(r.kv.get(k) == v for k, v in before_others.items()))
    check("including the client whose id contains hers",
          ten <= set(r.kv) and bob <= set(r.kv))
    check("she left the active-user set and the others stayed",
          r.sets[U._ACTIVE_SET] == {ALICE_TEN, BOB}, str(r.sets[U._ACTIVE_SET]))
    d = out["deleted"]
    check("every reported category counts something it removed",
          all(d[c] > 0 for c in ("rules", "journal", "notifications", "licence",
                                 "ctraderLink", "settings", "trades",
                                 "automation", "caches")), str(d))
    check("the Supabase user is reported deleted only through the injected call",
          out["authUserDeleted"] is True)

    again = AD.delete(ALICE, {"confirm": "DELETE"}, stop_automation=stop_ok,
                      auth_deleter=lambda *a: 404)
    check("a second erasure reports zeros and does not fail",
          all(v == 0 for v in again["deleted"].values()), str(again["deleted"]))
finally:
    os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    restore()

print("\n[2] an unreachable store is never reported as deleted")
for op in ("scan", "delete"):
    try:
        r = FakeRedis()
        install(r)
        seed(r, ALICE)
        keys_before = dict(r.kv)
        r.fail.add(op)
        try:
            AD.delete(ALICE, {"confirm": "DELETE"}, stop_automation=stop_ok)
            check(f"erasure with {op} down raises", False)
        except U.StoreUnavailable:
            check(f"erasure with {op} down raises StoreUnavailable", True)
        check(f"nothing is claimed deleted after {op} failed",
              set(keys_before) >= set(r.kv) and (op != "scan" or r.kv == keys_before))
    finally:
        restore()

print("\n[3] a failed stop erases nothing on Redis either")
try:
    r = FakeRedis()
    install(r)
    seed(r, ALICE)
    before = dict(r.kv)

    def bad_stop(uid):
        raise RuntimeError("could not stop")

    try:
        AD.delete(ALICE, {"confirm": "DELETE"}, stop_automation=bad_stop)
        check("refused", False)
    except AD.AccountDataError as e:
        check("refused with AUTOMATION_STOP_FAILED", e.code == "AUTOMATION_STOP_FAILED")
    check("and every key is still there", r.kv == before)
finally:
    restore()

print("\n[4] every per-user key kind the platform writes has been decided about")
# Kinds written under `<ns>:a4t:` that are NOT per-user records, with why.
NOT_PER_USER = {
    "waitlist": "keyed by a digest of an e-mail address, before any account exists",
}
# Per-user records that carry the user id in the VALUE of a key named for
# something else, so a scan on the id cannot find them. Not erased today; each
# is a decision for the owner, listed so a new one cannot appear silently.
KEYED_BY_OTHER_ID = {
    "review": "billing:review:<stripe event> holds claimedUserId for a payment "
              "held for manual review; a payment record, retention is a legal "
              "question (issue #70 follow-up)",
}

written = set()
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "apex")):
    for f in files:
        if f.endswith(".py") and not f.endswith("_pb2.py"):
            text = open(os.path.join(dirpath, f), encoding="utf-8").read()
            written.update(re.findall(r"_P\}:([a-z_]+)", text))
check("the scan found the key kinds in the source", len(written) >= 15, str(sorted(written)))
unknown = sorted(k for k in written
                 if k not in AD._A4T_CATEGORY and k not in NOT_PER_USER)
check("no key kind is neither mapped to an erasure category nor exempted",
      not unknown, f"decide about: {unknown}")
check("each exemption names a reason", all(NOT_PER_USER.values()) and all(KEYED_BY_OTHER_ID.values()))
check("the exemptions are still real kinds", set(NOT_PER_USER) <= written,
      str(set(NOT_PER_USER) - written))

billing_src = open(os.path.join(ROOT, "apex", "platform", "billing.py"),
                   encoding="utf-8").read()
check("the review record still names a user in its value (the gap is real)",
      "claimedUserId" in billing_src and "billing:review:" in billing_src)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All account erasure (Redis) checks passed.")
