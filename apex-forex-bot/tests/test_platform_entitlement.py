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
    CL.handle_callback({"code": "c", "state": state})
    return CL.complete(
        USER, begun["nonce"],
        exchanger=lambda c, u: {"accessToken": "TOKEN-SECRET-VALUE",
                                "refreshToken": "REFRESH-SECRET",
                                "expiresIn": expires_in},
        lister=lambda a: accounts)


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
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All entitlement checks passed.")
