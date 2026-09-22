"""The platform API: authenticated, owned, licensed, honest.

The fourth of those is the one worth stating. Endpoints whose data needs a
broker connection answer 501 UNSUPPORTED rather than 200 with an empty list,
because an empty list is a CLAIM — "you have no open positions" — and until
the broker is wired the platform does not know whether that is true. A
dashboard that renders a confident "No positions" over an unconnected backend
is the fabricated screen the brief forbids.

Run: python tests/test_platform_api.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-api-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

import requests  # noqa: E402

from apex.platform import api as A  # noqa: E402
from apex.platform import identity as I  # noqa: E402
from apex.platform import licence as L  # noqa: E402
from apex.platform import ruledoc as R  # noqa: E402

failures = []
calls = {"n": 0}


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
_USERS = {
    "alice": {"id": ALICE, "email": "alice@example.com",
              "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "bob": {"id": BOB, "email": "bob@example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z"},
    # The SAME id as alice, with no confirmed_at: the email gate has to be
    # reached by the rule's actual owner, or ownership answers 404 first and
    # the check under test never runs.
    "unverified": {"id": ALICE, "email": "alice@example.com"},
}
_MODE = {"status": 200, "user": "alice"}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


def _fake_get(url, **kw):
    calls["n"] += 1
    if _MODE["status"] == "boom":
        raise OSError("unreachable")
    return _Resp(_MODE["status"], _USERS.get(_MODE["user"]))


_real_get = requests.get
requests.get = _fake_get


def as_user(who):
    _MODE["user"] = who
    _MODE["status"] = 200
    I.forget_all()
    return {"Authorization": f"Bearer token-{who}"}


def call(method, path, who="alice", body=None, headers=None):
    h = headers if headers is not None else as_user(who)
    return A.handle(method, path, h,
                    json.dumps(body) if body is not None else None)


try:
    print("\n1. nothing is reachable without a session")
    check("an unrelated path falls through so other routes keep working",
          A.handle("GET", "/health") is None)
    for p in ("me", "conditions", "rules", "rules/x", "accounts",
              "positions", "journal"):
        st, _ = A.handle("GET", f"/api/v1/{p}", {}, None)
        check(f"GET {p} without a token is 401", st == 401, str(st))
    st, b = A.handle("POST", "/api/v1/rules/x/activate",
                     {"Authorization": "not-a-bearer"}, None)
    check("a malformed Authorization header is 401", st == 401, str(st))

    print("\n2. 'we cannot check' is 503, never 401")
    hdr = as_user("alice")
    _MODE["status"] = "boom"
    I.forget_all()
    st, b = A.handle("GET", "/api/v1/me", hdr, None)
    check("an unreachable Supabase is 503", st == 503, str(st))
    check("and carries its own code",
          b["error"]["code"] == "AUTH_UNAVAILABLE", b["error"]["code"])

    print("\n3. identity and licence are reported, never invented")
    st, b = call("GET", "/api/v1/me")
    check("me returns the Supabase user id as the platform identity",
          b["user"]["userId"] == ALICE, str(b["user"]))
    check("a client with no record is reported as unlicensed, not active",
          b["licence"]["state"] == L.NONE, b["licence"]["state"])
    check("no token is echoed anywhere in the response",
          "token" not in json.dumps(b).lower())

    print("\n4. the builder can only offer conditions the evaluator implements")
    st, b = call("GET", "/api/v1/conditions")
    check("the library is served", st == 200 and len(b["conditions"]) == 12,
          str(len(b.get("conditions", {}))))
    check("every entry carries its parameters and defaults",
          all("params" in v for v in b["conditions"].values()))

    print("\n5. a rule belongs to the session, not to the request body")
    st, b = call("POST", "/api/v1/rules", body={
        "name": "alice rule", "symbols": ["EUR_USD"], "timeframe": "1h",
        "userId": BOB,                       # forged
        "sides": "BUY", "accountId": "ct-demo-1",
        "entry": {"combine": "AND", "conditions": [
            {"id": "rsi", "params": {"op": "below", "value": 30}}]},
        "exit": {"combine": "OR", "conditions": [
            {"id": "rsi", "params": {"op": "above", "value": 70}}]},
    })
    check("a draft is created", st == 200 and b["rule"]["state"] == R.DRAFT,
          str(st))
    rid = b["rule"]["ruleDocId"]
    check("the forged owner is ignored", b["rule"]["userId"] == ALICE,
          b["rule"]["userId"])
    st, b = call("GET", f"/api/v1/rules/{rid}", who="bob")
    check("another client reading it gets 404, not the document", st == 404,
          str(st))
    st, b = call("PUT", f"/api/v1/rules/{rid}", who="bob", body={"name": "x"})
    check("another client cannot overwrite it", st == 404, str(st))
    st, b = call("POST", f"/api/v1/rules/{rid}/activate", who="bob")
    check("another client cannot activate it", st == 404, str(st))
    st, b = call("GET", "/api/v1/rules", who="bob")
    check("and it is absent from their list", b["rules"] == [], str(b))
    st, b = call("GET", "/api/v1/rules")
    check("the owner sees it", [r["ruleDocId"] for r in b["rules"]] == [rid])
    check("the list is a summary, not every parameter",
          "entry" not in b["rules"][0])

    print("\n6. activation is the gate, and it is not a formality")
    st, b = call("POST", f"/api/v1/rules/{rid}/validate")
    check("validate reports the rule as complete", b["valid"] is True,
          str(b.get("problems")))
    st, b = call("POST", f"/api/v1/rules/{rid}/activate")
    check("without a licence, activation is 402", st == 402, str(st))
    check("and names the licence state",
          b["error"]["licenceState"] == L.NONE, str(b["error"]))
    L.grant(ALICE, plan="pro")
    _MODE["user"] = "unverified"          # same id, unconfirmed address
    I.forget_all()
    st, b = A.handle("POST", f"/api/v1/rules/{rid}/activate",
                     {"Authorization": "Bearer t"}, None)
    check("an unconfirmed email still cannot activate", st == 401, str(st))
    # Reuse ONE set of headers without clearing the cache, so the counter
    # actually measures caching rather than the test resetting it.
    hdr = as_user("alice")
    A.handle("GET", "/api/v1/me", hdr, None)
    warm = calls["n"]
    A.handle("GET", "/api/v1/me", hdr, None)
    check("an ordinary read is served from the cache",
          calls["n"] == warm, f"{warm}->{calls['n']}")
    before = calls["n"]
    st, b = A.handle("POST", f"/api/v1/rules/{rid}/activate", hdr, None)
    check("with a licence and a confirmed address it activates",
          st == 200 and b["rule"]["state"] == R.ACTIVE, str(st))
    check("but activation re-checks the session rather than trusting a "
          "cached answer that a revocation may already have overtaken",
          calls["n"] == before + 1, f"{before}->{calls['n']}")
    st, b = call("PUT", f"/api/v1/rules/{rid}", body={"name": "edited"})
    check("an active rule cannot be edited in place", st in (400, 422),
          str(st))
    st, b = call("POST", f"/api/v1/rules/{rid}/version")
    check("editing it makes a draft at the next version",
          b["rule"]["version"] == 2 and b["rule"]["state"] == R.DRAFT)
    st, b = call("GET", f"/api/v1/rules/{rid}/versions/1")
    check("version 1 is still readable exactly as activated",
          b["rule"]["version"] == 1 and b["rule"]["state"] == R.ACTIVE)

    # An expired licence is its own sentence with its own next step: "renew"
    # rather than "buy". Folding it into NONE would send a paying client who
    # lapsed to a sign-up page.
    L.grant(ALICE, plan="pro", expires_at=1.0)      # long past
    st, b = call("POST", f"/api/v1/rules/{rid}/activate")
    check("an expired licence does not activate anything", st == 402, str(st))
    check("and is reported as expired, not as never having existed",
          b["error"]["licenceState"] == L.EXPIRED, str(b["error"]))
    L.grant(ALICE, plan="pro")

    print("\n7. an invalid rule is refused with its problems, not a 500")
    st, b = call("POST", "/api/v1/rules", body={"name": "no symbols"})
    rid2 = b["rule"]["ruleDocId"]
    st, b = call("POST", f"/api/v1/rules/{rid2}/validate")
    check("validate lists every problem at once",
          b["valid"] is False and len(b["problems"]) > 1,
          str(b.get("problems"))[:60])
    st, b = call("POST", f"/api/v1/rules/{rid2}/activate")
    check("activating it is 422", st == 422, str(st))
    check("and the response carries the problems the form must show",
          isinstance(b["error"].get("problems"), list))
    check("no BUY or SELL is anywhere in that refusal",
          "BUY" not in json.dumps(b) and "SELL" not in json.dumps(b))

    print("\n8. what is not built yet says so")
    for cap in ("journal", "notifications"):
        st, b = call("GET", f"/api/v1/{cap}")
        check(f"{cap} answers 501 UNSUPPORTED, not an empty list",
              st == 501 and b["error"]["code"] == "UNSUPPORTED", str(st))
        check(f"{cap} returns no fabricated data",
              "ok" in b and b["ok"] is False)
    # positions and orders left this list once the read-only broker views
    # were built. They answer 200 with connected:false for a client who has
    # linked nothing — and crucially WITHOUT a positions key, so nothing is
    # claimed about an account the platform cannot see.
    for cap in ("positions", "orders"):
        st, b = call("GET", f"/api/v1/{cap}")
        check(f"{cap} reports the link state instead of 501",
              st == 200 and b["connected"] is False, f"{st} {b}")
        check(f"{cap} claims no data for an unlinked client",
              cap not in b, str(b))
        check(f"{cap} says why", b.get("status") == "not_connected", str(b))

    # accounts left this list once the cTrader link was built. Its empty list
    # is now a FACT — the link says nothing is connected — rather than the
    # placeholder an unbuilt endpoint would have returned.
    st, b = call("GET", "/api/v1/accounts")
    check("accounts reports the real link state instead of 501",
          st == 200 and b["connected"] is False, f"{st} {b}")
    check("and its empty list is backed by a stated connection status",
          b["accounts"] == [] and "liveAllowed" in b, str(b))
    check("live accounts are not permitted in this environment",
          b["liveAllowed"] is False)

    st, b = call("POST", f"/api/v1/rules/{rid}/preview")
    check("a decision preview without a broker is 501, not a made-up verdict",
          st == 501 and b["error"]["code"] == "UNSUPPORTED", str(st))

    print("\n9. malformed requests get a reason, not a stack trace")
    st, b = A.handle("POST", "/api/v1/rules", as_user("alice"), "{not json")
    check("a broken body is 400 with a message", st == 400, str(st))
    st, b = A.handle("POST", "/api/v1/rules", as_user("alice"), '["a"]')
    check("a JSON array body is 400", st == 400, str(st))
    st, b = call("DELETE", f"/api/v1/rules/{rid}")
    check("an unsupported method is 405", st == 405, str(st))
    st, b = call("GET", "/api/v1/nothing-here")
    check("an unknown endpoint under the prefix is 404", st == 404, str(st))
    st, b = call("GET", "/api/v1/rules/../../etc/passwd")
    check("a traversal attempt matches no route", st == 404, str(st))
finally:
    requests.get = _real_get
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
