"""The commercial model: a free trial, a paid live plan, and referred accounts.

THE TRAP AT THE CENTRE OF THIS FILE

`entitlement` used to read the licence STATE alone: any ACTIVE licence became
`paid_live`. That was right while there was one thing to sell. A free
fourteen-day trial is ALSO an active licence, so the moment one exists, the
free tier reports itself as the paid live entitlement — and the only reason
that would not have handed out live trading is that live trading does not
exist yet. Section [2] is that assertion, and it is the one to keep.

THE FACT THE PLATFORM CANNOT ESTABLISH

Extra trading accounts are unlocked by the client's broker account sitting
under the operator's introducing-broker code. Nothing in the cTrader Open API
says who introduced an account — it exposes the trader's accounts, not their
provenance. So "arrived through the link" (which the platform CAN see) and
"the broker account is under the IB" (which it cannot) are kept apart, and
nothing infers the second from the first. Section [6] asserts there is no such
inference.

AND THE RULE THAT PROTECTS IT

Confirming a referral grants paid-for capability, so it is an entitlement
change, so §7 requires it recorded with its actor. The confirmation writes the
audit record FIRST and refuses outright when the audit trail cannot take it —
section [8]. An entitlement change nobody can attribute afterwards is exactly
the one that gets disputed.

Run: python3 tests/test_platform_plans_referral.py
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-plans-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["A4T_REFERRAL_CODE"] = "APEX-OWNER"
os.environ.pop("A4T_REFERRED_ACCOUNT_ALLOWANCE", None)
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/cb"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from apex import user_store                             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def attempt(fn, *a, **kw):
    """The value, or whatever was raised — so a defect that changes WHICH
    exception comes out fails a named check instead of killing the run."""
    try:
        return fn(*a, **kw)
    except BaseException as e:                               # noqa: BLE001
        return e


# A shared backend, installed BEFORE the platform imports so that one store
# serves the whole file. Installing it half way through would switch the store
# under records already written and they would simply vanish — which is a
# property of this harness, not of the code, and a confusing way to discover
# it.
#
# Every primitive `platform.store` reaches for is faked, not only the one the
# audit trail needs: _write uses set_blob, _read uses get_blob, and
# _read_strict uses get_blob_strict. A half-installed fake would send some
# writes to a redis client that does not exist.
class FakeShared:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        user_store.set_blob_nx = self.set_blob_nx
        user_store.set_blob = self.set_blob
        user_store.get_blob = self.get_blob
        user_store.get_blob_strict = self.get_blob_strict
        user_store.del_blob = self.del_blob
        user_store.claim = self.claim
        user_store.claim_value = self.claim_value
        user_store.release_claim = self.release_claim

    def set_blob_nx(self, key, value_str):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = value_str
            return True

    def set_blob(self, key, value_str, ttl_s=None):
        with self.lock:
            self.data[key] = value_str
        return True

    def get_blob(self, key):
        with self.lock:
            return self.data.get(key)

    def get_blob_strict(self, key):
        return self.get_blob(key)

    def del_blob(self, key):
        with self.lock:
            return self.data.pop(key, None)

    # The lock primitives, so a flow that takes a lease does not fall through
    # to a redis client that does not exist and log a confusing error.
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


FAKE = FakeShared()
FAKE.install()

from apex.platform import entitlement as E               # noqa: E402
from apex.platform import licence as L                   # noqa: E402
from apex.platform import plans as P                      # noqa: E402
from apex.platform import referral as R                   # noqa: E402

from apex.platform import billing as _billing             # noqa: E402


def _billing_price():
    """The approved figure, read from the module that owns it."""
    return _billing.APPROVED_PRICE_MINOR


U1 = "1111eeee-2222-4333-8444-1111ffff6666"
U2 = "2222eeee-3333-4444-8555-2222ffff7777"
U3 = "3333eeee-4444-4555-8666-3333ffff8888"
NOW = 1_760_000_000.0
DAY = 86400.0


# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] the free trial: fourteen days, demo, and it does not renew")
_t = P.start_trial(U1, now=NOW)
check("a fresh account gets a trial", _t.get("plan") == P.DEMO_TRIAL, str(_t))
check("it is active", _t.get("state") == L.ACTIVE, str(_t))
check(f"it lasts {P.TRIAL_DAYS} days",
      abs(float(_t["expiresAt"]) - (NOW + P.TRIAL_DAYS * DAY)) < 1.0,
      str(_t.get("expiresAt")))
_exp_first = float(_t["expiresAt"])

_t2 = P.start_trial(U1, now=NOW + 5 * DAY)
check("starting it again does NOT move the expiry",
      abs(float(_t2["expiresAt"]) - _exp_first) < 1.0,
      f"{_t2.get('expiresAt')} vs {_exp_first} — a trial that restarts on "
      f"every sign-in is not a trial, and nobody would ever pay")

_s = P.trial_state(U1, now=NOW + 5 * DAY)
check("days left counts down", _s["daysLeft"] == 9, str(_s))
check("and rounds UP, so a part-day is not reported as zero while the "
      "product still works",
      P.trial_state(U1, now=NOW + 13 * DAY + 3600)["daysLeft"] == 1,
      str(P.trial_state(U1, now=NOW + 13 * DAY + 3600)))
check("at the boundary it is expired, not 'zero days left and working'",
      P.trial_state(U1, now=NOW + 14 * DAY + 1)["expired"] is True,
      str(P.trial_state(U1, now=NOW + 14 * DAY + 1)))

L.grant(U2, plan=P.FOUNDER_LIVE, expires_at=None, now=NOW)
P.start_trial(U2, now=NOW)
check("a trial is never granted over a plan the client already holds",
      P.plan_of(U2, now=NOW) == P.FOUNDER_LIVE, P.plan_of(U2, now=NOW))
check("and an expired trial is not resurrected by asking again",
      P.trial_state(U1, now=NOW + 20 * DAY)["expired"] is True,
      str(P.start_trial(U1, now=NOW + 20 * DAY)))


# ═══════════════════════════════════════════════════════════════════════════
print("\n[2] AN ACTIVE TRIAL IS NOT THE PAID LIVE ENTITLEMENT")
check("a client on the free trial is free_demo",
      E.entitlement_of(U1, now=NOW) == E.FREE_DEMO,
      f"{E.entitlement_of(U1, now=NOW)!r} — reading the licence STATE alone "
      f"makes fourteen free days report themselves as the paid plan")
check("the paid plan is paid_live",
      E.entitlement_of(U2, now=NOW) == E.PAID_LIVE,
      E.entitlement_of(U2, now=NOW))
check("and the distinction is the PLAN, not the state — both are ACTIVE",
      L.status_for(U1, now=NOW)["state"] == L.ACTIVE
      and L.status_for(U2, now=NOW)["state"] == L.ACTIVE)
check("only named plans pay for live",
      P.live_plans() == (P.FOUNDER_LIVE,),
      f"{P.live_plans()} — named rather than inferred, so a new plan is not "
      f"a live plan until somebody says it is")

# THE BUG THIS PINS. plans.py first called the live plan "founder_live" while
# billing.py grants "founder_lifetime". Nothing matched, so a client who paid
# would have been read as a free trial — a paid customer on the free tier,
# with no error anywhere, and nobody would have traced it to a constant.
check("the live plan is the name the PAYMENT PATH actually grants",
      P.FOUNDER_LIVE == _billing.APPROVED_PLAN,
      f"plans says {P.FOUNDER_LIVE!r}, billing grants "
      f"{_billing.APPROVED_PLAN!r} — a paying client would read as free_demo")
check("and a client holding exactly what billing grants is paid_live",
      P.is_live_plan(_billing.APPROVED_PLAN))

# billing takes its plan name from A4T_PLAN, so the name a paying client
# receives is settable at runtime. A check that knew only the shipped name
# would read a legitimately renamed plan as the free tier.
_had_plan = os.environ.get("A4T_PLAN")
try:
    os.environ["A4T_PLAN"] = "founder_2027"
    check("a plan renamed through A4T_PLAN still pays for live",
          P.is_live_plan("founder_2027"), str(P.live_plans()))
    check("and the shipped name keeps working alongside it",
          P.is_live_plan(P.FOUNDER_LIVE), str(P.live_plans()))
    os.environ["A4T_PLAN"] = P.DEMO_TRIAL
    check("but pointing A4T_PLAN at the TRIAL cannot make the free tier paid",
          not P.is_live_plan(P.DEMO_TRIAL),
          f"{P.live_plans()} — the whole confusion this module ends, "
          f"re-entering through an environment variable")
finally:
    if _had_plan is None:
        os.environ.pop("A4T_PLAN", None)
    else:
        os.environ["A4T_PLAN"] = _had_plan
check("the trial plan is not one of them",
      not P.is_live_plan(P.DEMO_TRIAL) and not P.is_live_plan(None)
      and not P.is_live_plan("anything_else"))
check("buying the paid plan still does not enable live execution",
      E.live_execution_enabled() is False,
      "a plan that unlocked an unreviewed execution path would be the most "
      "dangerous line in this product")


print("\n[3] the trial length is stated once, and the PRICE is elsewhere")
check("the plan notice carries the trial length from plans.py",
      f"{P.TRIAL_DAYS}-day" in E.PLAN_NOTICE, E.PLAN_NOTICE)

# The price is NOT in plans.py and not in the notice. It lives in billing,
# where offer_drift() watches one figure and the browser reads it from
# billing/offer. A second copy — in this module, or baked into static copy —
# is a price no gate is watching, and it goes stale the day it changes.
check("plans.py states no price of its own",
      not hasattr(P, "FOUNDER_PRICE_USD_CENTS")
      and not hasattr(P, "FOUNDER_PRICE_LABEL"),
      "the money belongs to billing.APPROVED_PRICE_MINOR")
check("and the notice names no price either",
      "$" not in E.PLAN_NOTICE and "497" not in E.PLAN_NOTICE,
      E.PLAN_NOTICE)
check("the decided price is the one billing will charge",
      _billing_price() == 49700, str(_billing_price()))


# ═══════════════════════════════════════════════════════════════════════════
print("\n[4] what the client is TOLD when there is no live trial")
_cap_none = E.capability(U3, now=NOW)
check("an account with no trial cannot automate",
      _cap_none["canAutomate"] is False, str(_cap_none.get("canAutomate")))
check("and is told so specifically", _cap_none["reason"] == "NO_LICENCE",
      str(_cap_none.get("reason")))
check("with a message that names a next step",
      len(_cap_none.get("message") or "") > 30, str(_cap_none.get("message")))

_cap_exp = E.capability(U1, now=NOW + 20 * DAY)
check("an expired trial cannot automate either",
      _cap_exp["canAutomate"] is False, str(_cap_exp.get("canAutomate")))
check("and is told it was the TRIAL that ended, not something generic",
      _cap_exp["reason"] == "TRIAL_EXPIRED", str(_cap_exp.get("reason")))
check("the two situations are different reasons, because they have "
      "different next steps",
      _cap_none["reason"] != _cap_exp["reason"])
check("a client can still build and activate rules after the trial ends",
      _cap_exp["canActivate"] is True,
      "refusing that loses every client who was going to pay after looking")
check("the capability carries the trial for the UI to render",
      E.capability(U1, now=NOW)["trialDaysLeft"] == 14
      and E.capability(U1, now=NOW)["onTrial"] is True,
      str(E.capability(U1, now=NOW).get("trialDaysLeft")))

# This is the inconsistency the trial work closed, stated as its own check.
from apex import user_loop                               # noqa: E402

check("the UI gate and the ENGINE gate now agree about no licence",
      user_loop._entitled(U3) is False
      and E.capability(U3, now=NOW)["canAutomate"] is False,
      "the engine always refused a platform user with no active licence "
      "while capability() said automation was available, so the UI offered a "
      "Start button that came back ENGINE_REFUSED")
check("and they agree about an expired trial",
      user_loop._entitled(U1) is False
      and E.capability(U1, now=NOW + 20 * DAY)["canAutomate"] is False)


# ═══════════════════════════════════════════════════════════════════════════
print("\n[5] one account by default")
check("the default allowance is one",
      P.account_allowance(U1) == 1, str(P.account_allowance(U1)))
check("and the capability reports it",
      E.capability(U1, now=NOW)["accountAllowance"] == 1,
      str(E.capability(U1, now=NOW).get("accountAllowance")))


print("\n[6] arriving through the link is NOT the broker account being under it")
_a = R.attribute(U1, code="APEX-OWNER", source=R.SRC_LINK, now=NOW)
check("an arrival is attributed", _a.get("code") == "apex-owner", str(_a))
check("codes are case-folded, so a link pasted from a phone still counts",
      R.arrived_through_link(U1) is True)
check("confirmation starts ABSENT, not false — it has not been looked at",
      _a.get("brokerConfirmed") is None, str(_a.get("brokerConfirmed")))
check("THE INFERENCE DOES NOT EXIST: arriving through the link confirms "
      "nothing",
      R.is_confirmed(U1) is False,
      "the cTrader API cannot say who introduced an account, so inferring "
      "it would grant paid-for capability on a guess")
check("so the allowance is still one",
      P.account_allowance(U1) == 1, str(P.account_allowance(U1)))

check("attribution is idempotent for the same code",
      R.attribute(U1, code="apex-owner", now=NOW)["code"] == "apex-owner")
_other = attempt(R.attribute, U1, code="SOMEBODY-ELSE", now=NOW)
check("and refuses a DIFFERENT code rather than overwriting",
      isinstance(_other, R.ReferralError)
      and _other.code == "ALREADY_ATTRIBUTED",
      f"{type(_other).__name__}: {_other} — a later claim must not displace "
      f"an earlier one, and it would always arrive later")
check("an unattributed client has no referral state",
      R.attribution_of(U3) is None and R.arrived_through_link(U3) is False)
R.attribute(U3, code="SOMEONE-ELSES-CODE", now=NOW)
check("attribution to another party's code is not the operator's referral",
      R.arrived_through_link(U3) is False,
      "treating any attribution as the operator's would pay them for "
      "somebody else's client")
for bad in ("", "  ", "a", "x" * 65, "has space", "semi;colon"):
    check(f"{bad[:14]!r} is refused as a code",
          isinstance(attempt(R.normalise, bad), R.ReferralError))


# ═══════════════════════════════════════════════════════════════════════════
print("\n[7] a confirmation must name its evidence")
for kw, why in (
    ({"actor": "", "broker_account": "9001", "report_ref": "IB-2026-10"},
     "no actor"),
    ({"actor": "admin:ops", "broker_account": "", "report_ref": "IB-2026-10"},
     "no broker account"),
    ({"actor": "admin:ops", "broker_account": "9001", "report_ref": ""},
     "no report reference"),
):
    _e = attempt(R.confirm_broker_account, U1, **kw)
    check(f"a confirmation with {why} is refused",
          isinstance(_e, R.ReferralError), f"{type(_e).__name__}: {_e}")
_e = attempt(R.confirm_broker_account, U2, actor="admin:ops",
             broker_account="9002", report_ref="IB-2026-10")
check("and one for a client with no attribution on file is refused",
      isinstance(_e, R.ReferralError) and _e.code == "NOT_ATTRIBUTED",
      f"{type(_e).__name__}: {_e}")


print("\n[8] a grant that cannot be AUDITED does not happen")
# The contract is "write the audit record FIRST, and if it cannot be written,
# change nothing". Tested by making the audit write fail, rather than by
# taking the backend away — the audit module's own refusal without a shared
# backend is asserted in tests/test_platform_audit.py, and reusing that here
# would also take away the store holding the referral record, so the
# confirmation would fail for the wrong reason and the check would pass
# while proving nothing.
_real_audit = R._audit_confirmation


def _audit_down(*_a, **_kw):
    raise RuntimeError("the audit trail cannot take this record")


R._audit_confirmation = _audit_down
try:
    _e = attempt(R.confirm_broker_account, U1, actor="admin:ops",
                 broker_account="9001", report_ref="IB-2026-10", now=NOW)
    check("when the audit record cannot be written, the confirmation RAISES",
          isinstance(_e, BaseException),
          f"{type(_e).__name__}: {_e} — an entitlement change nobody can "
          f"attribute afterwards is the one that gets disputed")
    check("and nothing was granted", R.is_confirmed(U1) is False)
    check("so the allowance did not move", P.account_allowance(U1) == 1)
finally:
    R._audit_confirmation = _real_audit

_c = R.confirm_broker_account(U1, actor="admin:ops", broker_account="9001",
                              report_ref="IB-2026-10", now=NOW)
check("with the audit trail available, the confirmation lands",
      _c.get("brokerConfirmed") is True, str(_c.get("brokerConfirmed")))
check("it records who confirmed it", _c.get("confirmedBy") == "admin:ops",
      str(_c.get("confirmedBy")))
check("and which report it came from", _c.get("reportRef") == "IB-2026-10",
      str(_c.get("reportRef")))

from apex.platform import audit as A                     # noqa: E402

_rows = [r for r in A.query(U1) if r.get("kind") == A.ENTITLEMENT]
check("an audit record exists for the grant", len(_rows) == 1, str(len(_rows)))
check("naming the actor", _rows and _rows[0].get("actor") == "admin:ops",
      str(_rows[0].get("actor") if _rows else None))
check("and the trail verifies", A.verify(U1).get("ok") is True,
      str(A.verify(U1)))
check("the client-facing view carries no report reference or operator name",
      "reportRef" not in R.state_of(U1)
      and "confirmedBy" not in R.state_of(U1), str(R.state_of(U1)))


print("\n[9] a confirmed referral unlocks more accounts")
check("the allowance is now above one",
      P.account_allowance(U1) == P.referred_account_allowance()
      and P.account_allowance(U1) > 1, str(P.account_allowance(U1)))
check("an unconfirmed client is unaffected",
      P.account_allowance(U3) == 1, str(P.account_allowance(U3)))

_had = os.environ.get("A4T_REFERRED_ACCOUNT_ALLOWANCE")
try:
    for bad, why in (("not-a-number", "mistyped"), ("0", "below the default"),
                     ("-3", "negative")):
        os.environ["A4T_REFERRED_ACCOUNT_ALLOWANCE"] = bad
        check(f"a {why} allowance never drops below the default",
              P.referred_account_allowance() >= P.DEFAULT_ACCOUNT_ALLOWANCE,
              f"{bad!r} -> {P.referred_account_allowance()} — a mistyped "
              f"variable must not take away access a client paid for")
    os.environ["A4T_REFERRED_ACCOUNT_ALLOWANCE"] = "3"
    check("and a valid value is honoured",
          P.referred_account_allowance() == 3,
          str(P.referred_account_allowance()))
finally:
    if _had is None:
        os.environ.pop("A4T_REFERRED_ACCOUNT_ALLOWANCE", None)
    else:
        os.environ["A4T_REFERRED_ACCOUNT_ALLOWANCE"] = _had


print("\n[10] the allowance fails CLOSED")
_real = R.is_confirmed


def _broken(_uid):
    raise RuntimeError("the referral store is unreachable")


R.is_confirmed = _broken
try:
    check("a referral store that cannot answer is not a confirmation",
          P.account_allowance(U1) == 1,
          f"{P.account_allowance(U1)} — granting the larger allowance on an "
          f"error turns an outage into free capability")
finally:
    R.is_confirmed = _real
check("and it recovers", P.account_allowance(U1) > 1)


print("\n[12] the limit has teeth: select_account enforces it")
from apex.brokers import ctrader as _ct_broker            # noqa: E402
from apex.platform import ctrader_link as CL              # noqa: E402

# One cTrader login carrying a demo and three real-money accounts — the shape
# a broker actually hands out.
THREE = [{"ctid": 7000, "live": False}, {"ctid": 7001, "live": True},
         {"ctid": 7002, "live": True}, {"ctid": 7003, "live": True}]
_ct_broker.list_accounts = lambda token: list(THREE)


def connect(user_id):
    """One cTrader login carrying three demo accounts."""
    begun = CL.begin(user_id)
    state = begun["authorizeUrl"].split("state=")[1].split("&")[0]
    CL.handle_callback({"code": "c", "state": state},
                       exchanger=lambda c, u: {"accessToken": "TOK",
                                               "refreshToken": "REF",
                                               "expiresIn": 2592000})
    CL.complete(user_id, begun["nonce"], lister=lambda a: list(THREE))


def sel(user_id, ctid):
    """The selected ctid, or the exception.

    Every selection below goes through this: a defect in the limit turns an
    accepted selection into a raise, and a check that called select_account
    directly would kill the run instead of failing by name.

    `live_allowed` is forced on for the duration, because this environment
    blocks real-money accounts and the limit being tested is about them. That
    block is asserted where it belongs, in tests/test_platform_entitlement.py.
    """
    real = CL.live_allowed
    CL.live_allowed = lambda: True
    try:
        out = attempt(CL.select_account, user_id, ctid)
    finally:
        CL.live_allowed = real
    if isinstance(out, BaseException):
        return out
    return out["selected"]["ctid"]


U4 = "4444eeee-5555-4666-8777-4444ffff9999"
connect(U4)

# Demo first, and it must never count: the ordinary client has a demo and a
# live account from one login, and charging them for the demo would earn
# nothing — a demo produces no traded volume and so no rebate.
check("a demo account is accepted", sel(U4, 7000) == 7000, str(sel(U4, 7000)))

check("the first real-money account is accepted", sel(U4, 7001) == 7001,
      str(sel(U4, 7001)))
check("re-selecting the SAME account is not a second account",
      sel(U4, 7001) == 7001,
      f"{sel(U4, 7001)} — switching back and forth must not consume the "
      f"allowance")

_e = sel(U4, 7002)
check("a second real-money account is refused on the default allowance",
      isinstance(_e, CL.LinkError) and _e.code == "ACCOUNT_LIMIT",
      f"{type(_e).__name__}: {_e}")
check("and the refusal says how to get more without blaming the client",
      "referral" in str(_e).lower() and "unaffected" in str(_e).lower(),
      str(_e))
check("and it says demo accounts are not the thing being limited",
      "demo accounts are not limited" in str(_e).lower(), str(_e))
check("the demo account still works while the live limit is reached",
      sel(U4, 7000) == 7000,
      f"{sel(U4, 7000)} — the free trial must not be collateral damage")
check("the account they already use still works after the refusal",
      sel(U4, 7001) == 7001,
      f"{sel(U4, 7001)} — a limit that strands the account somebody is "
      f"already trading is an outage, not a limit")

R.attribute(U4, code="APEX-OWNER", now=NOW)
R.confirm_broker_account(U4, actor="admin:ops", broker_account="7001",
                         report_ref="IB-2026-10", now=NOW)
check("once the referral is confirmed, the second account is accepted",
      sel(U4, 7002) == 7002, str(sel(U4, 7002)))
check("and a third", sel(U4, 7003) == 7003, str(sel(U4, 7003)))

# A connection made before any of this existed has no tradedCtids list. It
# must not read as "zero accounts used" and then lock the client out of the
# one they are already trading.
U5 = "5555eeee-6666-4777-8888-5555ffffaaaa"
connect(U5)
sel(U5, 7001)      # a real-money account, chosen before the limit existed
_conn = CL._read_conn(U5)
_conn.pop("tradedCtids", None)
CL._store._write(CL._k_conn(U5), _conn)
check("a connection predating the limit keeps the account it already uses",
      sel(U5, 7001) == 7001, str(sel(U5, 7001)))
check("and is still held to one NEW account",
      isinstance(sel(U5, 7002), CL.LinkError), str(sel(U5, 7002)))


print("\n[13] the trial actually REACHES clients")
# The gap this closes was mine: plans.py granted a trial that nothing in
# production ever called, while demo automation had started requiring an
# active licence. The result would have been a platform where no client could
# start anything — a shipping blocker invisible to every test that granted the
# trial itself, which is all of the ones above.
from apex.platform import api as API                      # noqa: E402


class _Principal:
    def __init__(self, uid, verified=True):
        self.user_id = uid
        self.email_verified = verified


U6 = "6666eeee-7777-4888-8999-6666ffffbbbb"
check("a confirmed account has no trial before it is seen",
      P.trial_state(U6, now=NOW)["plan"] == P.NONE)
API._start_trial_if_new(_Principal(U6))
check("authenticating starts it", P.trial_state(U6)["onTrial"] is True,
      str(P.trial_state(U6)))
_first = P.trial_state(U6)["expiresAt"]
API._start_trial_if_new(_Principal(U6))
check("and signing in again does not extend it",
      P.trial_state(U6)["expiresAt"] == _first,
      "a trial that renews on every request is not a trial")

U7 = "7777eeee-8888-4999-8aaa-7777ffffcccc"
API._start_trial_if_new(_Principal(U7, verified=False))
check("an UNVERIFIED address does not start the clock",
      P.trial_state(U7, now=NOW)["plan"] == P.NONE,
      "the fourteen days would tick while they cannot use the product, and "
      "they would arrive to a shorter trial than they were promised")

U8 = "8888eeee-9999-4aaa-8bbb-8888ffffdddd"
L.grant(U8, plan=P.FOUNDER_LIVE, expires_at=None, now=NOW)
API._start_trial_if_new(_Principal(U8))
check("a PAYING client is never downgraded to a trial by signing in",
      P.plan_of(U8, now=NOW) == P.FOUNDER_LIVE, P.plan_of(U8, now=NOW))

_real_start = P.start_trial
P.start_trial = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("store down"))
try:
    API._start_trial_if_new(_Principal("9999eeee-aaaa-4bbb-8ccc-9999ffffeeee"))
    check("a store failure here does not fail the request", True)
except Exception as e:
    check("a store failure here does not fail the request", False, str(e))
finally:
    P.start_trial = _real_start

check("and it is wired into the ONE place every request authenticates",
      "_start_trial_if_new(principal)" in open(
          os.path.join(ROOT, "apex", "platform", "api.py"),
          encoding="utf-8").read(),
      "there is no sign-up hook to use; _authenticate is the only place that "
      "sees every client")


print("\n[11] payments are still off")
check("checkout is not enabled by any of this",
      os.getenv("ENABLE_CHECKOUT") in (None, "", "false", "0"),
      "this work prices the plan; it does not take money")


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All plan, trial and referral invariants hold.")
