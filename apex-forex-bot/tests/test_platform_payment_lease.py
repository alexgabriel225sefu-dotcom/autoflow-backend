"""A Redis SET NX lease is not a completed payment grant.

`user_store.claim` stores ``1`` with a TTL. That means a worker holds the
payment. It does not mean the licence was written. This file starts a
local Redis, on 127.0.0.1 only, with persistence off, and talks to it with
the redis client the application uses. It does not read a production URL.

If `redis-server` is not installed, the file says so and does not pretend
the cases ran. A local-file fallback is not this proof.

Run: python3 tests/test_platform_payment_lease.py
"""
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-lease-")
os.environ["ALLOW_PLAINTEXT_DEV_STORAGE"] = "true"
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_STRIPE_WEBHOOK_SECRET", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import user_store                                          # noqa: E402
from apex.platform import billing as B                               # noqa: E402
from apex.platform import licence as LIC                             # noqa: E402
from apex.platform import store as ST                                # noqa: E402

_fails = []
SECRET = "whsec_synthetic_payment_lease"
USER = "dddddddd-4444-4444-8444-dddddddddddd"


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


def sign(raw):
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def deliver(event):
    raw = json.dumps(event).encode()
    return B.handle_event(raw, sign(raw), secret=SECRET)


def session(eid, pi, etype="checkout.session.completed"):
    return {"id": eid, "type": etype, "livemode": True, "data": {"object": {
        "object": "checkout.session", "payment_status": "paid",
        "payment_intent": pi, "amount_total": B.APPROVED_PRICE_MINOR,
        "currency": "usd", "metadata": {B.USER_META_KEY: USER}}}}


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def start_redis():
    binary = shutil.which("redis-server")
    if not binary:
        print("LIMITATION: redis-server is not installed. The shared SET NX "
              "cases were not executed against Redis. This run is not Redis proof.")
        return None, None
    port = free_port()
    directory = tempfile.mkdtemp(prefix="a4t-redis-")
    proc = subprocess.Popen(
        [binary, "--bind", "127.0.0.1", "--port", str(port),
         "--protected-mode", "yes", "--save", "", "--appendonly", "no",
         "--dir", directory, "--dbfilename", "dump.rdb",
         "--logfile", os.path.join(directory, "redis.log"),
         "--daemonize", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import redis
    client = redis.Redis(host="127.0.0.1", port=port, db=0, decode_responses=True,
                         socket_connect_timeout=0.2)
    deadline = time.time() + 5
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            if client.ping():
                return proc, client
        except Exception:
            time.sleep(0.05)
    proc.kill()
    print("LIMITATION: redis-server did not answer. The shared SET NX cases "
          "were not executed. This run is not Redis proof.")
    return None, None


print("\n[0] local Redis, persistence off, loopback only")
proc, client = start_redis()
if proc is None:
    sys.exit(0)

saved = (user_store._r, user_store._BACKEND, user_store._USE_REDIS)
user_store._r = client
user_store._BACKEND = "redis"
user_store._USE_REDIS = True
try:
    client.flushdb()
    info = client.info("server")
    check("the server identifies itself as Redis",
          str(info.get("redis_version") or ""), str(info.get("redis_version")))

    print("\n[1] a held lease is not a completed grant")
    PI = "pi_lease_held"
    owned = user_store.claim(B._k_once_lease(PI), ttl_s=B._LEASE_S)
    check("the lease was taken", owned is True)
    raw = user_store.get_blob(B._k_once_lease(PI))
    check("the lease value is the bare claim, not an outcome", raw == "1", repr(raw))
    ttl = client.ttl(B._k_once_lease(PI))
    check("the lease expires", 0 < int(ttl) <= B._LEASE_S, str(ttl))
    check("no durable grant record yet",
          user_store.get_blob(B._k_once(PI)) in (None, ""))
    st, out = deliver(session("evt_while_leased", PI))
    check("the second event is a retry, not a duplicate",
          st == 500 and out.get("duplicate") is not True
          and out.get("outcome") != "granted", str(out))
    check("no licence was written under the lease",
          LIC.status_for(USER)["state"] != LIC.ACTIVE)

    print("\n[2] deleting the lease, as expiry would, lets the payment grant")
    client.delete(B._k_once_lease(PI))
    st, out = deliver(session("evt_after_expiry", PI))
    check("the payment grants after the lease is gone",
          st == 200 and out.get("outcome") == "granted", str(out))
    durable = user_store.get_blob(B._k_once(PI))
    check("the durable record says granted",
          isinstance(durable, str) and "granted" in durable, repr(durable))
    st, out = deliver(session("evt_after_grant", PI, "checkout.session.async_payment_succeeded"))
    check("a later event for that payment is a duplicate",
          st == 200 and out.get("duplicate") is True, str(out))
    check("still one active licence", LIC.status_for(USER)["state"] == LIC.ACTIVE)

    print("\n[3] a grant that raises releases the lease, and the retry grants")
    LIC.revoke(USER)
    PI2 = "pi_lease_crash"

    def boom(*_a, **_k):
        raise RuntimeError("worker died after the claim")

    real_grant = B._lic.grant
    B._lic.grant = boom
    try:
        st, out = deliver(session("evt_crash", PI2))
        check("the failed grant is a retry", st == 500 and out.get("duplicate") is not True,
              str(out))
    finally:
        B._lic.grant = real_grant
    check("the lease was released", user_store.get_blob(B._k_once_lease(PI2)) in (None, ""))
    check("no durable record from the crash",
          user_store.get_blob(B._k_once(PI2)) in (None, ""))
    st, out = deliver(session("evt_crash_retry", PI2))
    check("the retry grants", st == 200 and out.get("outcome") == "granted", str(out))

    print("\n[4] an unreadable completion record fails closed")
    PI3 = "pi_lease_unknown"
    real_read = ST._read_strict

    def unreadable(key):
        if key == B._k_once(PI3):
            raise user_store.StoreUnavailable("completion unreadable")
        return real_read(key)

    ST._read_strict = unreadable
    try:
        st, out = deliver(session("evt_unknown", PI3))
        check("unknown storage is a retry",
              st == 500 and out.get("error", {}).get("message") == "StoreUnavailable",
              str(out))
    finally:
        ST._read_strict = real_read
    check("no durable record was written for the unreadable payment",
          user_store.get_blob(B._k_once(PI3)) in (None, ""))

    print("\n[5] a stale open read does not grant after the other worker finished")
    PI5 = "pi_lease_interleave"
    LIC.revoke(USER)
    saw_open = threading.Event()
    release_a = threading.Event()
    real_outcome = B._outcome_of
    seen = {"open": False}

    def stale_open(key):
        if key == B._k_once(PI5) and not seen["open"]:
            seen["open"] = True
            saw_open.set()
            release_a.wait(5)
            return "open"
        return real_outcome(key)

    B._outcome_of = stale_open
    holder = {}

    def worker_a():
        holder["gate"] = B._claim_payment(PI5)
        holder["token"] = B._take_token("payment", PI5)

    stalled = threading.Thread(target=worker_a)
    stalled.start()
    check("A is sitting on the open read", saw_open.wait(5))
    st, out = deliver(session("evt_b_finished", PI5))
    check("B grants while A is still looking",
          st == 200 and out.get("outcome") == "granted", str(out))
    release_a.set()
    stalled.join(5)
    B._outcome_of = real_outcome
    check("A is not told to grant", holder.get("gate") != "go", str(holder))
    check("one active licence after the interleaving",
          LIC.status_for(USER)["state"] == LIC.ACTIVE)
    if holder.get("token"):
        published = user_store.publish_if_owner(
            B._k_once_lease(PI5), holder["token"], B._k_once(PI5),
            '{"outcome":"second"}')
        check("A's token cannot publish", published is False, str(published))

    print("\n[6] a second process with the replacement token keeps the lease")
    PI6 = "pi_lease_two_process"
    token_a = "owner-a"
    token_b = "owner-b"
    check("A took the lease",
          user_store.claim_value(B._k_once_lease(PI6), token_a, ttl_s=60) is True)
    client.delete(B._k_once_lease(PI6))
    child = r'''
import sys
sys.path.insert(0, %r)
from apex import user_store
import redis
user_store._r = redis.Redis(host="127.0.0.1", port=int(sys.argv[1]), db=0,
                            decode_responses=True)
user_store._BACKEND = "redis"
user_store._USE_REDIS = True
lease, token_a, token_b = sys.argv[2], sys.argv[3], sys.argv[4]
got = user_store.claim_value(lease, token_b, ttl_s=60)
released = user_store.release_claim(lease, token_a)
published = user_store.publish_if_owner(lease, token_a, lease + ":stale",
                                        '{"outcome":"stale"}')
print("GOT", got)
print("RELEASED", released)
print("PUBLISHED", published)
print("HELD", user_store.get_blob(lease))
''' % ROOT
    proc_b = subprocess.run(
        [sys.executable, "-c", child, str(client.connection_pool.connection_kwargs["port"]),
         B._k_once_lease(PI6), token_a, token_b],
        capture_output=True, text=True)
    text = proc_b.stdout
    check("the child acquired the expired lease", "GOT True" in text, text or proc_b.stderr)
    check("the stale token did not release it", "RELEASED False" in text, text)
    check("the stale token did not publish", "PUBLISHED False" in text, text)
    check("the replacement still holds the lease", "HELD " + token_b in text, text)

    print("\n[7] a crash after the licence write does not revive a refund")
    PI7 = "pi_lease_half_written"
    LIC.revoke(USER)
    gate = B._claim_payment(PI7)
    token = B._take_token("payment", PI7)
    check("the crashing worker owned the lease", gate == "go" and bool(token), str(gate))
    LIC.grant(USER, plan=B.APPROVED_PLAN, payment_ref=PI7)
    client.delete(B._k_once_lease(PI7))
    check("the licence is active and the grant record is absent",
          LIC.status_for(USER)["state"] == LIC.ACTIVE
          and user_store.get_blob(B._k_once(PI7)) in (None, ""))
    from apex.platform import store as _ST
    _ST._write(B._k_refunded(PI7), {"userId": USER, "type": "charge.refunded"})
    LIC.revoke(USER)
    st, out = deliver(session("evt_late_after_revoke", PI7))
    check("the late event does not grant",
          out.get("outcome") != "granted", str(out))
    check("the revoked licence stays revoked",
          LIC.status_for(USER)["state"] == LIC.REVOKED, str(LIC.status_for(USER)))
finally:
    user_store._r, user_store._BACKEND, user_store._USE_REDIS = saved
    proc.kill()
    proc.wait(timeout=5)

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
