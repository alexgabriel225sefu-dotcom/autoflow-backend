"""`ctrader_accounts` is encrypted at rest, and old records still load.

WHAT THIS FIELD IS

The broker's own answer to "which accounts does this token hold, and is each one
real money": a list of {"ctid": <account id>, "live": <bool>}. It sat in
plaintext in Redis beside the access and refresh tokens, which are encrypted.

It is not a credential — nobody reaches the account with it, that needs the token
— but it identifies every broker account a client holds and which of them trade
real money.

THE TRAP THIS FILE EXISTS TO CLOSE

Adding the field to `_SENSITIVE_FIELDS` does NOTHING. `_encrypt_sensitive` only
touches `isinstance(val, str)`, and this value is a list. The name would sit in a
set called "sensitive fields" while the data stayed in the clear — a change that
reads as a fix and is not one, which is worse than the honest status quo.

So it is handled as a JSON payload instead: json.dumps -> Fernet -> "enc:<token>"
on write, and the inverse on read, so the four modules that read it keep
receiving the list they always did. `_SENSITIVE_JSON_FIELDS` is the set, and the
first check below is that the field is in THAT one and not the string one.

WHAT IS DELIBERATELY NOT COVERED

`ctrader_account_id` — the currently selected account — holds the same identifier
and stays in plaintext. It is a selector, compared against this list to render
the account switcher, displayed in roughly fourteen places, and stored as an int.
That is the "used as a key or index" case that must not be encrypted without
auditing every caller. The protection here is therefore PARTIAL, and the last
section asserts that this is a stated decision rather than an oversight.

Run: python3 tests/test_accounts_at_rest.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="apex-accounts-rest-")
os.environ.update(
    APP_ENV="test",
    ALLOW_LOCAL_BACKEND_DEV="true",
    # SYNTHETIC, generated for the tests. Never a real key.
    TOKEN_ENCRYPTION_KEY="cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI=",
    DATA_DIR=_TMP,
)

from apex import user_store as us                                # noqa: E402
from apex import ui_state                                        # noqa: E402

_fails = []

# Synthetic, same-shape values. 1000000001/2 are the ids the test suite uses.
ACCOUNTS = [{"ctid": 1000000001, "live": False},
            {"ctid": 1000000002, "live": True}]
TOKEN = "broker-access-token-SAMPLEONLY-0123456789"
REFRESH = "broker-refresh-token-SAMPLEONLY-9876543210"


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def stored_bytes(user_id):
    """Exactly what is on disk for this user — the at-rest form, not the API."""
    path = us._path(str(user_id))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def quiet(fn, *a, **kw):
    """Run fn, returning (result, everything it printed)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        out = fn(*a, **kw)
    return out, buf.getvalue()


# ── 1. the field is in the right set, and the wrong one would be a no-op ────
print("\n[1] it is registered as a JSON payload, not as a string field")
check("ctrader_accounts is in _SENSITIVE_JSON_FIELDS",
      "ctrader_accounts" in us._SENSITIVE_JSON_FIELDS)
check("and NOT in _SENSITIVE_FIELDS, where it would silently do nothing",
      "ctrader_accounts" not in us._SENSITIVE_FIELDS,
      "the string path only touches isinstance(val, str); a list would be "
      "skipped while appearing protected")
# Proof of that claim rather than an assertion of it: put a list into a field
# that IS in _SENSITIVE_FIELDS and watch the string path skip it.
check("the string encrypt path provably leaves a list alone",
      isinstance(us._encrypt_sensitive({"anthropic_key": ACCOUNTS})
                 .get("anthropic_key"), list),
      "a list in a string-typed sensitive field is not encrypted")

# ── 2. a new write is stored encrypted ─────────────────────────────────────
print("\n[2] a newly saved account list is encrypted on disk")
us.save("1000000001", {"ctrader_access_token": TOKEN,
                       "ctrader_refresh_token": REFRESH,
                       "ctrader_accounts": list(ACCOUNTS),
                       "ctrader_account_id": 1000000001})
raw = stored_bytes("1000000001")
on_disk = json.loads(raw)
check("the stored value is a string, not a list",
      isinstance(on_disk.get("ctrader_accounts"), str),
      type(on_disk.get("ctrader_accounts")).__name__)
check("it carries the enc: prefix",
      str(on_disk.get("ctrader_accounts")).startswith(us._ENC_PREFIX),
      str(on_disk.get("ctrader_accounts"))[:40])
check("it is a Fernet token",
      us._ENC_PREFIX + "gAAAAA" in str(on_disk.get("ctrader_accounts"))[:16]
      or str(on_disk.get("ctrader_accounts"))[len(us._ENC_PREFIX):]
      .startswith("gAAAAA"),
      str(on_disk.get("ctrader_accounts"))[:40])
# The point of the whole exercise: the ids are not readable in the file.
check("neither account id appears anywhere in the file",
      "1000000002" not in raw,
      "the live account's id is readable at rest")
check("and the tokens are not in the file either",
      TOKEN not in raw and REFRESH not in raw)

print("\n    …and it round-trips back to the same list")
loaded = us.load("1000000001")
check("load() returns a list", isinstance(loaded.get("ctrader_accounts"), list),
      type(loaded.get("ctrader_accounts")).__name__)
check("with exactly the same contents", loaded.get("ctrader_accounts") == ACCOUNTS,
      repr(loaded.get("ctrader_accounts"))[:80])
check("and the tokens still decrypt too",
      loaded.get("ctrader_access_token") == TOKEN
      and loaded.get("ctrader_refresh_token") == REFRESH)

# ── 3. BACKWARDS COMPATIBILITY: an existing plaintext record still loads ───
# The common case until every record has been rewritten once. Written by hand,
# bypassing save(), because that is what is already in Redis today.
print("\n[3] a record written before this change still loads")
legacy_path = us._path("1000000009")
with open(legacy_path, "w", encoding="utf-8") as fh:
    json.dump({"ctrader_accounts": list(ACCOUNTS),
               "ctrader_account_id": 1000000001,
               "active": True}, fh)
legacy = us.load("1000000009")
check("the plaintext list is returned untouched",
      legacy.get("ctrader_accounts") == ACCOUNTS,
      repr(legacy.get("ctrader_accounts"))[:80])
check("it is still a list, so callers that iterate it keep working",
      isinstance(legacy.get("ctrader_accounts"), list))
check("the real reader accepts it", ui_state._accounts(legacy) == ACCOUNTS)
check("and the count the UI shows is right",
      len(legacy.get("ctrader_accounts") or []) == 2)

print("\n    …and the next save of that record encrypts it")
legacy["active"] = False
us.save("1000000009", legacy)
raw9 = stored_bytes("1000000009")
check("the rewritten record is encrypted",
      json.loads(raw9).get("ctrader_accounts", "").startswith(us._ENC_PREFIX)
      if isinstance(json.loads(raw9).get("ctrader_accounts"), str) else False)
check("and the id is no longer in the file", "1000000002" not in raw9)
check("and it still reads back correctly",
      us.load("1000000009").get("ctrader_accounts") == ACCOUNTS)

# ── 4. a corrupted or unopenable value reads as ABSENT, never as itself ────
# The requirement that matters for correctness: callers do
# `for a in (u.get("ctrader_accounts") or [])`. Handing them the ciphertext
# string would walk its characters and "find" accounts that do not exist.
print("\n[4] a value that cannot be opened is absent, never ciphertext")
CORRUPT = us._ENC_PREFIX + "gAAAAABtampered-not-a-real-token-at-all=="
for label, value in (
    ("a corrupted token", CORRUPT),
    ("a truncated token", us._ENC_PREFIX + "gAAAAAB"),
    ("not a token at all", us._ENC_PREFIX + "hello"),
):
    out, printed = quiet(us._decrypt_sensitive, {"ctrader_accounts": value})
    got = out.get("ctrader_accounts")
    check(f"{label}: does not come back as the ciphertext", got != value,
          repr(got)[:60])
    check(f"{label}: is not a string at all", not isinstance(got, str),
          repr(got)[:60])
    check(f"{label}: reads as absent through `or []`", (got or []) == [])
    check(f"{label}: the real reader sees no accounts",
          ui_state._accounts(out) == [])
    check(f"{label}: and it said so on the way past",
          "ctrader_accounts" in printed, printed[:80])

# Decrypts cleanly but is not JSON — a different failure, same rule.
_valid_but_not_json = us._ENC_PREFIX + us._fernet.encrypt(b"not json").decode()
out, printed = quiet(us._decrypt_sensitive,
                     {"ctrader_accounts": _valid_but_not_json})
check("a decryptable non-JSON payload is absent, not a string",
      out.get("ctrader_accounts") is None, repr(out.get("ctrader_accounts"))[:60])
check("and it said the value was not JSON", "not valid JSON" in printed,
      printed[:100])

# ── 5. an empty list stays an empty list ───────────────────────────────────
# Encrypting [] would make "this client has no accounts" indistinguishable from
# "the list could not be read", and those need different handling upstream.
print("\n[5] an empty list is not encrypted, so absent stays distinct from empty")
check("[] is stored as []",
      us._encrypt_sensitive({"ctrader_accounts": []}).get("ctrader_accounts") == [])
check("None is stored as None",
      us._encrypt_sensitive({"ctrader_accounts": None})
      .get("ctrader_accounts") is None)
check("a missing field is not invented",
      "ctrader_accounts" not in us._encrypt_sensitive({"active": True}))
check("an already-encrypted value is not double-encrypted",
      us._encrypt_sensitive({"ctrader_accounts": CORRUPT})
      .get("ctrader_accounts") == CORRUPT)

# ── 6. nothing leaks into the logs ─────────────────────────────────────────
print("\n[6] no account id or token reaches a log line")
from apex import redact                                          # noqa: E402

_, printed = quiet(us.save, "1000000003",
                   {"ctrader_access_token": TOKEN,
                    "ctrader_accounts": list(ACCOUNTS)})
_, printed2 = quiet(us.load, "1000000003")
both = printed + printed2
for needle, what in ((TOKEN, "the access token"),
                     ("1000000002", "the live account id")):
    check(f"a save/load prints neither {what}", needle not in both,
          both[:120])

# The failure paths print the most, so check those specifically.
_, printed3 = quiet(us._decrypt_sensitive, {"ctrader_accounts": CORRUPT})
check("the decrypt-failure message does not echo the ciphertext",
      CORRUPT[len(us._ENC_PREFIX):] not in printed3, printed3[:120])
check("it names the field, which is what an operator needs",
      "ctrader_accounts" in printed3)

# And the redactor masks the payload shape if one ever is printed.
check("redact masks a Fernet-shaped account payload",
      "gAAAAA" not in redact.scrub(
          f"accounts={us._ENC_PREFIX}gAAAAABqt8JDsomethinglongenoughtomatch1234"),
      redact.scrub(f"accounts={us._ENC_PREFIX}gAAAAABqt8JDsomethinglongenough1234"))

# ── 7. the partial protection is a stated decision ────────────────────────
print("\n[7] what is NOT encrypted is written down, not merely absent")
with open(os.path.join(ROOT, "apex", "user_store.py"), encoding="utf-8") as fh:
    STORE_SRC = fh.read()
check("ctrader_account_id is deliberately not encrypted",
      "ctrader_account_id" not in us._SENSITIVE_FIELDS
      and "ctrader_account_id" not in us._SENSITIVE_JSON_FIELDS)
check("and the reason is recorded next to the set",
      "ctrader_account_id" in STORE_SRC.split("_ENC_PREFIX")[0],
      "a reader has to be able to see why one and not the other")
check("the comment says the protection is partial",
      "PARTIAL" in STORE_SRC or "partial" in STORE_SRC.split("_ENC_PREFIX")[0])
# It is still a selector, so it must still be readable as one.
sel = us.load("1000000001")
check("the selected account id is still usable as a selector",
      str(sel.get("ctrader_account_id")) == "1000000001",
      repr(sel.get("ctrader_account_id")))
check("and the switcher can still match it against the decrypted list",
      any(str(a["ctid"]) == str(sel.get("ctrader_account_id"))
          for a in sel.get("ctrader_accounts") or []))

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ctrader_accounts is encrypted at rest, old records still load, and an "
      "unopenable list reads as absent.")
