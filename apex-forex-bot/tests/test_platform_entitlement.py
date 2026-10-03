"""Free demo access, paid live access, and the release that has neither path.

THE MATRIX THIS EXISTS FOR

Two entitlements times two account modes is four combinations, and three of
them refuse. The one that is easy to get wrong is `paid_live` + a LIVE
account, because it is the combination that will one day be allowed and is
not allowed now. A test that only covers the free tier would let somebody
"fix" that case by deleting a check.

So all four are asserted here, and the live ones are asserted in the only
environment where a live account can even be selected — otherwise the refusal
under test would be the environment's, not the entitlement's, and the thing
this file claims to prove would be untested.

Run: python3 tests/test_platform_entitlement.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-ent-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/api/v1/ctrader/callback"
# A real key: the OAuth state is signed with material derived from it.
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from apex.platform import automation as AU       # noqa: E402
from apex.platform import ctrader_link as CL     # noqa: E402
from apex.platform import entitlement as E       # noqa: E402
from apex.platform import licence as L           # noqa: E402
from apex.platform import ruledoc as RD          # noqa: E402
from apex.platform import store as ST            # noqa: E402

USER = "eeeeeeee-1111-4111-8111-eeeeeeeeeeee"
_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def connect(accounts, *, expires_in=2592000):
    """A real link, built the way the real flow builds one.

    The account list comes from `lister`, which stands in for cTrader's own
    response — so `mode` is derived exactly as it is in production, from the
    broker's `live` flag and from nothing the client sent.
    """
    begun = CL.begin(USER)
    state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
    # The exchange belongs to the callback: cTrader's authorization code lives
    # one minute, so it cannot survive until a second, human-timed request.
    CL.handle_callback({"code": "c", "state": state},
                       exchanger=lambda c, u: {
                           "accessToken": "TOKEN-SECRET-VALUE",
                           "refreshToken": "REFRESH-SECRET",
                           "expiresIn": expires_in})
    return CL.complete(USER, begun["nonce"], lister=lambda a: accounts)


def select(ctid, *, allow_live=False):
    real = CL.live_allowed
    if allow_live:
        CL.live_allowed = lambda: True
    try:
        return CL.select_account(USER, ctid)
    finally:
        CL.live_allowed = real


DEMO_ACC = {"ctid": 501, "live": False}
LIVE_ACC = {"ctid": 502, "live": True}

# ── 1. the mode comes from the broker ───────────────────────────────────────
print("\n[1] account mode is derived from the broker, never from the client")
connect([DEMO_ACC, LIVE_ACC])
check("nothing selected yet reads as unknown, not as demo",
      E.account_mode(USER) == E.UNKNOWN, E.account_mode(USER))
select(501)
check("selecting the demo account reads demo", E.account_mode(USER) == E.DEMO,
      E.account_mode(USER))
select(502, allow_live=True)
check("selecting the live account reads live", E.account_mode(USER) == E.LIVE,
      E.account_mode(USER))
check("an unknown user is unknown, never demo",
      E.account_mode("nobody-at-all") == E.UNKNOWN)

# The value must not be reachable from a request body. This reads the source
# rather than trusting a comment: `mode` is written in exactly two places and
# both derive it from the account list the broker returned.
src = open(os.path.join(ROOT, "apex", "platform", "ctrader_link.py"),
           encoding="utf-8").read()
check("mode is only ever written from the broker's own `live` flag",
      src.count('"mode": LIVE if a.get("live") else DEMO') == 1, "shape changed")
check("and select_account copies it from the matched account, not the request",
      'rec["selectedMode"] = match["mode"]' in src)
check("no path parses a mode out of a request body",
      "body.get(\"mode\")" not in src and "payload.get(\"mode\")" not in src)

# ── 2. the four combinations ────────────────────────────────────────────────
print("\n[2] entitlement x account mode — all four, not just the two that pass")


def cap(): return E.capability(USER)


rows = []
for lic_state, want_ent in (("none", E.FREE_DEMO), ("active", E.PAID_LIVE)):
    for ctid, want_mode in ((501, E.DEMO), (502, E.LIVE)):
        if lic_state == "active":
            L.grant(USER, plan="pro")
        else:
            ST._write(f"{ST._ns()}:{ST._P}:licence:{USER}", None)
        select(ctid, allow_live=(ctid == 502))
        c = cap()
        rows.append((want_ent, want_mode, c))
        check(f"{want_ent} + {want_mode}: entitlement is read correctly",
              c["entitlement"] == want_ent, c["entitlement"])
        check(f"{want_ent} + {want_mode}: mode is read correctly",
              c["accountMode"] == want_mode, c["accountMode"])

by = {(e, m): c for e, m, c in rows}
check("free_demo + demo CAN automate", by[(E.FREE_DEMO, E.DEMO)]["canAutomate"] is True)
check("paid_live + demo CAN automate", by[(E.PAID_LIVE, E.DEMO)]["canAutomate"] is True)
check("free_demo + live CANNOT", by[(E.FREE_DEMO, E.LIVE)]["canAutomate"] is False)
# The one that matters. Paying does not conjure an execution path.
check("paid_live + live CANNOT EITHER",
      by[(E.PAID_LIVE, E.LIVE)]["canAutomate"] is False,
      "a paid plan must not unlock a path that does not exist")
check("and both live refusals give the same reason",
      by[(E.FREE_DEMO, E.LIVE)]["reason"]
      == by[(E.PAID_LIVE, E.LIVE)]["reason"] == "LIVE_NOT_AVAILABLE")
check("worded exactly as the release states it",
      by[(E.PAID_LIVE, E.LIVE)]["message"]
      == "live trading is not available in this release",
      by[(E.PAID_LIVE, E.LIVE)]["message"])
check("live execution is reported as disabled in every combination",
      all(c["liveExecutionEnabled"] is False for _, _, c in rows))
check("and the module says so on its own",
      E.live_execution_enabled() is False)

# ── 3. badges ───────────────────────────────────────────────────────────────
print("\n[3] the server decides the badge, not the browser")
check("a demo account is DEMO", by[(E.FREE_DEMO, E.DEMO)]["badge"] == "DEMO")
check("a live account is LIVE BLOCKED",
      by[(E.FREE_DEMO, E.LIVE)]["badge"] == "LIVE BLOCKED")
CL.disconnect(USER)
c = cap()
check("nothing connected is NOT CONNECTED", c["badge"] == "NOT CONNECTED", c["badge"])
check("and it cannot automate", c["canAutomate"] is False)
check("and the reason is NOT_CONNECTED, not a licence problem",
      c["reason"] == "NOT_CONNECTED", c["reason"])

# A session that cannot be revived is its own state with its own next step.
connect([DEMO_ACC], expires_in=-10)     # already expired
select(501)
rec_key = None
c = cap()
check("an expired connection with no usable refresh is REAUTH REQUIRED",
      c["badge"] == "REAUTH REQUIRED", f"{c['badge']} {c['reason']}")
check("and says to connect again rather than showing an empty account",
      "connect the account again" in c["message"], c["message"])
check("and it cannot automate", c["canAutomate"] is False)

# ── 4. withdrawal still stops everything ────────────────────────────────────
# Free demo access must not route around the one lever support has.
print("\n[4] a withdrawn licence outranks the free tier")
connect([DEMO_ACC])
select(501)
L.grant(USER, plan="pro")
check("granted, the client can automate", cap()["canAutomate"] is True)
L.revoke(USER)
c = cap()
check("revoked, they cannot", c["canAutomate"] is False)
check("and the reason says so", c["reason"] == "LICENCE_REVOKED", c["reason"])
check("the entitlement drops back to the free tier name",
      c["entitlement"] == E.FREE_DEMO, c["entitlement"])
check("but the licence state still records the withdrawal",
      c["licenceState"] == L.REVOKED, c["licenceState"])
try:
    E.require_activation(USER)
    check("a revoked client cannot activate a rule", False, "no refusal")
except E.NotEntitled as e:
    check("a revoked client cannot activate a rule", e.code == "LICENCE_REVOKED")

# ── 5. no licence, and no expired one, blocks the free tier ─────────────────
# This is the behaviour the business decision changed: demo access is free, so
# an absent or lapsed licence is not a refusal. The distinction is still
# CARRIED — licenceState says which — it just no longer gates demo.
print("\n[5] an absent or lapsed licence does not block demo automation")
ST._write(f"{ST._ns()}:{ST._P}:licence:{USER}", None)
check("no licence at all still automates on demo", cap()["canAutomate"] is True)
check("and is named as the free tier", cap()["entitlement"] == E.FREE_DEMO)
L.grant(USER, plan="pro", expires_at=1.0)       # long past
c = cap()
check("a lapsed licence still automates on demo", c["canAutomate"] is True)
check("and is reported as expired, not as never having existed",
      c["licenceState"] == L.EXPIRED, c["licenceState"])
check("and as the free tier, because the paid tier is what lapsed",
      c["entitlement"] == E.FREE_DEMO)

# ── 6. the copy this release makes about paid access ────────────────────────
print("\n[6] one sentence about paid access, in one place")
check("the notice is carried to the client",
      cap()["planNotice"] == E.PLAN_NOTICE)
check("and says demo is free",
      "Demo accounts are free." in E.PLAN_NOTICE)
check("and that live is not enabled in this release",
      "live execution is not enabled in this release" in E.PLAN_NOTICE)
check("and promises no date, price or outcome",
      not any(w in E.PLAN_NOTICE.lower() for w in
              ("soon", "guarantee", "profit", "$", "€", "return")),
      E.PLAN_NOTICE)

# ── 7. automation start enforces it, not just the badge ─────────────────────
print("\n[7] automation.start refuses, rather than rendering a disabled button")
ST._write(f"{ST._ns()}:{ST._P}:licence:{USER}", None)
# Built through the real API, so the rule is exactly the shape the product
# creates — a hand-written document would be a shape nothing else produces.
from apex.platform import api as A               # noqa: E402
import apex.platform.identity as _id             # noqa: E402


class _P:
    user_id = USER
    email = "tester@example.test"
    email_verified = True

    def as_dict(self):
        return {"userId": self.user_id}


_id.verify_token = lambda tok, **kw: _P()
HDR = {"Authorization": "Bearer t"}
_st, _b = A.handle("POST", "/api/v1/rules", HDR, json.dumps({
    "name": "entitlement rule", "symbols": ["EUR_USD"], "timeframe": "1h",
    "accountId": "501", "sides": "BUY",
    "entry": {"combine": "AND", "conditions": [
        {"id": "rsi", "params": {"op": "below", "value": 30}}]},
    "exit": {"combine": "OR", "conditions": [
        {"id": "rsi", "params": {"op": "above", "value": 70}}]},
}).encode())
rid = _b["rule"]["ruleDocId"]
_st, _b = A.handle("POST", f"/api/v1/rules/{rid}/activate", HDR, None)
check("a client with NO licence can activate a rule — demo is free",
      _st == 200, f"{_st} {str(_b)[:120]}")

connect([DEMO_ACC, LIVE_ACC])
select(501)
started = []
AU.start(USER, rid, starter=lambda uid: started.append(uid) or True)
check("a free client starts automation on a demo account", started != [],
      "the free tier is not free if this refuses")
AU.stop(USER)

# The dangerous environment, deliberately. With the environment lock OPEN —
# production plus the explicit live-accounts flag — the entitlement layer is
# the thing that has to refuse, and this is the only way to prove it does.
select(502, allow_live=True)
_real_live_allowed = CL.live_allowed
CL.live_allowed = lambda: True
try:
    AU.start(USER, rid, starter=lambda uid: started.append("LIVE!") or True)
    check("a live account is refused even with the environment lock open",
          False, "it STARTED")
except E.NotEntitled as e:
    check("a live account is refused even with the environment lock open",
          e.code == "LIVE_NOT_AVAILABLE", e.code)
    check("with the release's own words",
          str(e) == "live trading is not available in this release", str(e))
except AU.AutomationRefused as e:
    check("a live account is refused even with the environment lock open",
          e.code == "LIVE_NOT_AVAILABLE", e.code)
finally:
    CL.live_allowed = _real_live_allowed
check("and nothing was started", "LIVE!" not in started, str(started))

# And with the environment lock closed, it is refused earlier still. Three
# independent locks, and the test says which one answered rather than being
# satisfied that something did.
try:
    AU.start(USER, rid, starter=lambda uid: started.append("LIVE2!") or True)
    check("a live account is refused by the environment too", False, "it STARTED")
except CL.LinkError as e:
    check("a live account is refused by the environment too",
          e.code == "LIVE_BLOCKED", e.code)
check("and nothing was started then either", "LIVE2!" not in started, str(started))

L.revoke(USER)
select(501)
try:
    AU.start(USER, rid, starter=lambda uid: started.append("REVOKED!") or True)
    check("a withdrawn client is refused even on demo", False, "it STARTED")
except E.NotEntitled as e:
    check("a withdrawn client is refused even on demo",
          e.code == "LICENCE_REVOKED", e.code)
check("and nothing was started", "REVOKED!" not in started, str(started))

# ── 8. the two locks are independent, and each is proved alone ─────────────
# Removing either one of them left every test above green, because the other
# refused with the same code. That is the point of having two — and it also
# means a test that only checks "it refused" cannot tell they are both still
# there. So each is disabled in turn and the other one has to answer.
print("\n[8] each lock on the live path refuses on its own")
L.grant(USER, plan="pro")                # the entitlement that will not help
connect([DEMO_ACC, LIVE_ACC])
select(502, allow_live=True)
_real_live_allowed = CL.live_allowed
CL.live_allowed = lambda: True
try:
    # Lock 2 disabled: the connection claims demo while the stored selection
    # is live. This is exactly the disagreement the second lock exists for,
    # from the other side — and the entitlement layer has to catch it.
    _real_conn = CL.get_ctrader_connection
    CL.get_ctrader_connection = lambda uid, **kw: {
        "userId": str(uid), "accessToken": "T", "ctid": 502, "mode": "demo"}
    try:
        AU.start(USER, rid, starter=lambda uid: started.append("LOCK1!") or True)
        check("the entitlement lock refuses on its own", False, "it STARTED")
    except E.NotEntitled as e:
        check("the entitlement lock refuses on its own",
              e.code == "LIVE_NOT_AVAILABLE", e.code)
    finally:
        CL.get_ctrader_connection = _real_conn
    check("and nothing was started", "LOCK1!" not in started, str(started))

    # Lock 1 disabled: the entitlement check is a no-op. The connection's own
    # mode has to be enough.
    _real_req = E.require_automation
    import apex.platform.automation as _AU_mod
    _AU_mod._ent.require_automation = lambda uid, **kw: {"canAutomate": True}
    try:
        AU.start(USER, rid, starter=lambda uid: started.append("LOCK2!") or True)
        check("the connection lock refuses on its own", False, "it STARTED")
    except AU.AutomationRefused as e:
        check("the connection lock refuses on its own",
              e.code == "LIVE_NOT_AVAILABLE", e.code)
        check("with the same words, so which lock answered is not a UI change",
              e.detail == "live trading is not available in this release",
              e.detail)
    finally:
        _AU_mod._ent.require_automation = _real_req
    check("and nothing was started", "LOCK2!" not in started, str(started))
finally:
    CL.live_allowed = _real_live_allowed

shutil.rmtree(_TMP, ignore_errors=True)

print()
# ── the start lock must be RELEASED, and a failed resume must stay paused ───
# Both found on the first real run of scripts/smoke_ctrader_controls.py against
# the broker, and neither had a test. START_IN_PROGRESS appeared nowhere in the
# suite, and resume was exercised only through HTTP.
print("\n[11] the start lock is dropped, and a failed resume keeps the pause")

_locks = {}
_lock_calls = []


def _fake_claim_value(key, value, ttl_s=120):
    """SET NX, in memory: True for the winner, False while somebody holds it."""
    _lock_calls.append(("claim", str(value)))
    if key in _locks:
        return False
    _locks[key] = str(value)
    return True


def _fake_release(key, value):
    """Compare-and-delete, like the real Lua script: only the owner drops it."""
    _lock_calls.append(("release", str(value)))
    if _locks.get(key) == str(value):
        del _locks[key]
        return True
    return False


_real_cv = AU.user_store.claim_value
_real_rel = AU.user_store.release_claim
AU.user_store.claim_value = _fake_claim_value
AU.user_store.release_claim = _fake_release
try:
    # Self-contained: earlier sections revoke the licence and archive rules, so
    # this builds its own through the real API rather than borrowing theirs.
    ST._write(f"{ST._ns()}:{ST._P}:licence:{USER}", None)
    connect([DEMO_ACC, LIVE_ACC])
    select(501)
    _s, _b = A.handle("POST", "/api/v1/rules", HDR, json.dumps({
        "name": "lock rule", "symbols": ["EUR_USD"], "timeframe": "1h",
        "accountId": "501", "sides": "BUY",
        "entry": {"combine": "AND", "conditions": [
            {"id": "rsi", "params": {"op": "below", "value": 30}}]},
        "exit": {"combine": "OR", "conditions": [
            {"id": "rsi", "params": {"op": "above", "value": 70}}]},
    }).encode())
    rid = _b["rule"]["ruleDocId"]
    A.handle("POST", f"/api/v1/rules/{rid}/activate", HDR, None)
    AU.stop(USER)

    # A successful start must leave no lock behind.
    _locks.clear(); _lock_calls.clear()
    AU.start(USER, rid, starter=lambda uid: True)
    check("a successful start releases its lock", _locks == {}, str(_locks))
    check("and releases it with the token it claimed with",
          [v for k, v in _lock_calls if k == "claim"]
          == [v for k, v in _lock_calls if k == "release"],
          str(_lock_calls))

    # THE REGRESSION: pause, then resume at once. This is what a client does,
    # and it was refused for thirty seconds with "another start for this
    # account is already in flight" — a sentence that was simply untrue.
    AU.pause(USER)
    _lock_calls.clear()
    resumed = AU.resume(USER, starter=lambda uid: True)
    check("resume immediately after pause is accepted",
          resumed.get("state") == "running", str(resumed.get("state")))
    check("and it leaves no lock behind either", _locks == {}, str(_locks))
    AU.stop(USER)

    # A start that the engine refuses must still drop the lock, or one refusal
    # locks the account out for the TTL.
    _locks.clear(); _lock_calls.clear()
    try:
        AU.start(USER, rid, starter=lambda uid: False)
        check("an engine refusal raises", False, "it did not")
    except AU.AutomationRefused as e:
        check("an engine refusal raises ENGINE_REFUSED", e.code == "ENGINE_REFUSED",
              e.code)
    check("and a refused start still releases its lock", _locks == {},
          str(_locks))

    # And a starter that raises, which is not the same path.
    _locks.clear()
    try:
        AU.start(USER, rid, starter=lambda uid: (_ for _ in ()).throw(
            RuntimeError("engine exploded")))
    except Exception:
        pass
    check("a starter that raises still releases its lock", _locks == {},
          str(_locks))

    # Somebody else's lock is not ours to drop.
    _locks.clear(); _lock_calls.clear()
    _locks[AU._k_lock(USER)] = "another-container"
    try:
        AU.start(USER, rid, starter=lambda uid: True)
        check("a held lock refuses the start", False, "it proceeded")
    except AU.AutomationRefused as e:
        check("a held lock refuses with START_IN_PROGRESS",
              e.code == "START_IN_PROGRESS", e.code)
    check("and it does NOT release a lock it never won",
          _locks.get(AU._k_lock(USER)) == "another-container", str(_locks))
    _locks.clear()

    # No shared backend: nothing was claimed, so nothing is released.
    AU.user_store.claim_value = lambda key, value, ttl_s=120: None
    _lock_calls.clear()
    AU.stop(USER)
    AU.start(USER, rid, starter=lambda uid: True)
    check("with no shared backend, no release is attempted",
          [k for k, _ in _lock_calls] == [], str(_lock_calls))
    AU.user_store.claim_value = _fake_claim_value
    AU.stop(USER)

    # ── a failed resume must leave the pause intact ─────────────────────────
    # It used to write STOPPED before calling start. A start that then refused
    # left stopped-but-still-remembering-a-rule: resume raises NOT_PAUSED, and
    # no control recovers it.
    _locks.clear()
    AU.start(USER, rid, starter=lambda uid: True)
    AU.pause(USER)
    try:
        AU.resume(USER, starter=lambda uid: False)
        check("a resume whose engine refuses raises", False, "it did not")
    except AU.AutomationRefused:
        pass
    check("a failed resume leaves automation PAUSED, not stopped",
          AU.status(USER).get("state") == "paused",
          str(AU.status(USER).get("state")))
    check("and the rule is still remembered, so it can be retried",
          AU.status(USER).get("ruleDocId") == rid,
          str(AU.status(USER).get("ruleDocId")))
    # The proof that it is recoverable: the same call again, and it works.
    again = AU.resume(USER, starter=lambda uid: True)
    check("so resuming again works, instead of being stuck",
          again.get("state") == "running", str(again.get("state")))
    AU.stop(USER)
finally:
    AU.user_store.claim_value = _real_cv
    AU.user_store.release_claim = _real_rel

# ── every broker built for a user must be told WHICH user ───────────────────
# A platform client's cTrader token lives in the ctrader_link record, not in
# the user_store record, so _make_broker can only find it when it is given the
# user id. broker_read passes it; all six call sites inside user_loop did not,
# and for a platform client CTRADER_ACCOUNT_ID was therefore the empty string.
# The engine started, and then every broker read died on int('') — the loop was
# running and blind. Seen in production on 2026-10-02:
#   initial balance read failed: invalid literal for int() with base 10: ''
# Checked on the source, because the defect was a MISSING ARGUMENT and no
# behavioural test of a healthy Telegram user could ever see it: their token is
# in the record, so the branch that needs the id never runs for them.
print("\n[12] no broker is built without the user it belongs to")
import re as _re                                    # noqa: E402

_ul = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
_bare = _re.findall(r"_make_broker\(\s*user\s*\)", _ul)
check("user_loop builds no broker without a user id", _bare == [], str(_bare))
_withid = _re.findall(r"_make_broker\(\s*user\s*,", _ul)
check("and it does build them with one, so the check is not vacuous",
      len(_withid) >= 6, f"{len(_withid)} call sites")

_br = open(os.path.join(ROOT, "apex", "platform", "broker_read.py"),
           encoding="utf-8").read()
check("broker_read still passes the user id too",
      "_make_broker(user, user_id)" in _br)

# And the behaviour the argument buys: with the id, the ctid comes from the
# link record; without it, it cannot.
import apex.user_loop as _ULM                       # noqa: E402

connect([DEMO_ACC, LIVE_ACC])
select(501)
_bare_user = {"paper": False}                        # no ctrader token at all
_, _cfg_with = _ULM._make_broker(dict(_bare_user), USER)
check("given the user id, the account id comes from the link record",
      str(_cfg_with.CTRADER_ACCOUNT_ID) == "501",
      repr(_cfg_with.CTRADER_ACCOUNT_ID))
_, _cfg_without = _ULM._make_broker(dict(_bare_user))
check("without it, the account id is empty — which is what int() choked on",
      _cfg_without.CTRADER_ACCOUNT_ID == "",
      repr(_cfg_without.CTRADER_ACCOUNT_ID))

# ── [13] ───────────────────────────────────────────────────────────────────
# Seen in production on 2026-10-02: the owner's phone showed "No cTrader
# account is connected" on one screen and the connected DEMO account on
# another, minutes apart, for the only user that exists in Supabase — a user
# whose link record is intact.
#
# The cause was not the UI. user_store's read helpers return None on ANY
# failure — a 429, a timeout, a dropped connection — and `_read_conn` turns
# None into NOT_CONNECTED, which public_status turns into connected=false,
# which the browser prints as a sentence about the reader's own account. A
# failed read rendered as a fact. `_redis_set` carries a docstring about this
# exact bug being fixed for WRITES; the read half was never done.
print("\n[13] a store that cannot be reached is never rendered as a fact")
from apex import user_store as _US                  # noqa: E402
from apex.platform import api as _API               # noqa: E402
from apex.platform import identity as _ID           # noqa: E402

connect([DEMO_ACC, LIVE_ACC])
select(501)

# Controls first. The fix must not make a healthy read, or a genuinely empty
# one, into an error — otherwise everything below passes for the wrong reason.
check("control: a reachable store reports the connection",
      CL.public_status(USER).get("connected") is True)
check("control: an absent record is still connected=false, not an error",
      CL.public_status("ffffffff-2222-4222-8222-ffffffffffff")
      .get("connected") is False)

_saved = (_US._USE_REDIS, _US.get_blob, _US.get_blob_strict)


def _down_strict(key):
    raise _US.StoreUnavailable("upstash GET failed: ReadTimeout")


try:
    # A deployment with a shared backend, whose backend is not answering.
    _US._USE_REDIS = True
    _US.get_blob = lambda key: None          # what the lenient path still does
    _US.get_blob_strict = _down_strict

    check("the lenient read still reports None, so the two paths differ",
          ST._read(CL._k_conn(USER)) is None)

    try:
        ST._read_strict(CL._k_conn(USER))
        check("the strict read raises instead of reading back empty", False)
    except _US.StoreUnavailable:
        check("the strict read raises instead of reading back empty", True)

    try:
        _st = CL.public_status(USER)
        check("public_status does not claim the account has nothing",
              False, f"returned connected={_st.get('connected')!r}")
    except _US.StoreUnavailable:
        check("public_status does not claim the account has nothing", True)

    # And the answer the browser actually receives.
    _ID_saved = _ID.verify_token
    _API_verify = _API._id.verify_token
    try:
        _API._id.verify_token = lambda token, **kw: _ID.Principal(
            user_id=USER, email="o@apex4traders.test", email_verified=True)
        _res = _API._handle("GET", "/api/v1/ctrader/status",
                            headers={"Authorization": "Bearer stub"},
                            client_key="203.0.113.13")
        check("the endpoint answers at all", _res is not None)
        _status, _body = _res
        check("an unreachable store answers 503, not 200", _status == 503,
              f"status {_status}")
        check("with a code the client can branch on",
              ((_body or {}).get("error") or {}).get("code")
              == "STORE_UNAVAILABLE", json.dumps(_body)[:160])
        check("and the body never carries a connected flag to render",
              "connected" not in json.dumps(_body), json.dumps(_body)[:160])
    finally:
        _API._id.verify_token = _API_verify
finally:
    _US._USE_REDIS, _US.get_blob, _US.get_blob_strict = _saved

# get_blob_strict must actually reach the strict GET. Every check above stubs
# get_blob_strict itself, so none of them executes its body — a mutation that
# pointed it back at the lenient _redis_get survived them all. This drives the
# real chain: get_blob_strict -> _redis_get_strict -> _upstash_strict, on a
# backend declared present and in fact unconfigured.
_saved2 = (_US._USE_REDIS, _US._BACKEND)
try:
    _US._USE_REDIS, _US._BACKEND = True, "upstash"
    _k = "forex:platform:probe"
    check("the lenient blob read swallows the failure and answers None",
          _US.get_blob(_k) is None)
    try:
        _US.get_blob_strict(_k)
        check("the strict blob read does not", False, "returned without raising")
    except _US.StoreUnavailable:
        check("the strict blob read does not", True)
finally:
    _US._USE_REDIS, _US._BACKEND = _saved2

# The failure message must not carry the key or the value: an Upstash argument
# is a key or a value, and the values include encrypted broker tokens. The old
# code interpolated the requests exception, which carries the whole URL.
_leaked = None
try:
    _US._upstash_strict(["SET", "forex:platform:ctrader:secret-user",
                         "gAAAAA-encrypted-token-material"])
except _US.StoreUnavailable as e:
    _leaked = str(e)
except Exception as e:                               # noqa: BLE001
    _leaked = f"wrong exception {type(e).__name__}: {e}"
check("a failed command raises StoreUnavailable",
      _leaked is not None and not _leaked.startswith("wrong exception"),
      str(_leaked))
check("and its message carries neither the key nor the value",
      _leaked is not None
      and "secret-user" not in _leaked
      and "encrypted-token-material" not in _leaked,
      str(_leaked))
check("while still naming the command, so a log line is diagnosable",
      bool(_leaked) and "SET" in _leaked, str(_leaked))

# ── [14] ───────────────────────────────────────────────────────────────────
# The envelope every read route answers in.
#
# The defect: GET ctrader/status wrapped its payload as {"ctrader": {...}}
# while GET accounts returned the SAME payload flat. Five screens read
# `connected` off the top level of ctrader/status, got undefined, and printed
# "no cTrader account is connected" about a connected account. The status
# strip read the flat route and showed the account, so the two disagreed on
# the same screen. TypeScript could not catch it: the client casts the body
# with `payload as T` and never checks it.
#
# So the shape is pinned here, on the server, which is the only side that
# knows it. A read answers the resource flat; an action answers it under a
# key that names what changed.
print("\n[14] a read route answers the resource flat")
connect([DEMO_ACC, LIVE_ACC])
select(501)


def _body(route, method="GET", payload=None):
    _res = _API._handle(method, "/api/v1/" + route,
                        headers={"Authorization": "Bearer stub"},
                        body=(json.dumps(payload) if payload else None),
                        client_key="203.0.113.%d" % (hash(route) % 200 + 20))
    assert _res is not None, route
    return _res


_vt = _API._id.verify_token
try:
    _API._id.verify_token = lambda token, **kw: _ID.Principal(
        user_id=USER, email="o@apex4traders.test", email_verified=True)

    for _route in ("ctrader/status", "accounts"):
        _s, _b = _body(_route)
        check(f"GET {_route} answers 200", _s == 200, f"status {_s}")
        check(f"GET {_route} carries connected at the top level",
              _b.get("connected") is True,
              f"keys {sorted((_b or {}).keys())}")
        check(f"GET {_route} carries the selection at the top level",
              (_b.get("selected") or {}).get("ctid") == 501,
              json.dumps(_b.get("selected")))
        check(f"GET {_route} does not nest it under a key the client ignores",
              "ctrader" not in _b, f"keys {sorted((_b or {}).keys())}")

    # Both routes read the same thing, so they must answer the same thing —
    # the discrepancy itself was the bug, not either shape on its own.
    _, _b1 = _body("ctrader/status")
    _, _b2 = _body("accounts")
    check("and the two read routes agree, key for key",
          {k: v for k, v in _b1.items() if k != "ok"}
          == {k: v for k, v in _b2.items() if k != "ok"},
          f"{sorted(_b1)} vs {sorted(_b2)}")

    # The action routes keep their naming envelope, which one client screen
    # already reads correctly — flattening those would break it.
    # 501, the demo account. The live one is refused in this environment, so
    # selecting it would test the environment's refusal, not the envelope.
    _s, _b = _body("ctrader/select", "POST", {"ctid": 501})
    check("POST ctrader/select answers 200", _s == 200, f"status {_s}")
    check("an action still names what it changed",
          isinstance(_b.get("ctrader"), dict), json.dumps(_b)[:120])
    check("and what it names is the same shape the read answers flat",
          (_b.get("ctrader") or {}).get("connected") is True,
          json.dumps(_b)[:120])
finally:
    _API._id.verify_token = _vt

# ── [15] ───────────────────────────────────────────────────────────────────
# Activation and automation are different permissions.
#
# The rule page decided activation for itself with `licence !== "active"`,
# which is stricter than require_activation and dead-ended the whole free
# tier: a demo client could build a rule and never activate it, so they could
# never start anything. The product the landing page invites people to was
# unusable by the people it invited. The server states it now.
print("\n[15] a free demo client can activate a rule")
connect([DEMO_ACC, LIVE_ACC])
select(501)

_cap = E.capability(USER)
check("the capability says activation is allowed with no licence",
      _cap.get("canActivate") is True, json.dumps(_cap.get("canActivate")))
check("and gives no refusal to display",
      _cap.get("activationRefusal") is None, str(_cap.get("activationRefusal")))
check("the licence really is absent, so this is not passing by accident",
      _cap.get("licenceState") == "none", str(_cap.get("licenceState")))
check("and the entitlement is the free one",
      _cap.get("entitlement") == E.FREE_DEMO, str(_cap.get("entitlement")))

# The behaviour behind the flag: require_activation must agree with it.
try:
    E.require_activation(USER)
    check("require_activation permits it too", True)
except Exception as e:                                   # noqa: BLE001
    check("require_activation permits it too", False, f"{type(e).__name__}: {e}")

# And the one case that is refused, so the flag is not simply always true.
_real_status = L.status_for
try:
    L.status_for = lambda uid, **kw: {"state": L.REVOKED, "expiresAt": None,
                                      "plan": None}
    _rev = E.capability(USER)
    check("a withdrawn licence cannot activate",
          _rev.get("canActivate") is False, str(_rev.get("canActivate")))
    check("and the server supplies the sentence to show",
          bool(_rev.get("activationRefusal")), str(_rev.get("activationRefusal")))
    try:
        E.require_activation(USER)
        check("require_activation refuses it too", False, "it did not refuse")
    except E.NotEntitled:
        check("require_activation refuses it too", True)
finally:
    L.status_for = _real_status

check("and the flag is back to allowed once the licence is not withdrawn",
      E.capability(USER).get("canActivate") is True)

# ── [16] ───────────────────────────────────────────────────────────────────
# The rule the builder actually produces must be activatable.
#
# Found by driving the real screens in a browser. The builder's own default —
# eleven steps, every field filled, summary reading "stop 1.5x ATR; target 2R"
# — saved a document that activation refused on two counts:
#
#   accountId: required                 the form never sent one
#   exit.conditions: at least one ...   the form offers "managed by stop and
#                                       target only" as a complete answer
#
# So the happy path ended in a refusal nobody could act on, after the work was
# done. Both are fixed here rather than in the form, because the server is
# what knows the selected account and what defines a valid rule.
print("\n[16] the default rule the builder writes can be activated")
from apex.platform import ruledoc as _RD                 # noqa: E402
from apex.platform import api as _API2                   # noqa: E402

connect([DEMO_ACC, LIVE_ACC])
select(501)

_vt2 = _API2._id.verify_token
try:
    _API2._id.verify_token = lambda token, **kw: _ID.Principal(
        user_id=USER, email="o@apex4traders.test", email_verified=True)

    # Exactly what the form posts: no accountId, no exit conditions.
    _res = _API2._handle(
        "POST", "/api/v1/rules", headers={"Authorization": "Bearer stub"},
        body=json.dumps({
            "name": "Builder default", "symbols": ["EURUSD"],
            "timeframe": "1h", "sides": "BOTH",
            "entry": {"combine": "AND",
                      "conditions": [{"id": "atr", "params": {"period": 14,
                                      "direction": "above", "value": 10}}]},
            "exit": {"combine": "OR", "conditions": []},
        }),
        client_key="203.0.113.41")
    _st, _b = _res
    check("the rule is created", _st == 200, f"{_st} {json.dumps(_b)[:120]}")
    _doc = (_b.get("rule") or {})
    _rid = _doc.get("ruleDocId")

    # 1 — the account came from the selection, not from the browser.
    check("it is bound to the selected account even though none was sent",
          _doc.get("accountId") == "501", repr(_doc.get("accountId")))

    # 2 — and it validates, with the exit block left empty.
    _problems = _RD.validate(_doc, known_condition_ids=None)
    check("the document the builder writes is valid",
          _problems == [], json.dumps(_problems))
    check("and its exit block really is empty, so this is not passing because "
          "something filled it in",
          (_doc.get("exit") or {}).get("conditions") == [],
          json.dumps(_doc.get("exit")))
finally:
    _API2._id.verify_token = _vt2

# The guard that makes an empty exit safe: a stop is mandatory. If that ever
# stops being true, an empty exit block becomes a position with no way out.
_nostop = dict(_doc, stopLoss={"mode": "none"})
check("a rule with no stop is still refused",
      any("stopLoss" in p for p in _RD.validate(_nostop)),
      json.dumps(_RD.validate(_nostop)))

# Entry is NOT relaxed. A rule that enters on nothing enters on everything.
_noentry = dict(_doc, entry={"combine": "AND", "conditions": []})
check("an empty ENTRY block is still refused",
      any("entry.conditions" in p for p in _RD.validate(_noentry)),
      json.dumps(_RD.validate(_noentry)))

# And the message a client without a selected account now gets.
_noacct = dict(_doc, accountId="")
_msg = " ".join(_RD.validate(_noacct))
check("a missing account says what to do about it",
      "select an account" in _msg, _msg[:140])

if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All entitlement checks passed.")
