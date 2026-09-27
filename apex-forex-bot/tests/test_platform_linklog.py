"""The broker-link log says enough to debug with, and leaks nothing.

WHY THIS FILE EXISTS

Logging was added to this flow because a one-minute authorization-code expiry
took a day to find: nothing was written down, so every diagnosis came from the
owner photographing his phone. The cure has an obvious way of being worse than
the disease — this flow handles an authorization code, an access token, a
refresh token, the application's client secret and a signed state, and a log
is exactly where all five end up by accident.

So this does not inspect the logging code and pronounce it careful. It runs
the REAL flow with sentinel credentials and greps everything the process
printed. If any sentinel appears, the check fails, whatever the code looks
like.

The second half is about usefulness, which is the whole point: a log that
leaks nothing and says nothing is a log that leaves the next failure being
diagnosed by screenshot again.

Run: python tests/test_platform_linklog.py
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-linklog-")
os.environ["DATA_DIR"] = _TMP
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["CTRADER_REDIRECT_URI"] = "https://api.test/api/v1/ctrader/callback"

from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("ALLOW_PLAINTEXT_DEV_STORAGE", None)

# The application's own credential. If this ever reaches a log line it is not
# one client's problem, it is every client's.
SENTINEL_SECRET = "SENTINEL-CLIENT-SECRET-zzz999"
os.environ["CTRADER_CLIENT_SECRET"] = SENTINEL_SECRET
os.environ["CTRADER_CLIENT_ID"] = "1000_sentinel_appid"

from apex.platform import ctrader_link as L  # noqa: E402
from apex.platform import linklog as LOG     # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


USER = "11111111-2222-4333-8444-555555555555"
OTHER = "99999999-8888-4777-8666-555555555555"

SENTINEL_CODE = "SENTINEL-AUTH-CODE-a1b2c3"
SENTINEL_ACCESS = "SENTINEL-ACCESS-TOKEN-d4e5f6"
SENTINEL_REFRESH = "SENTINEL-REFRESH-TOKEN-g7h8i9"

SENTINELS = {
    "the authorization code": SENTINEL_CODE,
    "the access token": SENTINEL_ACCESS,
    "the refresh token": SENTINEL_REFRESH,
    "the client secret": SENTINEL_SECRET,
}


def exchanger(code, redirect_uri):
    return {"accessToken": SENTINEL_ACCESS, "refreshToken": SENTINEL_REFRESH,
            "expiresIn": 2592000}


def lister(access):
    return [{"ctid": 111, "live": False, "label": "Demo 111"},
            {"ctid": 222, "live": True, "label": "Live 222"}]


@contextlib.contextmanager
def captured():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


try:
    print("\n1. the whole flow, watched")
    with captured() as buf:
        started = L.begin(USER)
        nonce = started["nonce"]
        state = started["authorizeUrl"].split("state=")[1].split("&")[0]
        L.handle_callback({"code": SENTINEL_CODE, "state": state},
                          exchanger=exchanger)
        L.complete(USER, nonce, lister=lister)
    out = buf.getvalue()
    check("the flow produced log lines at all", "[link]" in out,
          repr(out[:120]))
    check("and they cover every stage, so an attempt can be followed",
          all(s in out for s in ("begin", "callback.received", "callback.state",
                                 "callback.claim", "callback.pending",
                                 "exchange.attempt", "exchange.result",
                                 "complete.called", "complete.user_match",
                                 "accounts.result", "complete.connected")),
          out)

    print("\n2. no credential survived the round trip")
    for label, secret in SENTINELS.items():
        check(f"{label} is not in the log", secret not in out,
              [ln for ln in out.splitlines() if secret in ln][:1])

    print("\n3. nor the values that identify the attempt itself")
    # The nonce is a bearer-ish handle for the pending record and the state is
    # signed with the platform's own key. Neither belongs in a log, and a
    # PREFIX of either is still a head start on guessing the rest.
    check("the full nonce is not in the log", nonce not in out)
    check("nor any long prefix of it", nonce[:16] not in out)
    check("the full state is not in the log", state not in out)
    check("nor any long prefix of it", state[:16] not in out)
    check("nor the user id", USER not in out)

    print("\n4. but it says enough to be worth having")
    attempt = LOG.attempt_id(nonce)
    check("the attempt id appears, so one search finds the whole attempt",
          attempt in out, attempt)
    check("and it appears on every stage, not just the first",
          out.count(attempt) >= 8, str(out.count(attempt)))
    check("the redirect URI's host and path are visible, since a mismatch "
          "there is a real cause and neither is secret",
          "https://api.test/api/v1/ctrader/callback" in out)
    check("the outcome of the exchange is stated",
          "exchange.result" in out and "ok=true" in out.lower())
    check("so is how many accounts came back",
          "count=2" in out and "demo=1" in out and "live=1" in out)

    print("\n5. the attempt id is a reference, not the thing itself")
    check("it is short enough to read aloud", len(attempt) == 8, attempt)
    check("it is not a prefix of the nonce", not nonce.startswith(attempt))
    check("two different nonces get different ids",
          LOG.attempt_id("nonce-one") != LOG.attempt_id("nonce-two"))
    check("the same nonce gets the same id every time, or it cannot be "
          "searched for", LOG.attempt_id(nonce) == attempt)
    check("and it is keyed, so a guessed nonce cannot be confirmed by "
          "hashing it", LOG.attempt_id("x") != __import__("hashlib").sha256(
              b"x").hexdigest()[:8])
    check("a user reference does not contain the user id",
          USER not in LOG.user_ref(USER) and LOG.user_ref(USER) != USER)
    check("different users get different references",
          LOG.user_ref(USER) != LOG.user_ref(OTHER))

    print("\n6. a failure is logged as a failure, and still leaks nothing")
    with captured() as buf2:
        s2 = L.begin(USER)
        st2 = s2["authorizeUrl"].split("state=")[1].split("&")[0]

        def _boom(code, uri):
            # The provider's own message, which quotes nothing sensitive, but
            # a careless implementation could log the code alongside it.
            raise RuntimeError("cTrader token error: ACCESS_DENIED")
        try:
            L.handle_callback({"code": SENTINEL_CODE, "state": st2},
                              exchanger=_boom)
        except L.LinkError:
            pass
    out2 = buf2.getvalue()
    check("the failed exchange is recorded",
          "exchange.result" in out2 and "EXCHANGE_FAILED" in out2, out2)
    check("with the code that failed, which is what gets quoted in support",
          "ok=false" in out2.lower())
    check("and the authorization code still did not get logged",
          SENTINEL_CODE not in out2)

    print("\n7. a mismatched user is recorded without naming the other party")
    with captured() as buf3:
        s3 = L.begin(USER)
        st3 = s3["authorizeUrl"].split("state=")[1].split("&")[0]
        L.handle_callback({"code": SENTINEL_CODE, "state": st3},
                          exchanger=exchanger)
        try:
            L.complete(OTHER, s3["nonce"], lister=lister)
        except L.LinkError:
            pass
    out3 = buf3.getvalue()
    check("the mismatch is visible", "match=false" in out3.lower(), out3)
    check("the user who OWNS the attempt is not named in it",
          USER not in out3)
    check("nor is the caller's raw id", OTHER not in out3)

    print("\n8. the logger itself refuses the obvious mistakes")
    with captured() as buf4:
        LOG.event("probe", token=SENTINEL_ACCESS, accessToken=SENTINEL_ACCESS,
                  refreshToken=SENTINEL_REFRESH, client_secret=SENTINEL_SECRET,
                  authorization="Bearer " + SENTINEL_ACCESS)
    out4 = buf4.getvalue()
    check("a field NAMED like a credential is dropped whatever is in it",
          not any(s in out4 for s in SENTINELS.values()), out4)

    with captured() as buf5:
        LOG.event("probe", note="A" * 500 + SENTINEL_ACCESS)
    out5 = buf5.getvalue()
    check("an over-long value is truncated, so a secret in an innocent field "
          "cannot arrive whole", SENTINEL_ACCESS not in buf5.getvalue(),
          out5[:80])

    with captured() as buf6:
        LOG.event("probe", note="first line\nsecond=forged")
    check("a newline cannot forge a second log line",
          len(buf6.getvalue().strip().splitlines()) == 1, buf6.getvalue())

    with captured() as buf7:
        class Exploding:
            def __str__(self):
                raise RuntimeError("boom")
        LOG.event("probe", bad=Exploding())
    check("a value that cannot be rendered does not take the request down",
          True)

    print("\n9. the log calls cannot drift back into leaking")
    # The checks above prove the CURRENT calls are safe. This one is about the
    # next edit: an AST walk over every linklog call in the flow, refusing any
    # that hands over a variable holding one of the things that must never be
    # written down. A substring search would not do — it matches comments and
    # docstrings, which cost this project real time before.
    import ast
    FORBIDDEN = {"code", "access", "refresh", "tok", "state", "secret",
                 "nonce", "user_id", "access_enc", "already"}
    src = io.open(os.path.join(ROOT, "apex", "platform", "ctrader_link.py"),
                  encoding="utf-8").read()
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "event"
                and isinstance(fn.value, ast.Name) and fn.value.id == "_log"):
            continue
        for kw in node.keywords:
            v = kw.value
            if isinstance(v, ast.Name) and v.id in FORBIDDEN:
                offenders.append(f"{kw.arg}={v.id} (line {node.lineno})")
    check("no log call passes a raw credential-bearing variable",
          not offenders, "; ".join(offenders))
    # And the check must be able to find something, or it proves nothing.
    planted = ast.parse("_log.event('x', attempt=attempt, leaked=code)")
    found = []
    for node in ast.walk(planted):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if isinstance(kw.value, ast.Name) and kw.value.id in FORBIDDEN:
                    found.append(kw.arg)
    check("and the walk above does detect one when it is there",
          found == ["leaked"], str(found))
finally:
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
