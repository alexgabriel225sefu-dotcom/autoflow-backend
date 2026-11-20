"""A client can export their own data and erase their account. (GDPR.)

THE CONTRACT THE WEB APP BUILDS AGAINST

  GET    /api/v1/account/export
         200 {"ok": true, "exportedAt": "<iso>", "data": {...}}
  DELETE /api/v1/account   body {"confirm": "DELETE"}
         200 {"ok": true, "deleted": {"<category>": <count>, ...},
              "authUserDeleted": <bool>, "note": "<sentence>"}

WHAT THESE TESTS WILL NOT ACCEPT

* An export carrying another client's data, or any token or secret.
* An erasure without the confirmation word.
* An erasure that runs before automation is stopped, or that erases anything
  when the stop failed.
* A key of the caller's left behind, or a key of another client removed.
* A second erasure failing (it is idempotent and reports zeros).
* The Supabase auth user reported deleted when no service-role key is set,
  or the service-role key appearing in an answer.
* Either route reachable without a session, or erasure outside the strict
  rate-limit bucket.

Run: python3 tests/test_account_data.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-acct-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["RATE_LIMIT_STORE"] = "memory"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

import requests                                              # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
USERS = {"alice": {"id": ALICE, "email": "alice@example.com",
                   "email_confirmed_at": "2026-01-01T00:00:00Z"},
         "bob": {"id": BOB, "email": "bob@example.com",
                 "email_confirmed_at": "2026-01-01T00:00:00Z"}}
MODE = {"user": "alice"}


class _Resp:
    def __init__(self, body):
        self.status_code, self._b = 200, body

    def json(self):
        return self._b


requests.get = lambda url, **kw: _Resp(USERS[MODE["user"]])

from apex import user_store as U                             # noqa: E402
from apex.platform import account_data as AD                 # noqa: E402
from apex.platform import api as A                           # noqa: E402
from apex.platform import identity as I                      # noqa: E402
from apex.platform import licence as L                       # noqa: E402
from apex.platform import notifications as N                 # noqa: E402
from apex.platform import ratelimit as RL                    # noqa: E402
from apex.platform import ruledoc as R                       # noqa: E402
from apex.platform import store as S                         # noqa: E402

SECRET_TOKEN = "SAMPLE-ACCESS-TOKEN-must-not-leak"
SECRET_REFRESH = "SAMPLE-REFRESH-TOKEN-must-not-leak"
stops = []


def fake_stop(uid):
    stops.append(uid)
    return {"stopped": True}


A._auto.stop = fake_stop


def call(method, path, who="alice", body=None):
    MODE["user"] = who
    I.forget_all()
    RL.reset_all()
    return A.handle(method, f"/api/v1/{path}",
                    {"Authorization": f"Bearer token-{who}"},
                    json.dumps(body) if body is not None else None)


def seed(uid, tag):
    S.create(uid, R.blank(user_id=uid, account_id="ct-1",
                          symbols=["EUR_USD"], timeframe="1h"))
    N.notify(uid, type="system", title=f"hello {tag}")
    L.grant(uid, plan="pro")
    S._write(f"{S.namespace_prefix()}ctrader:{uid}", {
        "userId": uid, "accessToken": SECRET_TOKEN,
        "refreshToken": SECRET_REFRESH, "accounts": [{"ctid": "501"}],
        "selectedCtid": "501", "connectedAt": 1})
    U.save(uid, {"active": False, "risk_percent": 1.0,
                 "ctrader_access_token": SECRET_TOKEN,
                 "ctrader_refresh_token": SECRET_REFRESH})
    U.save_trades(uid, [{"symbol": "EURUSD", "pnl": 1.0, "tag": tag}])
    S._write(f"{S.namespace_prefix()}billing:ref:pi_{tag}",
             {"userId": uid, "at": 1})


seed(ALICE, "alice")
seed(BOB, "bob")

print("\n[1] both routes need a session")
for method, path in (("GET", "account/export"), ("DELETE", "account")):
    st, _ = A.handle(method, f"/api/v1/{path}", {}, None)
    check(f"{method} {path} without a token is 401", st == 401, str(st))
check("erasure is metered in its own strict bucket",
      RL.classify("DELETE", "account") == "account_delete"
      and RL.LIMITERS["account_delete"].limit <= 10)

print("\n[2] the export is the caller's, and carries no credential")
st, b = call("GET", "account/export")
raw = json.dumps(b)
check("200 with the agreed shape", st == 200 and b.get("ok") is True
      and isinstance(b.get("exportedAt"), str) and isinstance(b.get("data"), dict),
      str(b)[:200])
d = b["data"]
check("rules are alice's", len(d["rules"]) == 1
      and d["rules"][0]["userId"] == ALICE)
check("notifications, licence, link, settings and trades are present",
      d["notifications"] and d["licence"]["state"] == L.ACTIVE
      and d["ctraderLink"]["connected"] is True
      and d["settings"].get("risk_percent") == 1.0
      and d["trades"][0]["tag"] == "alice", json.dumps(d)[:400])
check("nothing of bob's", BOB not in raw and '"bob"' not in raw
      and "hello bob" not in raw)
check("no token anywhere", SECRET_TOKEN not in raw and SECRET_REFRESH not in raw
      and "accessToken" not in raw and "ctrader_access_token" not in raw)
check("export wrote nothing", stops == [])

print("\n[3] erasure needs the confirmation word")
for body in (None, {}, {"confirm": True}, {"confirm": "delete"}):
    st, b = call("DELETE", "account", body=body)
    check(f"{body!r} refused 400", st == 400
          and b["error"]["code"] == "CONFIRMATION_REQUIRED", f"{st} {b}")
check("and nothing stopped or erased", stops == [] and S.list_docs(ALICE))

print("\n[4] a failed stop erases nothing")


def broken_stop(uid):
    raise RuntimeError("halt failed")


try:
    AD.delete(ALICE, {"confirm": "DELETE"}, stop_automation=broken_stop)
    check("refused", False)
except AD.AccountDataError as e:
    check("refused as 503 AUTOMATION_STOP_FAILED",
          e.status == 503 and e.code == "AUTOMATION_STOP_FAILED")
check("alice's rules are untouched", len(S.list_docs(ALICE)) == 1)

print("\n[5] erasure stops automation first, then removes every owned key")
before_bob = [k for k, _c, _k in AD.owned_keys(BOB)]
st, b = call("DELETE", "account", body={"confirm": "DELETE"})
check("200 with the agreed shape", st == 200 and b.get("ok") is True
      and isinstance(b.get("deleted"), dict)
      and b.get("authUserDeleted") is False, str(b)[:300])
check("automation was stopped for alice", stops == [ALICE], str(stops))
dl = b["deleted"]
for cat in ("rules", "notifications", "licence", "ctraderLink", "settings",
            "trades"):
    check(f"{cat} counted", dl.get(cat, 0) >= 1, json.dumps(dl))
check("the payment index entry counted", dl.get("billing") == 1, json.dumps(dl))
check("the note says the auth user needs manual removal",
      "support" in b.get("note", ""), b.get("note"))
check("no owned key left", AD.owned_keys(ALICE) == [],
      str(AD.owned_keys(ALICE)))
check("the engine record and trades are gone",
      U.load(ALICE) == {} and U.load_trades(ALICE) == [])
check("the licence reads as none", L.status_for(ALICE)["state"] == L.NONE)
check("bob's keys are all still there",
      [k for k, _c, _k in AD.owned_keys(BOB)] == before_bob)
check("bob's payment index is still there",
      S._read(f"{S.namespace_prefix()}billing:ref:pi_bob") is not None)

print("\n[6] erasure is idempotent")
st, b = call("DELETE", "account", body={"confirm": "DELETE"})
check("200 again", st == 200, f"{st} {b}")
check("every count zero", all(v == 0 for v in b["deleted"].values()),
      json.dumps(b["deleted"]))
check("and the request itself started no trial",
      L.status_for(ALICE)["state"] == L.NONE)

print("\n[7] with a service-role key the auth user is deleted")
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "service-role-test-only"
seen = {}


def deleter(url, key, uid):
    seen.update(url=url, key=key, uid=uid)
    return 204


AD._default_auth_deleter = deleter
st, b = call("DELETE", "account", who="bob", body={"confirm": "DELETE"})
check("authUserDeleted true", st == 200 and b["authUserDeleted"] is True,
      str(b))
check("for the caller only", seen.get("uid") == BOB, str(seen.get("uid")))
check("the key is not in the answer", "service-role-test-only" not in json.dumps(b))
AD._default_auth_deleter = lambda url, key, uid: 500
U.save(BOB, {"active": False})
st, b = call("DELETE", "account", who="bob", body={"confirm": "DELETE"})
check("a failing Supabase reports false, data still erased",
      st == 200 and b["authUserDeleted"] is False
      and b["deleted"]["settings"] >= 1, str(b))
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

print("\n[8] the per-person limit holds")
RL.reset_all()
MODE["user"] = "alice"
codes = []
for _ in range(8):
    I.forget_all()
    codes.append(A.handle("DELETE", "/api/v1/account",
                          {"Authorization": "Bearer token-alice"},
                          json.dumps({"confirm": "DELETE"}))[0])
check("refused after the bucket", 429 in codes, str(codes))

print("\n[9] an id that cannot be scanned safely is refused")
try:
    AD.owned_keys("a*b")
    check("refused", False)
except AD.AccountDataError:
    check("refused", True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All account data checks passed.")
