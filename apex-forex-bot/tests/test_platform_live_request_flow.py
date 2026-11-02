"""Request, reject, request again, approve. The order door stays shut.

The client sees a scrubbed rejection reason and a notification. The operator
id does not travel with either. Real switches stay unset, so an approval
does not open a live order.

Run: python3 tests/test_platform_live_request_flow.py
"""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-livereq-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_EMERGENCY_HALT", None)
for _banned in ("A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS",
                "A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS",
                "A4T_LIVE_PILOT_MAX_UNITS", "PAPER_TRADING"):
    os.environ.pop(_banned, None)

from apex import user_store                              # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class Fake:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        for name in ("set_blob_nx", "set_blob", "get_blob", "get_blob_strict",
                     "del_blob", "claim", "claim_value", "release_claim", "incr"):
            setattr(user_store, name, getattr(self, name))

    def set_blob_nx(self, key, value):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = value
            return True

    def set_blob(self, key, value, ttl_s=None):
        with self.lock:
            self.data[key] = value
        return True

    def get_blob(self, key):
        with self.lock:
            return self.data.get(key)

    def get_blob_strict(self, key):
        return self.get_blob(key)

    def del_blob(self, key):
        with self.lock:
            return self.data.pop(key, None)

    def claim(self, key, ttl_s=120):
        return self.claim_value(key, "1", ttl_s=ttl_s)

    def claim_value(self, key, value, ttl_s=120):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = str(value)
            return True

    def release_claim(self, key, value):
        with self.lock:
            if self.data.get(key) != str(value):
                return False
            del self.data[key]
        return True

    def incr(self, key, ttl_s=60):
        with self.lock:
            self.data[key] = int(self.data.get(key, 0)) + 1
            return self.data[key]


Fake().install()

from apex.platform import ctrader_link as CL             # noqa: E402
from apex.platform import entitlement as E               # noqa: E402
from apex.platform import live_gate as LG                # noqa: E402
from apex.platform import notifications as N             # noqa: E402

ACTOR = "operator-1"
CLIENT = "client-1"
LEAK = "https://evil.example/steal Bearer sekretvalueplease"


class Principal:
    def __init__(self, user_id):
        self.user_id = user_id
        self.email = "person@example.test"
        self.email_verified = True


os.environ[LG.OPERATOR_ENV] = ACTOR
client = Principal(CLIENT)
operator = Principal(ACTOR)

print("\n[1] a failed notification does not undo the decision")
for doc in LG.DOCUMENTS:
    LG.publish(doc, "v1", actor=ACTOR)
LG.accept_current("notify-down")
LG.request_live("notify-down")
_real_notify = N.notify


def _down(*_a, **_k):
    raise RuntimeError(LEAK)


N.notify = _down
try:
    decided = LG.decide("notify-down", "rejected", actor=ACTOR, reason="later")
finally:
    N.notify = _real_notify
check("the rejection is stored", decided["status"] == "rejected", str(decided))
stored = LG._load(LG._key("request:notify-down"))[0]
check("the record says rejected", stored["status"] == "rejected", str(stored))
quiet = N.query("notify-down")
check("no notification was written", quiet["notifications"] == [], str(quiet))

print("\n[2] request, reject with a secret in the reason, show the client")
LG.accept_current(CLIENT)
LG.request_live(CLIENT)
status, queue = LG.http("GET", "live/queue", operator, {})
pending = [row for row in queue.get("requests") or [] if row.get("userId") == CLIENT]
check("the queue lists the pending request",
      status == 200 and pending and pending[0]["status"] == "pending",
      str(queue)[:240])

reason = f"documents do not match; see {LEAK}"
status, review = LG.http(
    "POST", f"live/requests/{CLIENT}/decide", operator,
    {"decision": "rejected", "reason": reason})
check("the operator rejection is recorded",
      status == 200 and review.get("status") == "rejected", str(review)[:240])

status, shown = LG.http("GET", "live/status", client, {})
blob = json.dumps(shown)
check("the client reads a rejection",
      status == 200 and shown["request"]["status"] == "rejected", blob[:300])
check("the scrubbed reason is on the client verdict",
      "documents do not match" in shown["request"].get("reason", ""),
      str(shown["request"]))
check("the url and the bearer token are gone",
      "evil.example" not in blob and "sekretvalueplease" not in blob
      and "https://" not in blob, blob)
check("the operator id is not on the client verdict",
      ACTOR not in blob and "actor" not in shown["request"], blob[:400])
notes = N.query(CLIENT)
bodies = " ".join(n.get("body") or "" for n in notes["notifications"])
titles = " ".join(n.get("title") or "" for n in notes["notifications"])
check("the client is notified of the decline",
      "Live access request declined" in titles and "documents do not match" in bodies,
      str(notes)[:400])
check("the notification does not carry the operator id or the secret",
      ACTOR not in bodies and ACTOR not in titles
      and "sekretvalueplease" not in bodies and "evil.example" not in bodies,
      bodies)
check("the notification points at the live page",
      all(n.get("link") == "/live" for n in notes["notifications"]),
      str(notes)[:200])

print("\n[3] a rejected client can request again, then be approved")
again = LG.request_live(CLIENT)
check("a new request is pending", again["status"] == "pending", str(again))
status, approved = LG.http(
    "POST", f"live/requests/{CLIENT}/decide", operator,
    {"decision": "approved", "reason": "reviewed"})
check("approval is recorded",
      status == 200 and approved.get("status") == "approved", str(approved)[:240])
status, shown = LG.http("GET", "live/status", client, {})
check("approval does not send the reason or the actor to the client",
      shown["request"] == {"status": "approved"} and ACTOR not in json.dumps(shown),
      str(shown["request"]))
notes = N.query(CLIENT)
approved_notes = [n for n in notes["notifications"]
                  if n.get("title") == "Live access request approved"]
check("approval notifies without claiming live trading is available",
      len(approved_notes) == 1
      and "every other condition is met" in approved_notes[0]["body"]
      and "live trading is available" not in approved_notes[0]["body"].lower()
      and ACTOR not in approved_notes[0]["body"],
      str(approved_notes))

print("\n[4] a licence and an approval still leave the real switches closed")
LG.grant_operator_licence(CLIENT, actor=ACTOR)
real = LG.public_verdict(
    CLIENT,
    release_switch=E.live_execution_enabled(),
    live_accounts_allowed=CL.live_allowed())
check("the release switch is off", E.live_execution_enabled() is False)
check("live accounts are not allowed", CL.live_allowed() is False)
check("the live-account flag is off",
      os.environ.get("APEX_ALLOW_LIVE_ACCOUNTS") is None
      and os.environ.get("A4T_LIVE_EXECUTION") is None)
blocked = LG.order_block(CLIENT)
check("order_block still refuses",
      blocked is not None and blocked[0] == "LIVE_GATE_CLOSED", str(blocked))
check("the public verdict with the real switch is closed",
      real["open"] is False and real["status"] == "closed", str(real.get("missing")))

if _fails:
    print(f"\n{len(_fails)} FAILED")
    for item in _fails:
        print(" -", item)
    sys.exit(1)
print("\nall checks passed")
