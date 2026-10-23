"""A close's claim is released when nothing was sent, kept when the outcome is unknown.

FOUND BY AN INDEPENDENT REVIEW (LOW, three findings):

* A failure BEFORE anything reached cTrader (no such account, a broken
  connection lookup, a malformed id) kept the claim, and several came back as
  "the broker close result is unknown". Any retry within minutes was refused as
  DUPLICATE_CLOSE although nothing had been closed.
* The claim was keyed on the raw path text, and not on the account: "123",
  "0123" took separate claims, and a close sent under the wrong account used up
  the claim the right account then needed.

WHAT THESE TESTS WILL NOT ACCEPT

* A claim taken for an id that is not a whole number.
* A claim kept after a failure that happened before the broker was asked.
* A claim released after an exception from the submit itself (the broker may
  have filled the close).
* One position under two spellings, or under two accounts, sharing a claim.

Run: python3 tests/test_close_claims.py
"""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-claims-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import gates                                       # noqa: E402
from apex.platform import ctrader_link as LINK               # noqa: E402
from apex.platform import position_close as PC               # noqa: E402

PC._account_mode = lambda uid, ctid: "demo"
released, gated = [], []


class _Dec:
    def __init__(self, ok=True):
        self.ok = ok
        self.reason, self.detail = "OK", ""

    def __bool__(self):
        return self.ok


def gate(uid, *, position_id, origin):
    gated.append(position_id)
    return _Dec(), "rid-1"


PC._ledger.release = lambda rid: released.append(rid)


def run(**kw):
    released.clear()
    gated.clear()
    try:
        PC.close_demo("u", ctid="501", gate_fn=gate, **kw)
        return None
    except Exception as e:                                   # noqa: BLE001
        return e


class Broker:
    def __init__(self, result=None, exc=None):
        self.result, self.exc = result, exc

    def close_position_by_id(self, pid):
        if self.exc:
            raise self.exc
        return self.result


ok_conn = lambda *a, **k: {"ctid": "501", "mode": "demo"}       # noqa: E731

# ── 1. the id is validated before a claim is taken ──────────────────────────
print("\n[1] a malformed id never reaches the gate")
for bad in ("abc", "", "12.5", "-3", "1_23", "0x10", " "):
    e = run(position_id=bad, broker_fn=lambda: Broker({"status": "FILLED"}), connection_fn=ok_conn)
    check(f"{bad!r}: refused as BAD_POSITION_ID, 400",
          isinstance(e, PC.CloseRefused) and e.code == "BAD_POSITION_ID" and e.status == 400, repr(e))
    check(f"{bad!r}: no claim was taken", gated == [], str(gated))

print("\n[1b] spellings of one id become one")
for spelled in ("123", "0123", " 123 "):
    run(position_id=spelled, broker_fn=lambda: Broker({"status": "FILLED"}), connection_fn=ok_conn)
    check(f"{spelled!r} reaches the gate as '123'", gated == ["123"], str(gated))

# ── 2. nothing was sent → the claim is released, with a specific refusal ─────
print("\n[2] a failure before the broker was asked releases the claim")


def link_error(*a, **k):
    raise LINK.LinkError("NO_SUCH_ACCOUNT", "that account is not one of the connected ones")


e = run(position_id="7", connection_fn=link_error)
check("a link error is re-raised as itself", isinstance(e, LINK.LinkError) and e.code == "NO_SUCH_ACCOUNT", repr(e))
check("and the claim was released", released == ["rid-1"], str(released))


def odd_error(*a, **k):
    raise RuntimeError("redis down")


e = run(position_id="7", connection_fn=odd_error)
check("an unexpected error while preparing is BROKER_UNAVAILABLE (503), not 'unknown'",
      isinstance(e, PC.CloseRefused) and e.code == "BROKER_UNAVAILABLE" and e.status == 503, repr(e))
check("with the claim released", released == ["rid-1"], str(released))
check("and 'nothing was sent' said", "nothing was sent" in getattr(e, "detail", ""), getattr(e, "detail", ""))

# ── 3. the submit itself failing keeps the claim ────────────────────────────
print("\n[3] an exception from the submit may mean it filled: the claim stays")
e = run(position_id="7", connection_fn=ok_conn, broker_fn=lambda: Broker(exc=TimeoutError("no response")))
check("CloseUnknown", isinstance(e, PC.CloseUnknown), repr(e))
check("the claim was NOT released", released == [], str(released))

# ── 4. the default gate keys on account and integer id ──────────────────────
print("\n[4] the default gate's claim is per account and per integer id")
seen = []
_real = gates.authorize_close
gates.authorize_close = lambda uid, **kw: (seen.append(kw["position_id"]) or (_Dec(), "r"))
try:
    gates.authorize_platform_demo_close("u", position_id="0123", account="501")
    gates.authorize_platform_demo_close("u", position_id="123", account="502")
    gates.authorize_platform_demo_close("u", position_id="123")
finally:
    gates.authorize_close = _real
check("'0123' under account 501 -> '501:123'", seen[0] == "501:123", str(seen))
check("the same id under account 502 is a different claim", seen[1] == "502:123" and seen[0] != seen[1], str(seen))
check("without an account the old key is unchanged (other callers)", seen[2] == "123", str(seen))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All close-claim checks passed.")
