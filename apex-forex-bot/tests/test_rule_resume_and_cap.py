"""Resuming a rule is held to activation's gate, and rules are capped per user.

FOUND BY THE SECURITY AUDIT.

1. `POST rules/{id}/resume` moved a PAUSED or ARCHIVED rule straight back to
   ACTIVE through `store.set_state`, with no licence check, no confirmed
   address and a cached session. A client whose licence support had WITHDRAWN
   — the one lever that is meant to stop everything — could archive a rule
   before the withdrawal and resume it after, while `activate` refused them.
2. Nothing bounded how many rule documents one account could store. Every
   create is a write to the shared store, so a script could fill it.

WHAT THESE TESTS WILL NOT ACCEPT

* A withdrawn licence resuming a paused or archived rule.
* An unconfirmed address resuming a rule.
* Resume trusting a cached session.
* A licensed, confirmed client being unable to resume (the gate must not
  become a lock-out).
* More than the cap of rules stored for one client, or a refusal that is a
  generic 400 instead of its own code.
* The cap of one client limiting another.

Run: python3 tests/test_rule_resume_and_cap.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-resume-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["RATE_LIMIT_STORE"] = "memory"
os.environ["A4T_MAX_RULES_PER_USER"] = "5"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"

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
USERS = {
    "alice": {"id": ALICE, "email": "alice@example.com",
              "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "unverified": {"id": ALICE, "email": "alice@example.com"},
    "bob": {"id": BOB, "email": "bob@example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z"},
}
MODE = {"user": "alice"}
calls = {"n": 0}


class _Resp:
    def __init__(self, body):
        self.status_code, self._b = 200, body

    def json(self):
        return self._b


def _fake_get(url, **kw):
    calls["n"] += 1
    return _Resp(USERS[MODE["user"]])


requests.get = _fake_get

from apex.platform import api as A                           # noqa: E402
from apex.platform import identity as I                      # noqa: E402
from apex.platform import licence as L                       # noqa: E402
from apex.platform import ratelimit as RL                    # noqa: E402
from apex.platform import ruledoc as R                       # noqa: E402
from apex.platform import store as S                         # noqa: E402

RULE = {"name": "r", "symbols": ["EUR_USD"], "timeframe": "1h",
        "sides": "BUY", "accountId": "ct-demo-1",
        "entry": {"combine": "AND", "conditions": [
            {"id": "rsi", "params": {"op": "below", "value": 30}}]},
        "exit": {"combine": "OR", "conditions": [
            {"id": "rsi", "params": {"op": "above", "value": 70}}]}}


def call(method, path, who="alice", body=None, keep_cache=False):
    MODE["user"] = who
    if not keep_cache:
        I.forget_all()
    RL.reset_all()
    return A.handle(method, f"/api/v1/{path}",
                    {"Authorization": f"Bearer token-{who}"},
                    json.dumps(body) if body is not None else None)


def new_active_rule():
    st, b = call("POST", "rules", body=dict(RULE))
    rid = b["rule"]["ruleDocId"]
    st, b = call("POST", f"rules/{rid}/activate")
    assert st == 200, (st, b)
    return rid


print("\n[1] a withdrawn licence cannot resume an archived or paused rule")
for parked in ("archive", "pause"):
    L.grant(ALICE, plan="pro")
    rid = new_active_rule()
    st, _ = call("POST", f"rules/{rid}/{parked}")
    check(f"{parked} works", st == 200, str(st))
    L.revoke(ALICE)
    st, b = call("POST", f"rules/{rid}/resume")
    check(f"resume after {parked} refused as 402 LICENCE_REQUIRED",
          st == 402 and b["error"]["code"] == "LICENCE_REQUIRED", f"{st} {b}")
    check("and the rule stayed parked",
          S.get(ALICE, rid)["state"] != R.ACTIVE, S.get(ALICE, rid)["state"])

print("\n[2] an unconfirmed address cannot resume")
L.grant(ALICE, plan="pro")
rid = new_active_rule()
call("POST", f"rules/{rid}/archive")
st, b = call("POST", f"rules/{rid}/resume", who="unverified")
check("401", st == 401, f"{st} {b}")
check("still archived", S.get(ALICE, rid)["state"] == R.ARCHIVED)

print("\n[3] resume re-checks the session instead of trusting the cache")
call("GET", "me")                                # warm the cache
before = calls["n"]
st, b = call("POST", f"rules/{rid}/resume", keep_cache=True)
check("a licensed, confirmed client resumes", st == 200
      and b["rule"]["state"] == R.ACTIVE, f"{st} {b}")
check("with a fresh Supabase lookup", calls["n"] == before + 1,
      f"{before}->{calls['n']}")

print("\n[4] another client's rule is a 404, before any licence check")
L.revoke(BOB)
st, _ = call("POST", f"rules/{rid}/resume", who="bob")
check("404", st == 404, str(st))
L.grant(BOB, plan="pro")

print("\n[5] rules are capped per user")
# Alice already holds three rules from the sections above.
held = len(S.list_docs(ALICE))
codes = []
for _ in range(10):
    st, b = call("POST", "rules", body=dict(RULE))
    codes.append(st)
check("creates stop at the cap", len(S.list_docs(ALICE)) == 5,
      f"held {held} -> {len(S.list_docs(ALICE))}")
st, b = call("POST", "rules", body=dict(RULE))
check("the refusal is 409 RULE_LIMIT_REACHED",
      st == 409 and b["error"]["code"] == "RULE_LIMIT_REACHED", f"{st} {b}")
check("and says what the limit is", "5" in b["error"]["message"],
      b["error"]["message"])
st, b = call("POST", "rules", who="bob", body=dict(RULE))
check("another client is not limited by the first", st == 200, f"{st} {b}")
try:
    S.create(ALICE, R.blank(user_id=ALICE, account_id="", symbols=["EUR_USD"],
                            timeframe="1h"))
    check("the cap holds at the store, not only at the API", False)
except S.RuleLimitReached:
    check("the cap holds at the store, not only at the API", True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All resume and rule-cap checks passed.")
