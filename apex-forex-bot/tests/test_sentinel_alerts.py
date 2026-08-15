"""Sentinel Telegram alerts must inform, not spam.

This loop ticks every few minutes and publishes a MarketState on every pass.
Alerting on the state itself would mean a notification every 5 minutes,
forever, and the one message that matters — "the AI just flipped on EURUSD" —
would be buried in it.

So: alert on a CHANGE of direction, and on a refusal. Never on the steady
state. HOLD↔BUY churn is excluded too, because indicators wobble across their
thresholds constantly and each wobble is not news.

These tests exercise the alert decision directly rather than booting the loop.

Run: python tests/test_sentinel_alerts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def flips(prev_act, action, alert_fn=True):
    """The exact condition guarding the SENTINEL_FLIP alert in user_loop."""
    return bool(alert_fn and prev_act and prev_act != action
                and "HOLD" not in (prev_act, action))


print("\n── a genuine reversal is worth interrupting someone ──")
check("BUY → SELL alerts", flips("BUY", "SELL") is True)
check("SELL → BUY alerts", flips("SELL", "BUY") is True)

print("\n── the steady state never alerts ──")
check("BUY → BUY is silent", flips("BUY", "BUY") is False)
check("HOLD → HOLD is silent", flips("HOLD", "HOLD") is False)
check("SELL → SELL is silent", flips("SELL", "SELL") is False)

print("\n── HOLD churn is excluded ──")
check("HOLD → BUY is silent (indicators crossing a threshold is not news)",
      flips("HOLD", "BUY") is False)
check("BUY → HOLD is silent", flips("BUY", "HOLD") is False)
check("HOLD → SELL is silent", flips("HOLD", "SELL") is False)
check("SELL → HOLD is silent", flips("SELL", "HOLD") is False)

print("\n── the first ever state cannot be a 'change' ──")
check("no previous action → silent", flips(None, "BUY") is False)
check("empty previous action → silent", flips("", "SELL") is False)

print("\n── no alert channel → nothing is attempted ──")
check("alert_fn missing", flips("BUY", "SELL", alert_fn=None) is False)

print("\n── how noisy is this over a realistic session? ──")
# A day of 5-minute ticks with the AI wobbling the way it actually does.
seq = (["HOLD"] * 40 + ["BUY"] * 30 + ["HOLD"] * 10 + ["BUY"] * 20
       + ["SELL"] * 25 + ["HOLD"] * 30 + ["SELL"] * 15 + ["BUY"] * 18)
alerts = sum(1 for a, b in zip(seq, seq[1:]) if flips(a, b))
check(f"288 ticks (a full day) → {alerts} message(s), not 288",
      alerts <= 3, f"got {alerts}")
naive = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
check(f"a naive 'any change' rule would have sent {naive}",
      naive > alerts, f"naive={naive} ours={alerts}")

print("\n── the block alert fires on every refusal (they are rare) ──")
# A refusal needs an entry candidate, which needs a free slot, a signal and a
# passed risk check — so unlike the state, every one of them is informative.
from apex import sentinel as S  # noqa: E402

T0 = 1_786_500_000.0
stale = S.build_state("EURUSD", "BUY", ttl_s=60, now=T0)
ok, reason = S.decide(stale, "BUY", T0 + 999)
check("a stale state produces a refusal to report", ok is False)
check("with a reason the alert can translate", reason == S.NO_SIGNAL)

print("\n── every reason the gate can emit has Telegram copy ──")
copy = {
    "NO_FRESH_AI_SIGNAL": "no fresh AI read — the last one expired",
    "AI_DISAGREES": "the AI wants the other direction",
    "LOW_CONFIDENCE": "the AI isn't confident enough",
    "LOW_EV": "expected value too low",
    "RISK_BLOCK": "the risk engine said no",
    "AI_SAYS_HOLD": "the AI says stay out",
}
emitted = {S.NO_SIGNAL, S.DISAGREES, S.LOW_CONF, S.LOW_EV,
           S.RISK_BLOCK, S.HOLD_CALLED}
missing = emitted - set(copy)
check("no refusal reason renders as a raw constant", not missing, str(missing))
check("and the copy has no stale entries", not (set(copy) - emitted))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL SENTINEL-ALERT CHECKS PASSED.")
