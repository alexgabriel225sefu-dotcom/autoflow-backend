"""Production must never accept an OAuth callback it cannot attribute.

Two separate guarantees, and the file proves both:

  CONFIGURATION — `CTRADER_ALLOW_STATELESS_CALLBACK` re-enables a fallback
  that binds a callback carrying no usable state to whoever is mid-flow. That
  exists for one scenario: cTrader silently stops echoing `state` and
  onboarding breaks for everyone with no way in. It is a development-time
  diagnosis, not a production posture — in production an unsigned callback
  can wire one person's broker account to another person's chat. So the
  service refuses to START in that configuration rather than warning, because
  the setting is one environment variable and a variable left on after a
  debugging session is exactly how it ends up live.

  REPLAY — a signed state must be redeemable exactly once, and "I cannot
  prove it is unused" must count as used. In-process memory cannot see
  another container: instance A consumes it, Redis blips, instance B accepts
  the same state and links an account.

`_production` is patched rather than driven through the environment on
purpose. Reloading user_store under a production environment trips ITS
guards first — no encryption key, no shared backend — which are correct and
unrelated, and would leave this file testing them instead of this one.

Run: python tests/test_oauth_production_guard.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-oauth-")

from apex import ctrader_oauth as oauth, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


class env:
    """Pin the environment and the escape-hatch flag for one block."""

    def __init__(self, production, stateless):
        self.production, self.stateless = production, stateless

    def __enter__(self):
        self._prod, self._flag = oauth._production, oauth.ALLOW_STATELESS
        oauth._production = lambda: self.production
        oauth.ALLOW_STATELESS = self.stateless

    def __exit__(self, *a):
        oauth._production, oauth.ALLOW_STATELESS = self._prod, self._flag


def starts():
    try:
        oauth.assert_safe_config()
        return True
    except oauth.StatelessCallbackInProduction:
        return False


print("\n🔐 OAUTH — production cannot trust an unsigned callback\n")

print("1. Startup refuses the unsafe configuration")
with env(production=True, stateless=True):
    check("production + stateless=true does NOT start", starts() is False,
          "a warning would not be enough; the variable is one line of config")
    check("and the runtime path refuses too",
          oauth.stateless_allowed() is False,
          "defence in depth for anything that starts without the check")

with env(production=True, stateless=False):
    check("production + stateless=false starts", starts() is True)
    check("and never takes the stateless path",
          oauth.stateless_allowed() is False)

with env(production=False, stateless=True):
    check("development + stateless=true still starts", starts() is True,
          "the escape hatch has to remain usable where it is diagnosed")
    check("and the hatch is open there", oauth.stateless_allowed() is True)

with env(production=False, stateless=False):
    check("development + stateless=false starts", starts() is True)

print("\n2. An unknown environment counts as production")


def boom():
    raise RuntimeError("cannot tell")


_prod, _flag = oauth._production, oauth.ALLOW_STATELESS
try:
    oauth.ALLOW_STATELESS = True
    oauth._production = boom
    check("if the environment cannot be established, the hatch stays shut",
          oauth.stateless_allowed() is False,
          "UNKNOWN must not resolve to 'probably a laptop'")
finally:
    oauth._production, oauth.ALLOW_STATELESS = _prod, _flag

print("\n3. A callback with no usable state is refused by default")
oauth._record_pending("111")
with env(production=True, stateless=False):
    check("nobody is guessed at, even with exactly one pending",
          oauth._recent_pending() is None)
oauth._pending.clear()

print("\n4. A signed state is redeemable exactly once")
state = oauth.make_state("7585109158")
check("it round-trips to its owner", oauth.parse_state(state) == "7585109158")
check("first use is accepted", oauth._consume_state(state) is True)
check("second use is refused", oauth._consume_state(state) is False,
      "a replayed state must never link an account twice")
check("a tampered state does not parse",
      oauth.parse_state(state[:-2] + ("aa" if not state.endswith("aa") else "bb"))
      is None)
check("a fabricated state does not parse", oauth.parse_state("not-a-state") is None)

print("\n5. Replay protection that cannot answer is a refusal, not a fallback")
_claim, _redis = user_store.claim, getattr(user_store, "_USE_REDIS", False)
try:
    # A shared backend IS configured, and the claim errored or timed out.
    user_store.claim = lambda *a, **k: None
    user_store._USE_REDIS = True
    check("an unprovable state is rejected",
          oauth._consume_state(oauth.make_state("222")) is False,
          "in-process memory cannot see the other container")

    # Somebody else holds it.
    user_store.claim = lambda *a, **k: False
    check("a state already claimed elsewhere is rejected",
          oauth._consume_state(oauth.make_state("333")) is False)

    # Clean claim.
    user_store.claim = lambda *a, **k: True
    check("a cleanly claimed state is accepted",
          oauth._consume_state(oauth.make_state("444")) is True)
finally:
    user_store.claim, user_store._USE_REDIS = _claim, _redis

print("\n6. The guard is actually called at startup")
BOT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "bot.py"), encoding="utf-8").read()
head = BOT.split("def main():")[1][:1200]
check("bot.main() asserts the configuration", "assert_safe_config()" in head,
      "checking at point of use means the service starts and looks healthy")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — production cannot trust an unsigned callback.")
