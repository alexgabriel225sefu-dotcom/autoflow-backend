"""The cTrader demo smoke script — its refusals, not its happy path.

WHAT IS ACTUALLY BEING TESTED

The script's job is to talk to a real broker account, which means the only
parts a test can meaningfully cover are the parts that stop it: the guards
that refuse to start, the refusal to touch anything that is not a demo
account, the promise that no token reaches the output, and the fact that it
calls read-only endpoints in a fixed order and no others.

The happy path needs cTrader, and pretending otherwise by asserting against
stubs and calling it verified is exactly the thing this product does not do.
A stubbed run IS used here — to pin the call sequence — and it proves the
sequence, not the integration.

Run: python3 tests/test_smoke_harness.py
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-smoke-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import smoke_ctrader_demo as S                  # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def refusal(env):
    try:
        S.guard(env)
        return None
    except S.Refused as e:
        return str(e)


BASE = {"SMOKE_CONFIRM_DEMO_ONLY": "yes", "SMOKE_USER_ID": "u-1",
        "TOKEN_ENCRYPTION_KEY": "a-key-that-is-long-enough"}

# ── 1. it refuses to start without an explicit statement ────────────────────
print("\n[1] it will not start on a guess")
msg = refusal({k: v for k, v in BASE.items() if k != "SMOKE_CONFIRM_DEMO_ONLY"})
check("no confirmation -> refused", msg is not None)
check("and the refusal names the variable to set",
      msg and "SMOKE_CONFIRM_DEMO_ONLY" in msg, str(msg))
check("and says why it is asking", msg and "DEMO" in msg, str(msg))

for wrong in ("", "no", "maybe", "1", "demo", "YES please"):
    check(f"{wrong!r} is not a confirmation",
          refusal(dict(BASE, SMOKE_CONFIRM_DEMO_ONLY=wrong)) is not None, wrong)
for right in ("yes", "YES", "Yes", "true", "y"):
    check(f"{right!r} is accepted",
          refusal(dict(BASE, SMOKE_CONFIRM_DEMO_ONLY=right)) is None, right)

# ── 2. every other missing prerequisite is named ────────────────────────────
print("\n[2] each missing prerequisite refuses, and says which")
for var in ("SMOKE_USER_ID", "TOKEN_ENCRYPTION_KEY"):
    m = refusal({k: v for k, v in BASE.items() if k != var})
    check(f"missing {var} -> refused", m is not None)
    check(f"and {var} is named in the refusal", m and var in m, str(m))
check("with everything set, it does not refuse", refusal(dict(BASE)) is None)

# ── 3. it refuses a release that could place a live order ───────────────────
# If live execution ever becomes real, "read-only by construction" stops being
# something this script can claim, and it must stop rather than assume.
print("\n[3] it refuses a release whose live path is enabled")
_real = S._ent.live_execution_enabled
S._ent.live_execution_enabled = lambda: True
try:
    m = refusal(dict(BASE))
    check("live execution enabled -> refused", m is not None)
    check("and it says that is the reason", m and "live execution" in m, str(m))
finally:
    S._ent.live_execution_enabled = _real

# ── 4. it refuses anything that is not the selected DEMO account ────────────
print("\n[4] the platform's own record has to agree that this is demo")


def status(**kw):
    return lambda _uid: kw


try:
    S.demo_only("u-1", status_fn=status(connected=False))
    check("not connected -> refused", False, "it proceeded")
except S.Refused as e:
    check("not connected -> refused", "connect one first" in str(e), str(e))

try:
    S.demo_only("u-1", status_fn=status(connected=True, selected=None))
    check("connected but nothing selected -> refused", False, "it proceeded")
except S.Refused as e:
    check("connected but nothing selected -> refused",
          "none is selected" in str(e), str(e))

try:
    S.demo_only("u-1", status_fn=status(
        connected=True, selected={"ctid": 902, "mode": "live"}))
    check("a LIVE selected account -> refused", False, "IT PROCEEDED")
except S.Refused as e:
    check("a LIVE selected account -> refused", "not 'demo'" in str(e), str(e))
    check("and it says the environment does not override that",
          "whatever the environment says" in str(e), str(e))

sel = S.demo_only("u-1", status_fn=status(
    connected=True, selected={"ctid": 501, "mode": "demo"}))
check("a demo account proceeds", sel["ctid"] == 501)

chosen = S.select_for_smoke(
    "u-1", "501",
    selector=lambda uid, ctid: {"selected": {"ctid": ctid, "mode": "demo"}})
check("an explicit smoke ctid is selected through the link layer",
      chosen["selected"]["ctid"] == "501", str(chosen))
check("a missing explicit ctid does not select anything",
      S.select_for_smoke("u-1", "", selector=lambda *_: {"selected": {}})
      is None)
try:
    S.select_for_smoke(
        "u-1", "501",
        selector=lambda uid, ctid: {"selected": {"ctid": "999",
                                                "mode": "demo"}})
    check("a selection mismatch refuses", False, "it proceeded")
except S.Refused as e:
    check("a selection mismatch refuses",
          "did not become the selected account" in str(e), str(e))
try:
    S.select_for_smoke(
        "u-1", "501",
        selector=lambda uid, ctid: {"selected": {"ctid": "501",
                                                "mode": "live"}})
    check("selecting live through the smoke script refuses", False,
          "it proceeded")
except S.Refused as e:
    check("selecting live through the smoke script refuses",
          "not 'demo'" in str(e), str(e))

# ── 5. nothing token-shaped reaches the output ──────────────────────────────
print("\n[5] no token, no key, no account number in full")
os.environ["CTRADER_ACCESS_TOKEN_SMOKE"] = "SUPER-SECRET-ACCESS-TOKEN-1234"
buf = io.StringIO()
rep = S.Report(out=buf)
# A real Fernet token's length, because the shape that masks it is bounded —
# a 16-character lookalike is deliberately left alone, and a test that used
# one would be asserting the wrong thing.
FERNET = ("gAAAAABm" + "QkZha2VUb2tlblZhbHVlRm9yVGVzdGluZw"
          "ZmFrZS1jaXBoZXJ0ZXh0LWJvZHktaGVyZQ")
rep.say(f"token is SUPER-SECRET-ACCESS-TOKEN-1234 and a key is {FERNET}")
rep.step("a step whose detail leaked a token", False,
         "failed with SUPER-SECRET-ACCESS-TOKEN-1234")
printed = buf.getvalue()
check("the env-held token is masked",
      "SUPER-SECRET-ACCESS-TOKEN-1234" not in printed, printed[:80])
check("a Fernet-shaped value is masked too", FERNET not in printed,
      printed[:120])
check("but the step name survives, or the report is useless",
      "a step whose detail leaked a token" in printed)
del os.environ["CTRADER_ACCESS_TOKEN_SMOKE"]

check("an account number is masked to its last three digits",
      S.mask_ctid(1234567) == "…567", S.mask_ctid(1234567))
check("a short one is left alone rather than mangled",
      S.mask_ctid(12) == "12", S.mask_ctid(12))
check("and None does not crash it", S.mask_ctid(None) == "")

# ── 6. the sequence is read-only, fixed, and in order ───────────────────────
print("\n[6] it calls exactly the read-only sequence, in order")
called = []


def rec(name, payload):
    def fn(*a, **kw):
        called.append(name)
        return payload
    return fn


bars = [{"time": i, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05}
        for i in range(10)]

# The four broker reads are NOT hand-written dicts. A hand-written stub can
# carry keys the real reader never emits, and that is precisely how a step
# asserting a currency on the balance passed here and then failed against the
# broker: broker_read.account() has no currency in its contract, and only the
# stub did. It can also skip validation the real reader performs, which is how
# a default timeframe in cTrader's notation reached a live run. So these
# payloads come out of broker_read itself, driven by a fake broker, and the
# shape the script is asserted against is the shape a deployment answers with.
from apex.platform import broker_read as BR                  # noqa: E402


class FakeBroker:
    """Exactly the four read methods broker_read is allowed to call."""

    def get_balance(self):
        return 10_000.0

    def get_all_positions(self):
        return []

    def get_pending_orders(self):
        return []

    def get_candles(self, symbol, timeframe, limit):
        return bars


def _conn(user_id, ctid=None):
    return {"ctid": 4762501, "mode": "demo"}


_FAKE = {"connection_fn": _conn, "broker_fn": FakeBroker}


def via(name, fn):
    """Like rec(), but the payload is whatever the real reader answers."""
    def call(*a, **kw):
        called.append(name)
        return fn(*a, **kw)
    return call


readers = {
    "accounts": rec("accounts", {"connected": True,
                                 "selected": {"ctid": 4762501, "mode": "demo"}}),
    "capability": rec("capability", {"canAutomate": True, "badge": "DEMO",
                                     "liveExecutionEnabled": False,
                                     "message": "ok"}),
    "balance": via("balance", lambda uid, **kw: BR.account(uid, **_FAKE)),
    "positions": via("positions",
                     lambda uid, **kw: BR.positions(uid, **_FAKE)),
    "orders": via("orders", lambda uid, **kw: BR.orders(uid, **_FAKE)),
    # Forwarded, so the script's own symbol and timeframe defaults go through
    # validate_candle_query rather than past it.
    "candles": via("candles",
                   lambda uid, **kw: BR.candles(uid, **dict(kw, **_FAKE))),
}
os.environ.pop("SMOKE_SYMBOL", None)
os.environ.pop("SMOKE_TIMEFRAME", None)
out = io.StringIO()
rep = S.run("u-1", report=S.Report(out=out), readers=readers)
check("every step passed against the stub", rep.failures == [], str(rep.failures))
check("the sequence is exactly the declared one",
      tuple(called) == S.SEQUENCE, f"{called} vs {list(S.SEQUENCE)}")
check("and the declared sequence contains nothing that writes",
      not ({"start", "stop", "place", "close", "amend", "select", "connect",
            "disconnect"} & set(S.SEQUENCE)), str(S.SEQUENCE))
check("the masked account number is in the report",
      "…501" in out.getvalue(), out.getvalue()[:120])
check("and the full one is nowhere in it",
      "4762501" not in out.getvalue(), out.getvalue()[:120])

# A failing read must be reported as a failure, not smoothed into a pass.
called.clear()
readers2 = dict(readers, candles=rec("candles", {"status": "unavailable",
                                                 "reason": "broker timed out"}))
rep2 = S.run("u-1", report=S.Report(out=io.StringIO()), readers=readers2)
check("an unavailable read fails the run rather than passing quietly",
      "candles read ok" in rep2.failures, str(rep2.failures))

# ── the defaults must be ones broker_read will actually accept ──────────────
# SMOKE_TIMEFRAME defaulted to cTrader's own "M15", which
# validate_candle_query rejects by design. Against the broker the run died on
# a traceback before it read a single bar, and no hand-written stub could have
# caught it, because a stub validates nothing.
seen = {}


def _capture(uid, **kw):
    seen.update(kw)
    return {"status": "ok", "candles": bars}


S.run("u-1", report=S.Report(out=io.StringIO()),
      readers=dict(readers, candles=_capture))
try:
    BR.validate_candle_query(seen.get("symbol"), seen.get("timeframe"),
                             seen.get("limit"))
    check("the default symbol and timeframe pass broker_read's validator",
          True, f"{seen.get('symbol')} {seen.get('timeframe')}")
except ValueError as e:
    check("the default symbol and timeframe pass broker_read's validator",
          False, str(e))

# ── a reader that raises fails its step; it does not abort the run ──────────
# A traceback out of run() takes every later step with it, so one bad default
# reads as a total unknown instead of one failed step.
def _boom(*a, **kw):
    raise ValueError("timeframe must be one of 1m, 5m, 15m, got 'M15'")


buf3 = io.StringIO()
rep3 = S.run("u-1", report=S.Report(out=buf3),
             readers=dict(readers, candles=_boom))
check("a reader that raises fails its step instead of aborting the run",
      "candles read ok" in rep3.failures, str(rep3.failures))
check("and the steps before it are still reported",
      "balance reads ok" in [n for n, _ in rep3.steps],
      str([n for n, _ in rep3.steps]))
check("and the exception type reaches the report",
      "ValueError" in buf3.getvalue(), buf3.getvalue()[-160:])

# The answer must come back as None and not as an empty dict. An empty dict
# would be evaluated by the dependent steps, and "an empty list is a FACT"
# reads as a PASS against one — a step passing on a read that never happened.
rep4 = S.run("u-1", report=S.Report(out=io.StringIO()),
             readers=dict(readers, positions=_boom))
check("and the steps that depended on it are skipped, not passed on a guess",
      [n for n, _ in rep4.steps if n.startswith("and an empty list")] == [],
      str([n for n, _ in rep4.steps]))

# ── a balance is a number, because a dashboard formats it ───────────────────
check("a float is a balance", S._is_number(10.0))
check("and a whole number is too", S._is_number(10))
check("a string that looks like one is not", not S._is_number("10.0"))
check("and True is not a balance, whatever isinstance says",
      not S._is_number(True))

rep5 = S.run("u-1", report=S.Report(out=io.StringIO()),
             readers=dict(readers, balance=lambda uid, **kw: {
                 "connected": True, "status": "ok", "balance": "10000.00"}))
check("a balance that arrives as a string fails the run",
      "and the balance is a number, not a string or a None" in rep5.failures,
      str(rep5.failures))

# ── 7. it contains no execution path at all ─────────────────────────────────
# A comment promising this is worth nothing; the file is read instead.
print("\n[7] the script cannot place, close or amend anything")
src = open(os.path.join(ROOT, "scripts", "smoke_ctrader_demo.py"),
           encoding="utf-8").read()
for forbidden in ("place_order", "close_position", "amend_sltp", "force_trade",
                  "authorize_order", "authorize_close"):
    check(f"it never calls {forbidden}", f"{forbidden}(" not in src)
for module in ("bridge", "execution", "gates", "automation"):
    check(f"it imports nothing from {module}",
          f"import {module}" not in src and f"platform import {module}" not in src)
check("it does not import the broker directly either",
      "from apex.brokers" not in src)
check("the optional selection uses ctrader_link, not the broker",
      "_link.select_account" in src)
# `str.index` raises when the needle is gone, which aborts the whole file and
# skips every check below it — a crash is not a test result. This reports a
# clean failure instead, and says which half was missing.
def _before(first, second):
    """True when `first` appears, `second` appears, and first comes first."""
    a, b = src.find(first), src.find(second)
    if a < 0 or b < 0:
        missing = first if a < 0 else second
        check(f"the file still contains {missing!r}, which an ordering "
              f"check needs", False, "it was removed or renamed")
        return False
    return a < b


check("redaction is installed before any platform import",
      _before("redact.install()", "from apex.platform"))

# ── the refusal must name the variable the operator actually needs ───────────
# apex.platform.store refuses at import time without TOKEN_ENCRYPTION_KEY — it
# fails closed by design. So when the guards ran only inside main(), an operator
# who had merely forgotten SMOKE_CONFIRM_DEMO_ONLY got told about
# TOKEN_ENCRYPTION_KEY instead: safe, but it names the wrong variable, and a
# script that misdirects gets run again with a guess. The env-only guards
# therefore run before the imports, and that order is asserted here rather than
# left to whoever next tidies the import block.
check("the env-only guard is defined before apex is imported",
      _before("def guard_env(", "from apex import redact"))
check("and it runs before apex is imported, when run as a script",
      _before("guard_env()", "from apex import redact"))
check("guard() still delegates to it, so both paths refuse identically",
      "guard_env(env)" in src)

# Run as a real subprocess with a stripped environment: importing the module
# cannot show this, because the test preamble has already set the variables.
_ORDER = (
    ({}, "SMOKE_CONFIRM_DEMO_ONLY"),
    ({"SMOKE_CONFIRM_DEMO_ONLY": "yes"}, "SMOKE_USER_ID"),
    ({"SMOKE_CONFIRM_DEMO_ONLY": "yes", "SMOKE_USER_ID": "1000000001"},
     "TOKEN_ENCRYPTION_KEY"),
)
for _extra, _expected in _ORDER:
    _env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    _env.update(_extra)
    _p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "smoke_ctrader_demo.py")],
        capture_output=True, text=True, env=_env, timeout=120)
    _first = (_p.stdout or _p.stderr).strip().splitlines()
    _first = _first[0] if _first else ""
    check(f"with {sorted(_extra) or 'nothing'} set, it names {_expected}",
          _expected in _first and "REFUSED" in _first, _first[:100])
    check(f"and exits 2 (refused), not 1 (a step failed): {_expected}",
          _p.returncode == 2, f"exit {_p.returncode}")

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All smoke-harness checks passed.")
