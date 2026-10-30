"""Operator alerts: de-duplicated, redacted, and unable to hurt the caller.

WHAT THESE TESTS WILL NOT ACCEPT

* The same (user, cause) alerting twice inside 30 minutes.
* A raw user id, a token, a Bearer value or the webhook URL in the payload.
* A sender that raises (or hangs on a bad URL) reaching the supervisor.
* A supervisor that revives, cannot revive, or fails repeatedly in silence.
* A licence lapse or a client's own Stop paging the operator.
* /readyz failing closed in production without an alert.

Run: python3 tests/test_ops_alerts.py
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-alerts-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex.platform import alerts as A                       # noqa: E402

URL = "https://hooks.example.test/services/T000/B000/SECRETPATHVALUE"
UID = "11111111-2222-4333-8444-555555555555"


class Sender:
    def __init__(self, boom=False):
        self.calls, self.boom = [], boom

    def __call__(self, url, body, timeout):
        self.calls.append((url, body, timeout))
        if self.boom:
            raise OSError("connection reset " + url)


def fresh(url=URL):
    A.reset()
    if url:
        os.environ["OPS_ALERT_WEBHOOK_URL"] = url
    else:
        os.environ.pop("OPS_ALERT_WEBHOOK_URL", None)


print("\n[1] de-duplication: one per user per cause per 30 minutes")
fresh()
s = Sender()
check("first alert sent", A.notify_ops("loop_revived", user_id=UID, sender=s, now=1000.0))
check("same user+cause again is dropped",
      not A.notify_ops("loop_revived", user_id=UID, sender=s, now=1100.0))
check("different cause for the same user is sent",
      A.notify_ops("revival_refused:MODE_UNKNOWN", user_id=UID, sender=s, now=1100.0))
check("different user, same cause is sent",
      A.notify_ops("loop_revived", user_id="other-user", sender=s, now=1100.0))
check("after 30 minutes it may fire again",
      A.notify_ops("loop_revived", user_id=UID, sender=s, now=1000.0 + 1801))
check("exactly the sent ones reached the sender", len(s.calls) == 4, str(len(s.calls)))

print("\n[2] a global ceiling stops a storm")
fresh()
s = Sender()
sent = sum(bool(A.notify_ops("loop_revived", user_id=f"u{i}", sender=s, now=5000.0))
           for i in range(100))
check("no more than the ceiling in one window", sent == A.MAX_PER_WINDOW,
      f"sent={sent}")

print("\n[3] redaction: no raw id, no token, no URL")
fresh()
s = Sender()
A.notify_ops("loop_revived", user_id=UID,
             detail="Bearer abcdefghijklmnop1234 access_token=zzzzzzzzzzzz",
             sender=s, now=1.0)
url, body, timeout = s.calls[0]
text = json.dumps(body)
check("posted to the configured URL", url == URL)
check("body carries a text field (Slack/Telegram) and content (Discord)",
      "text" in body and "content" in body)
check("raw user id is absent", UID not in text and UID[:8] not in text, text)
check("a short stable hash of the user is present", A.short_user(UID) in text)
check("bearer token is absent", "abcdefghijklmnop1234" not in text, text)
check("access_token value is absent", "zzzzzzzzzzzz" not in text, text)
check("the webhook URL never appears in the body", "SECRETPATHVALUE" not in text)
check("short_user is stable and not the id",
      A.short_user(UID) == A.short_user(UID) and A.short_user(UID) != UID
      and len(A.short_user(UID)) <= 12)
check("a short timeout is used", 0 < timeout <= 5, str(timeout))

print("\n[4] never raises into the caller")
fresh()
boom = Sender(boom=True)
try:
    r = A.notify_ops("loop_revived", user_id=UID, sender=boom, now=1.0)
    check("a raising sender is swallowed", r is False or r is True)
except Exception as e:                                       # noqa: BLE001
    check("a raising sender is swallowed", False, repr(e))


def bad_clock():
    raise RuntimeError("clock")


class Weird:
    def __str__(self):
        raise RuntimeError("no str")


try:
    A.notify_ops(Weird(), user_id=Weird(), detail=Weird(), sender=Sender(), now=2.0)
    check("garbage arguments are swallowed", True)
except Exception as e:                                       # noqa: BLE001
    check("garbage arguments are swallowed", False, repr(e))
buf = io.StringIO()
with redirect_stdout(buf):
    A.notify_ops("loop_revived", user_id="zz", sender=Sender(boom=True), now=3.0)
check("a failed send does not print the webhook URL",
      "SECRETPATHVALUE" not in buf.getvalue(), buf.getvalue())

print("\n[5] no webhook configured is a quiet no-op")
fresh(url=None)
s = Sender()
check("returns False and sends nothing",
      A.notify_ops("loop_revived", user_id=UID, sender=s, now=1.0) is False and not s.calls)
fresh(url="http://insecure.example.test/hook")
s = Sender()
check("a plain-http webhook is refused",
      A.notify_ops("loop_revived", user_id=UID, sender=s, now=1.0) is False and not s.calls)
fresh(url="file:///etc/passwd")
check("a non-http scheme is refused",
      A.notify_ops("loop_revived", user_id=UID, sender=s, now=1.0) is False and not s.calls)

print("\n[6] structured log line")
buf = io.StringIO()
os.environ["SOME_API_SECRET"] = "supersecretvalue123"
with redirect_stdout(buf):
    A.log_event("warn", "loop_revived", user_id=UID, note="saw supersecretvalue123",
                access_token="whatever-token-value", count=3)
line = buf.getvalue().strip()
rec = json.loads(line)
check("one JSON line", "\n" not in line and rec["event"] == "loop_revived")
check("has level and ts", rec["level"] == "warn" and "ts" in rec)
check("fields are nested", rec["fields"]["count"] == 3)
check("user id is shortened, not raw", UID not in line and rec["fields"]["user"] == A.short_user(UID))
check("known secret value is masked", "supersecretvalue123" not in line)
check("a secret-named field is dropped from the line",
      "whatever-token-value" not in line)
hook_calls = []
A.set_error_hook(lambda ev, fields: hook_calls.append((ev, fields)))
with redirect_stdout(io.StringIO()):
    A.log_event("error", "boom", user_id=UID)
    A.log_event("info", "fine")
check("error hook gets error-level events only", [h[0] for h in hook_calls] == ["boom"])
A.set_error_hook(lambda *_: (_ for _ in ()).throw(RuntimeError("hook broke")))
try:
    with redirect_stdout(io.StringIO()):
        A.log_event("error", "boom2")
    check("a broken error hook cannot raise", True)
except Exception as e:                                       # noqa: BLE001
    check("a broken error hook cannot raise", False, repr(e))
A.set_error_hook(None)

print("\n[7] the supervisor alerts on revive, on refusal and on repeats")
from apex import user_loop, user_store                      # noqa: E402
from apex.platform import automation as AUTO                # noqa: E402
from apex.platform import ctrader_link as CTL               # noqa: E402
from apex.platform import entitlement as ENT                # noqa: E402

PU = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
try:
    user_store.update(PU, {"active": True})
except Exception:                                            # noqa: BLE001
    pass
CTL.is_platform_account = lambda uid: True
user_store.all_active = lambda: [PU]
user_loop.is_running = lambda uid: False
AUTO._read = lambda uid: {"state": AUTO.RUNNING, "ruleDocId": "r1"}

sent = []
A._default_sender = lambda url, body, timeout: sent.append(body)
fresh()


def run(start_impl):
    AUTO.start = start_impl
    return AUTO.supervise()


def ok_start(*a, **k):
    return {}


def refuse(code):
    def f(*a, **k):
        raise AUTO.AutomationRefused(code, "detail with Bearer abcdefghijklmnop1234")
    return f


def raise_ent(*a, **k):
    raise ENT.NotEntitled("LICENCE_WITHDRAWN", "licence")


def raise_other(*a, **k):
    raise ValueError("kaboom abcdefghijklmnop1234")


with redirect_stdout(io.StringIO()):
    fresh()
    sent.clear()
    alive, revived = run(ok_start)
A.drain() if hasattr(A, "drain") else None
check("a revived loop alerts the operator", revived == 1 and len(sent) == 1, str(sent))
check("the alert names the cause", "loop_revived" in json.dumps(sent))

with redirect_stdout(io.StringIO()):
    fresh()
    sent.clear()
    run(refuse("MODE_UNKNOWN"))
A.drain() if hasattr(A, "drain") else None
check("a refusal for a non-licence reason alerts", len(sent) == 1, str(sent))
check("and carries the code, not the detail text",
      "MODE_UNKNOWN" in json.dumps(sent) and "abcdefghijklmnop1234" not in json.dumps(sent))

for quiet in ("STOPPED_MEANWHILE",):
    with redirect_stdout(io.StringIO()):
        fresh()
        sent.clear()
        run(refuse(quiet))
    A.drain() if hasattr(A, "drain") else None
    check(f"{quiet} (the client's own stop) does not alert", not sent, str(sent))

with redirect_stdout(io.StringIO()):
    fresh()
    sent.clear()
    run(raise_ent)
A.drain() if hasattr(A, "drain") else None
check("a lapsed licence does not alert", not sent, str(sent))

with redirect_stdout(io.StringIO()):
    fresh()
    sent.clear()
    run(raise_other)
A.drain() if hasattr(A, "drain") else None
check("an unexpected failure alerts, with the type and not the message",
      len(sent) == 1 and "ValueError" in json.dumps(sent)
      and "kaboom" not in json.dumps(sent), str(sent))

with redirect_stdout(io.StringIO()):
    fresh()
    sent.clear()
    AUTO._revive_failures.clear()
    for i in range(AUTO.REPEAT_FAILURE_THRESHOLD):
        # Distinct codes so de-dup of the single cause is not what is measured.
        run(refuse(f"CODE_{i}"))
A.drain() if hasattr(A, "drain") else None
check("repeated failures raise a distinct alert",
      any("revival_repeated_failure" in json.dumps(b) for b in sent), str(sent))

with redirect_stdout(io.StringIO()):
    fresh()
    sent.clear()
    AUTO.start = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    A.notify_ops = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("alerts down"))
    try:
        AUTO.supervise()
        check("a broken alert path cannot break the supervisor", True)
    except Exception as e:                                   # noqa: BLE001
        check("a broken alert path cannot break the supervisor", False, repr(e))

print("\n[8] /readyz failing closed in production alerts")
import importlib                                            # noqa: E402
importlib.reload(A)
from apex.platform import health as H                       # noqa: E402
seen = []
H._alerts = type("X", (), {
    "notify_ops": staticmethod(lambda cause, **k: seen.append(cause)),
    "log_event": staticmethod(lambda *a, **k: None)})
os.environ["APP_ENV"] = "production"
for n in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "TOKEN_ENCRYPTION_KEY"):
    os.environ.pop(n, None)
H.reset_cache()
with redirect_stdout(io.StringIO()):
    status, payload = H.ready(force=True)
check("production readiness is failing in this fixture", status == 503)
check("an alert names the failed checks, no values",
      seen and seen[0].startswith("readyz_fail:") and "supabase" in seen[0], str(seen))
seen.clear()
os.environ["APP_ENV"] = "dev"
H.reset_cache()
with redirect_stdout(io.StringIO()):
    H.ready(force=True)
check("a development box does not alert", not seen, str(seen))

print()
if _fails:
    print(f"FAILED {len(_fails)}:")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL OPS ALERT CHECKS PASSED")
