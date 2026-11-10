"""Legacy broker secrets are rewritten before a fail-closed read can see them.

Production refuses a plaintext broker token. The API used to revive trading
loops, and then open its socket, with those tokens still in the clear — so the
first thing a deploy did to a connected account was treat it as disconnected.
The boot path now rewrites user records and platform ``:ctrader:`` records
first.

The rewrite is compare-and-swap, so a token refresh that lands during the
scan is not overwritten with the value we had already read. A second boot
writes nothing. A failure is a count and a type name, and the process still
binds. With no Fernet key the scan does not run and does not touch the
records.

Nothing in the boot line is a token, a ciphertext, a user id, or an account
id. The fixtures below are synthetic and exist to prove that.

Run: python3 tests/test_startup_secret_migration.py
"""
import io
import json
import os
import signal
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

_TMP = tempfile.mkdtemp(prefix="apex-startup-migrate-")
for _name in ("REDIS_URL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(_name, None)
os.environ.update(
    APP_ENV="test",
    ALLOW_LOCAL_BACKEND_DEV="true",
    ALLOW_PLAINTEXT_DEV_STORAGE="true",
    PRODUCT="forex",
    A4T_SKIP_BROKER_PROBE="1",
    A4T_ALLOWED_ORIGIN="https://example.test",
    # SYNTHETIC, generated for the tests. Never a real key.
    TOKEN_ENCRYPTION_KEY="cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI=",
    DATA_DIR=_TMP,
)

import migrate_sensitive_records as mig                       # noqa: E402
import platform_server as ps                                  # noqa: E402
from apex import user_store as us                             # noqa: E402
from apex.platform import store as pstore                     # noqa: E402

_fails = []

# Distinctive on purpose. A boot log that contains any of them has leaked.
USER = "should-not-log-user"
RETRY_USER = "should-not-log-retry"
DEV_USER = "should-not-log-dev"
CRASH_USER = "should-not-log-crash"
TOKEN = "SHOULD-NOT-LOG-TOKEN-access"
REFRESH = "SHOULD-NOT-LOG-TOKEN-refresh"
FINISH = "SHOULD-NOT-LOG-TOKEN-finish"
DEV_TOKEN = "SHOULD-NOT-LOG-TOKEN-dev"
CTID = 4242424242
ACCOUNTS = [{"ctid": CTID, "live": True}]
KEY = f"{pstore.namespace_prefix()}ctrader:{USER}"
DECOY = f"{pstore.namespace_prefix()}note:decoy"
SECRETS = (USER, RETRY_USER, DEV_USER, CRASH_USER, TOKEN, REFRESH, FINISH,
           DEV_TOKEN, str(CTID))


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def secrets_absent(label, text):
    for name, secret in (
        ("user id", USER), ("retry id", RETRY_USER), ("dev id", DEV_USER),
        ("crash id", CRASH_USER), ("access token", TOKEN),
        ("refresh token", REFRESH), ("finish token", FINISH),
        ("dev token", DEV_TOKEN), ("account id", str(CTID)),
        ("ciphertext", "gAAAA"),
    ):
        check(f"{label} does not include the {name}", secret not in text,
              "redacted")


def write_user(user_id, token):
    path = us._path(user_id)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"ctrader_access_token": token,
                   "ctrader_refresh_token": REFRESH,
                   "ctrader_accounts": list(ACCOUNTS),
                   "ctrader_account_id": CTID,
                   "active": False}, fh)
    return path


def platform_record():
    return {
        "userId": USER,
        "accessToken": TOKEN,
        "refreshToken": REFRESH,
        "finishToken": FINISH,
        "ctrader_accounts": list(ACCOUNTS),
        "accounts": [{"ctid": CTID, "mode": "live", "label": "sample"}],
        "selectedCtid": CTID,
        "selectedMode": "live",
    }


def readable(user_id):
    """What a production fail-closed read returns, without printing it."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        loaded = us.load(user_id)
        try:
            rec = pstore._read_strict(KEY)
        except Exception:
            rec = {}
        access = us.decrypt_value((rec or {}).get("accessToken") or "",
                                  fail_closed=True)
        refresh = us.decrypt_value((rec or {}).get("refreshToken") or "",
                                   fail_closed=True)
        finish = us.decrypt_value((rec or {}).get("finishToken") or "",
                                  fail_closed=True)
        wrapped = (rec or {}).get("ctrader_accounts")
        opened = us.decrypt_value(wrapped or "", fail_closed=True) \
            if isinstance(wrapped, str) else ""
    try:
        parsed = json.loads(opened) if opened else None
    except ValueError:
        parsed = None
    return loaded, rec, access, refresh, finish, parsed, buf.getvalue()


# ── 1. the call sits before any read, in the source and not only by luck ──
print("\n[1] startup rewrites secrets before the engine and before serving")
_main = open(os.path.join(ROOT, "platform_server.py"), encoding="utf-8").read()
_main = _main.split("def main(", 1)[1]
_order = [_main.index(token) for token in (
    "_migrate_legacy_secrets()",
    "_start_broker_probe()",
    "_supervise_platform_loops()",
    "_start_forward_watcher()",
    "serve_forever()",
)]
check("migration is before the probe, the engine, the watcher, and the socket",
      _order == sorted(_order), str(_order))
_store_src = open(os.path.join(ROOT, "apex", "platform", "store.py"),
                  encoding="utf-8").read()
check("a platform replace compares the previous bytes before it writes",
      "cur ~= ARGV[1]" in _store_src and "redis.call('SET', KEYS[1], ARGV[2])"
      in _store_src)

# ── 2. compare-and-swap does not clobber a newer value ─────────────────────
print("\n[2] a stale platform write loses to a value that landed first")
_cas = f"{pstore.namespace_prefix()}ctrader:cas-subject"
pstore.write_raw(_cas, json.dumps({"accessToken": "first"}, separators=(",", ":")))
_stale = pstore.read_raw(_cas)
_newer = json.dumps({"accessToken": "newer"}, separators=(",", ":"))
pstore.write_raw(_cas, _newer)
check("a stale expected value is a conflict",
      pstore.replace_if_unchanged(_cas, _stale, '{"accessToken":"enc:stale"}')
      == "conflict")
check("and the newer value is still the one stored",
      pstore.read_raw(_cas) == _newer)
_current = pstore.read_raw(_cas)
_fresh = '{"accessToken":"enc:fresh"}'
check("a current expected value is written",
      pstore.replace_if_unchanged(_cas, _current, _fresh) == "written")
check("the written bytes are the new bytes", pstore.read_raw(_cas) == _fresh)
check("that write then loses to the next reader",
      pstore.replace_if_unchanged(_cas, _current, '{"accessToken":"enc:late"}')
      == "conflict")
check("a missing key is not created",
      pstore.replace_if_unchanged(
          f"{pstore.namespace_prefix()}ctrader:missing", "old", "new")
      == "missing")
os.remove(pstore._local_path(_cas))

# ── 3. a user-record conflict is retried, and the id is not required ──────
print("\n[3] a user-record version conflict is retried")
write_user(RETRY_USER, TOKEN)
_calls = {"n": 0}
_real_save = us.save


def _flaky_save(*args, **kwargs):
    _calls["n"] += 1
    if _calls["n"] == 1:
        raise us.ConflictError("changed during migration")
    return _real_save(*args, **kwargs)


us.save = _flaky_save
try:
    _retry_ok = us.migrate_sensitive_record(RETRY_USER)
finally:
    us.save = _real_save
check("the retried migration reports the record", _retry_ok is True)
check("it called the writer twice", _calls["n"] == 2, str(_calls["n"]))
_retry_raw = open(us._path(RETRY_USER), encoding="utf-8").read()
check("the retried record is encrypted",
      TOKEN not in _retry_raw and "enc:" in _retry_raw)
os.remove(us._path(RETRY_USER))

# ── 4. boot converts both records before either fail-closed read ──────────
print("\n[4] boot migrates the user record and the platform record first")
write_user(USER, TOKEN)
pstore.write_raw(KEY, json.dumps(platform_record(), separators=(",", ":")))
_decoy_body = json.dumps({"accessToken": TOKEN}, separators=(",", ":"))
pstore.write_raw(DECOY, _decoy_body)
us._is_production = lambda: True
_before_user, _before_rec, _before_access, *_rest, _before_log = readable(USER)
check("a production user read refuses the legacy token before migration",
      _before_user.get("ctrader_access_token") == "")
check("a production platform read refuses the legacy token before migration",
      _before_access == "")
check("those refusals do not echo the token or the account id",
      TOKEN not in _before_log and str(CTID) not in _before_log, "redacted")

_events = []


def _engine():
    _events.append("engine")
    _loaded, _rec, _access, _refresh, _finish, _parsed, _log = readable(USER)
    _events.append(_loaded.get("ctrader_access_token") == TOKEN
                   and _loaded.get("ctrader_refresh_token") == REFRESH
                   and _loaded.get("ctrader_accounts") == ACCOUNTS
                   and _access == TOKEN and _refresh == REFRESH
                   and _finish == FINISH and _parsed == ACCOUNTS
                   and isinstance(_rec.get("accounts"), list)
                   and _rec.get("selectedCtid") == CTID)
    _events.append(TOKEN not in _log and str(CTID) not in _log)


class _Server:
    def serve_forever(self):
        _events.append("serve")
        _loaded, _rec, _access, *_rest = readable(USER)
        _events.append(_loaded.get("ctrader_access_token") == TOKEN
                       and _access == TOKEN)

    def server_close(self):
        _events.append("closed")


ps._start_broker_probe = lambda: _events.append("probe")
ps._supervise_platform_loops = _engine
ps._start_forward_watcher = lambda: _events.append("watch")
ps.build_server = lambda port=None: _Server()

_boot = io.StringIO()
with redirect_stdout(_boot):
    ps.main()
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
_boot_log = _boot.getvalue()
_eng = _events.index("engine")
check("the engine read the migrated tokens", _events[_eng + 1] is True,
      str(_events))
check("the engine read did not log the secret", _events[_eng + 2] is True)
check("serving happens after that read", _events.index("serve") > _eng)
check("a request served after boot still sees the token",
      _events[_events.index("serve") + 1] is True)
secrets_absent("the boot log", _boot_log)
check("the boot log reports both migrations",
      "users scanned=" in _boot_log and "platform scanned=" in _boot_log
      and "migrated=" in _boot_log and "failed=0" in _boot_log,
      "redacted")
_user_at_rest = open(us._path(USER), encoding="utf-8").read()
_platform_at_rest = pstore.read_raw(KEY)
check("the user token is no longer stored in the clear",
      TOKEN not in _user_at_rest and REFRESH not in _user_at_rest
      and str(_user_at_rest).count("enc:") >= 3)
check("the platform tokens are no longer stored in the clear",
      TOKEN not in _platform_at_rest and REFRESH not in _platform_at_rest
      and FINISH not in _platform_at_rest)
_stored = json.loads(_platform_at_rest)
check("the account list the product reads stays a list",
      isinstance(_stored.get("accounts"), list)
      and _stored.get("selectedCtid") == CTID)
check("a record that is not a cTrader link is not rewritten",
      pstore.read_raw(DECOY) == _decoy_body)

# ── 5. the second boot writes nothing ──────────────────────────────────────
print("\n[5] a second run is a no-op")
_user_bytes = open(us._path(USER), "rb").read()
_platform_bytes = open(pstore._local_path(KEY), "rb").read()
_second_buf = io.StringIO()
with redirect_stdout(_second_buf):
    _second = mig.run_startup()
_second_log = _second_buf.getvalue()
check("the second run migrates nothing",
      _second["skipped"] is False
      and _second["users"]["migrated"] == 0
      and _second["platform"]["migrated"] == 0
      and _second["users"]["failed"] == 0
      and _second["platform"]["failed"] == 0,
      "counts mismatch")
check("the second run does not rewrite the user record",
      open(us._path(USER), "rb").read() == _user_bytes)
check("the second run does not rewrite the platform record",
      open(pstore._local_path(KEY), "rb").read() == _platform_bytes)
secrets_absent("the second-run log", _second_log)
_again, _, _access_again, *_rest = readable(USER)
check("the token is still readable after the second run",
      _again.get("ctrader_access_token") == TOKEN and _access_again == TOKEN)

# ── 6. one bad record is a count, not a crash and not a log line ──────────
print("\n[6] a record failure is counted and does not leak or rewrite")
_real_one = mig._migrate_one_platform


def _explode(key, attempts=5):
    raise RuntimeError(TOKEN)


mig._migrate_one_platform = _explode
_kept = open(pstore._local_path(KEY), "rb").read()
try:
    _bad_buf = io.StringIO()
    with redirect_stdout(_bad_buf):
        _bad = mig.run_startup()
finally:
    mig._migrate_one_platform = _real_one
check("the scan returns instead of raising",
      _bad["platform"]["failed"] >= 1 and _bad["users"]["failed"] == 0)
check("the already migrated record is left as it was",
      open(pstore._local_path(KEY), "rb").read() == _kept)
secrets_absent("the failure log", _bad_buf.getvalue())

# ── 7. a broken migration does not stop the process, or rewrite on the way ─
print("\n[7] a migration that raises does not stop startup")
_crash_path = write_user(CRASH_USER, TOKEN)
_crash_before = open(_crash_path, "rb").read()
_real_run = mig.run_startup


def _boom():
    raise RuntimeError(TOKEN)


mig.run_startup = _boom
_events.clear()
try:
    _crash_buf = io.StringIO()
    with redirect_stdout(_crash_buf):
        ps.main()
finally:
    mig.run_startup = _real_run
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
_crash_log = _crash_buf.getvalue()
check("the process still reaches serve", "serve" in _events, str(_events))
check("the failure is named by its type",
      "RuntimeError" in _crash_log and "continuing" in _crash_log)
check("the unmigrated record is still the record we wrote",
      open(_crash_path, "rb").read() == _crash_before)
secrets_absent("the crash log", _crash_log)
os.remove(_crash_path)

# ── 8. no key: skip, and do not make the development read worse ───────────
print("\n[8] without an encryption key the migration skips")
_dev_path = write_user(DEV_USER, DEV_TOKEN)
_dev_before = open(_dev_path, "rb").read()
_saved_fernet = us._fernet
us._fernet = None
try:
    _skip_buf = io.StringIO()
    with redirect_stdout(_skip_buf):
        _skip = mig.run_startup()
finally:
    us._fernet = _saved_fernet
check("the scan reports that it skipped", _skip["skipped"] is True)
check("it did not count a failure",
      _skip["users"]["failed"] == 0 and _skip["users"]["migrated"] == 0)
check("it did not rewrite the plaintext record",
      open(_dev_path, "rb").read() == _dev_before)
secrets_absent("the skip log", _skip_buf.getvalue())
us._is_production = lambda: False
_dev_loaded = us.load(DEV_USER)
check("a development read still returns the legacy token",
      _dev_loaded.get("ctrader_access_token") == DEV_TOKEN
      and _dev_loaded.get("ctrader_accounts") == ACCOUNTS)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for _item in _fails:
        print("  -", _item)
    sys.exit(1)
print("startup migration rewrites legacy broker secrets before they are read.")
