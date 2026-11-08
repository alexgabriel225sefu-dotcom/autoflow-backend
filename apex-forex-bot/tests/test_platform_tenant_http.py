"""Two synthetic users, over the real platform HTTP server.

No production session, no production row, no broker. Identity is a local
stand-in. What is checked is that Alice's rule id, journal id and pending
approval are not readable as Bob.

Run: python3 tests/test_platform_tenant_http.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update(
    APP_ENV="test",
    ALLOW_LOCAL_BACKEND_DEV="true",
    ALLOW_PLAINTEXT_DEV_STORAGE="true",
    PRODUCT="forex",
    TOKEN_ENCRYPTION_KEY="cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI=",
    DATA_DIR=tempfile.mkdtemp(prefix="a4t-tenant-"),
    SUPABASE_URL="https://stub.supabase.co",
    SUPABASE_ANON_KEY="stub-anon",
    A4T_ALLOWED_ORIGIN="https://apex4traders.test",
)
os.environ.pop("A4T_STRIPE_WEBHOOK_SECRET", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)

from apex.platform import identity as ident                          # noqa: E402
from apex.platform import journal as journal                         # noqa: E402
from apex.platform import journal_store as journal_store             # noqa: E402
from apex import user_store                                          # noqa: E402
import platform_server as ps                                         # noqa: E402

ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
MARK = "ALICE_PRIVATE_RULE_9f3c"
SYMBOL = "ALICEPRIVATESYMBOL"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


def verify_token(token, **_kw):
    if token == "alice":
        return ident.Principal(user_id=ALICE, email="alice@example.test",
                               email_verified=True)
    if token == "bob":
        return ident.Principal(user_id=BOB, email="bob@example.test",
                               email_verified=True)
    raise ident.AuthFailed("unknown synthetic user")


ident.verify_token = verify_token

srv = ps.build_server(port=0)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw}
        return e.code, parsed


print("\n[1] Bob cannot read Alice's rule by id")
status, created = call("POST", "/api/v1/rules", "alice",
                       {"name": MARK, "symbols": ["EURUSD"]})
check("alice can create", status == 200 and created.get("ok") is True,
      str(status) + str(created)[:240])
rule = created.get("rule") or {}
rid = rule.get("ruleDocId")
check("the id came back", bool(rid), str(created)[:200])
status, bob_rule = call("GET", f"/api/v1/rules/{rid}", "bob")
check("bob is told it does not exist", status == 404, str(status))
blob = json.dumps(bob_rule)
check("bob's body does not contain the private name", MARK not in blob, blob[:300])
status, bob_list = call("GET", "/api/v1/rules", "bob")
check("bob's list does not contain it",
      status == 200 and MARK not in json.dumps(bob_list), str(bob_list)[:300])
status, alice_got = call("GET", f"/api/v1/rules/{rid}", "alice")
check("alice still can", status == 200 and MARK in json.dumps(alice_got))

print("\n[2] Bob cannot read Alice's journal entry by id")
entry = journal.JournalEntry(
    kind=journal.EVALUATION, correlation_id="corr-alice-1", user_id=ALICE,
    symbol=SYMBOL, status=journal.HOLD)
journal_store.append(entry)
status, bob_j = call("GET", f"/api/v1/journal/{entry.entry_id}", "bob")
check("bob gets not found", status == 404, str(status))
check("the symbol is not in bob's body",
      SYMBOL not in json.dumps(bob_j), str(bob_j)[:300])
status, alice_j = call("GET", f"/api/v1/journal/{entry.entry_id}", "alice")
check("alice can read her entry",
      status == 200 and SYMBOL in json.dumps(alice_j), str(status))

print("\n[3] Bob's approval list is not Alice's suggestion")
user_store.update(ALICE, {
    "active": True,
    "pending_suggestion": {"symbol": SYMBOL, "side": "BUY", "ts": 1_700_000_000},
})
status, bob_a = call("GET", "/api/v1/approvals", "bob")
check("bob's approvals answer", status == 200, str(status))
check("alice's symbol is not on bob's approval",
      SYMBOL not in json.dumps(bob_a), str(bob_a)[:300])
status, alice_a = call("GET", "/api/v1/approvals", "alice")
check("alice sees her own suggestion",
      status == 200 and SYMBOL in json.dumps(alice_a), str(alice_a)[:300])

if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for item in _fails:
        print(f"  - {item}")
    sys.exit(1)
print("\nALL OK")
