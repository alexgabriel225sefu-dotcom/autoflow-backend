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

# ── the preview step, against the REAL evaluator and a REAL rule doc ────────
# This step had never been exercised at all, and it could not have passed:
# it read `verdict` off the top level of preview()'s answer (it lives on
# `decision`), it compared against a "SETUP" that has never been a verdict in
# this product, and it sent no `ts` — which build_snapshot refuses on purpose
# rather than reading the clock. Three of the same mistake as the currency
# step. So it is driven here through apex.platform.preview itself, with a rule
# doc the real validator accepts and bars in the shape broker_read emits.
from apex.platform import decision as PD                     # noqa: E402
from apex.platform import ruledoc as PRD                     # noqa: E402
from apex.platform import store as PS                        # noqa: E402

# ruledoc.blank() rather than a dict written here, so the document has every
# field the UI would give it and the validator is answering about a real shape.
RULE = dict(PRD.blank(user_id="u-1", account_id="ct-demo-1",
                      symbols=["EUR_USD"], timeframe="15m"),
            name="smoke rule", sides="BUY",
            entry={"combine": "AND", "conditions": [
                {"id": "rsi", "params": {"op": "below", "value": 30}}]},
            exit={"combine": "OR", "conditions": [
                {"id": "rsi", "params": {"op": "above", "value": 70}}]})
_rule = PS.create("u-1", RULE)
_rid = _rule["ruleDocId"]
PS.activate("u-1", _rid)

# FALLING closes, deliberately. RSI(14) then reads 0, the entry condition
# passes and the verdict is BUY — a verdict that is in decision.VERDICTS and is
# NOT in the ("SETUP", "HOLD", "REJECT") tuple the step used to check against.
# Rising bars would give HOLD, which that broken tuple also contains, and the
# check would pass while still being wrong. Five keys per bar, the same five
# broker_read._shape() narrows a bar down to.
_real_bars = [{"time": 1790700000 + i * 900, "open": 1.10 - i * 0.001,
               "high": 1.101 - i * 0.001, "low": 1.099 - i * 0.001,
               "close": 1.1005 - i * 0.001} for i in range(60)]


def _with_bars(bars):
    return dict(readers, candles=via("candles", lambda uid, **kw: {
        "status": "ok", "candles": bars}))


buf6 = io.StringIO()
rep6 = S.run("u-1", report=S.Report(out=buf6),
             readers=_with_bars(_real_bars), rule_id=_rid)
_names6 = [n for n, _ in rep6.steps]
check("the preview step runs the real evaluator on real-shaped bars",
      "preview runs on real bars" in _names6, str(_names6))
check("and it passes, so the payload satisfies build_snapshot",
      "preview runs on real bars" not in rep6.failures,
      buf6.getvalue()[-300:])
check("and the verdict is an entry, which only a real evaluator produces",
      "BUY" in buf6.getvalue(), buf6.getvalue()[-200:])
check("and the verdict is explained",
      "and the verdict is explained, not asserted" not in rep6.failures,
      str(rep6.failures))
check("and a preview is never executable",
      "and the preview is reported as unexecutable" not in rep6.failures,
      str(rep6.failures))
check("SETUP is not and never was a verdict", "SETUP" not in PD.VERDICTS,
      str(PD.VERDICTS))

# ── a step that did not run must say so, and must reach the summary ─────────
# The first clean run of this script exited 0 with twelve steps. The thirteenth
# — preview on real bars — had not failed; it had never run, because the
# account had no rule to preview. Nothing in the output said so, and `exit 0`
# with a step missing is indistinguishable from `exit 0` with every step
# passing unless somebody compares step counts between runs. X1 is closed on
# this script's exit code.
buf_skip = io.StringIO()
rep_skip = S.run("u-1", report=S.Report(out=buf_skip),
                 readers=_with_bars(_real_bars))        # no rule_id at all
check("with no rule, the preview step is recorded as skipped",
      [n for n, _ in rep_skip.skipped] == ["preview runs on real bars"],
      str(rep_skip.skipped))
check("and it is NOT counted as a passed step",
      "preview runs on real bars" not in [n for n, _ in rep_skip.steps],
      str([n for n, _ in rep_skip.steps]))
check("and it is NOT a failure either, because nothing went wrong",
      rep_skip.failures == [], str(rep_skip.failures))
check("and the word SKIP appears in the report",
      "SKIP" in buf_skip.getvalue(), buf_skip.getvalue()[-200:])

# The summary is what an operator actually reads before recording a pass, so
# the skip has to survive all the way into it. summarise() exists separately
# from main() precisely so this can be checked without a broker.
rc = S.summarise(rep_skip)
sum_out = buf_skip.getvalue()
check("a run with a skipped step still exits 0, because nothing failed",
      rc == 0, str(rc))
check("but the summary says it was not a complete pass",
      "not a complete pass" in sum_out, sum_out[-400:])
tail = sum_out.split("not a complete pass")[-1]
check("and the summary names the step that did not run",
      "preview runs on real bars" in tail, tail[:300])
check("and tells the operator to record the skip, not just the pass",
      "Record what was SKIPPED" in tail, tail[:300])

# A clean run with nothing skipped must NOT carry that warning, or the warning
# becomes noise that gets ignored on the run where it matters.
clean = io.StringIO()
rep_clean = S.run("u-1", report=S.Report(out=clean),
                  readers=_with_bars(_real_bars), rule_id=_rid)
rc_clean = S.summarise(rep_clean)
check("a complete run exits 0 with no skip warning",
      rc_clean == 0 and "not a complete pass" not in clean.getvalue(),
      f"rc={rc_clean}")
check("and it does carry the preview step, so the two runs differ",
      "preview runs on real bars" in [n for n, _ in rep_clean.steps],
      str([n for n, _ in rep_clean.steps]))

# ── the payload's symbol and timeframe must be the ones the bars came from ──
# Dropping either lets build_snapshot fall back to the RULE's own symbol and
# timeframe, and the evaluator then compares the rule against itself and always
# agrees — so a rule written for GBPUSD 1h would be evaluated on EURUSD 15m
# bars and answer BUY, with nothing anywhere saying the instrument was wrong.
# evaluator.py rejects a mismatch on purpose (lines 219 and 222); these two
# rules exist so that refusal is reachable, because a rule that matches the
# bars cannot tell the two behaviours apart.
def _rule_on(symbols, timeframe):
    doc = PS.create("u-1", dict(
        PRD.blank(user_id="u-1", account_id="ct-demo-1", symbols=symbols,
                  timeframe=timeframe),
        name=f"mismatch {symbols[0]} {timeframe}", sides="BUY",
        entry={"combine": "AND", "conditions": [
            {"id": "rsi", "params": {"op": "below", "value": 30}}]},
        exit={"combine": "OR", "conditions": [
            {"id": "rsi", "params": {"op": "above", "value": 70}}]}))
    PS.activate("u-1", doc["ruleDocId"])
    return doc["ruleDocId"]


_other_symbol = _rule_on(["GBP_USD"], "15m")
buf9 = io.StringIO()
S.run("u-1", report=S.Report(out=buf9), readers=_with_bars(_real_bars),
      symbol="EURUSD", timeframe="15m", rule_id=_other_symbol)
check("EURUSD bars against a GBPUSD rule are refused, not evaluated",
      "not one of this rule's instruments" in buf9.getvalue(),
      buf9.getvalue()[-220:])

_other_tf = _rule_on(["EUR_USD"], "1h")
buf10 = io.StringIO()
S.run("u-1", report=S.Report(out=buf10), readers=_with_bars(_real_bars),
      symbol="EURUSD", timeframe="15m", rule_id=_other_tf)
check("15m bars against a 1h rule are refused, not evaluated",
      "rule runs on 1h" in buf10.getvalue(), buf10.getvalue()[-220:])

# The two negative cases below DO stub preview, and that is the point: they
# test whether the step's assertion is sensitive, not what the module returns.
# The positive case above is the real module; these ask "if the answer were
# wrong, would this step notice?" — which no amount of real data can show,
# because the real module never answers wrongly.
_real_preview = S._preview


class _FixedPreview:
    def __init__(self, answer):
        self._answer = answer

    def preview(self, rule_doc, payload):
        return self._answer


S._preview = _FixedPreview(
    {"status": "ok", "executable": True,
     "decision": {"verdict": "HOLD", "reason": "why",
                  "conditions": [{"id": "rsi", "passed": False}]}})
rep7 = S.run("u-1", report=S.Report(out=io.StringIO()),
             readers=_with_bars(_real_bars), rule_id=_rid)
check("a preview that calls itself executable fails the run",
      "and the preview is reported as unexecutable" in rep7.failures,
      str(rep7.failures))

S._preview = _FixedPreview(
    {"status": "ok", "executable": False, "decision": {"verdict": "HOLD"}})
rep8 = S.run("u-1", report=S.Report(out=io.StringIO()),
             readers=_with_bars(_real_bars), rule_id=_rid)
check("a verdict with neither conditions nor a reason fails the run",
      "and the verdict is explained, not asserted" in rep8.failures,
      str(rep8.failures))

S._preview = _real_preview
check("the real preview module is put back",
      S._preview is _real_preview)

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
    _env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
    }
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
# ── 8. the CONTROLS script: it acts, so it has the opposite contract ────────
# scripts/smoke_ctrader_demo.py is read-only and section 7 walks its source to
# keep it that way. The controls script is the other half of X1 gate 1 — start,
# pause, resume and stop are the only part of the platform that CHANGES
# something at the broker — so it necessarily imports automation. Two scripts,
# two opposite contracts, both asserted, because a single file could not hold
# both and the read script's guarantee is worth more than the convenience.
print("\n[8] the controls script acts, and always stops what it started")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import smoke_ctrader_controls as C                  # noqa: E402

csrc = open(os.path.join(ROOT, "scripts", "smoke_ctrader_controls.py"),
            encoding="utf-8").read()

check("it does import automation, unlike the read-only script",
      "from apex.platform import automation" in csrc)
check("but it still places no order itself",
      not any(f"{t}(" in csrc for t in ("place_order", "close_position",
                                        "amend_sltp", "submit")))
check("redaction is installed before any platform import",
      csrc.find("redact.install()") < csrc.find("from apex.platform"))
check("the declared sequence is the four controls plus their idempotency",
      C.SEQUENCE == ("status", "start", "start_again", "pause", "resume",
                     "stop", "stop_again"), str(C.SEQUENCE))

# ── it refuses on both confirmations, separately ────────────────────────────
# One variable covering both would let an operator who meant "this is a demo
# account" also grant "you may trade on it".
BASE_C = {"SMOKE_CONFIRM_DEMO_ONLY": "yes",
          "SMOKE_CONFIRM_START_AUTOMATION": "yes",
          "SMOKE_USER_ID": "u-1", "SMOKE_RULE_ID": "r-1",
          "TOKEN_ENCRYPTION_KEY": "a-key-that-is-long-enough"}


def crefusal(env):
    try:
        C.guard_env(env)
        return None
    except C.Refused as e:
        return str(e)


check("it refuses without the demo confirmation",
      "SMOKE_CONFIRM_DEMO_ONLY" in (crefusal(
          dict(BASE_C, SMOKE_CONFIRM_DEMO_ONLY="")) or ""),
      str(crefusal(dict(BASE_C, SMOKE_CONFIRM_DEMO_ONLY=""))))
check("and separately without the start-automation confirmation",
      "SMOKE_CONFIRM_START_AUTOMATION" in (crefusal(
          dict(BASE_C, SMOKE_CONFIRM_START_AUTOMATION="")) or ""),
      str(crefusal(dict(BASE_C, SMOKE_CONFIRM_START_AUTOMATION=""))))
check("and the start refusal says a position may be opened",
      "OPEN A DEMO" in (crefusal(
          dict(BASE_C, SMOKE_CONFIRM_START_AUTOMATION="")) or ""))
check("it refuses without a rule, because start would refuse anyway",
      "SMOKE_RULE_ID" in (crefusal(dict(BASE_C, SMOKE_RULE_ID="")) or ""),
      str(crefusal(dict(BASE_C, SMOKE_RULE_ID=""))))
check("the demo confirmation alone is not enough",
      crefusal({"SMOKE_CONFIRM_DEMO_ONLY": "yes"}) is not None)

# ── the sequence, against fake controls that record what was called ─────────
ccalled = []


def fake_controls(fail_at=None):
    """The five control functions, recording order. `fail_at` raises on one."""
    state = {"state": "stopped", "ruleDocId": None, "mode": None}

    def status(uid):
        ccalled.append("status")
        return dict(state)

    def start(uid, rid, **kw):
        ccalled.append("start")
        if fail_at == "start":
            raise RuntimeError("engine refused")
        if state["state"] == "running" and state["ruleDocId"] == rid:
            return dict(state, started=False, alreadyRunning=True)
        state.update({"state": "running", "ruleDocId": rid, "mode": "demo"})
        return dict(state, started=True, alreadyRunning=False)

    def pause(uid, **kw):
        ccalled.append("pause")
        if fail_at == "pause":
            raise RuntimeError("could not halt")
        state["state"] = "paused"
        return dict(state, paused=True)

    def resume(uid, **kw):
        ccalled.append("resume")
        state["state"] = "running"
        return dict(state, started=True, alreadyRunning=False)

    def stop(uid, **kw):
        ccalled.append("stop")
        already = state["state"] == "stopped"
        state.update({"state": "stopped", "ruleDocId": None, "mode": None})
        return dict(state, stopped=not already, alreadyStopped=already)

    return {"status": status, "start": start, "pause": pause,
            "resume": resume, "stop": stop}, state


# The journal is real here; an empty one must fail the journal step rather than
# pass it, so the step is asserted to be the ONLY failure.
cbuf = io.StringIO()
ctrl, cstate = fake_controls()
ccalled.clear()
crep = C.run("u-1", "r-1", report=C.Report(out=cbuf), controls=ctrl)
check("start, the idempotent second start, pause, resume and stop all ran",
      ccalled == ["status", "start", "start", "pause", "resume", "stop",
                  "stop", "status"], str(ccalled))
check("and the account is left stopped", cstate["state"] == "stopped",
      cstate["state"])
check("and every step but the journal passed",
      crep.failures == ["the journal records the controls"],
      str(crep.failures))

# ── THE PROPERTY THAT MATTERS: a failure must not leave a loop running ──────
# A smoke test that gives up halfway and leaves automation running is worse
# than no smoke test, because the operator reads a failure and not a warning.
cbuf2 = io.StringIO()
ctrl2, cstate2 = fake_controls(fail_at="pause")
ccalled.clear()
crep2 = C.run("u-1", "r-1", report=C.Report(out=cbuf2), controls=ctrl2)
check("when a control fails, stop still runs", "stop" in ccalled, str(ccalled))
check("and the account is still left stopped", cstate2["state"] == "stopped",
      cstate2["state"])
check("and the failure is reported", "pause is accepted" in crep2.failures,
      str(crep2.failures))

# Even when the very first start raises: nothing was started, but stop must be
# attempted anyway, because "nothing was started" is a belief and the record is
# the only evidence.
cbuf3 = io.StringIO()
ctrl3, cstate3 = fake_controls(fail_at="start")
ccalled.clear()
crep3 = C.run("u-1", "r-1", report=C.Report(out=cbuf3), controls=ctrl3)
check("a start that raises still reaches the stop", "stop" in ccalled,
      str(ccalled))
check("and it is reported as a failed step, not a traceback",
      "start is accepted" in crep3.failures, str(crep3.failures))

# ── a stop that cannot stop must shout ─────────────────────────────────────
def stuck_controls():
    def status(uid):
        return {"state": "running", "ruleDocId": "r-1", "mode": "demo"}

    def start(uid, rid, **kw):
        return {"state": "running", "ruleDocId": rid, "mode": "demo",
                "started": True, "alreadyRunning": False}

    def pause(uid, **kw):
        return {"state": "paused", "ruleDocId": "r-1", "paused": True}

    def resume(uid, **kw):
        return {"state": "running", "ruleDocId": "r-1"}

    def stop(uid, **kw):
        return {"state": "running", "ruleDocId": "r-1", "stopped": False,
                "alreadyStopped": False}
    return {"status": status, "start": start, "pause": pause,
            "resume": resume, "stop": stop}


cbuf4 = io.StringIO()
crep4 = C.run("u-1", "r-1", report=C.Report(out=cbuf4),
              controls=stuck_controls())
check("a stop that does not stop fails the run",
      "and the account is left with nothing running" in crep4.failures,
      str(crep4.failures))
check("and it tells the operator to go and stop it from the dashboard",
      "COULD NOT STOP IT" in cbuf4.getvalue(), cbuf4.getvalue()[-200:])
check("and that run cannot exit 0",
      C.summarise(crep4) == 1, str(C.summarise(crep4)))

# ── malformed control responses must still reach the stop ──────────────────
# _attempt catches Exception, so raised failures become ordinary failed steps.
# The other dangerous case is a control answering with the wrong SHAPE. That
# used to raise at `.get(...)`; the smoke harness must record the bad shape
# while continuing through stop and final status, because the whole point is to
# avoid leaving a loop running after a bad control response.
def shape_liar():
    calls = []

    def status(uid):
        calls.append("status")
        return "running"            # not a dict

    def nop(*a, **kw):
        calls.append("other")
        return {"state": "stopped", "alreadyStopped": True}
    return {"status": status, "start": nop, "pause": nop, "resume": nop,
            "stop": nop}, calls


cbuf6 = io.StringIO()
sl, slcalls = shape_liar()
crep6 = C.run("u-1", "r-1", report=C.Report(out=cbuf6), controls=sl)
check("a control answering with the wrong shape still reaches the stop",
      "other" in slcalls, str(slcalls))
check("and the operator sees the stop attempt in the report",
      "stop is accepted" in cbuf6.getvalue(), cbuf6.getvalue()[-200:])
check("and the wrong status shape fails the run instead of crashing",
      "automation starts from stopped" in crep6.failures, str(crep6.failures))

# A malformed stop response used to be worse: it raised inside `finally`,
# skipped the second stop and skipped the final status check. A bad first stop
# must be a failed smoke result, not the end of cleanup.
def bad_stop_shape_controls():
    calls = []
    state = {"state": "stopped", "ruleDocId": None, "mode": None}

    def status(uid):
        calls.append("status")
        return dict(state)

    def start(uid, rid, **kw):
        calls.append("start")
        if state["state"] == "running":
            return dict(state, started=False, alreadyRunning=True)
        state.update({"state": "running", "ruleDocId": rid, "mode": "demo"})
        return dict(state, started=True, alreadyRunning=False)

    def pause(uid, **kw):
        calls.append("pause")
        state["state"] = "paused"
        return dict(state, paused=True)

    def resume(uid, **kw):
        calls.append("resume")
        state["state"] = "running"
        return dict(state)

    def stop(uid, **kw):
        calls.append("stop")
        if calls.count("stop") == 1:
            return "stopped"
        already = state["state"] == "stopped"
        state.update({"state": "stopped", "ruleDocId": None, "mode": None})
        return dict(state, stopped=not already, alreadyStopped=already)

    return {"status": status, "start": start, "pause": pause,
            "resume": resume, "stop": stop}, calls, state


cbuf8 = io.StringIO()
bad_stop, bad_stop_calls, bad_stop_state = bad_stop_shape_controls()
crep8 = C.run("u-1", "r-1", report=C.Report(out=cbuf8), controls=bad_stop)
check("a malformed first stop response still reaches the second stop",
      bad_stop_calls.count("stop") == 2, str(bad_stop_calls))
check("and it still checks final status after the malformed stop",
      bad_stop_calls[-1] == "status", str(bad_stop_calls))
check("and the loop is left stopped after the retry",
      bad_stop_state["state"] == "stopped", str(bad_stop_state))
check("and the malformed stop response fails the run",
      "stop is accepted" in crep8.failures, str(crep8.failures))


def bad_final_status_controls():
    ctrl, state = fake_controls()
    calls = []

    def wrap(name, fn):
        def inner(*a, **kw):
            calls.append(name)
            if name == "status" and calls.count("status") == 2:
                return "stopped"
            return fn(*a, **kw)
        return inner

    return {name: wrap(name, fn) for name, fn in ctrl.items()}, calls, state


cbuf9 = io.StringIO()
bad_status, bad_status_calls, bad_status_state = bad_final_status_controls()
crep9 = C.run("u-1", "r-1", report=C.Report(out=cbuf9),
              controls=bad_status)
check("a malformed final status is reported instead of crashing",
      "and the account is left with nothing running" in crep9.failures,
      str(crep9.failures))
check("and it happens after stop already left the loop stopped",
      bad_status_state["state"] == "stopped", str(bad_status_state))

# ── controls that LIE about idempotency must fail the run ───────────────────
# The honest fakes above never exercise these assertions, because they answer
# correctly. The dangerous case is a second start that really did start a
# second loop against one account and says so, and a stop that calls an
# already-stopped account newly stopped.
def lying_controls():
    def status(uid):
        return {"state": "stopped", "ruleDocId": None, "mode": None}

    def start(uid, rid, **kw):
        # Claims a fresh start EVERY time: a second loop on one account.
        return {"state": "running", "ruleDocId": rid, "mode": "demo",
                "started": True, "alreadyRunning": False}

    def pause(uid, **kw):
        return {"state": "paused", "ruleDocId": "r-1", "paused": True}

    def resume(uid, **kw):
        return {"state": "running", "ruleDocId": "r-1"}

    def stop(uid, **kw):
        return {"state": "stopped", "ruleDocId": None, "stopped": True,
                "alreadyStopped": False}
    return {"status": status, "start": start, "pause": pause,
            "resume": resume, "stop": stop}


crep7 = C.run("u-1", "r-1", report=C.Report(out=io.StringIO()),
              controls=lying_controls())
check("a second start that claims to be a fresh start fails the run",
      "a second start is idempotent, not a second loop" in crep7.failures,
      str(crep7.failures))
check("and a stop that calls an already-stopped account newly stopped fails",
      "stopping something stopped is fine" in crep7.failures,
      str(crep7.failures))

# ── the summary refuses to bless a failed run ─────────────────────────────
cbuf5 = io.StringIO()
crep5 = C.Report(out=cbuf5)
crep5.step("something", True)
check("a clean controls run exits 0", C.summarise(crep5) == 0)
check("and says automation is stopped",
      "automation is stopped" in cbuf5.getvalue(), cbuf5.getvalue()[-200:])

if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All smoke-harness checks passed.")
