"""Operators are licensed. They are not exempt from live trading.

The badge and the automation gate both read licence.status_for. An id on
A4T_OPERATOR_USER_IDS is reported active, including when the stored record
has lapsed or been withdrawn. The stored record is not rewritten.

That answer does not open the live gate, the release switch, or a live
account. A client who is not an operator keeps whatever state is on file.

Run: python3 tests/test_platform_operator_licence.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-op-lic-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "test"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_LIVE_EXECUTION", None)
os.environ.pop("APEX_ALLOW_LIVE_ACCOUNTS", None)

from apex.platform import entitlement as E          # noqa: E402
from apex.platform import licence as L              # noqa: E402
from apex.platform import live_gate as LG           # noqa: E402
from apex.platform import plans as P                # noqa: E402
from apex.platform import store as ST               # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


NOW = 1_700_000_000.0
OP = "op-operator-licence"
CLIENT = "client-operator-licence"
PAST = NOW - 86_400

os.environ[LG.OPERATOR_ENV] = OP

for uid in (OP, CLIENT):
    L.grant(uid, plan=P.DEMO_TRIAL, expires_at=PAST, now=PAST - 10)

print("\n[1] an operator is licensed; a client with the same record is not")
op = L.status_for(OP, now=NOW)
cl = L.status_for(CLIENT, now=NOW)
check("operator state is active", op["state"] == L.ACTIVE, str(op))
check("operator plan stays the stored trial", op["plan"] == P.DEMO_TRIAL, str(op))
check("a lapsed operator trial does not keep counting down",
      op["expiresAt"] is None, str(op))
check("client state is expired", cl["state"] == L.EXPIRED, str(cl))
check("client expiry is still the stored one", cl["expiresAt"] == PAST, str(cl))

raw = ST._read(L._key(OP))
check("the operator's stored record was not rewritten",
      raw.get("state") == L.ACTIVE and raw.get("expiresAt") == PAST, str(raw))

print("\n[2] automation follows the licence; live trading does not")
cap_client = E.capability(CLIENT, now=NOW)
check("expired client cannot automate", cap_client["canAutomate"] is False)
check("expired client is told the trial ended",
      cap_client["reason"] == "TRIAL_EXPIRED"
      and cap_client["licenceState"] == L.EXPIRED, str(cap_client.get("reason")))

_mode = E.account_mode
_reauth = E._reauth_needed
try:
    E.account_mode = lambda _uid: E.DEMO
    E._reauth_needed = lambda *_a, **_k: False
    cap_op = E.capability(OP, now=NOW)
    check("operator on a demo account may automate",
          cap_op["canAutomate"] is True and cap_op["licenceState"] == L.ACTIVE,
          str(cap_op))
    check("that permission is still the free tier, not a paid live plan",
          cap_op["entitlement"] == E.FREE_DEMO, str(cap_op.get("entitlement")))

    E.account_mode = lambda _uid: E.LIVE
    cap_live = E.capability(OP, now=NOW)
    check("operator on a live account is still blocked",
          cap_live["canAutomate"] is False, str(cap_live))
    check("the block is the release switch",
          cap_live["reason"] == "LIVE_NOT_AVAILABLE", str(cap_live.get("reason")))
    check("the licence on that refusal is still active",
          cap_live["licenceState"] == L.ACTIVE, str(cap_live.get("licenceState")))
finally:
    E.account_mode = _mode
    E._reauth_needed = _reauth

closed = LG.public_verdict(OP, release_switch=False, live_accounts_allowed=False)
opened = LG.public_verdict(OP, release_switch=True, live_accounts_allowed=True)
check("the live gate stays closed while the switch is off",
      closed["open"] is False, str(closed.get("open")))
check("opening the switches does not approve the operator",
      opened["open"] is False, str(opened.get("status")))

print("\n[3] withdrawal still binds a client, and not an operator")
L.revoke(CLIENT)
L.revoke(OP)
check("a withdrawn client stays withdrawn",
      L.status_for(CLIENT, now=NOW)["state"] == L.REVOKED)
check("a withdrawn client still cannot automate",
      E.capability(CLIENT, now=NOW)["canAutomate"] is False)
check("a withdrawn operator is still licensed",
      L.status_for(OP, now=NOW)["state"] == L.ACTIVE)
stored = ST._read(L._key(OP))
check("withdrawal stays on the stored record",
      stored.get("state") == L.REVOKED, str(stored.get("state")))

print("\n[4] with the operator list empty, the stored record is what is reported")
os.environ.pop(LG.OPERATOR_ENV, None)
check("nobody is an operator", LG.operators() == set())
check("the operator id follows the stored withdrawal again",
      L.status_for(OP, now=NOW)["state"] == L.REVOKED)

print()
if _fails:
    print(f"FAILED ({len(_fails)}): {_fails}")
    sys.exit(1)
print("All operator-licence checks passed.")
