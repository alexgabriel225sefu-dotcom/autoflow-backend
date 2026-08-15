"""Broker secrets must not sit on disk in plaintext.

runtime.json is written whenever a client sets something through Telegram, and
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
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


SECRET = "s3cr3t-broker-credential-value"


def fresh(with_key):
    """Reload the modules under a chosen TOKEN_ENCRYPTION_KEY and DATA_DIR."""
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-rt-")
    if with_key:
        from cryptography.fernet import Fernet
        os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    else:
        os.environ.pop("TOKEN_ENCRYPTION_KEY", None)
    for m in ("apex.config", "apex.user_store", "apex.telegram", "apex.bot"):
        if m in sys.modules:
            del sys.modules[m]
    cfg = importlib.import_module("apex.config")
    us = importlib.import_module("apex.user_store")
    tg = importlib.import_module("apex.telegram")
    rt = os.path.join(os.environ["DATA_DIR"], "runtime.json")
    tg._RUNTIME = rt
    return cfg, us, tg, rt


print("\n── with a key: encrypted at rest, usable in memory ──")
cfg, us, tg, RT = fresh(with_key=True)
tg._save_runtime({"CTRADER_CLIENT_SECRET": SECRET, "RISK_PER_TRADE": 0.01})
raw = json.load(open(RT))
check("the secret is on disk", "CTRADER_CLIENT_SECRET" in raw)
check("but NOT in plaintext", SECRET not in json.dumps(raw), json.dumps(raw)[:120])
check("it is marked as encrypted",
      str(raw["CTRADER_CLIENT_SECRET"]).startswith("enc:"), str(raw)[:100])
check("non-secret settings stay readable", raw["RISK_PER_TRADE"] == 0.01)
check("reading it back gives the real value",
      tg._load_runtime()["CTRADER_CLIENT_SECRET"] == SECRET)
check("the raw reader does not decrypt",
      tg._load_runtime_raw()["CTRADER_CLIENT_SECRET"].startswith("enc:"))

print("\n── a second write does not undo the first ──")
tg._save_runtime({"RISK_PER_TRADE": 0.02})
raw2 = json.load(open(RT))
check("the untouched secret is still encrypted",
      str(raw2["CTRADER_CLIENT_SECRET"]).startswith("enc:"), str(raw2)[:120])
check("and still not in plaintext anywhere", SECRET not in json.dumps(raw2))
check("the new setting landed", raw2["RISK_PER_TRADE"] == 0.02)
check("and the secret still opens", tg._load_runtime()["CTRADER_CLIENT_SECRET"] == SECRET)

print("\n── a rotated or missing key never yields ciphertext as a credential ──")
enc = raw2["CTRADER_CLIENT_SECRET"]
cfg2, us2, tg2, RT2 = fresh(with_key=True)          # a DIFFERENT key
check("a value it cannot open reads as absent, not as ciphertext",
      us2.decrypt_value(enc) == "", us2.decrypt_value(enc)[:40])
_, us3, _, _ = fresh(with_key=False)                 # no key at all
check("no key at all → also absent", us3.decrypt_value(enc) == "")
check("plaintext still passes through untouched",
      us3.decrypt_value("plain-legacy-value") == "plain-legacy-value")

print("\n── without a key: refuse rather than write it in the clear ──")
cfg4, us4, tg4, RT4 = fresh(with_key=False)
tg4._save_runtime({"CTRADER_CLIENT_SECRET": SECRET, "STOP_LOSS_PIPS": 30})
raw4 = json.load(open(RT4))
check("the secret was NOT written", "CTRADER_CLIENT_SECRET" not in raw4, str(raw4))
check("nothing resembling it is on disk", SECRET not in json.dumps(raw4))
check("the ordinary setting still saved", raw4.get("STOP_LOSS_PIPS") == 30)

print("\n── every secret key is covered, not just the one tested ──")
for k in tg4._SETTABLE_SECRETS:
    check(f"{k} is treated as a secret", tg4.is_secret_key(k))
cfg5, us5, tg5, RT5 = fresh(with_key=True)
tg5._save_runtime({k: SECRET for k in tg5._SETTABLE_SECRETS})
blob = json.dumps(json.load(open(RT5)))
check("none of them are in plaintext", SECRET not in blob, blob[:160])

print("\n── the loader that applies them decrypts first ──")
BOT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "bot.py"), encoding="utf-8").read()
i = BOT.index("def _load_runtime_config")
seg = BOT[i:i + 1400]
check("bot.py decrypts before applying", "decrypt_value" in seg)
check("and does it before _apply_config",
      seg.index("decrypt_value") < seg.index("_apply_config"))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — no broker credential is written in the clear.")
