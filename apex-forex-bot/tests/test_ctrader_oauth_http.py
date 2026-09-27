"""The cTrader OAuth token exchange, over real HTTP. Nothing mocked.

WHY THIS FILE EXISTS

`apex/brokers/ctrader.py` had no test coverage at all for `_token_request`,
`exchange_code` or `refresh_access_token` — the three functions that turn an
OAuth grant into the broker access token everything else depends on. They were
written against a documented quirk:

    cTrader's /apps/token reads QUERY-STRING params (not a form body) and
    returns JSON with an in-band errorCode even on HTTP 200.

Both halves of that are the kind of thing a mock cannot check. A mocked
`requests.get` proves our code called something; it does not prove the
credentials went into the query string rather than a body, and it does not prove
that a 200 carrying `errorCode` is treated as a failure. Get either wrong and
the visible symptom is a client who cannot connect their broker, with an HTTP
200 in the logs.

So this stands a local HTTP server in for cTrader, points `_OAUTH_TOKEN` at it
and calls the real functions through the real `requests`. It also pins the thing
that would be worst: the client secret travels in that query string, so it must
not reach an exception message or a log line.

Run: python3 tests/test_ctrader_oauth_http.py
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY",
                      "cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI=")  # SYNTHETIC

from apex.brokers import ctrader                                 # noqa: E402

_fails = []

# Synthetic throughout. SECRET is the string every leak check looks for.
CLIENT_ID = "1000_appid_SAMPLEONLY"
SECRET = "s3cr3t-SAMPLEONLY-must-never-appear-in-output"
CODE = "auth-code-SAMPLEONLY"
REFRESH = "refresh-token-SAMPLEONLY"


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── a stand-in for cTrader's /apps/token ────────────────────────────────────
# `reply` decides what the next request gets, so one server covers every case.
reply = {"status": 200, "body": {}}
seen = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        seen.append({
            "method": "GET",
            "path": parsed.path,
            "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
            "accept": self.headers.get("Accept", ""),
            "body": self.rfile.read(length).decode() if length else "",
        })
        out = json.dumps(reply["body"]).encode()
        self.send_response(reply["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        self.do_GET()


srv = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
LOCAL = f"http://127.0.0.1:{srv.server_port}/apps/token"

_real_token_url = ctrader._OAUTH_TOKEN
ctrader._OAUTH_TOKEN = LOCAL
ctrader.cfg.CTRADER_CLIENT_ID = CLIENT_ID
ctrader.cfg.CTRADER_CLIENT_SECRET = SECRET


def call(fn, *args, status=200, body=None):
    """Point the server at one reply, run fn, return (result, exception, request)."""
    seen.clear()
    reply["status"] = status
    reply["body"] = {} if body is None else body
    try:
        return fn(*args), None, (seen[0] if seen else None)
    except Exception as e:                                   # noqa: BLE001
        return None, e, (seen[0] if seen else None)


# ── 1. the real endpoint is still the real endpoint ─────────────────────────
print("\n[1] the production URL is cTrader's own, and this test redirected it")
check("the module constant points at openapi.ctrader.com",
      _real_token_url == "https://openapi.ctrader.com/apps/token", _real_token_url)
check("the authorize URL points at id.ctrader.com",
      ctrader._OAUTH_AUTH.startswith("https://id.ctrader.com/"), ctrader._OAUTH_AUTH)
check("both are https", _real_token_url.startswith("https://")
      and ctrader._OAUTH_AUTH.startswith("https://"))

# ── 2. exchange_code: credentials go in the QUERY STRING ────────────────────
print("\n[2] exchange_code sends the grant in the query string, as cTrader reads it")
GOOD = {"accessToken": "at-SAMPLEONLY", "refreshToken": "rt-SAMPLEONLY",
        "expiresIn": 2628000, "tokenType": "bearer"}
res, err, req = call(ctrader.exchange_code, CODE, "https://example.test/cb",
                     body=GOOD)
check("it returned the parsed token document", res == GOOD, f"{err or res}")
check("the request reached the endpoint", req is not None)
if req:
    q = req["query"]
    check("grant_type=authorization_code", q.get("grant_type") == "authorization_code",
          str(q.get("grant_type")))
    check("the code is in the query", q.get("code") == CODE)
    check("redirect_uri is in the query",
          q.get("redirect_uri") == "https://example.test/cb")
    check("client_id is in the query", q.get("client_id") == CLIENT_ID)
    check("client_secret is in the query", q.get("client_secret") == SECRET)
    # The quirk this function exists for: NOT a form body.
    check("nothing was sent as a request body", req["body"] == "",
          repr(req["body"])[:60])
    check("it asks for JSON", "application/json" in req["accept"], req["accept"])

# ── 3. refresh_access_token: the same path, different grant ────────────────
print("\n[3] refresh_access_token sends the refresh grant")
res, err, req = call(ctrader.refresh_access_token, REFRESH, body=GOOD)
check("it returned the parsed token document", res == GOOD, f"{err or res}")
if req:
    check("grant_type=refresh_token",
          req["query"].get("grant_type") == "refresh_token")
    check("the refresh token is in the query",
          req["query"].get("refresh_token") == REFRESH)

# ── 4. an in-band errorCode on HTTP 200 is a FAILURE ───────────────────────
# The reason _token_request is not a bare requests.get. A 200 with errorCode
# would otherwise be stored as a token document and every later call would fail
# with something unrelated.
print("\n[4] a 200 carrying errorCode raises rather than being stored")
for body in ({"errorCode": "INVALID_REQUEST", "description": "bad code"},
             {"errorCode": "ALREADY_USED"},
             {"errorCode": "CH_CLIENT_AUTH_FAILURE", "description": ""}):
    res, err, _ = call(ctrader.exchange_code, CODE, "https://example.test/cb",
                       status=200, body=body)
    check(f"errorCode={body['errorCode']} raises", err is not None, f"returned {res}")
    if err:
        check(f"and the message names the code: {body['errorCode']}",
              body["errorCode"] in str(err), str(err)[:80])

# A document with no errorCode and no token is NOT an error here — it is
# returned as-is. Asserted so the behaviour is deliberate rather than assumed.
res, err, _ = call(ctrader.exchange_code, CODE, "https://example.test/cb",
                   body={"unexpected": "shape"})
check("a 200 with no errorCode is returned, not raised",
      err is None and res == {"unexpected": "shape"}, f"{err}")

# ── 5. HTTP error statuses raise ────────────────────────────────────────────
print("\n[5] an HTTP error status raises, it is not parsed as a token")
for status in (400, 401, 403, 429, 500, 503):
    res, err, _ = call(ctrader.exchange_code, CODE, "https://example.test/cb",
                       status=status, body={"accessToken": "should-be-ignored"})
    check(f"HTTP {status} raises", err is not None, f"returned {res}")

# ── 6. THE SECRET MUST NOT LEAK ────────────────────────────────────────────
# It travels in the query string, and requests puts the URL in the message of
# the HTTPError that raise_for_status produces. An exception that reaches a log
# line would put the application's client_secret in it — the credential for
# every client's broker connection, not one client's.
print("\n[6] the client secret does not reach an exception message")
for status in (400, 401, 500):
    res, err, _ = call(ctrader.exchange_code, CODE, "https://example.test/cb",
                       status=status)
    text = f"{err}" + "".join(str(a) for a in getattr(err, "args", ()))
    check(f"HTTP {status}: the secret is absent from the message",
          SECRET not in text, f"LEAKED in: {text[:160]}")
    check(f"HTTP {status}: the auth code is absent too",
          CODE not in text, f"LEAKED in: {text[:160]}")
res, err, _ = call(ctrader.refresh_access_token, REFRESH, status=401)
text = f"{err}" + "".join(str(a) for a in getattr(err, "args", ()))
check("a failed refresh does not put the refresh token in the message",
      REFRESH not in text, f"LEAKED in: {text[:160]}")

# THE TRACEBACK, not just the message. A rewritten message is worth nothing if
# the original is chained onto it — "During handling of the above exception" puts
# the URL back, and the traceback is what a log captures.
import traceback                                                 # noqa: E402


def full_traceback(fn, *args, status=200, body=None):
    seen.clear()
    reply["status"] = status
    reply["body"] = {} if body is None else body
    try:
        fn(*args)
        return ""
    except Exception:                                            # noqa: BLE001
        return traceback.format_exc()


for label, status in (("HTTP 400", 400), ("HTTP 401", 401), ("HTTP 503", 503)):
    tb = full_traceback(ctrader.exchange_code, CODE, "https://example.test/cb",
                        status=status)
    check(f"{label}: the secret is absent from the whole traceback",
          SECRET not in tb, f"LEAKED: {tb[-200:]}")
    check(f"{label}: no chained requests exception re-adds the URL",
          "During handling of the above exception" not in tb
          and "another exception occurred" not in tb,
          tb[-200:])
tb = full_traceback(ctrader.refresh_access_token, REFRESH, status=401)
check("a failed refresh leaks neither secret nor refresh token in the traceback",
      SECRET not in tb and REFRESH not in tb, f"LEAKED: {tb[-200:]}")

# The TRANSPORT failure paths, which no live server can produce: a refused
# connection and a timeout. requests puts the URL in those messages too, and the
# original exception chains onto the traceback unless it is suppressed — so this
# is the same leak by a different route.
import socket as _socket                                         # noqa: E402

with _socket.socket() as _s:
    _s.bind(("127.0.0.1", 0))
    _DEAD = _s.getsockname()[1]

_saved = ctrader._OAUTH_TOKEN
ctrader._OAUTH_TOKEN = f"http://127.0.0.1:{_DEAD}/apps/token"
try:
    ctrader.exchange_code(CODE, "https://example.test/cb")
    _tb, _msg = "", ""
    check("a refused connection raises", False, "it returned")
except Exception as _e:                                          # noqa: BLE001
    _tb = traceback.format_exc()
    _msg = str(_e)
    check("a refused connection raises", True)
ctrader._OAUTH_TOKEN = _saved

check("the refusal message says the endpoint was unreachable",
      "failed to reach the endpoint" in _msg, _msg[:100])
check("a refused connection leaks no secret in the message", SECRET not in _msg,
      _msg[:160])
check("and none in the traceback either", SECRET not in _tb, _tb[-200:])
check("and no chained requests exception re-adds the URL",
      "During handling of the above exception" not in _tb
      and "another exception occurred" not in _tb, _tb[-220:])
# The URL itself, not just the credential: it is the carrier.
check("the traceback does not contain the token URL at all",
      f"127.0.0.1:{_DEAD}" not in _tb, _tb[-200:])

# A non-JSON body and a JSON array, which the hand-rolled parsing now handles.
res, err, _ = call(ctrader.exchange_code, CODE, "https://example.test/cb",
                   body=["not", "an", "object"])
check("a JSON array is refused rather than treated as a token document",
      err is not None and "not an object" in str(err), f"{err or res}")

# And the redactor catches it if one ever does reach a print.
from apex import redact                                          # noqa: E402
check("redact masks a client_secret query parameter",
      SECRET not in redact.scrub(f"GET {LOCAL}?client_secret={SECRET}"),
      redact.scrub(f"GET {LOCAL}?client_secret={SECRET}")[:120])

# ── 7. every OAuth call has a timeout ──────────────────────────────────────
# A request with no timeout can hang a per-user thread for ever, and the thread
# that hangs here is the one that reconnects a client's broker session.
print("\n[7] the OAuth calls cannot hang for ever")
import ast                                                        # noqa: E402
with open(os.path.join(ROOT, "apex", "brokers", "ctrader.py"),
          encoding="utf-8") as fh:
    SRC = fh.read()
tree = ast.parse(SRC)
calls = [n for n in ast.walk(tree)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and isinstance(n.func.value, ast.Name) and n.func.value.id == "requests"]
check("there is at least one requests call to check", bool(calls))
for c in calls:
    kw = {k.arg for k in c.keywords}
    check(f"requests.{c.func.attr} on line {c.lineno} passes a timeout",
          "timeout" in kw, str(sorted(kw)))

# ── 8. authorize_url ───────────────────────────────────────────────────────
print("\n[8] the authorize URL carries the state and does not carry the secret")
url = ctrader.authorize_url("https://example.test/cb", "signed-state-123",
                            scope="accounts")
check("it is built on the real authorize endpoint", url.startswith(ctrader._OAUTH_AUTH))
q = parse_qs(urlparse(url).query)
check("client_id is present", q.get("client_id") == [CLIENT_ID])
check("the state is carried through", q.get("state") == ["signed-state-123"])
check("the requested scope is honoured", q.get("scope") == ["accounts"])
check("the redirect_uri is carried through",
      q.get("redirect_uri") == ["https://example.test/cb"])
# The authorize link is handed to the CLIENT. The secret must never be in it.
check("the client secret is NOT in the authorize URL", SECRET not in url)

srv.shutdown()
ctrader._OAUTH_TOKEN = _real_token_url

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("cTrader OAuth over real HTTP: query-string grant, in-band errorCode "
      "handled, no credential in any message.")

# ── 9. a reloaded callback page is not an attack ───────────────────────────
# The first real connection died here. The visitor landed on the callback,
# saw raw JSON, refreshed — the only thing the page invited — and the identical
# code and state came back as STATE_REPLAYED with no way forward.
#
# Replay protection still has to hold for the case that matters: a DIFFERENT
# code presented against the same state, which would swap which broker account
# gets linked. So the two are separated here rather than treated alike.
print("\n[9] the same code replayed is idempotent; a different one is refused")
import tempfile as _tf                                            # noqa: E402
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["DATA_DIR"] = _tf.mkdtemp(prefix="apex-replay-")

from apex.platform import ctrader_link as _link                   # noqa: E402
from apex.platform import store as _pstore                        # noqa: E402

_UID = "27d43c19-0000-0000-0000-000000000000"


def _stub_exchange(code, redirect_uri):
    """Stands in for cTrader. The callback exchanges the code on the spot now,
    because the real code expires one minute after it is issued."""
    return {"accessToken": f"ACCESS-FOR-{code}", "refreshToken": "R",
            "expiresIn": 2592000}


def _fresh_attempt():
    """A pending attempt that has already come back from cTrader."""
    began = _link.begin(_UID, redirect_uri="https://example.test/cb",
                        authorize_url_fn=lambda uri, state: f"https://x/?s={state}")
    state = began["authorizeUrl"].split("s=", 1)[1]
    return state


_state = _fresh_attempt()
_first = _link.handle_callback({"code": "THE-CODE", "state": _state},
                               exchanger=_stub_exchange)
check("the first callback spends the code", bool(_first.get("nonce")), str(_first))

_second = None
_raised = None
try:
    _second = _link.handle_callback({"code": "THE-CODE", "state": _state},
                                    exchanger=_stub_exchange)
except Exception as e:                                            # noqa: BLE001
    _raised = e
check("the SAME code replayed returns the same nonce instead of failing",
      _raised is None and _second and _second.get("nonce") == _first["nonce"],
      f"raised {_raised}" if _raised else str(_second))

_state2 = _fresh_attempt()
_link.handle_callback({"code": "FIRST-CODE", "state": _state2},
                      exchanger=_stub_exchange)
try:
    _link.handle_callback({"code": "ATTACKER-CODE", "state": _state2},
                          exchanger=_stub_exchange)
    check("a DIFFERENT code against the same state is refused", False,
          "it was accepted — this is the swap the guard exists to stop")
except Exception as e:                                            # noqa: BLE001
    check("a DIFFERENT code against the same state is refused",
          getattr(e, "code", "") == "STATE_REPLAYED", f"{type(e).__name__}: {e}")

# And the attempt still belongs to the FIRST code, not the attacker's. The
# spent code itself is not kept any more, so what is checked is the pair that
# replaced it: the digest that recognises a reload, and the token the first
# code actually bought.
_rec = _pstore._read(_link._k_pending(_link.parse_state(_state2)[0]))
from apex import user_store as _us                                # noqa: E402
check("the attempt still recognises the first code, not the attacker's",
      _rec.get("codeDigest") == _link._code_digest("FIRST-CODE")
      and _rec.get("codeDigest") != _link._code_digest("ATTACKER-CODE"))
check("and the parked token is the one the first code bought",
      _us.decrypt_value(_rec.get("accessToken") or "") == "ACCESS-FOR-FIRST-CODE",
      repr(_us.decrypt_value(_rec.get("accessToken") or ""))[:40])
check("with no authorization code left in the record at all",
      not _rec.get("code") and "FIRST-CODE" not in json.dumps(_rec),
      str(list(_rec.keys())))


# ── 10. a credential pasted with whitespace ────────────────────────────────
# The failure this pair of checks exists to stop: /readyz reported the
# credentials configured, because it asked about the STRIPPED value, while the
# connector sent the RAW one. cTrader answered ACCESS_DENIED to the token
# exchange and nothing tied the two facts together. Cost a real session.
print("\n[10] whitespace around a credential cannot pass silently")
import importlib                                                  # noqa: E402

_saved = {k: os.environ.get(k) for k in
          ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_REDIRECT_URI")}
os.environ["CTRADER_CLIENT_ID"] = "  1000_appid_SAMPLEONLY\n"
os.environ["CTRADER_CLIENT_SECRET"] = "s3cr3t-SAMPLEONLY  "
os.environ["CTRADER_REDIRECT_URI"] = " https://example.test/cb\t"

from apex import config as _cfg                                   # noqa: E402
importlib.reload(_cfg)
check("the client id is stripped when read",
      _cfg.CTRADER_CLIENT_ID == "1000_appid_SAMPLEONLY",
      repr(_cfg.CTRADER_CLIENT_ID))
check("the client secret is stripped when read",
      _cfg.CTRADER_CLIENT_SECRET == "s3cr3t-SAMPLEONLY",
      repr(_cfg.CTRADER_CLIENT_SECRET))
check("the redirect URI is stripped when read",
      _cfg.CTRADER_REDIRECT_URI == "https://example.test/cb",
      repr(_cfg.CTRADER_REDIRECT_URI))

from apex.platform import health as _health                       # noqa: E402
importlib.reload(_health)
_c = _health._ctrader()
check("and readiness reports the padding rather than a bare ok",
      _c.get("status") == "degraded", str(_c))
check("naming which variables are untidy",
      set(_c.get("padded") or []) == set(_saved), str(_c.get("padded")))
check("without putting any credential VALUE in the payload",
      "s3cr3t-SAMPLEONLY" not in json.dumps(_c), json.dumps(_c)[:120])

for k, v in _saved.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
importlib.reload(_cfg)
importlib.reload(_health)
