"""Who the caller is, and what they are allowed to touch.

WHAT THIS FILE IS DEFENDING

Two failures, both silent, both expensive on a platform that holds connected
broker accounts:

  one client reading or changing another client's rules
  a request being served as authenticated when the platform could not
  actually tell who sent it

The second is the subtler one. Every path in identity.py that cannot prove
who the caller is must raise — an unset variable, an unreachable Supabase, a
200 with no user in it. None of them may end with a Principal, and "we could
not check" must not be reported to the client as "your login is invalid",
because that sends the operator hunting a phantom auth bug instead of reading
their own misconfiguration.

Run: python tests/test_platform_identity_store.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-store-")
os.environ["DATA_DIR"] = _TMP          # before user_store computes _DIR
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex.platform import conditions as C  # noqa: E402
from apex.platform import identity as I  # noqa: E402
from apex.platform import ruledoc as R  # noqa: E402
from apex.platform import store as S  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def raises(exc, fn):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print(f"       (raised {type(e).__name__} instead)")
        return False


ALICE = "11111111-1111-4111-8111-111111111111"   # Supabase user ids
BOB = "22222222-2222-4222-8222-222222222222"


def a_rule(owner, name="rule"):
    d = R.blank(user_id=owner, account_id="ct-1", symbols=["EUR_USD"],
                timeframe="1h")
    d["name"] = name
    d["sides"] = "BUY"
    d["entry"] = {"combine": "AND", "conditions": [
        {"id": "rsi", "params": {"op": "below", "value": 30}}]}
    d["exit"] = {"combine": "OR", "conditions": [
        {"id": "rsi", "params": {"op": "above", "value": 70}}]}
    return d


# ════════════════════════════════════════════════════════════════════════
print("\n1. a client cannot reach another client's rules")
alice_doc = S.create(ALICE, a_rule(ALICE, "alice's rule"))
rid = alice_doc["ruleDocId"]
check("the owner can read their own rule", S.get(ALICE, rid)["name"]
      == "alice's rule")
check("another client gets NotFound, not the document",
      raises(S.NotFound, lambda: S.get(BOB, rid)))
check("and cannot tell it apart from a rule that never existed",
      raises(S.NotFound, lambda: S.get(BOB, "does-not-exist")))
check("another client cannot overwrite it",
      raises(S.NotFound, lambda: S.save_draft(BOB, alice_doc)))
check("another client cannot activate it",
      raises(S.NotFound, lambda: S.activate(
          BOB, rid, known_condition_ids=C.available())))
check("another client cannot pause it",
      raises(S.NotFound, lambda: S.set_state(BOB, rid, R.PAUSED)))
check("another client cannot fork it into a new version",
      raises(S.NotFound, lambda: S.next_version(BOB, rid)))
check("it does not appear in another client's list",
      S.list_docs(BOB) == [])
check("it does appear in the owner's list",
      [d["ruleDocId"] for d in S.list_docs(ALICE)] == [rid])
bob_doc = S.create(BOB, a_rule(BOB, "bob's rule"))
check("the index is per-owner, so ids do not leak across accounts even "
      "before a document is read",
      bob_doc["ruleDocId"] not in S._index_members(ALICE)
      and rid not in S._index_members(BOB))
# The key namespace is the first line of defence. This is the second: a
# document sitting under the right key carrying the wrong owner must still be
# refused, because that can only mean a key-construction bug.
S._write(S._k_current(ALICE, "planted"), dict(bob_doc, ruleDocId="planted"))
check("a document under the right key with the wrong owner is refused",
      raises(S.OwnershipViolation, lambda: S.get(ALICE, "planted")))


print("\n2. the owner comes from the session, never from the request body")
forged = a_rule(ALICE, "forged")
forged["userId"] = ALICE                    # Bob claims Alice's id
stored = S.create(BOB, forged)
check("a forged userId is replaced with the caller's",
      stored["userId"] == BOB, stored["userId"])
check("and the document lands in the forger's own account, not the victim's",
      S.get(BOB, forged["ruleDocId"])["userId"] == BOB)
check("the victim never sees it",
      forged["ruleDocId"] not in [d["ruleDocId"] for d in S.list_docs(ALICE)])
moved = dict(S.get(ALICE, rid))
moved["userId"] = BOB                       # try to hand a rule to Bob
S.save_draft(ALICE, moved)
check("a saved draft cannot change hands either",
      S.get(ALICE, rid)["userId"] == ALICE)


print("\n3. an activated version is written once and never again")
live = S.activate(ALICE, rid, known_condition_ids=C.available())
check("activation freezes the terms", live["state"] == R.ACTIVE)
check("the frozen version is retrievable by number",
      S.get_version(ALICE, rid, 1)["state"] == R.ACTIVE)
check("re-activating the same version is refused",
      raises(ValueError, lambda: S.activate(
          ALICE, rid, known_condition_ids=C.available())))
# The line above cannot tell WHICH refusal fired: RuleDocInvalid is itself a
# ValueError, so a state check would satisfy it and the write-once guard could
# be deleted unnoticed. Pausing makes the state legal again, leaving only the
# frozen version to do the refusing.
S.set_state(ALICE, rid, R.PAUSED)
_why = ""
try:
    S.activate(ALICE, rid, known_condition_ids=C.available())
except Exception as _e:  # noqa: BLE001
    _why = str(_e)
check("and it is the recorded version that refuses, not the state",
      "already recorded" in _why, _why[:70])
S.set_state(ALICE, rid, R.ACTIVE)
check("an active rule cannot be edited in place",
      raises(R.RuleDocInvalid, lambda: S.save_draft(ALICE, live)))
draft2 = S.next_version(ALICE, rid)
check("editing it produces a draft at the next version",
      draft2["version"] == 2 and draft2["state"] == R.DRAFT,
      f"v{draft2['version']}/{draft2['state']}")
check("and version 1 is still exactly what it was — the journal points here",
      S.get_version(ALICE, rid, 1)["version"] == 1)
check("another client cannot read a frozen version either",
      raises(S.NotFound, lambda: S.get_version(BOB, rid, 1)))
bad = a_rule(ALICE, "no stop")
bad["stopLoss"] = {"mode": "none"}
S.create(ALICE, bad)
check("an invalid rule cannot be activated at all",
      raises(R.RuleDocInvalid, lambda: S.activate(
          ALICE, bad["ruleDocId"], known_condition_ids=C.available())))
check("a rule naming an unknown condition cannot be activated either",
      raises(R.RuleDocInvalid, lambda: (
          lambda d: (d["entry"]["conditions"].__setitem__(
              0, {"id": "moon_phase", "params": {}}),
              S.save_draft(ALICE, d),
              S.activate(ALICE, d["ruleDocId"],
                         known_condition_ids=C.available()))
      )(S.create(ALICE, a_rule(ALICE, "unknown cond")))))
check("a draft is not started by setting its state",
      raises(ValueError, lambda: S.set_state(
          ALICE, draft2["ruleDocId"], R.ACTIVE)))


# ════════════════════════════════════════════════════════════════════════
print("\n4. authentication refuses whenever it cannot prove who the caller is")


class FakeResponse:
    def __init__(self, status, body=None, bad_json=False):
        self.status_code = status
        self._body = body
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._body


def with_supabase(response=None, boom=None, configured=True):
    """Install a stubbed Supabase and return the call counter."""
    import requests
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        if boom:
            raise boom
        return response
    requests.get = fake_get
    if configured:
        os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
        os.environ["SUPABASE_ANON_KEY"] = "anon-key"
    else:
        os.environ.pop("SUPABASE_URL", None)
        os.environ.pop("SUPABASE_ANON_KEY", None)
    I.forget_all()
    return calls


import requests as _rq  # noqa: E402
_real_get = _rq.get
OK_USER = {"id": ALICE, "email": "alice@example.com",
           "email_confirmed_at": "2026-01-01T00:00:00Z"}

try:
    with_supabase(configured=False)
    check("an unconfigured platform raises AuthUnavailable, not AuthFailed",
          raises(I.AuthUnavailable, lambda: I.verify_token("tok")))
    got = "sentinel"
    try:
        got = I.verify_token("tok")
    except I.AuthUnavailable:
        got = None
    check("and never returns a Principal", got is None, repr(got))

    with_supabase(FakeResponse(200, OK_USER))
    p = I.verify_token("tok")
    check("a valid token yields the Supabase user id as the platform identity",
          p.user_id == ALICE, p.user_id)
    check("and the confirmed address is recognised", p.email_verified is True)

    with_supabase(FakeResponse(401))
    check("an expired or invalid token is AuthFailed",
          raises(I.AuthFailed, lambda: I.verify_token("tok")))

    with_supabase(boom=OSError("connection reset"))
    check("an unreachable Supabase is AuthUnavailable — an outage must not "
          "sign everyone out",
          raises(I.AuthUnavailable, lambda: I.verify_token("tok")))

    with_supabase(FakeResponse(500))
    check("a 500 from Supabase is AuthUnavailable, not a login",
          raises(I.AuthUnavailable, lambda: I.verify_token("tok")))

    with_supabase(FakeResponse(500, OK_USER))
    check("a 500 carrying a valid-looking user is still not a login",
          raises(I.AuthUnavailable, lambda: I.verify_token("tok")))

    with_supabase(FakeResponse(200, bad_json=True))
    check("an unparseable 200 is AuthUnavailable, not a login",
          raises(I.AuthUnavailable, lambda: I.verify_token("tok")))

    with_supabase(FakeResponse(200, {"email": "nobody@example.com"}))
    check("a 200 carrying no user id is refused, not turned into a principal",
          raises(I.AuthFailed, lambda: I.verify_token("tok")))

    print("\n5. the cache spares reads without outliving a revocation")
    calls = with_supabase(FakeResponse(200, OK_USER))
    I.verify_token("tok")
    I.verify_token("tok")
    I.verify_token("tok")
    check("repeat reads hit Supabase once", calls["n"] == 1, str(calls["n"]))
    I.verify_token("tok", fresh=True)
    check("a sensitive call asks again", calls["n"] == 2, str(calls["n"]))
    I.forget("tok")
    I.verify_token("tok")
    check("signing out drops the cached answer at once", calls["n"] == 3,
          str(calls["n"]))
    check("the raw token is never a cache key",
          all("tok" != k for k in I._cache))
    check("cache keys are hashes", all(len(k) == 64 for k in I._cache))

    print("\n6. the bearer header is read strictly")
    check("Bearer is accepted", I.bearer_token("Bearer abc.def") == "abc.def")
    check("case does not matter on the scheme",
          I.bearer_token("bearer abc") == "abc")
    check("a bare token is rejected — it invites tokens in logs and referrers",
          I.bearer_token("abc.def") is None)
    check("another scheme is rejected", I.bearer_token("Basic abc") is None)
    check("an empty header is rejected", I.bearer_token("") is None)
    check("Bearer with nothing after it is rejected",
          I.bearer_token("Bearer ") is None)

    print("\n7. an unconfirmed address cannot connect a broker or trade")
    with_supabase(FakeResponse(200, {"id": BOB, "email": "bob@example.com"}))
    unconfirmed = I.verify_token("tok2")
    check("the principal is authenticated", unconfirmed.user_id == BOB)
    check("but is refused at the verified-email gate",
          raises(I.AuthFailed, lambda: I.require_verified_email(unconfirmed)))
    with_supabase(FakeResponse(200, OK_USER))
    check("a confirmed one passes it",
          I.require_verified_email(I.verify_token("tok")).user_id == ALICE)
    check("what is handed to a browser carries no token and no metadata",
          set(I.verify_token("tok").as_dict()) ==
          {"userId", "email", "emailVerified"})
finally:
    _rq.get = _real_get
    shutil.rmtree(_TMP, ignore_errors=True)


print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
