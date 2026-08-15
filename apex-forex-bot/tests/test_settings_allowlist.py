"""Configuration mutation must be an allowlist, not a free-for-all.

/setkeys accepted ANY key: it uppercased whatever was typed, wrote it to
os.environ, setattr'd it onto the live cfg module, and persisted it to
runtime.json. Nine keys had a type cast; everything else went through raw.

Admin-only is not a substitute for validation. The same path that let a typo
create a silently-ignored setting also accepted RISK_PER_TRADE=50 — five
thousand percent of balance per trade — with no complaint, because nothing
checked ranges. And a compromised or mistaken admin session had a generic
write primitive onto live trading configuration.

Covers the audit's checklist: unknown Telegram setting → rejected; invalid
setting type/range → rejected; secrets absent from audit output.

Run: python tests/test_settings_allowlist.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from apex import telegram as tg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def rejected(key, value):
    try:
        tg.validate_setting(key, value)
        return False
    except ValueError:
        return True


print("\n── unknown keys are refused ──")
for k in ("HACKED", "PATH", "TELEGRAM_BOT_TOKEN", "ADMIN_CHAT_ID",
          "TOKEN_ENCRYPTION_KEY", "DASHBOARD_TOKEN", "GROQ_API_KEY",
          "__class__", "risk_per_trade_typo"):
    check(f"{k} rejected", rejected(k, "x"))

print("\n── the settings that ARE allowed still work ──")
for k, v, want in (
    ("RISK_PER_TRADE", "0.02", 0.02),
    ("STOP_LOSS_PIPS", "35", 35.0),
    ("TAKE_PROFIT_PIPS", "70", 70.0),
    ("MIN_CONFIDENCE", "50", 50),
    ("CTRADER_ENV", "demo", "demo"),
    ("BROKER", "ctrader", "ctrader"),
    ("LEVERAGE", "30", 30.0),
    ("PAPER_TRADING", "false", False),
    ("PAPER_TRADING", "true", True),
    ("TRADE_SYMBOL", "eur_usd", "EURUSD"),
):
    try:
        ck, cv = tg.validate_setting(k, v)
        check(f"{k}={v} → {want!r}", cv == want, f"got {cv!r}")
    except ValueError as e:
        check(f"{k}={v} accepted", False, str(e))

print("\n── ranges are enforced, not just types ──")
check("RISK_PER_TRADE=50 rejected (5000% per trade)", rejected("RISK_PER_TRADE", "50"))
check("RISK_PER_TRADE=0 rejected", rejected("RISK_PER_TRADE", "0"))
check("RISK_PER_TRADE=-0.01 rejected", rejected("RISK_PER_TRADE", "-0.01"))
check("MIN_CONFIDENCE=150 rejected", rejected("MIN_CONFIDENCE", "150"))
check("MIN_CONFIDENCE=-1 rejected", rejected("MIN_CONFIDENCE", "-1"))
check("STOP_LOSS_PIPS=0 rejected", rejected("STOP_LOSS_PIPS", "0"))
check("LEVERAGE=100000 rejected", rejected("LEVERAGE", "100000"))

print("\n── malformed values are refused, not coerced to nonsense ──")
check("RISK_PER_TRADE=abc rejected", rejected("RISK_PER_TRADE", "abc"))
check("MIN_CONFIDENCE=nan rejected", rejected("MIN_CONFIDENCE", "nan"))
check("RISK_PER_TRADE=inf rejected", rejected("RISK_PER_TRADE", "inf"))
check("CTRADER_ENV=production rejected", rejected("CTRADER_ENV", "production"))
check("BROKER=oanda rejected", rejected("BROKER", "oanda"))
check("PAPER_TRADING=maybe rejected", rejected("PAPER_TRADING", "maybe"))
check("TRADE_SYMBOL=X rejected (too short)", rejected("TRADE_SYMBOL", "X"))
check("TRADE_SYMBOL with a path rejected", rejected("TRADE_SYMBOL", "../../etc/passwd"))

print("\n── credentials are a separate category ──")
check("client id is recognised as a secret", tg.is_secret_key("CTRADER_CLIENT_SECRET"))
check("risk is not a secret", tg.is_secret_key("RISK_PER_TRADE") is False)
check("a too-short secret is rejected", rejected("CTRADER_CLIENT_SECRET", "abc"))
check("a secret with whitespace is rejected",
      rejected("CTRADER_CLIENT_SECRET", "has space in it"))
try:
    _k, _v = tg.validate_setting("CTRADER_CLIENT_SECRET", "s" * 32)
    check("a well-formed secret is accepted", _v == "s" * 32)
except ValueError as e:
    check("a well-formed secret is accepted", False, str(e))

print("\n── secret VALUES never reach a message or an audit record ──")
shown = tg._safe_repr("CTRADER_CLIENT_SECRET", "supersecretvalue123")
check("the secret value is not echoed", "supersecret" not in shown, shown)
check("it shows as ***", shown == "***", shown)
check("a non-secret is shown in full",
      tg._safe_repr("RISK_PER_TRADE", 0.02) == "0.02")

print("\n── _apply refuses unknown keys too, not just the command path ──")
try:
    tg._apply("SOMETHING_NEW", "1")
    check("_apply rejects an unknown key", False, "it accepted one")
except ValueError:
    check("_apply rejects an unknown key", True)
check("and the rejected key was not written to the environment",
      os.environ.get("SOMETHING_NEW") is None)

print("\n── _apply installs the COERCED type, not the raw string ──")
tg._apply("PAPER_TRADING", "false")
check("PAPER_TRADING became a real bool",
      tg.cfg.PAPER_TRADING is False, repr(tg.cfg.PAPER_TRADING))
tg._apply("RISK_PER_TRADE", "0.015")
check("RISK_PER_TRADE became a float",
      isinstance(tg.cfg.RISK_PER_TRADE, float) and tg.cfg.RISK_PER_TRADE == 0.015,
      repr(tg.cfg.RISK_PER_TRADE))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL SETTINGS-ALLOWLIST CHECKS PASSED.")
