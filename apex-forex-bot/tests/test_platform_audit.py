"""The audit trail §7 demands, and the three ways a trail stops being one.

§7 is the only section of the live specification whose requirement is a
NEGATIVE: "a record the application can rewrite is not an audit trail". So
most of this file is about what must be impossible, which needs a different
shape of test from "does it store a row".

WHAT MAKES THIS DIFFERENT FROM THE JOURNAL

`journal_store` is evidence for a client reading their own history. It caps at
MAX_ENTRIES and DELETES the overflow, and it writes with `set_blob`, which
overwrites. Both are correct for a journal and disqualifying for an audit
trail — the records §7 lists are exactly the ones somebody comes looking for
after an incident, which is when they are oldest.

THE THREE FAILURES PINNED HERE

  * REWRITE. The write must be SET NX, so a record id that exists is refused
    rather than replaced. Asserted twice: by calling it, and on the module's
    AST, because `set_blob` sitting unused in this module is a rewrite waiting
    for a future edit.
  * SILENT LOSS. A record removed or altered in the store must be DETECTABLE.
    Append-only writes cannot stop infrastructure-level deletion, so the
    records are hash-chained and `verify()` names the first break. A trail
    that cannot be checked is a trail nobody can rely on.
  * A CREDENTIAL IN THE TRAIL. §7: the audit must never contain one in the
    first place. Redaction on the way IN, not on the way out, because a value
    that never entered cannot leak later through a read or an export.

Run: python3 tests/test_platform_audit.py
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-audit-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("REDIS_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import user_store                             # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def raised(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except exc as e:
        return e


# ── a shared backend with a real NX ─────────────────────────────────────────
class FakeShared:
    """SET NX without expiry, plus the overwriting SET a wrong one would use.

    `set_blob` is installed deliberately: if the module under test reaches for
    it, these counters say so and the AST check below fails as well.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.calls = {"set_blob_nx": 0, "set_blob": 0, "get_blob": 0,
                      "del_blob": 0}
        self.down = False

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        user_store.set_blob_nx = self.set_blob_nx
        user_store.set_blob = self.set_blob
        user_store.get_blob = self.get_blob
        user_store.del_blob = self.del_blob

    def set_blob_nx(self, key, value_str):
        self.calls["set_blob_nx"] += 1
        if self.down:
            return None                 # could not ask — NOT "already there"
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = value_str
            return True

    def set_blob(self, key, value_str, ttl_s=None):
        self.calls["set_blob"] += 1
        if self.down:
            return False
        with self.lock:
            self.data[key] = value_str
        return True

    def get_blob(self, key):
        self.calls["get_blob"] += 1
        if self.down:
            return None
        with self.lock:
            return self.data.get(key)

    def del_blob(self, key):
        self.calls["del_blob"] += 1
        with self.lock:
            return self.data.pop(key, None)


FAKE = FakeShared()
FAKE.install()

from apex.platform import audit as A                    # noqa: E402

USER = "aaaa1111-2222-4333-8444-aaaa55556666"
ACTOR = "client:aaaa1111"

# A request shaped the way a live order request is, carrying the kind of value
# that must never reach storage.
REQUEST = {"symbol": "EURUSD", "side": "BUY", "volume": 1000,
           "stopLoss": 1.2400, "takeProfit": 1.2600,
           "accessToken": "tok-live-must-never-be-stored",
           "auth": {"refreshToken": "refresh-must-never-be-stored"}}
REPLY = {"ok": True, "positionId": "pos-551", "filledPrice": 1.2502}


# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] every live order is recorded with everything §7 names")
r1 = A.record_live_order(
    user_id=USER, actor=ACTOR, account_id="902",
    rule_doc_id="rule-7", rule_doc_version=3, decision_id="dec-1",
    request=REQUEST, broker_reply=REPLY, position_id="pos-551")

for field, want in (("kind", A.LIVE_ORDER), ("userId", USER),
                    ("actor", ACTOR), ("accountId", "902"),
                    ("ruleDocId", "rule-7"), ("ruleDocVersion", 3),
                    ("decisionId", "dec-1"), ("positionId", "pos-551")):
    check(f"it records {field}", r1.get(field) == want,
          f"{r1.get(field)!r}, expected {want!r}")
check("it records WHEN, as a number", isinstance(r1.get("ts"), float),
      repr(r1.get("ts")))
check("it records the full request", isinstance(r1.get("request"), dict)
      and r1["request"].get("volume") == 1000, str(r1.get("request")))
check("and the broker's reply", isinstance(r1.get("brokerReply"), dict)
      and r1["brokerReply"].get("filledPrice") == 1.2502,
      str(r1.get("brokerReply")))

print("\n[2] no credential is in the trail, because none ever entered it")
_stored = json.dumps([json.loads(v) for v in FAKE.data.values()
                      if str(v).startswith("{")])
for leak in ("tok-live-must-never-be-stored",
             "refresh-must-never-be-stored"):
    check(f"{leak[:18]}... is nowhere in storage", leak not in _stored,
          "§7: the audit must never contain a credential in the first place")
check("the field is still named, so the record does not read as complete "
      "when it is not",
      "accessToken" in r1.get("request", {}), str(r1.get("request")))
check("and its value says it was masked",
      "tok-live" not in str(r1["request"]["accessToken"]),
      str(r1["request"]["accessToken"]))

print("\n[3] every refusal, with its gate and its code")
r2 = A.record_refusal(
    user_id=USER, actor=ACTOR, account_id="902", gate="risk_per_trade",
    code="RISK_PER_TRADE_EXCEEDED", reason="2.4% of balance, limit is 1%",
    rule_doc_id="rule-7", rule_doc_version=3, decision_id="dec-2")
check("the refusal names its gate", r2.get("gate") == "risk_per_trade",
      str(r2.get("gate")))
check("and its code", r2.get("code") == "RISK_PER_TRADE_EXCEEDED",
      str(r2.get("code")))
check("a refusal with no gate is refused — an unattributable refusal is not "
      "evidence",
      raised(ValueError, A.record_refusal, user_id=USER, actor=ACTOR,
             gate="", code="X", reason="y") is not None)
check("and nor is one with no code",
      raised(ValueError, A.record_refusal, user_id=USER, actor=ACTOR,
             gate="g", code="", reason="y") is not None)

print("\n[4] every entitlement and consent change, with the actor")
r3 = A.record_entitlement_change(
    user_id=USER, actor="admin:ops-1", field="liveEnabled",
    old_value=False, new_value=True, reason="review passed")
check("the entitlement change records the actor",
      r3.get("actor") == "admin:ops-1", str(r3.get("actor")))
check("and both sides of the change",
      r3.get("oldValue") is False and r3.get("newValue") is True,
      f"{r3.get('oldValue')!r} -> {r3.get('newValue')!r}")
r4 = A.record_consent_change(
    user_id=USER, actor=ACTOR, document="live_risk_disclosure",
    version="2026-10-01", granted=True)
check("the consent change records which document and which version",
      r4.get("document") == "live_risk_disclosure"
      and r4.get("documentVersion") == "2026-10-01", str(r4))
check("a change with no actor is refused — §7 requires who",
      raised(ValueError, A.record_entitlement_change, user_id=USER, actor="",
             field="liveEnabled", old_value=False, new_value=True) is not None)

print("\n[5] every mode verification and its answer")
r5 = A.record_mode_verification(
    user_id=USER, actor="system:loop", account_id="902",
    answer="demo", source="broker:ctrader", detail="trader.live=false")
check("the verification records its answer", r5.get("answer") == "demo",
      str(r5.get("answer")))
check("and where the answer came from",
      r5.get("source") == "broker:ctrader", str(r5.get("source")))
check("an answer the platform did not get from the broker is refused",
      raised(ValueError, A.record_mode_verification, user_id=USER,
             actor="system:loop", answer="demo", source="") is not None,
      "a mode 'verification' with no source is an assumption with a record")


# ═══════════════════════════════════════════════════════════════════════════
print("\n[6] APPEND-ONLY: the application cannot rewrite a record")
check("each record carries its own sequence number",
      [r.get("seq") for r in (r1, r2, r3, r4, r5)] == [1, 2, 3, 4, 5],
      str([r.get("seq") for r in (r1, r2, r3, r4, r5)]))
check("writing a sequence number that exists is REFUSED, not applied",
      raised(A.AuditImmutable, A._write_record,
             dict(r1, request={"tampered": True})) is not None,
      "a store that accepts the second write of one id is a store that "
      "forgets the first")
_again = A.get(USER, 1)
check("and the original record is untouched by the attempt",
      _again.get("request", {}).get("volume") == 1000
      and "tampered" not in _again.get("request", {}), str(_again))
check("the module never calls the overwriting set_blob for a record",
      FAKE.calls["set_blob"] == 0,
      f"{FAKE.calls['set_blob']} overwriting write(s) — an audit record "
      f"written with SET is a record the next one can replace")
check("nor does it delete anything", FAKE.calls["del_blob"] == 0,
      str(FAKE.calls["del_blob"]))

_src = open(os.path.join(ROOT, "apex", "platform", "audit.py"),
            encoding="utf-8").read()
_attrs = {n.attr for n in ast.walk(ast.parse(_src))
          if isinstance(n, ast.Attribute)}
check("and the overwriting primitives are not even named in the module",
      not ({"set_blob", "del_blob"} & _attrs),
      f"{sorted({'set_blob', 'del_blob'} & _attrs)} — unused today is one "
      f"edit away from used tomorrow")
check("the write-once primitive is what it uses", "set_blob_nx" in _attrs)

print("\n[7] nothing is evicted — the oldest record is the one that matters")
check("the audit declares no entry cap",
      getattr(A, "MAX_ENTRIES", None) is None,
      "journal_store caps at 5000 and DELETES the overflow; §7's records are "
      "the ones somebody reads after an incident, when they are oldest")
check("record 1 is still readable after the writes above",
      A.get(USER, 1).get("seq") == 1, str(A.get(USER, 1).get("seq")))

print("\n[8] TAMPER-EVIDENT: a record that changed can be shown to have")
_v = A.verify(USER)
check("an untouched trail verifies", _v.get("ok") is True, str(_v))
check("and says how many records it actually checked",
      _v.get("checked") == 5, str(_v))
check("each record chains to the one before it",
      A.get(USER, 2).get("prevHash") == A.get(USER, 1).get("hash"),
      f"{A.get(USER, 2).get('prevHash')!r} vs {A.get(USER, 1).get('hash')!r}")
check("and the first names no predecessor",
      not A.get(USER, 1).get("prevHash"), str(A.get(USER, 1).get("prevHash")))

# Tamper at the STORE level, which append-only writes cannot prevent — the
# question is only whether it can be detected afterwards.
_key = A._k_record(USER, 3)
_original = FAKE.data[_key]
_altered = json.loads(_original)
_altered["newValue"] = False          # the entitlement grant, reversed
FAKE.data[_key] = json.dumps(_altered)
_v2 = A.verify(USER)
check("an altered record breaks the chain and verify SAYS WHICH ONE",
      _v2.get("ok") is False and _v2.get("brokenAt") == 3, str(_v2))
check("and the detail says what kind of break it was",
      len(str(_v2.get("detail") or "")) > 30, str(_v2.get("detail")))
FAKE.data[_key] = _original
check("restoring it verifies again, so the check is about the DATA and not "
      "about having run once",
      A.verify(USER).get("ok") is True, str(A.verify(USER)))

# A removal is the other half: a chain that only checks the records present
# would report a shortened trail as healthy.
del FAKE.data[A._k_record(USER, 4)]
_v3 = A.verify(USER)
check("a REMOVED record is detected too, not read as a shorter trail",
      _v3.get("ok") is False and _v3.get("brokenAt") == 4, str(_v3))
FAKE.data[A._k_record(USER, 4)] = json.dumps(r4)
check("and the trail is whole again once it is back",
      A.verify(USER).get("ok") is True, str(A.verify(USER)))

# REWRITING HISTORY PROPERLY is the attack the chain has to survive, and the
# only thing that stops it is that each record's hash covers its own prevHash.
#
# The earlier check altered a record and left its hash stale, which any
# checksum catches. An attacker who knows the scheme does not leave it stale:
# they change record 3, RECOMPUTE record 3's hash so it is self-consistent,
# and then have exactly one loose end — record 4's prevHash, which now points
# at a hash that no longer exists. Fixing that is one field. If prevHash sits
# outside the hashed body, record 4 stays self-consistent after the fix and
# the entire trail verifies with a reversed entitlement grant inside it.
#
# No record is removed here, so nothing is detectable by the gap probe. The
# chain binding is the only thing left to catch it.
_k3, _k4 = A._k_record(USER, 3), A._k_record(USER, 4)
_keep3, _keep4 = FAKE.data[_k3], FAKE.data[_k4]
_forged = json.loads(_keep3)
_forged["newValue"] = False                  # the grant, reversed
_forged["hash"] = A._hash_of(_forged)        # and made self-consistent
FAKE.data[_k3] = json.dumps(_forged)
_fixed = json.loads(_keep4)
_fixed["prevHash"] = _forged["hash"]         # the one loose end, tied off
FAKE.data[_k4] = json.dumps(_fixed)
_v4 = A.verify(USER)
check("a forged record with its chain tied off is STILL caught",
      _v4.get("ok") is False,
      f"{_v4} — with prevHash outside the hashed body, rewriting a record "
      f"and fixing one neighbouring field leaves a trail that verifies, and "
      f"the reversed entitlement grant inside it reads as genuine")
check("and the break is reported at the record whose link was edited",
      _v4.get("brokenAt") == 4, str(_v4))
FAKE.data[_k3], FAKE.data[_k4] = _keep3, _keep4
check("and the trail verifies once more after that is undone",
      A.verify(USER).get("ok") is True, str(A.verify(USER)))

print("\n[9] there is no mutable pointer to forge in the first place")
# A stored "head" would be the one rewritable thing in an append-only trail,
# and a stale or forged one could hide a trail's tail from every reader that
# trusted it. The end is derived from the records instead, so that class of
# attack does not exist here rather than being defended against.
check("no head pointer is stored for a trail",
      not [k for k in FAKE.data if "head" in k.lower()],
      str([k for k in FAKE.data if "head" in k.lower()]))
check("and the module has no setter for one",
      getattr(A, "_set_head", None) is None and getattr(A, "_head", None) is None,
      "a pointer that can be set is a pointer that can be set wrongly")
check("the next sequence number is derived from the records",
      A._last_seq(USER) == 5, str(A._last_seq(USER)))

r6 = A.record_mode_verification(
    user_id=USER, actor="system:loop", account_id="902",
    answer="demo", source="broker:ctrader", detail="the sixth record")
check("so the next write lands after everything already there",
      r6.get("seq") == 6, f"seq {r6.get('seq')!r}")
check("and the trail still verifies end to end",
      A.verify(USER).get("ok") is True, str(A.verify(USER)))
check("record 3 survived a write aimed at its neighbourhood",
      A.get(USER, 3).get("newValue") is True, str(A.get(USER, 3)))

# The write-once guarantee, stated directly: a record already at a sequence
# number is never replaced, whatever a caller aims at it.
check("a write aimed squarely at a taken sequence number is refused",
      raised(A.AuditImmutable, A._write_record,
             dict(r6, seq=3, request={"tampered": True})) is not None)
check("and record 3 is still itself",
      A.get(USER, 3).get("field") == "liveEnabled", str(A.get(USER, 3)))

print("\n[10] reading back: a client's own trail, scoped to them")
rows = A.query(USER)
check("every record written is returned", len(rows) == 6, str(len(rows)))
check("in sequence order", [r["seq"] for r in rows] == [1, 2, 3, 4, 5, 6],
      str([r["seq"] for r in rows]))
check("another owner's trail is empty, not somebody else's",
      A.query("bbbb2222-3333-4444-8555-bbbb66667777") == [])
OTHER = "bbbb2222-3333-4444-8555-bbbb66667777"
check("and a record is not served across owners",
      raised(A.AuditNotFound, A.get, OTHER, 1) is not None)

# The owner is in the KEY, so the lookup above misses for the ordinary reason
# and never reaches the second check. That check defends a key built wrong —
# the one case where the namespace says one owner and the record says another
# — so proving it is real means planting exactly that.
FAKE.data[A._k_record(OTHER, 1)] = json.dumps(dict(r1, seq=1))
check("a record found under one owner's key carrying another's id is refused",
      raised(A.AuditNotFound, A.get, OTHER, 1) is not None,
      "the key said one owner and the record said another, and it was served")
check("and it is not quietly included in that owner's trail either",
      A.query(OTHER) == [], str(A.query(OTHER)))
del FAKE.data[A._k_record(OTHER, 1)]
check("a kind filter narrows without inventing",
      [r["seq"] for r in A.query(USER, kind=A.MODE_VERIFICATION)] == [5, 6],
      str([r["seq"] for r in A.query(USER, kind=A.MODE_VERIFICATION)]))


# ═══════════════════════════════════════════════════════════════════════════
print("\n[11] a store that cannot answer does not get written to silently")
FAKE.down = True
_e = raised(A.AuditUnavailable, A.record_mode_verification,
            user_id=USER, actor="system:loop", answer="demo",
            source="broker:ctrader")
check("a write that could not be confirmed RAISES rather than returning",
      _e is not None,
      "an audit write that fails quietly is the one case where the caller "
      "must not carry on — §7 is non-negotiable")
FAKE.down = False
check("and nothing was recorded for it",
      len(A.query(USER)) == 6, str(len(A.query(USER))))


print("\n[11b] the audit's OWN backend guard, tested on its own")
# §7's "one trail" guarantee must belong to this module, not be borrowed from
# user_store's import gate. In production that gate fires first, so the
# subprocess below can never reach audit's check — which means without this
# in-process test, deleting assert_shared_backend would break nothing.
_was = user_store._USE_REDIS
user_store._USE_REDIS = False
try:
    check("with no shared backend, the guard refuses",
          raised(A.SharedBackendRequired, A.assert_shared_backend) is not None)
    check("and a record cannot be written at all",
          raised(A.SharedBackendRequired, A.record_mode_verification,
                 user_id=USER, actor="system:loop", answer="demo",
                 source="broker:ctrader") is not None,
          "a per-container trail reads as complete on every container")
    check("the refusal names the remedy",
          "REDIS_URL" in str(raised(A.SharedBackendRequired,
                                    A.assert_shared_backend)))
finally:
    user_store._USE_REDIS = _was
check("and it works again once the backend is back",
      A.assert_shared_backend() is True)


print("\n[12] in production it refuses to run without a shared backend")
# A real subprocess, because "the process must refuse to start" is a claim
# about a process, not about a function.
#
# TOKEN_ENCRYPTION_KEY is supplied so the probe gets PAST the encryption gate
# and fails on the backend. Without it the process still refuses, but for the
# other reason, and a test that cannot tell the two refusals apart would pass
# with the backend check deleted.
#
# In production `user_store` already refuses to import with no shared backend,
# so that gate fires first and audit's own assert_shared_backend is the
# backstop behind it. What is asserted here is the PROCESS outcome, which is
# what §7 actually requires.
_probe = (
    "import os, sys;"
    "os.environ['APP_ENV']='production';"
    "os.environ['PRODUCT']='forex';"
    "os.environ['TOKEN_ENCRYPTION_KEY']=%r;"
    "os.environ.pop('REDIS_URL', None);"
    "os.environ.pop('UPSTASH_REDIS_REST_URL', None);"
    "os.environ.pop('ALLOW_PLAINTEXT_DEV_STORAGE', None);"
    "os.environ.pop('ALLOW_LOCAL_BACKEND_DEV', None);"
    "sys.path.insert(0, %r);"
    "import apex.platform.audit" % (
        __import__("cryptography.fernet", fromlist=["Fernet"])
        .Fernet.generate_key().decode(), ROOT))
_p = subprocess.run([sys.executable, "-c", _probe], capture_output=True,
                    text=True, timeout=120)
check("importing it in production with no shared backend fails",
      _p.returncode != 0, f"exit {_p.returncode}")
check("and the refusal names the remedy, not just the problem",
      "REDIS_URL" in (_p.stdout + _p.stderr),
      (_p.stdout + _p.stderr)[-400:])

print("\n[13] the audit reaches no broker and places nothing")
_names = {n.id for n in ast.walk(ast.parse(_src)) if isinstance(n, ast.Name)}
check("it names no execution module",
      not ({"bridge", "execution"} & (_attrs | _names)),
      str(sorted({"bridge", "execution"} & (_attrs | _names))))
check("and no broker-mutating operation",
      not ({"place_order", "close_position", "amend_sltp", "submit"}
           & (_attrs | _names)))


print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All audit-trail invariants hold.")
