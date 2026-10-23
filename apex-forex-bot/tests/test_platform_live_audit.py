"""The future live path has an append-only audit trail before it is wired.

Run: python tests/test_platform_live_audit.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-live-audit-")

from apex.platform import live_audit as audit  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception as e:                              # noqa: BLE001
        return f"raised {type(e).__name__}: {e}"
    return "did not raise"


print("\n[1] every required live audit event can be recorded")
order = audit.record_live_order(
    event_id="evt-order-1",
    user_id="u1",
    actor_id="u1",
    account_id="acc-demo",
    rule_doc_id="rule-7",
    rule_doc_version=3,
    decision_id="decision-9",
    request={"symbol": "EURUSD", "side": "BUY", "units": 1000},
    broker_reply={"ok": True, "positionId": "pos-1"},
    position_id="pos-1",
    ts=1000.0,
)
check("live order stores who, rule version, decision, request and reply",
      order["userId"] == "u1"
      and order["actorId"] == "u1"
      and order["ruleDocVersion"] == 3
      and order["decisionId"] == "decision-9"
      and order["request"]["units"] == 1000
      and order["brokerReply"]["positionId"] == "pos-1"
      and order["positionId"] == "pos-1",
      str(order))

refusal = audit.record_refusal(
    event_id="evt-refusal-1",
    user_id="u1",
    actor_id="system",
    gate="entitlement",
    code="LIVE_NOT_AVAILABLE",
    decision_id="decision-10",
    detail={"message": "live trading is not available in this release"},
    ts=1001.0,
)
check("refusal stores the gate and code",
      refusal["gate"] == "entitlement"
      and refusal["code"] == "LIVE_NOT_AVAILABLE",
      str(refusal))

ent = audit.record_entitlement_change(
    event_id="evt-entitlement-1",
    user_id="u1",
    actor_id="billing-webhook",
    before={"state": "none"},
    after={"state": "active", "plan": "founder"},
    ts=1002.0,
)
consent = audit.record_consent_change(
    event_id="evt-consent-1",
    user_id="u1",
    actor_id="u1",
    before={"liveTrading": False},
    after={"liveTrading": True, "acceptedAt": 1003.0},
    ts=1003.0,
)
mode = audit.record_mode_verification(
    event_id="evt-mode-1",
    user_id="u1",
    actor_id="system",
    account_id="acc-demo",
    requested_mode="demo",
    broker_answer={"mode": "demo", "source": "broker"},
    ts=1004.0,
)
check("entitlement changes carry actor and before/after",
      ent["actorId"] == "billing-webhook"
      and ent["before"]["state"] == "none"
      and ent["after"]["plan"] == "founder", str(ent))
check("consent changes carry actor and before/after",
      consent["actorId"] == "u1"
      and consent["before"]["liveTrading"] is False
      and consent["after"]["liveTrading"] is True, str(consent))
check("mode verification stores the broker answer",
      mode["brokerAnswer"]["mode"] == "demo"
      and mode["requestedMode"] == "demo", str(mode))

print("\n[2] audit append refuses rewrites")
again = raises(audit.AuditConflict, lambda: audit.record_refusal(
    event_id="evt-refusal-1",
    user_id="u1",
    actor_id="system",
    gate="risk",
    code="DIFFERENT",
    ts=2000.0,
))
check("rewriting an existing audit event is refused", again is True, str(again))
stored = audit.get("u1", "evt-refusal-1")
check("the original row is still the row on disk",
      stored["gate"] == "entitlement"
      and stored["code"] == "LIVE_NOT_AVAILABLE"
      and stored["ts"] == 1001.0, str(stored))

print("\n[3] credentials are refused before redaction")
secret_order = raises(ValueError, lambda: audit.record_live_order(
    event_id="evt-secret-1",
    user_id="u1",
    actor_id="u1",
    account_id="acc-demo",
    rule_doc_id="rule-7",
    rule_doc_version=3,
    decision_id="decision-secret",
    request={"symbol": "EURUSD", "accessToken": "not-for-audit"},
    broker_reply={"ok": True},
))
check("credential-looking request fields are not stored",
      secret_order is True, str(secret_order))
missing = raises(LookupError, lambda: audit.get("u1", "evt-secret-1"))
check("the refused secret row was never written", missing is True, str(missing))

print("\n[4] query is scoped by owner and kind")
u1_orders = audit.query("u1", kind=audit.LIVE_ORDER)
check("query returns this user's live order",
      len(u1_orders) == 1 and u1_orders[0]["eventId"] == "evt-order-1",
      str(u1_orders))
u2 = audit.query("u2")
check("another user cannot see the row through query", u2 == [], str(u2))
other_get = raises(LookupError, lambda: audit.get("u2", "evt-order-1"))
check("another user cannot read the row directly", other_get is True,
      str(other_get))

print("\n[5] the module stays outside the live execution boundary")
src = open(os.path.join(ROOT, "apex", "platform", "live_audit.py"),
           encoding="utf-8").read()
check("live audit does not import bridge", "bridge" not in src, "")
check("live audit does not name broker-mutating operations",
      all(word not in src for word in (
          "place_order", "close_position", "amend_sltp", "force_trade",
          "authorize_order", "authorize_close", "modify_position")))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL LIVE-AUDIT CHECKS PASSED.")
