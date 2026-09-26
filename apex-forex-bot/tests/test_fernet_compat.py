"""Broker tokens encrypted by an older `cryptography` still open. Proved.

WHY THIS FILE EXISTS

`apex/user_store.py` is the only thing in this repository that uses the
`cryptography` package, and it uses one piece of it: Fernet, to encrypt broker
access tokens, refresh tokens and AI keys at rest. Those ciphertexts live in
Redis. They are not re-encrypted on deploy.

So a `cryptography` bump has a failure mode that no ordinary test would catch:
the new version encrypts and decrypts perfectly, every round-trip in the suite
passes, and the tokens already sitting in the store stop opening. The visible
symptom would be every connected client silently losing their broker connection
at once, with `decrypt_value` doing exactly what it is documented to do —
returning "" rather than handing out ciphertext — so the logs would say a secret
was "treated as absent" and nothing would say why.

Round-tripping on the installed version cannot detect that. The only thing that
can is a ciphertext produced by the OLD version, frozen into the repository, and
opened by whatever version is installed now.

THE VECTORS BELOW ARE SYNTHETIC. READ THIS BEFORE REACTING TO THEM.

`FERNET_KEY` and `PRE_BUMP` look like a leaked key and leaked broker tokens.
They are not. The key was generated for this file and is used nowhere else; the
plaintexts are obvious placeholders ending in "SAMPLEONLY", and the account id
inside the accounts payload is the synthetic 1000000001 used throughout the
tests, not anybody's account. Nothing here decrypts anything real, and this key
must never be set as TOKEN_ENCRYPTION_KEY anywhere.

They are committed deliberately: a vector regenerated at test time under the
current version proves nothing about cross-version compatibility, which is the
entire point. Fernet's wire format is fixed by its specification — version byte
0x80, timestamp, IV, ciphertext, HMAC — so a frozen vector is the right
artifact, and if a future release ever breaks it, that is precisely the news
this file exists to deliver.

    Minted with: cryptography 42.0.8   (the pin before 2026-09-26)
    Bumped to:   cryptography 50.0.1

Run: python3 tests/test_fernet_compat.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# user_store refuses to import without a key, by design — it fails closed rather
# than storing credentials in plaintext. Set the test key before importing it.
# The local-backend and dev flags are the same preamble every store test uses;
# without them the module refuses to start on a non-shared backend, which is
# also by design.
FERNET_KEY = "cDcb_wSOjqAiI8jn9la_Vx3J1GpCVJyFlJXX6VYHHWI="   # SYNTHETIC
os.environ["TOKEN_ENCRYPTION_KEY"] = FERNET_KEY
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-fernet-compat-")

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# ── the frozen vectors ───────────────────────────────────────────────────────
# field -> (ciphertext minted under 42.0.8, the plaintext it must yield)
PRE_BUMP = {
    "ctrader_access_token": (
        "gAAAAABqt8JDlHnyxHD79BHVm-1-ffMziW7OAVY83Nen4yDt5PmaR-nb9m8y1OL465HX"
        "i911DZLKN4rzvS3ChkIFLpEdfa4JkBQwl0qcD7DSv5mZa0CS5vNzGcDFR0WeU09ScLL4"
        "1jHq",
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890-SAMPLEONLY"),
    "ctrader_refresh_token": (
        "gAAAAABqt8JD0XeBR9cQ07PZknS7M25otmPigzYy-ovuJrdHqYGP11nHe-RMWCcboAZI"
        "9-oX_B6U2WQBOYjsK2Zj3yiIIa5oHEn67dbGLyT5YBGifv_LMVfAYIqcdzDNREvqXH6R"
        "S4Fn",
        "r9z8y7x6-w5v4-3210-fedc-ba0987654321-SAMPLEONLY"),
    "ctrader_accounts": (
        "gAAAAABqt8JDhTaWvO9gzcFpEOCSdJ3WYY0f7Q9xDrLvJWyDi8C8nVTOWP5BybyTq-IQ"
        "nfmcMQ6F-PdFQkkmwSPMybRWq4UdBlejJoZRx5x0hslKSUCCqpUNYew4EmVDFrkt_3f7"
        "85E3_OUp6F2D03zVYiT65Do8fA==",
        '[{"ctidTraderAccountId": 1000000001, "isLive": false}]'),
    # Non-ASCII, because a text token that survives a bump byte-wise can still
    # come back wrong if anything in the decode path changed.
    "unicode": (
        "gAAAAABqt8JD5xmTz4dl1dy36w4dPF2KunAgR08sSEWkHVf7iVforQNeVpjog9mgsvBr"
        "wLjO_utKICp_hqyNAPpiE8Q6G3aJckDL47XgxYEBZG90c1N1i2R_AvTHpZ94KeP3smbm"
        "XHM2",
        "diacritice: ăîșțâ — and an em dash"),
}

print("\n[0] the installed version, for the record")
import cryptography                                             # noqa: E402
from cryptography.fernet import Fernet, InvalidToken            # noqa: E402

print(f"       cryptography {cryptography.__version__} "
      f"(vectors minted under 42.0.8)")
check("it is at or above the version that cleared every advisory",
      tuple(int(x) for x in cryptography.__version__.split(".")[:2]) >= (50, 0),
      f"{cryptography.__version__}: 49.0.0 still leaves PYSEC-2026-3552; "
      f"50.0.0 is the floor that clears it")

# ── 1. raw Fernet: the old ciphertext opens ─────────────────────────────────
print("\n[1] tokens minted under 42.0.8 decrypt on the installed version")
_f = Fernet(FERNET_KEY.encode())
for field, (token, plain) in PRE_BUMP.items():
    try:
        got = _f.decrypt(token.encode()).decode()
    except InvalidToken:
        check(f"{field} decrypts", False, "InvalidToken — STORED TOKENS ARE DEAD")
        continue
    check(f"{field} decrypts to exactly what was encrypted", got == plain,
          f"{got!r} != {plain!r}")

# ── 2. the product path: user_store.decrypt_value, prefix and all ───────────
# Raw Fernet passing is not the claim that matters. What is stored is
# `enc:<token>`, and what reads it is decrypt_value.
print("\n[2] the same tokens open through user_store, which is what reads them")
from apex import user_store                                     # noqa: E402

check("user_store configured its cipher from the key", user_store._fernet is not None,
      str(user_store._FERNET_ERROR))
for field, (token, plain) in PRE_BUMP.items():
    stored = user_store._ENC_PREFIX + token
    check(f"decrypt_value opens the stored {field}",
          user_store.decrypt_value(stored) == plain,
          repr(user_store.decrypt_value(stored))[:60])

# And through the whole-record path the loop actually calls.
record = {f: user_store._ENC_PREFIX + t for f, (t, _) in PRE_BUMP.items()
          if f in user_store._SENSITIVE_FIELDS}
# Named explicitly rather than "at least one": if either broker token were ever
# dropped from _SENSITIVE_FIELDS, this loop would quietly cover less while
# still reporting green, and the two fields it would stop covering are the two
# that are a live broker credential.
for must in ("ctrader_access_token", "ctrader_refresh_token"):
    check(f"{must} is in _SENSITIVE_FIELDS, so the record path covers it",
          must in record, f"covered: {sorted(record)}")
opened = user_store._decrypt_sensitive(dict(record))
for field in record:
    check(f"_decrypt_sensitive opens {field}",
          opened.get(field) == PRE_BUMP[field][1],
          repr(opened.get(field))[:60])

# ── 3. forwards: what this version writes, this version reads ───────────────
print("\n[3] and the installed version still round-trips its own output")
for field, (_, plain) in PRE_BUMP.items():
    check(f"{field} survives encrypt_value -> decrypt_value",
          user_store.decrypt_value(user_store.encrypt_value(plain)) == plain)
check("an empty string is left alone rather than encrypted",
      user_store.encrypt_value("") == "")
check("an already-encrypted value is not double-encrypted",
      user_store.encrypt_value(user_store._ENC_PREFIX + PRE_BUMP[
          "ctrader_access_token"][0]).count(user_store._ENC_PREFIX) == 1)

# ── 4. the bump must not have weakened authentication ──────────────────────
# A version that decrypted everything, including tampered input, would pass
# every check above. This is the one that would catch it.
print("\n[4] a tampered token is still rejected, not silently accepted")
_tok = PRE_BUMP["ctrader_access_token"][0]
for label, bad in (
    ("last four characters changed",
     _tok[:-4] + ("AAAA" if not _tok.endswith("AAAA") else "BBBB")),
    ("one byte flipped mid-ciphertext",
     _tok[:40] + ("X" if _tok[40] != "X" else "Y") + _tok[41:]),
    ("truncated", _tok[:-12]),
    ("not a Fernet token at all", "definitely-not-a-token"),
):
    try:
        _f.decrypt(bad.encode())
        check(f"rejected: {label}", False, "IT DECRYPTED — the MAC is not checked")
    except Exception:
        check(f"rejected: {label}", True)
    # And user_store turns that rejection into absence, never into ciphertext
    # handed back to a caller as if it were a credential.
    out = user_store.decrypt_value(user_store._ENC_PREFIX + bad)
    check(f"and user_store reports it absent, not as ciphertext: {label}",
          out == "", repr(out)[:60])

# ── 5. the key format did not change ───────────────────────────────────────
# A stored TOKEN_ENCRYPTION_KEY is a 32-byte urlsafe-base64 string in an
# environment variable. If a release changed what Fernet() accepts, every
# deployment would fail to boot — loudly, but at the worst moment.
print("\n[5] a key generated before the bump is still a valid key")
check("the frozen key loads", isinstance(Fernet(FERNET_KEY.encode()), Fernet))
check("and generate_key still produces something that loads",
      isinstance(Fernet(Fernet.generate_key()), Fernet))

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("Fernet is backwards compatible: tokens encrypted under cryptography "
      "42.0.8 open under " + cryptography.__version__ + ".")
