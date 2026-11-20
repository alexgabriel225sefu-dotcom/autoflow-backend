"""A missing cTrader account id must not surface as int(None).

Seen on the owner's phone: Orders and the market panel printed
"int() argument must be a string, a bytes-like object or a real number,
not NoneType", and Orders also said "No account selected" while the status
strip showed demo #47765456.

The id lives on the link record. A null on the user record, including next
to a stale token, has to use that link. When there really is no id, the
sentence says so — it does not pass None to int().

Run: python3 tests/test_missing_account_id.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-ctid-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name if not detail else f"{name} — {detail}")
        print(f"  FAIL {name} {detail}")


from apex.brokers.ctrader import account_id          # noqa: E402
from apex.platform import broker_read as BR          # noqa: E402
import apex.user_loop as UL                          # noqa: E402
import apex.platform.ctrader_link as CL              # noqa: E402

def _raises_value(value):
    try:
        account_id(value)
    except ValueError:
        return True
    except TypeError:
        return False
    return False


print("\n[1] int(None) is a sentence, not a TypeError")
try:
    account_id(None)
    check("None is refused", False, "it returned")
except ValueError as e:
    check("None says no account is selected",
          "no cTrader account is selected" in str(e), str(e))
    check("the TypeError text is gone", "NoneType" not in str(e), str(e))
except TypeError as e:
    check("None is not a TypeError", False, str(e))

check("a blank string is the same refusal", _raises_value(""))
check("zero is refused for a real read", _raises_value(0))
check("zero is the pre-auth socket", account_id(0, allow_zero=True) == 0)
check("the demo id the owner uses parses", account_id("47765456") == 47765456)
check("an int parses", account_id(47765456) == 47765456)

print("\n[2] a raw TypeError is rewritten before it reaches the screen")
text = BR._human_broker_fault(TypeError(
    "int() argument must be a string, a bytes-like object or a real number, "
    "not 'NoneType'"))
check("the phone no longer sees NoneType", "NoneType" not in text, text)
check("it says the id was missing", "account id was missing" in text, text)
other = BR._human_broker_fault(TimeoutError("cTrader: no response"))
check("a real broker fault is kept", "no response" in other, other)

print("\n[3] a null on the user record still finds the linked account")
def _link(user_id, ctid=None, **_kw):
    return {"accessToken": "platform-token", "ctid": ctid or 47765456,
            "mode": "demo"}


CL.get_ctrader_connection = _link
user = {"paper": True, "ctrader_access_token": "stale-token",
        "ctrader_account_id": None, "leverage": 30}
_broker, cfg = UL._make_broker(dict(user), "user-1")
check("the link id is the one the broker will use",
      str(cfg.CTRADER_ACCOUNT_ID) == "47765456", repr(cfg.CTRADER_ACCOUNT_ID))
check("the env is demo, not None", cfg.CTRADER_ENV == "demo", repr(cfg.CTRADER_ENV))
check("a platform connection is not paper", cfg.PAPER_TRADING is False)

_, bare = UL._make_broker({"paper": False})
check("no user id still leaves the id empty — nothing to look up",
      bare.CTRADER_ACCOUNT_ID == "", repr(bare.CTRADER_ACCOUNT_ID))

print("\n[4] building the broker does not raise TypeError")
try:
    from apex.brokers.ctrader import CtraderBroker
    b = CtraderBroker(cfg)
    got = b._ctid()
    check("the broker reads 47765456", got == 47765456, repr(got))
except TypeError as e:
    check("broker construction is not a TypeError", False, str(e))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All missing-account-id checks passed.")
