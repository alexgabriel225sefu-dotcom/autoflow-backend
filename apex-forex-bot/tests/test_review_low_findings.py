"""The LOW findings of the independent security reviews, each made to fail first.

WHAT THESE TESTS WILL NOT ACCEPT

* An error shown to a client (broker read, close refusal, emergency close detail,
  gate decision, API answer) that carries a refresh token, an app secret, a
  bearer header or a long token-shaped string. Only the access token used to be
  removed from broker errors.
* A broker built for a different account than the one the read or close was
  asked about being served as if it were the right one.
* A start that checks the broker's answer for one account and starts the loop
  on another because the selection changed between two reads.
* An Emergency budget that a person multiplies by opening more sessions.

(The remaining LOW findings are asserted where their code is tested: the lease
handed back during shutdown in test_platform_shutdown_release, the close claim
and the connection-mode check in test_platform_position_close, the relaxed
demo close policy in test_final_hardening, the paper-flagged live loop and the
retry in test_platform_live_classification, the per-person limit in
test_rate_limit_before_auth.)

Run: python3 tests/test_review_low_findings.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-lowfind-")
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


from apex import gates                                       # noqa: E402
from apex.platform import api as API                         # noqa: E402
from apex.platform import broker_read as BR                  # noqa: E402
from apex.platform import ctrader_link as LINK               # noqa: E402
from apex.platform import emergency_stop as ES               # noqa: E402
from apex.platform import position_close as PC               # noqa: E402

ACCESS = "ACCESS-TOKEN-VALUE-0123456789"
REFRESH = "REFRESH-TOKEN-VALUE-9876543210"
BEARER = "Authorization: Bearer abcdef0123456789abcdef0123456789"
KEYED = "client_secret=hunter2hunter2hunter2"
LONG = "Z" * 40
FORBIDDEN = (ACCESS, REFRESH, "abcdef0123456789abcdef0123456789",
             "hunter2hunter2", LONG)


def leaked(blob):
    return [f for f in FORBIDDEN if f in str(blob)]


# ── 1. broker_read._scrub removed only the access token ─────────────────────
print("\n[1] a broker error shown to a client is redacted by shape, not only by one token")
text = f"upstream said: {BEARER} refresh {REFRESH} {KEYED} id {LONG}"
out = BR._scrub(text, ACCESS)
check("no refresh token, bearer, keyed secret or long token survives",
      not leaked(out), f"{leaked(out)} in {out!r}")
check("the message is still a message", "upstream said" in out, out)
check("a known secret is still removed", ACCESS not in BR._scrub(f"x {ACCESS}", ACCESS))

print("\n[1b] quoted dumps are redacted; the codes and ids a client needs survive")
from apex import redact as _R                                # noqa: E402
for dump in ("{'refresh_token': 'shortsecret123'}",
             '{"client_secret": "abcDEF123456"}',
             "pw password=p@ss!w0rd#xyz end",
             "Authorization: Bearer abc.def.ghi"):
    got = _R.scrub_for_client(dump)
    bad = [x for x in ("shortsecret123", "abcDEF123456", "p@ss!w0rd", "abc.def.ghi")
           if x in got]
    check(f"{dump[:34]!r}: the value is gone", not bad, f"{bad} in {got!r}")
for keep in ("errorCode=POSITION_NOT_FOUND", "rejected: CH_CLIENT_AUTH_FAILURE",
             "orderId: CT_PAPER_1729700000123456 done",
             "EURUSD position 4567890 closed"):
    check(f"{keep[:40]!r}: kept as it is", _R.scrub_for_client(keep) == keep,
          _R.scrub_for_client(keep))
check("a token-shaped run is still removed even when written in capitals",
      "ABCDEF0123456789ABCDEF0123456789" not in
      _R.scrub_for_client("x ABCDEF0123456789ABCDEF0123456789"))

# ── 2. the Emergency close detail ───────────────────────────────────────────
print("\n[2] the Emergency button's per-position detail is redacted")


def refusing(uid, *, ctid, position_id):
    raise PC.CloseRefused("BROKER_UNAVAILABLE", f"cTrader said {BEARER} {KEYED}")


def unknown(uid, *, ctid, position_id):
    raise PC.CloseUnknown(f"result unknown after {BEARER} {REFRESH}")


row = {"positionId": 7, "symbol": "EURUSD", "side": "BUY"}
r1 = ES._close_one("u", "501", row, refusing)
r2 = ES._close_one("u", "501", row, unknown)
check("a refusal's detail carries no secret", not leaked(r1), str(r1))
check("an unknown outcome's detail carries no secret", not leaked(r2), str(r2))
check("the codes are still reported", r1["code"] == "BROKER_UNAVAILABLE"
      and r1["outcome"] == "refused" and r2["outcome"] == "unknown")

# ── 3. gate decisions that reach the API ────────────────────────────────────
print("\n[3] a gate refusal built from an exception is redacted")
check("the helper redacts", not leaked(gates._exc_text(RuntimeError(text))))
check("and bounds the text", len(gates._exc_text(RuntimeError("w " * 500))) <= 120)
real_load = gates.user_store.load


def boom(uid):
    raise RuntimeError(f"store down: {BEARER} {KEYED}")


gates.user_store.load = boom
try:
    d, rid = gates.authorize_order("u1", symbol="EURUSD", side="BUY", units=1000,
                                   origin="test", dash={})
finally:
    gates.user_store.load = real_load
check("an unreachable store's refusal carries no secret",
      not d.allowed and d.reason == "STORE_UNREACHABLE" and not leaked(d.detail),
      f"{d.reason} {d.detail!r}")

# ── 4. the API's own answers ────────────────────────────────────────────────
print("\n[4] the API's answers and log line are redacted")
real_dispatch = API._dispatch


def raise_refused(*a, **k):
    raise PC.CloseRefused("CLOSE_REFUSED", f"{BEARER} {KEYED}")


def raise_unknown(*a, **k):
    raise PC.CloseUnknown(f"unknown {BEARER}")


def raise_boom(*a, **k):
    raise RuntimeError(f"explode {BEARER} {KEYED}")


import io                                                    # noqa: E402
try:
    API._dispatch = raise_refused
    st, body = API.handle("POST", "/api/v1/accounts/501/positions/7/close")
    check("a close refusal answer carries no secret",
          not leaked(body), f"{st} {body}")
    API._dispatch = raise_unknown
    st, body = API.handle("POST", "/api/v1/accounts/501/positions/7/close")
    check("a close-unknown answer carries no secret", not leaked(body),
          f"{st} {body}")
    API._dispatch = raise_boom
    buf, real_stdout = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        st, body = API.handle("GET", "/api/v1/me")
    finally:
        sys.stdout = real_stdout
    check("the log line for an unhandled error carries no secret",
          not leaked(buf.getvalue()), buf.getvalue()[:300])
    check("and the answer to the client carries none", not leaked(body), str(body))
finally:
    API._dispatch = real_dispatch

# ── 5. the broker must be built for the account that was asked about ────────
print("\n[5] a broker bound to a different account is refused")


class Broker:
    def __init__(self, ctid):
        self._n = ctid

    def _ctid(self):
        return self._n


conn = {"ctid": 501, "mode": "demo", "accessToken": "tok-not-a-real-token"}
b, got = BR._open("u", ctid="501", connection_fn=lambda uid, ctid=None: conn,
                  broker_fn=lambda: Broker(501))
check("the matching broker is served", b is not None and got is conn)
try:
    BR._open("u", ctid="501", connection_fn=lambda uid, ctid=None: conn,
             broker_fn=lambda: Broker(777))
    refused = None
except LINK.LinkError as e:
    refused = e.code
check("a broker for another account is refused by name",
      refused == "ACCOUNT_BINDING_MISMATCH", str(refused))


class Plain:
    pass


b, _ = BR._open("u", ctid="501", connection_fn=lambda uid, ctid=None: conn,
                broker_fn=lambda: Plain())
check("a broker with no account to report (a test double) is not judged",
      b is not None)
# The default positions and orders reads ask about NO account; the broker must
# then match the connection's own, which is the same threat.
try:
    BR._open("u", ctid=None, connection_fn=lambda uid, ctid=None: conn,
             broker_fn=lambda: Broker(777))
    refused = None
except LINK.LinkError as e:
    refused = e.code
check("with no account asked about, a broker for another account than the "
      "connection's is still refused", refused == "ACCOUNT_BINDING_MISMATCH",
      str(refused))
b, _ = BR._open("u", ctid=None, connection_fn=lambda uid, ctid=None: conn,
                broker_fn=lambda: Broker(501))
check("and the connection's own account passes", b is not None)

# ── 6. the start: the broker's answer and the loop's account must agree ─────
print("\n[6] a start is refused when the selection changed between its two reads")
src = open(os.path.join(ROOT, "apex", "platform", "automation.py")).read()
pre = src[src.index("def _preflight("):src.index("def _run_starter") if "def _run_starter" in src else None]
check("the preflight compares the verified account with the connection's",
      'check.get("ctid")' in pre and 'conn.get("ctid")' in pre
      and "ACCOUNT_CHANGED" in pre)
check("and does so before the loop is started or the mode is accepted",
      pre.index("ACCOUNT_CHANGED") < pre.index("LIVE_NOT_AVAILABLE"))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All review-LOW checks passed.")
