"""The journal says whose fault a failed start was — and never leaks a secret.

SEEN ON THE OWNER'S PHONE, 22 Oct 2026, right after a deploy: four "Broker
error — the engine refused to start this loop" entries, three minutes apart.
Nothing was wrong with the broker. The previous instance still held the loop's
lease, the supervisor retried every three minutes, and each refused retry was
journalled as a broker error. A QA pass then found the same wording again and
no cause behind it.

WHAT THESE TESTS WILL NOT ACCEPT

* A supervisor retry written to the journal at all.
* An internal exception, a timeout or a dropped socket labelled a BROKER error.
  Only a refusal the provider itself sent is one.
* Any token, secret or Bearer value reaching a journal entry — through the
  exception text, whether or not it is a known secret.
* A cause so long that a provider payload could ride along.
* The same persistent fault filling the journal once per retry.
* A Start the client pressed going unrecorded.

Run: python3 tests/test_revival_refusal_not_a_broker_error.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-revive-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import user_store                                  # noqa: E402
from apex.platform import automation as AU                  # noqa: E402
from apex.platform import journal as J                      # noqa: E402

broker_errs, engine_errs = [], []
_real_b, _real_e = AU._jstore.record_error, AU._jstore.record_engine_error
AU._jstore.record_error = lambda msg, **kw: broker_errs.append((msg, kw))
AU._jstore.record_engine_error = lambda msg, **kw: engine_errs.append((msg, kw))


def reset():
    broker_errs.clear()
    engine_errs.clear()


CONN = {"ctid": 501, "accessToken": "ACCESS-TOKEN-VALUE-0123456789",
        "refreshToken": "REFRESH-TOKEN-VALUE-9876543210"}
try:
    # ── 1. a revival's refusal is not a journal entry ───────────────────────
    print("\n[1] the supervisor's retry is not a journal entry")
    AU._note_engine_refused("u1", "c1", 501, revive=True)
    check("nothing is filed for a revival", not broker_errs and not engine_errs)

    print("\n[2] a Start the client pressed is filed — as an ENGINE error")
    reset()
    AU._note_engine_refused("u1", "c2", 501, revive=False)
    check("it is not a broker error", broker_errs == [], str(broker_errs))
    check("it is an engine error, with the user and account",
          len(engine_errs) == 1 and engine_errs[0][1]["user_id"] == "u1"
          and engine_errs[0][1]["account_id"] == "501", str(engine_errs))

    # ── 3. who is blamed ────────────────────────────────────────────────────
    print("\n[3] a refusal the PROVIDER sent is a broker error")
    for msg in ("cTrader error: ACCOUNT_NOT_AUTHORIZED not allowed",
                "cTrader order error: MARKET_CLOSED",
                "cTrader token error: invalid_grant — expired",
                "app auth failed (demo): bad client",
                "account auth failed (demo #501): denied"):
        reset()
        AU._record_starter_failure("u1", "c3", CONN, RuntimeError(msg), revive=False)
        check(f"{msg[:34]!r} -> broker error",
              len(broker_errs) == 1 and not engine_errs, f"{broker_errs} {engine_errs}")

    print("\n[3b] anything else is NOT the broker's")
    for exc in (KeyError("symbol"), ValueError("bad timeframe"),
                TimeoutError("cTrader: no response for ProtoOAReconcileRes"),
                ConnectionError("cTrader connection closed"),
                RuntimeError("the engine thread could not be created")):
        reset()
        AU._record_starter_failure("u1", "c4", CONN, exc, revive=False)
        check(f"{type(exc).__name__}: {str(exc)[:30]!r} -> engine error",
              len(engine_errs) == 1 and not broker_errs, f"{broker_errs} {engine_errs}")

    print("\n[3c] the entry names the real cause")
    reset()
    AU._record_starter_failure("u1", "c5", CONN, ValueError("bad timeframe"), revive=False)
    check("type and message are in the entry",
          "ValueError: bad timeframe" in engine_errs[0][0], engine_errs[0][0])
    check("and it says the ENGINE failed", engine_errs[0][0].startswith("the engine failed to start the loop"))

    # ── 4. no secret reaches the journal ────────────────────────────────────
    print("\n[4] credentials never reach the journal")
    leaks = [
        f"boom {CONN['accessToken']} boom",                         # a known secret
        f"refresh failed with {CONN['refreshToken']}",
        "Authorization: Bearer abcdef0123456789abcdef0123456789",   # unknown bearer
        "access_token=zzzzzzzzzzzzzzzzzzzzzzzzzzzz",                # keyed
        "client_secret: hunter2",                                   # short, keyed
        "payload eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
        "x" * 40,                                                   # long unbroken run
    ]
    forbidden = (CONN["accessToken"], CONN["refreshToken"], "abcdef0123456789abcdef0123456789",
                 "zzzzzzzzzzzzzzzzzzzzzzzzzzzz", "hunter2", "eyJhbGciOi", "x" * 24)
    for text in leaks:
        for exc in (RuntimeError(text), RuntimeError("cTrader error: " + text)):
            reset()
            AU._record_starter_failure("u1", "c6", CONN, exc, revive=False)
            blob = json.dumps(broker_errs + engine_errs)
            hit = [f for f in forbidden if f in blob]
            check(f"{text[:36]!r}: nothing secret-shaped is filed", not hit, f"{hit} in {blob}")
    reset()
    cause = AU._safe_cause(RuntimeError("w " * 500))
    check("the cause is bounded", len(cause) <= 200, str(len(cause)))

    print("\n[4b] the returned cause (shown in the API error) is redacted too")
    reset()
    got = AU._record_starter_failure("u1", "c7", CONN, RuntimeError(f"x {CONN['accessToken']}"), revive=False)
    check("no secret in the cause the API returns", CONN["accessToken"] not in got, got)

    # ── 5. a persistent fault is not journalled once per retry ──────────────
    print("\n[5] the supervisor's repeated failure is journalled once per hour per cause")
    reset()
    _claims = set()
    _real_claim = user_store.claim
    user_store.claim = lambda key, ttl_s=0, **kw: (False if key in _claims else (_claims.add(key) or True))
    try:
        for _ in range(4):
            AU._record_starter_failure("u1", "c8", CONN, ValueError("same fault"), revive=True)
        check("four identical revival failures -> one entry", len(engine_errs) == 1, str(len(engine_errs)))
        AU._record_starter_failure("u1", "c8", CONN, ValueError("a different fault"), revive=True)
        check("a different cause is its own entry", len(engine_errs) == 2, str(len(engine_errs)))
        reset()
        for _ in range(3):
            AU._record_starter_failure("u1", "c9", CONN, ValueError("same fault"), revive=False)
        check("but a Start the client pressed is always recorded", len(engine_errs) == 3, str(len(engine_errs)))
    finally:
        user_store.claim = _real_claim
finally:
    AU._jstore.record_error, AU._jstore.record_engine_error = _real_b, _real_e

# ── 6. wiring ───────────────────────────────────────────────────────────────
print("\n[6] start() really routes through these, and the status exists")
src = open(os.path.join(ROOT, "apex", "platform", "automation.py")).read()
body = src.split("def start(", 1)[1].split("\ndef ", 1)[0]
check("start wraps the starter and records the exception",
      "_record_starter_failure(user_id, corr, conn, e, revive=revive)" in body)
check("a starter exception becomes ENGINE_START_FAILED, not a 500", '"ENGINE_START_FAILED"' in body)
check("an engine refusal goes through the helper with revive",
      '_note_engine_refused(user_id, corr, conn.get("ctid"), revive=revive)' in body)
check("start no longer writes an error inline", "_jstore.record_error(" not in body)
check("engine_error is a journal status", J.ENGINE_ERROR in J.STATUSES and J.ENGINE_ERROR != J.BROKER_ERROR)
e = J.for_engine_error("x", correlation_id="c", user_id="u")
check("and an engine error entry carries it, not broker_error", e.status == J.ENGINE_ERROR)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All revival-journal checks passed.")
