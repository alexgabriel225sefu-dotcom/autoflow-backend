"""Honesty and safety remediations: copy, redaction, stop, journal reads, limits.

Run: python3 tests/test_platform_honesty_and_safety.py
"""
import inspect
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-honesty-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["RATE_LIMIT_STORE"] = "memory"

from apex import user_loop as UL                             # noqa: E402
from apex import user_store as US                            # noqa: E402
from apex.platform import automation as AU                   # noqa: E402
from apex.platform import broker_read as BR                  # noqa: E402
from apex.platform import engine_config as EC                # noqa: E402
from apex.platform import journal as J                       # noqa: E402
from apex.platform import journal_store as JS                # noqa: E402
from apex.platform import ratelimit as RL                    # noqa: E402
from apex.platform import store as ST                        # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── 1. engine_config honesty ────────────────────────────────────────────────
print("\n[1] flatten miss, empty daily cap, schedule miss only for presets")
applied, missed = EC.translate({"limits": {"onLimit": "flatten"}})
by_term = {m["term"]: m for m in missed}
check("flatten is reported as not applied", "On limit" in by_term, str(by_term))
check("flatten value is flatten",
      by_term.get("On limit", {}).get("value") == "flatten",
      str(by_term.get("On limit")))
check("flatten why says it is not executed",
      "not executed" in str(by_term.get("On limit", {}).get("why", "")),
      str(by_term.get("On limit")))

applied, _ = EC.translate({"limits": {}})
check("empty maxDailyTrades writes 0 (unlimited)",
      applied.get("max_trades_day") == 0, str(applied.get("max_trades_day")))
applied, _ = EC.translate({})
check("missing limits writes max_trades_day 0",
      applied.get("max_trades_day") == 0, str(applied.get("max_trades_day")))
applied, _ = EC.translate({"limits": {"maxDailyTrades": 4}})
check("numeric maxDailyTrades is written as int",
      applied.get("max_trades_day") == 4
      and isinstance(applied.get("max_trades_day"), int),
      str(applied.get("max_trades_day")))

sched = {"days": [0, 1], "windows": [{"from": "07:00", "to": "16:00"}]}
_, missed = EC.translate({"schedule": sched})
check("a condition-rule schedule is not a miss",
      "Schedule" not in {m["term"] for m in missed},
      str([m["term"] for m in missed]))

real_preset = EC._preset_strategy
EC._preset_strategy = lambda doc: "trend"
try:
    _, missed = EC.translate({"strategy": "trend", "schedule": sched})
    check("a preset with days/windows misses Schedule",
          "Schedule" in {m["term"] for m in missed},
          str([m["term"] for m in missed]))
    _, missed = EC.translate({"strategy": "trend"})
    check("a preset without a schedule does not miss Schedule",
          "Schedule" not in {m["term"] for m in missed},
          str([m["term"] for m in missed]))
finally:
    EC._preset_strategy = real_preset


# ── 2. journal error redaction ──────────────────────────────────────────────
print("\n[2] journal errors go through safe_errors")
poison = "broker failed at https://evil.example/v2 connect 8.8.8.8:443"
entry = J.for_error(poison, correlation_id="corr-1", user_id="u1")
check("for_error redacts the URL",
      "https://" not in str(entry.error) and "evil.example" not in str(entry.error),
      str(entry.error))
check("for_error redacts the IP",
      "8.8.8.8" not in str(entry.error), str(entry.error))
direct = J.JournalEntry(kind=J.ERROR, correlation_id="corr-2", user_id="u1",
                        error=poison)
check("constructor sanitizes on the way in",
      "https://" not in str(direct.error) and "8.8.8.8" not in str(direct.error),
      str(direct.error))
src = inspect.getsource(J.JournalEntry.__init__)
check("constructor calls safe_errors.message",
      "safe_errors.message" in src)


# ── 3. broker_read._scrub ───────────────────────────────────────────────────
print("\n[3] broker_read._scrub uses safe_errors.message")
got = BR._scrub("connect 10.1.2.3 failed https://api.broker.test/v1")
check("IP is gone", "10.1.2.3" not in got, got)
check("URL is gone",
      "https://" not in got and "api.broker.test" not in got, got)
check("_scrub source calls message",
      "safe_errors.message" in inspect.getsource(BR._scrub))


# ── 4. approve after Stop ───────────────────────────────────────────────────
print("\n[4] force_trade refuses approval after Stop, not every origin")
ft = inspect.getsource(UL.force_trade)
place = ft.find("broker.place_order")
stop_origin = ft.find('origin == "approval"')
stop_fn = ft.find("_stop_requested")
check("approval + _stop_requested is in force_trade",
      stop_origin != -1 and stop_fn != -1)
check("that check is after authorize and before place_order",
      0 < stop_origin < place and 0 < stop_fn < place,
      f"approval@{stop_origin} stop@{stop_fn} place@{place}")
check("force_trade does not require active is True for all origins",
      "active is True" not in ft)


# ── 5. journal MGET / _read_many ────────────────────────────────────────────
print("\n[5] get_blobs and _read_many raise rather than shrinking an ok page")
check("get_blobs([]) is []", US.get_blobs([]) == [])
try:
    US.get_blobs(["missing-key"])
    check("get_blobs without redis raises StoreUnavailable", False)
except US.StoreUnavailable:
    check("get_blobs without redis raises StoreUnavailable", True)

check("_read_many([]) is []", ST._read_many([]) == [])
check("a missing local key decodes as None",
      ST._read_many(["no-such-honesty-key"]) == [None])
ST._write("honesty-present", {"ok": True})
check("_read_many decodes a present key",
      ST._read_many(["honesty-present"]) == [{"ok": True}])

real_exists = ST.os.path.exists

def _disk_fail(_p):
    raise OSError("disk")

ST.os.path.exists = _disk_fail
try:
    ST._read_many(["honesty-io"])
    check("file IO error raises StoreUnavailable", False)
except US.StoreUnavailable:
    check("file IO error raises StoreUnavailable", True)
finally:
    ST.os.path.exists = real_exists

qsrc = inspect.getsource(JS.query)
check("query loads the page via _read_many", "_read_many" in qsrc)

ST._write(JS._k_index("honesty-u"), [{"id": "e1", "ts": 1.0}])
real_many = ST._read_many

def _store_down(_keys):
    raise US.StoreUnavailable("down")

ST._read_many = _store_down
try:
    JS.query("honesty-u")
    check("query does not return a shorter ok page on store failure", False)
except US.StoreUnavailable:
    check("query lets StoreUnavailable propagate", True)
finally:
    ST._read_many = real_many


# ── 6. rate limit ───────────────────────────────────────────────────────────
print("\n[6] approvals POST is control; GET is default")
check("POST approvals/approve -> control",
      RL.classify("POST", "approvals/approve") == "control")
check("POST approvals/reject -> control",
      RL.classify("POST", "approvals/reject") == "control")
check("GET approvals -> default",
      RL.classify("GET", "approvals") == "default")


# ── 7. automation start copy uses the real mode ─────────────────────────────
print("\n[7] automation start strings use conn mode, not hardcoded demo")
start_src = inspect.getsource(AU.start)
check("journal detail uses _mode",
      'detail=f"{_mode} account' in start_src, start_src[start_src.find("detail="):start_src.find("detail=")+80] if "detail=" in start_src else "")
check("notify body uses _mode",
      "on {_mode}" in start_src)
check("journal detail is not hardcoded demo",
      'detail=f"demo account' not in start_src)
check("notify body is not hardcoded on demo",
      "on demo " not in start_src)


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All honesty-and-safety checks passed.")
