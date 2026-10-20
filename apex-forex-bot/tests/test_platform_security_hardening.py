"""Regression checks for the platform audit hardening fixes."""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")

from apex import ledger  # noqa: E402
from apex.brokers import ctrader  # noqa: E402
from apex.platform import api  # noqa: E402


def test_platform_reads_pass_explicit_ctid_to_broker_factory():
    source = open(os.path.join(ROOT, "apex", "platform", "broker_read.py"),
                  encoding="utf-8").read()
    assert "_make_broker(\n            user, user_id, ctid=ctid)" in source


def test_close_requires_fresh_session():
    source = open(os.path.join(ROOT, "apex", "platform", "api.py"),
                  encoding="utf-8").read()
    route = source[source.index("close_match = _POSITION_CLOSE_RE"):]
    assert "_authenticate(headers, fresh=True)" in route.split(
        "# ── read-only broker views", 1)[0]


def test_unknown_close_execution_is_not_terminal():
    event = SimpleNamespace(errorCode="", executionType=999999)
    assert ctrader._is_close_terminal_execution(event) is False


def test_releasing_a_shared_claim_uses_owner_token():
    old_use = ledger.user_store._USE_REDIS
    old_claim_value = ledger.user_store.claim_value
    old_release_claim = ledger.user_store.release_claim
    old_local = dict(ledger._local)
    calls = []
    try:
        ledger.user_store._USE_REDIS = True
        ledger.user_store.claim_value = lambda key, value, ttl_s: True
        ledger.user_store.release_claim = (
            lambda key, value: calls.append((key, value)) or True)
        ledger._local.clear()
        ok, _reason, rid = ledger.claim(
            "user", "CLOSE:77", "CLOSE", 0, now=1_700_000_000)
        assert ok is True
        ledger.release(rid)
        assert calls
        assert all(value == key.rsplit(":", 1)[-1] for key, value in calls)
    finally:
        ledger.user_store._USE_REDIS = old_use
        ledger.user_store.claim_value = old_claim_value
        ledger.user_store.release_claim = old_release_claim
        ledger._local.clear()
        ledger._local.update(old_local)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK: {name}")
