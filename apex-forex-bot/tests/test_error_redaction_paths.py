"""Every path that puts an exception's text in front of a client, made to fail first.

WHAT THESE TESTS WILL NOT ACCEPT

* A typed API refusal (auth, store, link, licence, entitlement, automation,
  halt, preview, waitlist, approval, close, bad request) whose body carries a
  URL, a host, a filesystem path, a bearer header or a credential that the
  underlying exception happened to contain. Each handler is exercised with its
  own exception type, so putting the raw text back in ONE handler fails ONE
  named check.
* The emergency state (`storeError`) and the halt refusal built from it
  carrying the store's exception message.
* A broker-read status envelope (`reason`) carrying the connector's message.
* The code or the diagnostic id being lost to redaction: a client needs
  `STORE_UNAVAILABLE`, `POSITION_NOT_FOUND` and the attempt id, and is shown
  them.

Run: python3 tests/test_error_redaction_paths.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-errred-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["RATE_LIMIT_STORE"] = "memory"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


import types                                                 # noqa: E402

from apex import user_store as US                            # noqa: E402
from apex.platform import api as API                         # noqa: E402
from apex.platform import approvals as APPR                  # noqa: E402
from apex.platform import automation as AUTO                 # noqa: E402
from apex.platform import broker_read as BR                  # noqa: E402
from apex.platform import ctrader_link as LINK               # noqa: E402
from apex.platform import emergency as EM                    # noqa: E402
from apex.platform import entitlement as ENT                 # noqa: E402
from apex.platform import identity as ID                     # noqa: E402
from apex.platform import licence as LIC                     # noqa: E402
from apex.platform import position_close as PC               # noqa: E402
from apex.platform import preview as PRE                     # noqa: E402
from apex.platform import waitlist as WAIT                   # noqa: E402

# One poisoned message carrying every shape the brief names: a URL, a header,
# a token, a filesystem path, a host.
URL_BIT = "broker.example.test/v2/accounts"
POISON = ("upstream failed at https://" + URL_BIT + "?access_token=PoisonTokenValue1234567890 "
          "Authorization: Bearer PoisonBearer.abc.def "
          "refresh_token=PoisonRefresh987654 "
          "host='internal-db.example.test' "
          "trace /home/app/secrets/trace.py")
MARKERS = ("PoisonTokenValue", "broker.example.test", "PoisonBearer",
           "PoisonRefresh", "internal-db.example.test", "/home/app",
           "secrets/trace")


def leaked(blob):
    return [m for m in MARKERS if m in str(blob)]


def via_dispatch(exc, method="GET", path="/api/v1/me"):
    """Raise `exc` from inside the dispatcher and return (status, body)."""
    real = API._dispatch

    def boom(*a, **k):
        raise exc

    API._dispatch = boom
    try:
        return API.handle(method, path)
    finally:
        API._dispatch = real


# ── 1. each typed handler in _handle ────────────────────────────────────────
print("\n[1] each typed API refusal is redacted, and keeps its code")
CASES = [
    ("AuthFailed", ID.AuthFailed(POISON), 401, "AUTH_REQUIRED"),
    ("AuthUnavailable", ID.AuthUnavailable(POISON), 503, "AUTH_UNAVAILABLE"),
    ("StoreUnavailable", US.StoreUnavailable(POISON), 503, "STORE_UNAVAILABLE"),
    ("LinkConfigError", LINK.LinkConfigError("LINK_NOT_CONFIGURED", POISON), 503,
     "LINK_NOT_CONFIGURED"),
    ("LinkError", LINK.LinkError("ACCOUNT_LIMIT", POISON, attempt="att-123456"), 400,
     "ACCOUNT_LIMIT"),
    ("LicenceRequired", LIC.LicenceRequired("none", POISON), 402, "LICENCE_REQUIRED"),
    ("NotEntitled", ENT.NotEntitled("NOT_ENTITLED", POISON), 409, "NOT_ENTITLED"),
    ("NotEntitled (licence revoked)",
     ENT.NotEntitled("LICENCE_REVOKED", POISON, state="withdrawn"), 402,
     "LICENCE_REQUIRED"),
    ("AutomationRefused", AUTO.AutomationRefused("NO_RULE", POISON), 409, "NO_RULE"),
    ("Halted", EM.Halted("HALTED_ALL", POISON, scope="all"), 503, "HALTED_ALL"),
    ("PreviewRefused", PRE.PreviewRefused("BAD_WINDOW", POISON), 400, "BAD_WINDOW"),
    ("CloseRefused", PC.CloseRefused("CLOSE_REFUSED", POISON, status=409), 409,
     "CLOSE_REFUSED"),
    ("CloseUnknown", PC.CloseUnknown(POISON), 503, "CLOSE_UNKNOWN"),
    ("ValueError", ValueError(POISON), 400, "BAD_REQUEST"),
]
for name, exc, want_status, want_code in CASES:
    st, body = via_dispatch(exc)
    blob = json.dumps(body)
    check(f"{name}: no URL, host, path, header or token in the answer",
          not leaked(blob), f"{leaked(blob)} in {blob[:300]}")
    code = (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) \
        else body.get("code") or body.get("error")
    check(f"{name}: still answers {want_status} with the code {want_code}",
          st == want_status and want_code in blob, f"{st} {blob[:200]}")

st, body = via_dispatch(LINK.LinkError("ACCOUNT_LIMIT", POISON, attempt="att-123456"))
check("the diagnostic id survives redaction", "att-123456" in json.dumps(body),
      json.dumps(body)[:300])

# ── 2. the two handlers that answer inside _dispatch ────────────────────────
print("\n[2] the waitlist and approval refusals answered inside the dispatcher")
real_join = WAIT.join


def join_boom(*a, **k):
    raise WAIT.WaitlistError("NOT_CONFIGURED", POISON)


WAIT.join = join_boom
try:
    st, body = API.handle("POST", "/api/v1/waitlist", {}, b'{"email": "a@b.test"}')
finally:
    WAIT.join = real_join
check("waitlist: refusal text is redacted", not leaked(json.dumps(body)),
      json.dumps(body)[:300])
check("waitlist: and keeps its code", "NOT_CONFIGURED" in json.dumps(body),
      json.dumps(body)[:200])

real_auth, real_approve = API._authenticate, APPR.approve


def approve_boom(uid):
    raise APPR.ApprovalRefused("PROPOSAL_EXPIRED", POISON)


API._authenticate = lambda headers, fresh=False: types.SimpleNamespace(
    user_id="u-approve", email_verified=True)
API._id.require_verified_email = lambda p: None
APPR.approve = approve_boom
try:
    st, body = API.handle("POST", "/api/v1/approvals/approve", {}, b"{}")
finally:
    API._authenticate, APPR.approve = real_auth, real_approve
check("approval: refusal text is redacted", not leaked(json.dumps(body)),
      json.dumps(body)[:300])
check("approval: and keeps its code", "PROPOSAL_EXPIRED" in json.dumps(body),
      json.dumps(body)[:200])

# ── 3. the emergency state ──────────────────────────────────────────────────
print("\n[3] the emergency state and the halt built from it carry no store message")
real_read = EM._read_record


def store_down():
    raise RuntimeError(POISON)


EM._read_record = store_down
halted = None
try:
    st_ = EM.state()
    try:
        EM.check(user_id="u1", mode="live")
    except EM.Halted as h:
        halted = h
finally:
    EM._read_record = real_read
check("storeError carries no message from the store",
      not leaked(st_.get("storeError")), str(st_.get("storeError")))
check("but still says what kind of failure it was",
      str(st_.get("storeError", "")).startswith("STORE_UNREACHABLE"),
      str(st_.get("storeError")))
check("the state still fails safe (live scope, store unreachable)",
      st_.get("storeReachable") is False and st_.get("storeScope") == EM.LIVE,
      str(st_))
check("a non-demo account is refused as HALTED_UNCERTAIN",
      halted is not None and halted.code == "HALTED_UNCERTAIN", str(halted))
check("and the halt built from it carries no store message",
      halted is not None and not leaked(halted.reason) and not leaked(str(halted)),
      f"{getattr(halted, 'reason', None)!r} / {halted}")

# ── 4. the broker-read envelope ─────────────────────────────────────────────
print("\n[4] the broker-read status envelope carries no connector message")
conn = {"ctid": 501, "mode": "demo", "accessToken": "tok-not-a-real-token-0001"}


def broker_boom():
    raise RuntimeError(POISON)


b, other = BR._open("u", ctid="501", connection_fn=lambda uid, ctid=None: conn,
                    broker_fn=broker_boom)
check("no broker is returned", b is None, str(other))
check("and the reason is redacted", not leaked(json.dumps(other)),
      json.dumps(other)[:300])

# ── 5. the helper itself ────────────────────────────────────────────────────
print("\n[4b] a journal error is redacted on the way in")
from apex.platform import journal as J                       # noqa: E402
je = J.for_error(
    "broker failed at https://broker.example.test/v2 "
    "connect 10.0.3.14:6379",
    correlation_id="c1", user_id="u1")
check("journal for_error redacts the URL",
      "broker.example.test" not in str(je.error)
      and "https://" not in str(je.error), str(je.error))
check("journal for_error redacts the IP",
      "10.0.3.14" not in str(je.error), str(je.error))

print("\n[5] the shared helper")
from apex.platform.safe_errors import message                # noqa: E402
out = message(POISON)
check("removes every shape at once", not leaked(out), out)
check("is bounded", len(message("x " * 1000)) <= 300)
for keep in ("POSITION_NOT_FOUND", "CH_CLIENT_AUTH_FAILURE",
             "the position 4567890 is already closed", "use and/or Settings/Trading"):
    check(f"leaves {keep!r} readable", message(keep) == keep, message(keep))

print("\n[5b] the shapes a first pass missed")
for label, text, gone in (
        ("an IP with a port", "connect to 10.0.3.14:6379 refused", "10.0.3.14"),
        ("a short internal host", "lookup db.internal failed", "db.internal"),
        ("a cluster host", "dial redis.svc.cluster.local timeout", "redis.svc"),
        ("an email", "user ops@example.com rejected", "ops@example"),
        ("user:pw@host", "postgres failed for admin:hunter2@db", "hunter2"),
        ("a relative state file", "cannot read data/users.json", "users.json"),
        ("a dotted relative path", "open ./data/state.json", "state.json"),
        ("host='x' leaves no quote", "host='db1.internal' down", "'")):
    got = message(text)
    check(f"{label}: removed", gone not in got, got)
check("prose 'no bearer token' is not mangled", message("no bearer token") == "no bearer token",
      message("no bearer token"))
check("a real bearer header still is", "abcdef0123456789" not in message("Bearer abcdef0123456789"))

print("\n[6] hostile input is bounded before the shape regexes run")
import time as _time                                          # noqa: E402
for label, hostile in (("sk- x 66000", "sk-" * 66000), ("FORX- x 40000", "FORX-" * 40000),
                       ("query_id= x 18000", "query_id=a&" * 18000)):
    t0 = _time.perf_counter()
    message(hostile)
    took = _time.perf_counter() - t0
    check(f"{label}: scrubbed in well under a second", took < 1.0, f"{took:.1f}s")
t0 = _time.perf_counter()
API.handle("GET", "/api/v1/ctrader/callback?error=" + "sk-" * 20000)
check("the public callback with a hostile error parameter answers quickly",
      _time.perf_counter() - t0 < 2.0, f"{_time.perf_counter() - t0:.1f}s")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All error-redaction path checks passed.")
