"""Broker authorization failures become a single reconnect state."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="a4t-auth-state-"))
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex.platform import broker_read as BR  # noqa: E402
from apex.platform import ctrader_link as LINK  # noqa: E402

_fails = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


print("\n[1] broker auth refusal is a reconnect state, not an empty read")
marked = []
real_marker = BR._link.mark_reconnect_required
BR._link.mark_reconnect_required = lambda user_id: marked.append(user_id)
try:
    out = BR.positions(
        "user-auth", ctid=501,
        connection_fn=lambda user_id, **kw: {
            "ctid": 501, "mode": "demo", "accessToken": "redacted"},
        broker_fn=lambda: (_ for _ in ()).throw(
            RuntimeError("cTrader error: INVALID_REQUEST Trading account is not authorized")),
    )
finally:
    BR._link.mark_reconnect_required = real_marker
check("the read asks the owner to reconnect", out["status"] == BR.REAUTH_REQUIRED)
check("the marker is written for the requesting user", marked == ["user-auth"], str(marked))
check("the response does not expose the broker error", "INVALID_REQUEST" not in out["reason"])


print("\n[2] reconnect state is written once")
real_read = LINK._read_conn
real_save = LINK._save_link
real_log = LINK._log.event
record = {"userId": "user-state", "accessToken": "encrypted", "needsReconnect": False}
writes = []
LINK._read_conn = lambda user_id: record
LINK._save_link = lambda key, doc, **kw: writes.append((key, dict(doc)))
LINK._log.event = lambda *args, **kwargs: None
try:
    first = LINK.mark_reconnect_required("user-state")
    second = LINK.mark_reconnect_required("user-state")
finally:
    LINK._read_conn = real_read
    LINK._save_link = real_save
    LINK._log.event = real_log
check("the first refusal changes state", first is True)
check("the repeated refusal is quiet", second is False)
check("only one persistence write occurs", len(writes) == 1, str(writes))

# ── which errors count as a lost authorisation ─────────────────────────────
# A match persists "reconnect required", which locks the client out until they
# reconnect. The error seen in production must match; cTrader's generic
# refusals (bad symbol, bad volume, market closed) must NOT.
check("the production refusal is an auth failure",
      BR._is_auth_failure(Exception(
          "cTrader error: INVALID_REQUEST Trading account is not authorized")))
check("an expired token is an auth failure",
      BR._is_auth_failure(Exception("token expired")))
check("a bare INVALID_REQUEST is NOT an auth failure",
      not BR._is_auth_failure(Exception("cTrader error: INVALID_REQUEST bad symbol id")))
check("a volume refusal is NOT an auth failure",
      not BR._is_auth_failure(Exception("INVALID_REQUEST volume below minimum")))
check("a closed market is NOT an auth failure",
      not BR._is_auth_failure(Exception("MARKET_CLOSED the market is closed")))


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for failure in _fails:
        print("  -", failure)
    raise SystemExit(1)
print("All broker authorization-state checks passed.")
