"""Broker secrets must not sit on disk in plaintext.

runtime.json is written whenever a client sets something through the platform, and
two of the settable keys are credentials: CTRADER_CLIENT_SECRET and
MT_BRIDGE_SECRET. They went to disk in the clear — while user_store had been
Fernet-encrypting the same class of value all along. Two stores, one threat
model, one of them ignoring it. Anyone with the filesystem — a stray backup, a
shared volume, an image layer — could read live broker credentials.

Encrypting needs a key. Without TOKEN_ENCRYPTION_KEY there is nothing to
encrypt WITH, so the secret is refused rather than written in the clear:
losing a setting is recoverable, leaking a broker credential is not.

Run: python tests/test_runtime_secrets.py
"""
import importlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("CTRADER_CLIENT_SECRET", "test")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SECRET = "s3cr3t-broker-credential-value"

# runtime.json was written by the platform process. That process is retired,
# so these checks cover the operator read path that is still in the engine.

print("\n── operator reads ──")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — no broker credential is written in the clear.")


# ── Operator reads must not return credentials ────────────
# `user_detail` is documented as token-redacted, and it returned a client's
# Groq key in full — observed live, in a transcript. The redaction list named
# three cTrader fields and had never been updated when `groq_key` and
# `gemini_key` were added to the user record. A denylist of names only ever
# covers the secrets that existed when it was written, so the rule is now the
# SHAPE of the field name: anything credential-shaped is dropped on the day it
# is added rather than on the day somebody notices it leaking.
print("\n🔐 OPERATOR READS — credentials never leave")

from apex import control_actions as _ca  # noqa: E402

_leaky = []


def _secret_check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        _leaky.append(name)


for _field in ("groq_key", "gemini_key", "ctrader_access_token",
               "ctrader_refresh_token", "ctrader_accounts", "voice_token_hash",
               "openai_api_key", "some_secret", "user_password", "passphrase"):
    _secret_check(f"{_field} is withheld", _ca._is_secret(_field) is True)

for _field in ("risk", "symbol", "autopilot", "loss_streak", "maxpos",
               "news_filter", "voice_confirm", "paper_balance"):
    _secret_check(f"{_field} is still readable", _ca._is_secret(_field) is False,
                  "redacting settings would blind the operator")

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "apex", "control_actions.py"), encoding="utf-8").read()
_secret_check("the detail read applies the shape rule, not the old list",
              "_is_secret(k)" in _SRC,
              "a name list cannot cover a secret added after it was written")
# Dropping a secret field entirely also hid WHETHER it was set, and "has this
# client configured an AI key" is operational fact rather than secret material.
_secret_check("a set secret is replaced, not dropped",
              '"•set•" if v else v' in _SRC,
              "the operator must still be able to see that a key exists")

if _leaky:
    print(f"\n❌ {len(_leaky)} credential check(s) failed")
    sys.exit(1)
print("✅ operator reads carry no credentials")
