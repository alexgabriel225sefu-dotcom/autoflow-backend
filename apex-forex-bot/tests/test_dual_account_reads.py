"""Both linked accounts are readable. Live orders stay blocked.

The synthetic broker below is the only broker these tests talk to. It never
opens a socket and it never places an order.

Run: python3 tests/test_dual_account_reads.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-dual-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "test"
os.environ["PRODUCT"] = "forex"
os.environ["TELEGRAM_BOT_TOKEN"] = ""

from apex.platform import account_reads as AR          # noqa: E402
from apex.platform import automation as A              # noqa: E402
from apex.platform import broker_read as BR            # noqa: E402
from apex.platform import ctrader_link as L            # noqa: E402
from apex.platform import journal as J                 # noqa: E402
from apex.platform import journal_store as JS          # noqa: E402
from apex.platform import read_telemetry as RT         # noqa: E402
from apex.platform import risk_map as RM               # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


class Synthetic:
    """One account, in memory. `fault` names the next failure, then clears."""

    def __init__(self, mode="demo"):
        self.mode = mode
        self.fault = None
        self.calls = []
        self.balance = 2500.0
        self.positions = [{
            "symbol": "EURUSD", "side": "BUY", "units": 1000,
            "entryPrice": 1.1, "stopLoss": 1.09, "takeProfit": 1.12,
            "positionId": 1, "pnlAccount": 12.5,
        }]
        self.orders = [{"orderId": 7}]

    def _hit(self, operation):
        self.calls.append(operation)
        fault = self.fault
        self.fault = None
        if fault == "auth":
            raise RuntimeError("not authorized")
        if fault == "timeout":
            raise TimeoutError("timed out")
        if fault == "rate":
            raise RuntimeError("429 too many requests")
        if fault == "disconnect":
            raise ConnectionError("connection reset by peer")
        if fault == "malformed" and operation == "positions":
            return {"not": "a list"}
        if operation == "balance":
            return self.balance
        if operation == "positions":
            return self.positions
        if operation == "orders":
            return list(self.orders)
        raise AssertionError(operation)

    def get_balance(self):
        return self._hit("balance")

    def get_all_positions(self):
        return self._hit("positions")

    def get_pending_orders(self):
        return self._hit("orders")

    def get_bid_ask(self, _symbol):
        return 1.1, 1.1002


def connection(mode):
    def getter(user_id, ctid=None, purpose="read"):
        check("reads do not open a trading session", purpose == "read", purpose)
        return {"userId": user_id, "accessToken": "super-secret-token",
                "ctid": ctid, "mode": mode}
    return getter


def read(broker, mode):
    def fn(user_id, **kw):
        return BR._read(
            user_id, {"balance": "balance", "positions": "positions",
                      "orders": "orders"}[kw.pop("kind")],
            {"balance": lambda b: b.get_balance(),
             "positions": BR._enrich_positions,
             "orders": lambda b: b.get_pending_orders()}[kw.get("kind", "balance")],
            connection_fn=connection(mode), broker_fn=lambda: broker, **kw)
    # The kind is selected by account_reads via separate functions. Tests call
    # broker_read directly as well.
    return fn


def capture(fn):
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn()
    return result, buf.getvalue()


print("\n[1] a read logs the operation and nothing private")
broker = Synthetic()
result, log = capture(lambda: BR.account(
    "user", ctid="acct-9001", connection_fn=connection("demo"),
    broker_fn=lambda: broker, expected_mode="demo"))
check("the balance came back", result.get("status") == "ok" and result.get("balance") == 2500.0, result)
line = next(l for l in log.splitlines() if l.startswith("[broker-read]"))
payload = json.loads(line.split(" ", 1)[1])
check("telemetry keeps only the allowlist",
      set(payload) == {"correlation_id", "duration_ms", "error_code",
                       "http_status", "operation", "timestamp"},
      payload)
check("a success has no error code", payload["error_code"] is None and payload["http_status"] == 200)
check("the token is not in the log", "super-secret-token" not in log)
check("the account number is not in the log", "acct-9001" not in log)
check("the balance is not in the telemetry", "2500" not in json.dumps(payload))

print("\n[2] failures are named, and the next read can recover")
cases = [
    ("auth", "reauth_required", "AUTH_FAILED", 401),
    ("timeout", "unavailable", "TIMEOUT", 504),
    ("rate", "unavailable", "RATE_LIMITED", 429),
    ("disconnect", "unavailable", "DISCONNECTED", 503),
]
for fault, status, code, http in cases:
    broker.fault = fault
    result, log = capture(lambda: BR.account(
        "user", ctid="acct-9001", connection_fn=connection("demo"),
        broker_fn=lambda: broker))
    check(f"{fault} status", result.get("status") == status, result)
    check(f"{fault} code", result.get("errorCode") == code, result.get("errorCode"))
    check(f"{fault} correlation", bool(result.get("correlationId")))
    body = json.loads(next(l.split(" ", 1)[1] for l in log.splitlines() if l.startswith("[broker-read]")))
    check(f"{fault} http", body["http_status"] == http and body["error_code"] == code, body)
    check(f"{fault} log stays clean", "super-secret-token" not in log and "2500" not in log)

broker.positions = {"not": "a list"}
result, _log = capture(lambda: BR.positions(
    "user", ctid="acct-9001", connection_fn=connection("demo"),
    broker_fn=lambda: broker))
check("a malformed position payload is not an empty book",
      result.get("status") == "malformed" and "positions" not in result, result)
broker.positions = []

print("\n[3] an environment mismatch is not served as the other account")
called = []
result, _log = capture(lambda: BR.account(
    "user", ctid="live-1", expected_mode="demo",
    connection_fn=connection("live"),
    broker_fn=lambda: called.append(True) or broker))
check("mismatch status", result.get("status") == "env_mismatch", result)
check("the broker was not asked", called == [])
check("no balance was invented", "balance" not in result)

print("\n[4] recovery does not reuse a failed read")
broker.fault = "timeout"
first, _ = capture(lambda: BR.account(
    "user", connection_fn=connection("demo"), broker_fn=lambda: broker))
second, _ = capture(lambda: BR.account(
    "user", connection_fn=connection("demo"), broker_fn=lambda: broker))
check("the failure was not cached", first.get("status") == "unavailable", first)
check("the next read succeeded", second.get("status") == "ok" and second.get("balance") == 2500.0, second)

print("\n[5] both linked accounts are read, and unknown is not zero")
demo, live = Synthetic("demo"), Synthetic("live")
live.balance = 8000.0
live.positions = [{
    "symbol": "EURUSD", "side": "BUY", "units": 1000, "positionId": 2,
}]

def reader(user_id, kind, ctid, mode):
    broker = demo if mode == "demo" else live
    key = {"balance": "balance", "positions": "positions", "orders": "orders"}[kind]
    call = {"balance": lambda b: b.get_balance(),
            "positions": BR._enrich_positions,
            "orders": lambda b: b.get_pending_orders()}[kind]
    return BR._read(user_id, key, call, ctid=ctid, expected_mode=mode,
                    connection_fn=connection(mode), broker_fn=lambda: broker)

snap = AR.snapshot("user", status_fn=lambda _uid: {
    "connected": True,
    "accounts": [{"ctid": "d1", "mode": "demo"}, {"ctid": "l1", "mode": "live"}],
    "selected": {"ctid": "d1", "mode": "demo"},
}, read_fn=reader)
by_mode = {row["mode"]: row for row in snap["accounts"]}
check("demo and live are both present", set(by_mode) == {"demo", "live"}, snap)
check("demo balance is the demo broker's", by_mode["demo"]["balance"] == 2500.0)
check("demo equity is a number once every position has a p&l",
      isinstance(by_mode["demo"]["equity"], float), by_mode["demo"])
check("live balance is separate", by_mode["live"]["balance"] == 8000.0)
check("live equity is unknown when a position has no p&l",
      by_mode["live"]["equity"] is None, by_mode["live"])
check("live positions were still counted", by_mode["live"]["positions"]["count"] == 1)
live.fault = "auth"
failed = reader("user", "balance", "l1", "live")
check("a live read failure is not a zero balance",
      failed.get("status") == "reauth_required" and "balance" not in failed, failed)

print("\n[6] live selection and trading stay blocked while a read is allowed")
saved = (L.live_allowed, L._read_conn, L.access_token_for)
try:
    L.live_allowed = lambda: False
    L._read_conn = lambda uid: {
        "userId": str(uid),
        "accounts": [{"ctid": 9, "mode": "live"}],
        "needsReconnect": False,
    }
    L.access_token_for = lambda *a, **k: "super-secret-token"
    blocked = False
    try:
        L.get_ctrader_connection("user", ctid=9)
    except L.LinkError as exc:
        blocked = exc.code == "LIVE_BLOCKED"
    check("a trading session to live is refused", blocked)
    opened = L.get_ctrader_connection("user", ctid=9, purpose="read")
    check("a read session may name the live account",
          opened.get("mode") == "live" and opened.get("ctid") == 9, opened)
    try:
        L.select_account("user", 9)
        selected = True
    except L.LinkError as exc:
        selected = exc.code == "LIVE_BLOCKED"
    check("selecting the live account for automation is still refused", selected is True)
finally:
    L.live_allowed, L._read_conn, L.access_token_for = saved

src_loop = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
src_auto = open(os.path.join(ROOT, "apex", "platform", "automation.py"), encoding="utf-8").read()
src_read = open(os.path.join(ROOT, "apex", "platform", "broker_read.py"), encoding="utf-8").read()
check("the trading loop does not ask for a read session", 'purpose="read"' not in src_loop)
check("automation does not ask for a read session", 'purpose="read"' not in src_auto)
check("broker reads do", 'purpose="read"' in src_read)

print("\n[7] desired and actual loop state stay separate")
A._write("dual-user", {"state": A.RUNNING, "userId": "dual-user", "ruleDocId": "r"})
real_alive, real_lic = A._loop_alive, A._licence_active
try:
    A._licence_active = lambda _uid: True
    A._loop_alive = lambda _uid: False
    shown = A.status("dual-user", weekend_reader=lambda: False)
finally:
    A._loop_alive, A._licence_active = real_alive, real_lic
check("the chip says the loop is down", shown["state"] == A.STOPPED, shown.get("state"))
check("the desired state is still running", shown["desiredState"] == A.RUNNING, shown.get("desiredState"))
check("loopActive is false", shown["loopActive"] is False)
check("the stored record was not rewritten",
      A._read("dual-user").get("state") == A.RUNNING)

print("\n[8] journal history is scoped, and a broker filter is not an engine label")
legacy = J.JournalEntry(
    kind=J.ERROR, status=J.BROKER_ERROR, correlation_id="c-legacy", user_id="dual-user",
    account_id="live-1", environment="live",
    error="the engine refused to start this loop because the starter declined")
demo_row = J.JournalEntry(
    kind=J.EVALUATION, status=J.HOLD, correlation_id="c-demo", user_id="dual-user",
    account_id="demo-1", environment="demo", symbol="EURUSD")
real_broker = J.JournalEntry(
    kind=J.ERROR, status=J.BROKER_ERROR, correlation_id="c-broker", user_id="dual-user",
    account_id="live-1", environment="live", error="the broker rejected the order")
JS.append(legacy)
JS.append(demo_row)
JS.append(real_broker)
live_page = JS.query("dual-user", account_id="live-1", environment="live")
check("live history does not include the demo row",
      {e["correlationId"] for e in live_page["entries"]} == {"c-legacy", "c-broker"},
      [e["correlationId"] for e in live_page["entries"]])
check("nothing was deleted", JS.query("dual-user")["total"] == 3)
broker_page = JS.query("dual-user", account_id="live-1", environment="live",
                       status=J.BROKER_ERROR)
check("broker filter keeps the broker rejection",
      [e["correlationId"] for e in broker_page["entries"]] == ["c-broker"],
      broker_page["entries"])
check("broker filter does not return the old engine refusal",
      all(not str(e.get("error") or "").lower().startswith("the engine refused")
          for e in broker_page["entries"]))
engine_page = JS.query("dual-user", status=J.ENGINE_ERROR)
check("engine filter still finds the old refusal",
      [e["correlationId"] for e in engine_page["entries"]] == ["c-legacy"])
stored = JS.get("dual-user", legacy.entry_id)
check("the stored status is still broker_error", stored.get("status") == J.BROKER_ERROR, stored.get("status"))

print("\n[9] risk fails closed")
unknown = RM.build([{"symbol": "EURUSD", "side": "BUY", "units": 1000}], balance=1000)
check("missing stops are not 0% of balance", unknown["riskFraction"] is None, unknown)
check("correlation is unknown, not an empty book", unknown["correlatedPairs"] is None)
known = RM.build([
    {"symbol": "EUR_USD", "side": "BUY", "units": 1000, "riskToStop": 25},
    {"symbol": "GBP_USD", "side": "BUY", "units": 500, "riskToStop": 15},
], balance=1000)
check("a complete book has a fraction", known["riskFraction"] == 0.04, known["riskFraction"])
check("and a correlation", bool(known["correlatedPairs"]))
check("zero balance is unknown", RM.numeric_balance(0) is None)
check("a nested balance is read", RM.numeric_balance({"balance": 40}) == 40)
check("a missing balance is unknown", RM.numeric_balance(None) is None)

print("\n[10] platform_server imports with the Telegram token unset")
env = os.environ.copy()
env["TELEGRAM_BOT_TOKEN"] = ""
env.pop("PORT", None)
script = (
    "import os, threading, urllib.request\n"
    "os.environ['TELEGRAM_BOT_TOKEN'] = ''\n"
    "import platform_server\n"
    "server = platform_server.build_server(0)\n"
    "threading.Thread(target=server.serve_forever, daemon=True).start()\n"
    "port = server.server_address[1]\n"
    "body = urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=5).read()\n"
    "server.shutdown()\n"
    "print(body.decode())\n"
)
proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                      capture_output=True, text=True, timeout=30)
check("the process exited cleanly", proc.returncode == 0, proc.stderr[-500:])
check("health answered", "ok" in proc.stdout.lower(), proc.stdout)

print("\n[11] a caller cannot smuggle a balance into the log")
buf = io.StringIO()
with redirect_stdout(buf):
    RT.record(operation="balance", error_code=None, http_status=200,
              correlation_id="cid", duration_ms=3, balance=2500,
              accessToken="super-secret-token", email="a@b.test",
              account="acct-9001")
leaked = buf.getvalue()
check("extra fields are dropped", "2500" not in leaked and "super-secret-token" not in leaked
      and "a@b.test" not in leaked and "acct-9001" not in leaked, leaked)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for name in _fails:
        print("  -", name)
    sys.exit(1)
print("All dual-account read checks passed.")
