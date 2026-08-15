"""A 409 during our own deploy is not a misconfiguration.

Telegram allows one getUpdates consumer per token. Render starts the new
instance before draining the old one, so on every deploy both poll for a few
seconds and one loses. The old copy exits and it clears by itself.

The log said, every single time:

    409 Conflict — another instance of this bot token is polling. Find and
    stop it (check for a leftover Railway deployment or a second Render
    service).

There was no second service. Checked: one bot service, numInstances 1, the
only other deployment is the MCP server, which never polls Telegram. The
instance ids in the conflict window (5mr8v, d4nrm, 4zc75, f4mqt inside eleven
minutes) are the same service redeploying, and the conflicts stop dead once
the deploys settle — none at all in the following five hours.

So the message sent the operator hunting for something that did not exist,
on every deploy. That is how a REAL second deployment would have been waved
off as the usual noise.

Run: python tests/test_poll_conflict.py
"""
import os
import re
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
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-409-")

from apex import telegram as tg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
# Adjacent string literals are joined before matching. "Normal during a "
# "deploy" is one sentence to a reader and two literals to a grep, and a test
# that cannot see the difference fails on reformatting rather than on meaning.
_JOIN = re.compile(r'"\s*\n\s*f?"')
BLOCK = _JOIN.sub("", SRC[SRC.index("def _poll_loop"):])

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n── the grace window exists and is configurable ──")
check("there is a grace period", hasattr(tg, "_CONFLICT_GRACE_S"))
check("it is long enough to cover a handover", tg._CONFLICT_GRACE_S >= 30,
      str(tg._CONFLICT_GRACE_S))
check("but short enough to catch a real second instance quickly",
      tg._CONFLICT_GRACE_S <= 300, str(tg._CONFLICT_GRACE_S))
check("it can be tuned without a code change",
      "TELEGRAM_CONFLICT_GRACE_S" in SRC)
check("the loop records when it started", "_started_at = time.time()" in BLOCK)

print("\n── inside the window: explained, not accused ──")
_handover = BLOCK[BLOCK.index("_handover = "):BLOCK.index("elif _conflict_streak == 1")]
check("it names the real cause", "still draining" in _handover, _handover[:120])
check("it says this is expected", "Normal during a deploy" in _handover)
check("it does not send anyone hunting",
      "Railway" not in _handover and "second Render service" not in _handover)
check("it says so once, not every retry", "_conflict_streak == 1" in _handover)

print("\n── past the window: the accusation is earned ──")
_persist = BLOCK[BLOCK.index("elif _conflict_streak == 1"):BLOCK.index("time.sleep(wait)")]
check("it states how long it has persisted", "{_age:.0f}s" in _persist)
check("it rules out the innocent explanation first",
      "no longer a deploy handover" in _persist)
check("and only then lists where to look",
      "Railway" in _persist and "Render service" in _persist)
check("including a local copy, the case the old text missed",
      "locally" in _persist)
check("it is throttled, not per-retry", "_conflict_streak % 6 == 0" in _persist)

print("\n── the backoff still backs off ──")
check("the wait grows with the streak", "10 * _conflict_streak" in BLOCK)
check("and is capped", "min(120," in BLOCK)

print("\n── recovery is reported, so silence is never the only signal ──")
_clear = BLOCK[BLOCK.index("if _conflict_streak:"):BLOCK.index("_conflict_streak = 0\n            for u")]
check("clearing the conflict is logged", "conflict cleared" in _clear)
check("it says which instance won", "owns the poll" in _clear)
check("and only when there was a conflict to clear",
      _clear.strip().startswith("if _conflict_streak:"))

print("\n── the streak still resets on a good poll ──")
check("reset survives the new logging",
      re.search(r"_conflict_streak = 0\n\s+for u in data", BLOCK) is not None)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — a deploy handover no longer reads as a misconfiguration.")
