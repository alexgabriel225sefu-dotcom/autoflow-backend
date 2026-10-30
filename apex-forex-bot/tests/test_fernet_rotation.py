"""TOKEN_ENCRYPTION_KEY can be rotated without losing stored broker tokens.

FOUND BY THE SECURITY AUDIT. One key encrypted and decrypted everything, so
rotating it made every stored token unreadable at once (decrypt_value returns
"" for ciphertext it cannot open). TOKEN_ENCRYPTION_OLD_KEYS now lists retired
keys accepted for DECRYPTION only; TOKEN_ENCRYPTION_KEY still encrypts.

Each phase runs in its own process because user_store builds its cipher at
import, exactly as a deploy does. The keys below are SYNTHETIC, generated for
this file, and must never be configured anywhere.

WHAT THESE TESTS WILL NOT ACCEPT

* A value written under the old key unreadable after rotation.
* New values written under a retired key.
* A retired key alone opening values written after rotation.
* Ciphertext handed out when no configured key opens it.

Run: python3 tests/test_fernet_rotation.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OLD = "f8Y1Jm4jvR3x3e1m2V9QeQ8b5iXo6t3m0q2bS1YkZ2U="          # SYNTHETIC
NEW = "Qm9vVGVzdE9ubHlOb3RBUmVhbEtleUZvclJvdGF0aW8="          # SYNTHETIC

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def run(code, *, key, old=None):
    env = dict(os.environ, TOKEN_ENCRYPTION_KEY=key, APP_ENV="test",
               ALLOW_LOCAL_BACKEND_DEV="true", PRODUCT="forex",
               DATA_DIR=tempfile.mkdtemp(prefix="a4t-rot-"))
    env.pop("TOKEN_ENCRYPTION_OLD_KEYS", None)
    if old:
        env["TOKEN_ENCRYPTION_OLD_KEYS"] = old
    for k in ("REDIS_URL", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        env.pop(k, None)
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r)\nfrom apex import user_store as U\n"
         % ROOT + code],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return r.stdout.strip().splitlines()[-1]


print("\n[1] write under the old key")
ct_old = run("print(U.encrypt_value('SAMPLE-TOKEN-SAMPLEONLY'))", key=OLD)
check("encrypted", ct_old.startswith("enc:"), ct_old[:10])

print("\n[2] rotate: new key encrypts, old key still decrypts")
out = run(f"print(U.decrypt_value({ct_old!r}))", key=NEW, old=OLD)
check("old ciphertext opens after rotation", out == "SAMPLE-TOKEN-SAMPLEONLY",
      out)
ct_new = run("print(U.encrypt_value('NEW-TOKEN-SAMPLEONLY'))", key=NEW, old=OLD)
out = run(f"print(U.decrypt_value({ct_new!r}))", key=NEW)
check("new values are written under the NEW key", out == "NEW-TOKEN-SAMPLEONLY",
      out)
out = run(f"print(repr(U.decrypt_value({ct_new!r})))", key=OLD)
check("the retired key alone cannot open them", out == "''", out)

print("\n[3] without the old key listed, old values read as absent")
out = run(f"print(repr(U.decrypt_value({ct_old!r})))", key=NEW)
check("absent, never ciphertext", out == "''", out)

print("\n[4] several retired keys, comma-separated with spaces")
out = run(f"print(U.decrypt_value({ct_old!r}))", key=NEW,
          old=f" {NEW} , {OLD} ")
check("opens", out == "SAMPLE-TOKEN-SAMPLEONLY", out)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All Fernet rotation checks passed.")
