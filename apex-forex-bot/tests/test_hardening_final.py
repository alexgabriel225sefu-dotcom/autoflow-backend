"""Failure-injection regressions for the final production hardening.

Each check below corresponds to a defect that was live, and each one is
written so that putting the defect back makes it fail. Grouped by what the
failure costs.

  * LICENCE VERIFICATION FAILED OPEN ON A DATABASE OUTAGE. The server checked
    the HMAC signature first, then consulted Supabase for whether the key was
    actually paid for — and swallowed any DB error with a comment that said
    "fall through to fail-open allow below". The comment ten lines above it is
    the one that was right: "a valid signature is NOT proof of payment". A
    refunded customer, an expired trial and a never-paid checkout all hold a
    permanently valid signature, so for the duration of any Supabase outage
    all three verified as active.

  * ...AND THE FIX HAD TO NOT REVOKE ANYONE. The bot re-checks a granted
    client's licence every 12h and revokes on {valid:false}. The 503 that now
    carries that body would have revoked every paying customer for the length
    of the outage. First activation and revalidation must fail in OPPOSITE
    directions — a stranger with an unverifiable key gets nothing; an
    already-verified client with an unverifiable key keeps what they have.

  * A COMMITTED ENCRYPTION KEY. `_botConfigKey()` fell back to the literal
    'bot-cfg-fallback-change-me' when no secret was configured. That key
    encrypts client bot configs at rest, so anyone who could read both this
    repository and the bot_configs table could decrypt all of them.

  * A PER-PROCESS JWT SECRET IN PRODUCTION. The fallback minted a random
    secret per boot. Since the same secret derives the config encryption key,
    a restart made stored configs undecryptable and two instances could not
    read each other's — data loss wearing a warning label.

  * HARDCODED OPERATOR IDENTITY. Payment and fulfilment alerts fell back to
    one person's Telegram id and personal email, so an unconfigured
    deployment silently delivered another operator's alerts to them.

  * CRYPTO REMOVED, NOT DISABLED. A disabled mode is still a mode: config
    refuses any PRODUCT but "forex", and the instrument gate refuses coins
    outright so a stored watchlist cannot put one back in the order path.

Run: python tests/test_hardening_final.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-hard-")

from apex import config as cfg, forex  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def read(*parts):
    p = os.path.join(*parts)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


SERVER = read(REPO, "server.js")
TG = read(ROOT, "apex", "telegram.py")

print("\n🔒  FINAL HARDENING — FAILURE INJECTION\n")

# ── 1. licence: unknown state denies ──────────────────────────────────────
print("1. An unverifiable licence is not a licence")
check("the fail-open fall-through is gone",
      "fall through to fail-open allow below" not in SERVER,
      "that comment marked the exact line that granted access on a DB error")
check("a licence-store error answers 503, not valid:true",
      "licence store unreachable" in SERVER and "status(503)" in SERVER,
      "a valid signature is not proof of payment; only the DB knows")
check("the deny is logged, not silent",
      re.search(r"addLog\(`verify-license: licence store unreachable", SERVER) is not None)

print("\n2. …but revalidation must not revoke a paying customer")
check("revalidation ignores a 5xx body", "if r.status_code >= 500:" in
      TG.split("def _revalidate_license")[1].split("\ndef ")[0],
      "the 503 carries valid:false; reading it without the status revokes everyone")
check("first activation still denies on 5xx",
      "if r.status_code >= 500:" in
      TG.split("def _license_ok")[1].split("\ndef ")[0])
check("the opposite directions are explained where they are decided",
      "opposite of _license_ok" in TG,
      "an asymmetry nobody documents gets 'fixed' into a symmetry later")

# ── 3. secrets ────────────────────────────────────────────────────────────
print("\n3. No production secret has a fallback")
# Assert on the CODE, not on prose: the literal is named in the comment that
# explains why it was removed, so a bare substring test would fail on its own
# explanation (and would pass on a file that merely stopped mentioning it).
check("the committed config-encryption key is not used as a value",
      "|| 'bot-cfg-fallback-change-me'" not in SERVER
      and '|| "bot-cfg-fallback-change-me"' not in SERVER,
      "it encrypts client bot configs at rest")
check("config encryption refuses rather than improvises",
      "bot config encryption unavailable" in SERVER)
check("production refuses to start without JWT_SECRET",
      "[FATAL] JWT_SECRET is not set" in SERVER and "process.exit(1)" in SERVER,
      "the same secret derives the config key — a per-boot value orphans data")
for literal in ("apextrade-super-secret-key-change-in-prod",):
    check(f"no committed auth secret ({literal[:18]}…)",
          not any(literal in read(REPO, f) for f in os.listdir(REPO)
                  if f.endswith(".js")))

# ── 4. operator identity ──────────────────────────────────────────────────
print("\n4. No hardcoded operator identity")
check("no hardcoded Telegram operator id", "7585109158" not in SERVER)
check("no hardcoded operator email", "alexgabriel225sefu@gmail" not in SERVER)
check("an undeliverable alert is loud",
      "Admin alert UNDELIVERABLE" in SERVER,
      "an alert nobody receives is worse than no alert system")

# ── 5. crypto is removed, not disabled ────────────────────────────────────
print("\n5. Crypto cannot come back through a stored record")
check("PRODUCT accepts only forex", cfg.PRODUCT == "forex")
for sym in ("BTCUSD", "ETHUSD", "DOGEUSD", "SOLUSD", "BTCUSDT"):
    check(f"{sym} refused by the instrument gate",
          forex.is_tradeable(sym) is False,
          "a stored watchlist must not put a coin back in the order path")
check("crypto symbols are scrubbed from stored records",
      "BTCUSD" in cfg.CROSS_PRODUCT_BLOCK and "MATICUSD" in cfg.CROSS_PRODUCT_BLOCK)
check("the Auto-Pilot universe is forex only",
      all(forex.is_tradeable(s) for s in cfg.AUTOPILOT_UNIVERSE),
      f"{cfg.AUTOPILOT_UNIVERSE} contains something the order path refuses")
check("no crypto SKU can be bought", "'apex-crypto':" not in SERVER)
check("paid fulfilment refuses an unknown product",
      "REFUSED fulfilment for unknown product" in SERVER,
      "defaulting to the crypto branch mints a key for a bot that is gone")

# ── 6. no second execution path ───────────────────────────────────────────
print("\n6. There is one deployable trading path")
for gone in ("apex-crypto-bot", "apex-trade-bot", "apex-trade-api",
             "apex-trade-web", "apex-trade-mobile", "apex-trade-ml"):
    check(f"{gone}/ is gone", not os.path.isdir(os.path.join(REPO, gone)))
check("the root railway.json that deployed the legacy API is gone",
      not os.path.exists(os.path.join(REPO, "railway.json")))
check("the source-download route is gone", "app.get('/bot-access'" not in SERVER,
      "it streamed trading-bot source to any valid key holder")
wf = os.path.join(REPO, ".github", "workflows")
# Parse the workflow rather than regex it — `- name:` also matches every step.
try:
    import yaml
    _pub = yaml.safe_load(read(wf, "docker-publish.yml"))
    _matrix = [e.get("name") for e in
               _pub["jobs"]["build"]["strategy"]["matrix"]["include"]]
except Exception as _e:                      # noqa: BLE001
    _matrix = [f"unparseable: {_e}"]
check("CI publishes exactly one bot image", _matrix == ["apex-forex"],
      f"matrix builds {_matrix}")
check("no workflow deploys a legacy bot",
      not os.path.exists(os.path.join(wf, "deploy-bot.yml")))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — hardening regressions covered.")
