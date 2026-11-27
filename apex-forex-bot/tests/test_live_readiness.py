"""Live-readiness additions: consent that expires, a stop that reaches a running
live loop, and proof that the repository's defaults can place nothing live.

NOTHING HERE OPENS LIVE TRADING. Where a test needs the release switch "open"
to reach a gate behind it, it sets the variable in THIS process, for the length
of one block, and puts it back. No file, no default and no deployment setting
is touched, and every block that opens it also asserts the closed answer first.

WHAT IS PROVED

  [1] With the repository defaults, the switch and the live-account flag are
      closed, no deploy/config file in the repo sets either one, the opening
      value exists in exactly one production module, and the live order doors
      refuse without ever asking the broker anything.
  [2] Opening the switch ALONE places nothing: the pilot, the plan and the live
      gate each still refuse by themselves.
  [3] Consent expires. An old, undated or future-dated acceptance does not
      count; accepting again re-affirms it and is audited; withdrawing it is
      audited and closes the order gate on the very next order.
  [4] A stop reaches a RUNNING live loop. Each live condition, flipped on its
      own with the others satisfied, winds the loop down: the loop is stopped,
      the record says BLOCKED with the reason, the supervisor does not revive
      it, and the refusal is audited. Unreadable inputs wind it down too.
      Demo loops are left alone.

Run: python3 tests/test_live_readiness.py
"""
import contextlib
import os
import re
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-livereadiness-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
for _banned in ("A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS",
                "A4T_LIVE_PILOT_PAIRS", "A4T_LIVE_PILOT_SYMBOLS",
                "A4T_LIVE_PILOT_MAX_UNITS", "A4T_EMERGENCY_HALT",
                "PAPER_TRADING"):
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
    """An in-memory shared backend: the ledger, the audit trail and the order
    rate all refuse to run without one, correctly."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        for name in ("set_blob_nx", "set_blob", "get_blob", "get_blob_strict",
                     "del_blob", "claim", "claim_value", "release_claim",
                     "incr"):
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

from apex import user_loop                               # noqa: E402
from apex.platform import audit as AUD                   # noqa: E402
from apex.platform import automation as AU               # noqa: E402
from apex.platform import ctrader_link as CL             # noqa: E402
from apex.platform import emergency as EM                # noqa: E402
from apex.platform import entitlement as E               # noqa: E402
from apex.platform import live_execution as LX           # noqa: E402
from apex.platform import live_gate as LG                # noqa: E402
from apex.platform import store as ST                    # noqa: E402

OPERATOR = "operator-1"


@contextlib.contextmanager
def env(**values):
    """Set process environment for one block, then restore it exactly."""
    saved = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def patched(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def satisfy(user, *, now=None):
    """Every live-gate condition met, through the real operator/client paths."""
    for doc in LG.DOCUMENTS:
        LG.publish(doc, "v1", actor=OPERATOR)
    LG.accept_current(user, now=now)
    LG.grant_operator_licence(user, actor=OPERATOR)
    LG.request_live(user)
    LG.decide(user, "approved", actor=OPERATOR, reason="reviewed")


def verdict(user, *, now=None, switch=True, accounts=True):
    return LG.public_verdict(user, release_switch=switch,
                             live_accounts_allowed=accounts, now=now)


def missing_codes(v):
    return [c["code"] for c in v["missing"]]


# ════════════════════════════════════════════════════════════════════════════
print("\n[1] with the repository defaults, nothing live can be selected or placed")

check("the release switch is closed", E.live_execution_enabled() is False)
check("live accounts may not be selected", CL.live_allowed() is False)
check("the emergency halt variable is not set either",
      EM.state()["envScope"] == EM.NONE)

# --- no deploy or config file in the repository opens either switch ---------
_SCAN_NAMES = ("A4T_LIVE_EXECUTION", "APEX_ALLOW_LIVE_ACCOUNTS")
_SKIP_DIRS = {"node_modules", ".git", ".next", "__pycache__", ".venv",
              "venv", "dist", "build"}


def _config_files():
    """Deploy and environment files that could set a variable for a service."""
    out = []
    for dirpath, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, REPO)
        for fn in files:
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            low = fn.lower()
            if (low.startswith(".env") or low.endswith(".env")
                    or low in ("render.yaml", "render.yml")
                    or low.startswith("dockerfile")
                    or low.startswith("docker-compose")
                    or low.endswith(".sh")
                    or rel.startswith(os.path.join(".github", "workflows"))
                    or rel.startswith("config" + os.sep)
                    or (rel.startswith(os.path.join("docs", "deploy"))
                        and low.endswith((".yaml", ".yml", ".json")))):
                out.append(os.path.join(dirpath, fn))
    return out


_files = _config_files()
check("the scan is not vacuous: render.yaml is among the files read",
      any(os.path.basename(p) == "render.yaml" for p in _files),
      f"{len(_files)} files")
check("and the deploy workflows are", any(
    os.sep + os.path.join(".github", "workflows") + os.sep in p
    for p in _files))
_offenders = []
for _p in _files:
    try:
        text = open(_p, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    for _n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue                    # a comment cannot set anything
        if any(name in line for name in _SCAN_NAMES) \
                or E.LIVE_SWITCH_ON in line:
            _offenders.append(f"{os.path.relpath(_p, REPO)}:{_n}")
check("no deploy or environment file sets either live variable "
      "(comments aside)", not _offenders, ", ".join(_offenders))

# --- the opening value exists in one production module ----------------------
_holders = []
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and d != "tests"]
    for fn in files:
        if fn.endswith(".py"):
            full = os.path.join(dirpath, fn)
            if E.LIVE_SWITCH_ON in open(full, encoding="utf-8",
                                        errors="replace").read():
                _holders.append(os.path.relpath(full, ROOT))
check("the opening value appears in exactly one production module",
      _holders == [os.path.join("apex", "platform", "entitlement.py")],
      str(_holders))

# --- the doors refuse, and never reach the broker ----------------------------
_asked = []


def _mode_reader():
    _asked.append("mode")
    return "live"


def _broker(req):
    _asked.append("broker")
    return {"ok": True, "positionId": "p1"}


r = LX.authorize_order("someone", symbol="EURUSD", side="BUY", units=1000,
                       account_id="9001", mode_reader=_mode_reader)
check("authorize_order refuses at the release switch",
      r["allowed"] is False and r["code"] == LX.LIVE_NOT_ENABLED, str(r))
check("and did not even ask the broker for the mode", _asked == [], str(_asked))

r = LX.place({}, None, None, user_id="someone", account_id="9001",
             balance_reader=lambda: _asked.append("balance") or 1000.0,
             mode_reader=_mode_reader, broker=_broker)
check("place() refuses at the release switch",
      r["placed"] is False and r["code"] == LX.LIVE_NOT_ENABLED, str(r))
check("and neither the broker, the mode nor the balance was read",
      _asked == [], str(_asked))

check("guard_engine_order has no platform opinion on a non-platform account "
      "and so adds nothing that could open one",
      LX.guard_engine_order("not-a-platform-user", symbol="EURUSD",
                            side="BUY", units=1000) is None)

# A live account cannot be selected under the defaults.
CL_USER = "link-user-1"
_conn = {"accounts": [{"ctid": "9001", "mode": "live"},
                      {"ctid": "9002", "mode": "demo"}],
         "selectedCtid": "9002", "selectedMode": "demo"}
with patched(CL, _read_conn=lambda uid: dict(_conn)):
    try:
        CL.select_account(CL_USER, "9001")
        refused = None
    except CL.LinkError as e:
        refused = e.code
    except Exception as e:                                   # noqa: BLE001
        refused = f"other:{type(e).__name__}"
check("selecting a live account is refused (LIVE_BLOCKED)",
      refused == "LIVE_BLOCKED", str(refused))

# And a live loop on repo defaults is not a loop the platform leaves running.
check("a running live loop would be wound down at the release switch",
      AU.live_wind_down_reason("someone", {"accountId": "9001"})[0]
      == "LIVE_NOT_ENABLED")

# ════════════════════════════════════════════════════════════════════════════
print("\n[2] opening the switch alone places nothing")
with env(A4T_LIVE_EXECUTION=E.LIVE_SWITCH_ON):
    check("(the switch is open inside this block only)",
          E.live_execution_enabled() is True)
    _asked.clear()
    r = LX.authorize_order("someone", symbol="EURUSD", side="BUY",
                           units=1000, account_id="9001",
                           mode_reader=_mode_reader)
    check("a client without the plan is refused behind the switch",
          r["allowed"] is False and r["code"] == LX.NOT_ENTITLED, str(r))
    check("and the broker was still not asked", _asked == [], str(_asked))

    entitled = "entitled-no-gate"
    LG.grant_operator_licence(entitled, actor=OPERATOR)
    with patched(CL, live_allowed=lambda: True):
        r = LX.authorize_order(entitled, symbol="EURUSD", side="BUY",
                               units=1000, account_id="9001",
                               mode_reader=_mode_reader)
    check("a paid client with no accepted terms or approval is refused by "
          "the live gate", r["allowed"] is False
          and r["code"] == "LIVE_GATE_CLOSED", str(r))
    check("the broker was not asked", _asked == [], str(_asked))

    full = "entitled-and-gated"
    satisfy(full)
    with patched(CL, live_allowed=lambda: True):
        r = LX.authorize_order(full, symbol="EURUSD", side="BUY", units=1000,
                               account_id="9001", mode_reader=_mode_reader)
    check("a fully entitled and approved client is STILL refused while the "
          "pilot is unconfigured", r["allowed"] is False
          and r["code"] == "PILOT_UNCONFIGURED", str(r))
    check("and the broker was not asked", _asked == [], str(_asked))
check("(the switch is closed again)", E.live_execution_enabled() is False)

# ════════════════════════════════════════════════════════════════════════════
print("\n[3] consent expires, can be re-affirmed, and can be withdrawn")
T0 = 1_800_000_000.0
AGE = LG.CONSENT_MAX_AGE_S
check("the maximum age is a bounded number of days, not unlimited",
      0 < AGE <= 365 * 86400, str(AGE))

C1 = "consent-user-1"
satisfy(C1, now=T0)
v = verdict(C1, now=T0 + 10)
check("a fresh acceptance counts", v["open"] is True, str(missing_codes(v)))
v = verdict(C1, now=T0 + AGE)
check("on the last permitted second it still counts", v["open"] is True,
      str(missing_codes(v)))
v = verdict(C1, now=T0 + AGE + 1)
check("one second later every document is no longer accepted",
      sorted(missing_codes(v)) == ["LEGAL_TERMS_ACCEPTED",
                                    "REFUND_TERMS_ACCEPTED",
                                    "TAX_TERMS_ACCEPTED"], str(missing_codes(v)))
check("the gate is closed, not unknown", v["status"] == "closed"
      and v["open"] is False, v["status"])
check("and the client is told what to do",
      any("Accept again" in c["detail"] for c in v["missing"]))
with env(A4T_LIVE_EXECUTION=None):
    check("(expiry is judged the same with the switch closed)",
          verdict(C1, now=T0 + AGE + 1, switch=False)["open"] is False)

before = len(AUD.query(C1, kind=AUD.CONSENT))
LG.accept_current(C1, now=T0 + 5)
check("accepting again inside the window changes nothing",
      len(AUD.query(C1, kind=AUD.CONSENT)) == before)
LG.accept_current(C1, now=T0 + AGE + 1)
rows = AUD.query(C1, kind=AUD.CONSENT)
check("re-accepting after expiry is audited for each document",
      len(rows) == before + 3, f"{before} -> {len(rows)}")
check("and the new acceptance counts",
      verdict(C1, now=T0 + AGE + 2)["open"] is True)
check("the re-affirmation is dated now, not at the first acceptance",
      ST._read_strict(LG._key(f"accept:{C1}"))["terms"]["acceptedAt"]
      == T0 + AGE + 1)

# an acceptance that cannot be dated, or is dated in the future, is not consent
for label, entry in (
        ("with no date", {"version": "v1"}),
        ("with a date that is not a number",
         {"version": "v1", "acceptedAt": "yesterday"}),
        ("dated in the future",
         {"version": "v1", "acceptedAt": T0 + 10 * 86400})):
    rec = {d: dict(entry) for d in LG.DOCUMENTS}
    ST._write_strict(LG._key("accept:odd-user"), rec)
    v = LG.public_verdict("odd-user", release_switch=True,
                          live_accounts_allowed=True, now=T0)
    check(f"an acceptance {label} does not count",
          "LEGAL_TERMS_ACCEPTED" in missing_codes(v), str(missing_codes(v)))

# withdrawal
C2 = "consent-user-2"
satisfy(C2, now=T0)
check("(before withdrawal the gate is open)",
      verdict(C2, now=T0 + 1)["open"] is True)
LG.withdraw_consent(C2)
rows = [r for r in AUD.query(C2, kind=AUD.CONSENT) if r["granted"] is False]
check("a withdrawal is audited for each document, with the version",
      sorted(r["document"] for r in rows) == ["refund", "tax", "terms"]
      and all(r["documentVersion"] == "v1" for r in rows), str(rows))
check("and the actor is the client", all(r["actor"] == C2 for r in rows))
v = verdict(C2, now=T0 + 1)
check("the gate is closed after a withdrawal",
      v["open"] is False and "LEGAL_TERMS_ACCEPTED" in missing_codes(v))
check("withdrawing again is harmless",
      LG.withdraw_consent(C2) == {})
check("the audit chain is still intact", AUD.verify(C2)["ok"] is True,
      str(AUD.verify(C2)))

# through the HTTP route: no body is read, and it cannot name another user
class _P:
    def __init__(self, uid):
        self.user_id = uid


satisfy("consent-user-3", now=T0)
status, payload = LG.http("POST", "live/withdraw", _P("consent-user-3"),
                          {"userId": "consent-user-1"})
check("the route withdraws the caller's own consent", status == 200,
      str(payload)[:160])
check("and a body naming someone else changed nothing for them",
      verdict("consent-user-1", now=T0 + AGE + 2)["open"] is True)

# consent withdrawn reaches the ORDER door, with the switch simulated open
C4 = "consent-user-4"
satisfy(C4)
with env(A4T_LIVE_EXECUTION=E.LIVE_SWITCH_ON,
         A4T_LIVE_PILOT_PAIRS=f"{C4}:9001",
         A4T_LIVE_PILOT_SYMBOLS="EURUSD",
         A4T_LIVE_PILOT_MAX_UNITS="10000000"), \
        patched(CL, live_allowed=lambda: True):
    _asked.clear()
    r = LX.authorize_order(C4, symbol="EURUSD", side="BUY", units=1000,
                           account_id="9001", mode_reader=_mode_reader)
    check("(control) with every condition met the live gates allow the order",
          r["allowed"] is True, str(r))
    LG.withdraw_consent(C4)
    r = LX.authorize_order(C4, symbol="EURUSD", side="BUY", units=1000,
                           account_id="9001", mode_reader=_mode_reader)
    check("after withdrawal the very next order is refused by the live gate",
          r["allowed"] is False and r["code"] == "LIVE_GATE_CLOSED", str(r))
    LG.accept_current(C4)
    r = LX.authorize_order(C4, symbol="EURUSD", side="BUY", units=1000,
                           account_id="9001", mode_reader=_mode_reader)
    check("and accepting again reopens exactly that condition",
          r["allowed"] is True, str(r))

# ════════════════════════════════════════════════════════════════════════════
print("\n[4] a stop reaches a RUNNING live loop")
W = "winddown-user-1"
ACCT = "9001"
satisfy(W)

PILOT = dict(A4T_LIVE_PILOT_PAIRS=f"{W}:{ACCT}",
             A4T_LIVE_PILOT_SYMBOLS="EURUSD",
             A4T_LIVE_PILOT_MAX_UNITS="10000000")
RULE = {"symbols": ["EURUSD"]}
live_rec = {"state": AU.RUNNING, "ruleDocId": "r1", "mode": "live",
            "accountId": ACCT}

_stopped = []
_started = []
_selected = {"v": ACCT}
_running = {"v": True}


def _selected_ctid(uid):
    v = _selected["v"]
    if isinstance(v, Exception):
        raise v
    return v


def _stopper(uid):
    _stopped.append(str(uid))
    return True


def _start(uid, rid, **kw):
    _started.append((str(uid), rid))


def reset_loop(rec=None):
    _stopped.clear()
    _started.clear()
    _selected["v"] = ACCT
    _running["v"] = True
    AU._write(W, dict(rec or live_rec))


def live_open():
    """The switch open, in this process only, and the live-account flag
    answered yes for the duration of a block."""
    stack = contextlib.ExitStack()
    stack.enter_context(env(A4T_LIVE_EXECUTION=E.LIVE_SWITCH_ON, **PILOT))
    stack.enter_context(patched(
        CL, live_allowed=lambda: True, selected_ctid=_selected_ctid,
        is_platform_account=lambda uid: str(uid) == W))
    stack.enter_context(patched(AU._store, get=lambda u, r: dict(RULE)))
    stack.enter_context(patched(
        user_store, all_active=lambda: [W]))
    stack.enter_context(patched(
        user_loop, is_running=lambda uid: _running["v"]))
    stack.enter_context(patched(AU, start=_start))
    stack.enter_context(patched(
        user_store, update=lambda uid, patch: None))
    return stack


def sweep():
    return AU.supervise(stopper=_stopper)


# --- control: with every condition met, the loop is left alone --------------
with live_open():
    reset_loop()
    check("(control) every live condition holds, so there is no reason to stop",
          AU.live_wind_down_reason(W, live_rec) is None,
          str(AU.live_wind_down_reason(W, live_rec)))
    alive, revived = sweep()
    check("(control) the supervisor leaves the healthy live loop running",
          alive == 1 and not _stopped and AU._read(W)["state"] == AU.RUNNING,
          f"alive={alive} stopped={_stopped} state={AU._read(W)['state']}")


def expect_wind_down(label, code, *, mutate):
    """Flip ONE condition inside an otherwise satisfied setup."""
    with live_open():
        reset_loop()
        undo = mutate()
        try:
            reason = AU.live_wind_down_reason(W, live_rec)
            check(f"{label}: the reason is named",
                  reason is not None and reason[0] == code, str(reason))
            before = len(AUD.query(W, kind=AUD.REFUSAL))
            alive, revived = sweep()
            rec = AU._read(W)
            check(f"{label}: the loop is stopped", bool(_stopped)
                  and set(_stopped) == {W},
                  str(_stopped))
            check(f"{label}: the record says BLOCKED with the code",
                  rec.get("state") == AU.BLOCKED
                  and rec.get("blockCode") == code, str(rec))
            check(f"{label}: and with a sentence a client can read",
                  code in str(rec.get("blockReason")))
            check(f"{label}: nothing was restarted", _started == [] and
                  revived == 0, f"{_started} {revived}")
            rows = AUD.query(W, kind=AUD.REFUSAL)
            check(f"{label}: the wind-down is audited with its gate and code",
                  len(rows) == before + 1
                  and rows[-1]["gate"] == "live_wind_down"
                  and rows[-1]["code"] == code, str(rows[-1:]))
            _stopped.clear()
            sweep()
            check(f"{label}: a later pass does not revive or re-stop it",
                  _stopped == [] and _started == [], f"{_stopped} {_started}")
        finally:
            if undo:
                undo()


def _env_set(name, value):
    old = os.environ.get(name)
    os.environ[name] = value

    def undo():
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old
    return undo


expect_wind_down("the release switch is closed", "LIVE_NOT_ENABLED",
                 mutate=lambda: _env_set("A4T_LIVE_EXECUTION", "false"))
expect_wind_down("a global halt", "HALTED_ALL",
                 mutate=lambda: _env_set("A4T_EMERGENCY_HALT", "all"))
expect_wind_down("a live-scoped halt", "HALTED_LIVE",
                 mutate=lambda: _env_set("A4T_EMERGENCY_HALT", "live"))


def _store_client_halt():
    EM.halt(EM.NONE, reason="drill", by="operator-1", users=[W])
    return lambda: EM.release(by="operator-1")


expect_wind_down("a per-client halt", "HALTED_CLIENT",
                 mutate=_store_client_halt)


def _store_instrument_halt():
    EM.halt(EM.NONE, reason="drill", by="operator-1",
            instruments=["EUR_USD"])
    return lambda: EM.release(by="operator-1")


expect_wind_down("a per-instrument halt on the rule's instrument",
                 "HALTED_INSTRUMENT", mutate=_store_instrument_halt)


def _withdraw():
    LG.withdraw_consent(W)

    def undo():
        LG.accept_current(W)
    return undo


expect_wind_down("the client withdraws consent", "LIVE_GATE_CLOSED",
                 mutate=_withdraw)


def _revoke_plan():
    from apex.platform import licence as _lic
    _lic.revoke(W)
    return lambda: LG.grant_operator_licence(W, actor=OPERATOR)


def _account_changed():
    _selected["v"] = "9002"


def _disconnected():
    _selected["v"] = None


def _selected_unreadable():
    _selected["v"] = RuntimeError("store down")


expect_wind_down("the selected account changed", "ACCOUNT_CHANGED",
                 mutate=lambda: _account_changed())
expect_wind_down("the account was disconnected", "PLATFORM_DISCONNECTED",
                 mutate=lambda: _disconnected())
expect_wind_down("the selected account cannot be read (uncertainty)",
                 "ACCOUNT_UNREADABLE", mutate=lambda: _selected_unreadable())
expect_wind_down("the pilot no longer lists this account", "NOT_PILOT_ACCOUNT",
                 mutate=lambda: _env_set("A4T_LIVE_PILOT_PAIRS",
                                         "someone-else:1"))
expect_wind_down("the pilot is unconfigured", "PILOT_UNCONFIGURED",
                 mutate=lambda: _env_set("A4T_LIVE_PILOT_SYMBOLS", ""))


def _store_unreadable():
    saved = EM._read_record

    def boom():
        raise user_store.StoreUnavailable("down")
    EM._read_record = boom
    return lambda: setattr(EM, "_read_record", saved)


expect_wind_down("the emergency store cannot be read (uncertainty)",
                 "HALTED_UNCERTAIN", mutate=_store_unreadable)

with live_open():
    reset_loop()
    with patched(AU._store, get=lambda u, r: (_ for _ in ()).throw(
            RuntimeError("rule store down"))):
        reason = AU.live_wind_down_reason(W, live_rec)
    check("an unreadable running rule is uncertainty, and winds the loop down",
          reason is not None and reason[0] == "RULE_UNREADABLE", str(reason))

with live_open():
    reset_loop()
    with patched(AU, live_wind_down_reason=lambda *_a, **_k: 1 / 0):
        sweep()
    check("a crash in the check itself also winds a live loop down",
          AU._read(W).get("blockCode") == "LIVE_CHECK_FAILED",
          str(AU._read(W)))

# --- demo loops are not this function's business ----------------------------
with live_open():
    reset_loop({"state": AU.RUNNING, "ruleDocId": "r1", "mode": "demo",
                "accountId": ACCT})
    with env(A4T_LIVE_EXECUTION=None):
        alive, _ = sweep()
    check("a RUNNING demo loop is left alone even with the switch closed",
          _stopped == [] and alive == 1
          and AU._read(W)["state"] == AU.RUNNING,
          f"{_stopped} {AU._read(W)}")

# --- a failed stop is loud and does not pretend ------------------------------
with live_open():
    reset_loop()

    def _failing_stopper(uid):
        raise RuntimeError("cannot reach the loop")
    with env(A4T_LIVE_EXECUTION=None):
        AU.supervise(stopper=_failing_stopper)
    check("if the stop itself fails the record is NOT reported as blocked",
          AU._read(W).get("state") == AU.RUNNING, str(AU._read(W)))

# --- the wind-down does not close positions, and says so ---------------------
_told = []
with live_open():
    reset_loop()
    with env(A4T_LIVE_EXECUTION=None), patched(
            AU._notify, notify=lambda uid, **kw: _told.append(kw)):
        sweep()
check("the client is told the loop was stopped and why",
      any("Live automation stopped" == n.get("title")
          and "LIVE_NOT_ENABLED" in n.get("body", "") for n in _told),
      str(_told))
check("and told in the same message that open positions were NOT closed",
      any("does not close positions" in n.get("body", "") for n in _told),
      str(_told))

# ── done ────────────────────────────────────────────────────────────────────
if _fails:
    print(f"\nFAILED ({len(_fails)}):")
    for f in _fails:
        print(f"  - {f}")
    sys.exit(1)
print("\nALL PASSED")
