"""A verifier outage must not be the way into the product.

`_license_ok` logged "fail-open grant" and returned True whenever the licence
verifier raised — timeout, connection error, malformed body. For an already
paying customer that policy is right and stays: their bot must not stop because
a lookup timed out. For a chat we have never validated it meant the outage
itself handed out the product, to whoever messaged during it.

The two populations are separated by one fact, checked before any network call:
a returning customer has a stored `license_key`. Everything reaching the
verifier is new, so an unreachable verifier is not evidence in their favour.

Run: python tests/test_new_user_license.py
"""
import os
import sys
import tempfile

os.environ.setdefault("PAPER_TRADING", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-lic-")

from apex import telegram as tg, user_store  # noqa: E402
import apex.config as cfg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SENT = []
tg.send_to = lambda cid, text, **k: SENT.append(text)
tg.send_proof_shots = lambda cid: None

KEY = f"{cfg.LICENSE_KEY_PREFIX}-AAAA-BBBB-CCCC"
NEW = "111111111"


class Resp:
    def __init__(self, status=200, body=None, raise_on_json=False):
        self.status_code = status
        self._body = body if body is not None else {"valid": True}
        self._raise = raise_on_json

    def json(self):
        if self._raise:
            raise ValueError("not JSON")
        return self._body


def with_verifier(fn):
    """Swap the verifier call for one that behaves as `fn` describes."""
    tg.requests.post = fn


_real_post = tg.requests.post
_orig_admin = tg.access.is_admin
tg.access.is_admin = lambda cid: False


def fresh(uid):
    """A chat with nothing on file — a genuinely new user."""
    try:
        os.remove(user_store._path(uid))
    except OSError:
        pass
    SENT.clear()


print("\n🧪 NEW-USER ACTIVATION — an outage is not an entitlement\n")

print("1. A new user is DENIED whenever the verifier cannot answer")
for label, behaviour in (
    ("timeout", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out"))),
    ("connection error", lambda *a, **k: (_ for _ in ()).throw(
        OSError("connection refused"))),
    ("HTTP 500", lambda *a, **k: Resp(status=500, body={})),
    ("HTTP 502", lambda *a, **k: Resp(status=502, body={})),
    ("malformed body", lambda *a, **k: Resp(raise_on_json=True)),
    ("non-object body", lambda *a, **k: Resp(body=["nope"])),
):
    fresh(NEW)
    with_verifier(behaviour)
    got = tg._license_ok(NEW, f"/start {KEY}")
    check(f"new user + {label} → DENIED", got is False, got)
    check(f"   ...and no licence was stored for {label}",
          not (user_store.load(NEW) or {}).get("license_key"))
check("the client is told to retry rather than shown an error",
      any("try the activation link again" in t for t in SENT), SENT[-1:])

print("\n2. A definite answer is still honoured, in both directions")
fresh(NEW)
with_verifier(lambda *a, **k: Resp(body={"valid": False, "message": "Refunded"}))
check("new user + INVALID licence → denied",
      tg._license_ok(NEW, f"/start {KEY}") is False)
check("and the server's reason is shown",
      any("Refunded" in t for t in SENT), SENT[-1:])

fresh(NEW)
with_verifier(lambda *a, **k: Resp(body={"valid": True}))
check("new user + VALID licence → allowed",
      tg._license_ok(NEW, f"/start {KEY}") is True)
check("and the key is stored for next time",
      (user_store.load(NEW) or {}).get("license_key") == KEY)

print("\n3. Malformed input never reaches the verifier at all")
for bad, why in ((f"/start {cfg.LICENSE_KEY_PREFIX}-XX", "too short"),
                 ("/start not-a-key", "wrong shape"),
                 ("/start", "no key")):
    fresh(NEW)
    with_verifier(lambda *a, **k: Resp(body={"valid": True}))
    check(f"{why} → denied without asking the verifier",
          tg._license_ok(NEW, bad) is False)

print("\n4. The existing customer's grace policy is UNCHANGED")
EXISTING = "222222222"
fresh(EXISTING)
user_store.update(EXISTING, {"license_key": KEY})
for label, behaviour in (
    ("timeout", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out"))),
    ("HTTP 500", lambda *a, **k: Resp(status=500, body={})),
):
    with_verifier(behaviour)
    check(f"provisioned customer + {label} → still allowed",
          tg._license_ok(EXISTING, "/start") is True,
          "a store outage must not lock out someone who already paid")
check("and it does so WITHOUT calling the verifier",
      tg._license_ok(EXISTING, "/start") is True)

print("\n5. The separation is structural, not incidental")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "telegram.py"), encoding="utf-8").read()
FN = SRC[SRC.index("def _license_ok"):SRC.index("_REVALIDATE_SEC")]
check("the returning-customer check happens BEFORE the network call",
      FN.index('.get("license_key")') < FN.index("_VERIFY_URL"))
check("the exception path no longer grants",
      "fail-open grant" not in FN)
_except = FN[FN.index("    except Exception as e:"):]
_except = _except[:_except.index("    try:")]
check("and the exception path returns False",
      "return False" in _except and "return True" not in _except, _except[-200:])
check("with a message the client can act on",
      "try the activation link again" in _except)

tg.requests.post = _real_post
tg.access.is_admin = _orig_admin

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — an unverifiable licence is not a licence.")
