"""Isolation contract for the multi-account roadmap item.

This file is intentionally executable by tests/run_all.py without pytest.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="a4t-multi-account-"))
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"

from apex.platform.multi_account import AccountIsolation, scope_key


def test_scope_keys_are_user_and_account_bound():
    assert scope_key("alice", "100") != scope_key("bob", "100")
    assert scope_key("alice", "100") != scope_key("alice", "200")


def test_one_users_account_data_is_not_visible_to_another():
    store = AccountIsolation()
    store.put("alice", "100", {"risk": {"fraction": 0.02}, "secret": "a"})
    store.put("bob", "100", {"risk": {"fraction": 0.07}, "secret": "b"})
    assert store.get("alice", "100")["secret"] == "a"
    assert store.get("bob", "100")["secret"] == "b"
    assert store.get("alice", "100") != store.get("bob", "100")
    assert store.get("mallory", "100") is None
    assert all(row["userId"] == "alice" for row in store.list_user("alice"))


def test_account_kill_switch_does_not_touch_sibling_or_other_user():
    store = AccountIsolation()
    store.put("alice", "100", {"state": "running"})
    store.put("alice", "200", {"state": "running"})
    store.put("bob", "100", {"state": "running"})
    store.set_kill("alice", "100", True, reason="account test")
    assert store.is_killed("alice", "100") is True
    assert store.is_killed("alice", "200") is False
    assert store.is_killed("bob", "100") is False


def test_user_global_kill_switch_only_affects_that_users_accounts():
    store = AccountIsolation()
    for user in ("alice", "bob"):
        for ctid in ("100", "200"):
            store.put(user, ctid, {"state": "running"})
    store.set_kill("alice", None, True, reason="user emergency")
    assert store.is_killed("alice", "100") is True
    assert store.is_killed("alice", "200") is True
    assert store.is_killed("bob", "100") is False
    assert store.is_killed("bob", "200") is False


def test_reads_and_kill_switches_are_copy_on_write():
    store = AccountIsolation()
    original = {"risk": {"fraction": 0.01}}
    store.put("alice", "100", original)
    original["risk"]["fraction"] = 0.90
    read = store.get("alice", "100")
    read["risk"]["fraction"] = 0.80
    assert store.get("alice", "100")["risk"]["fraction"] == 0.01
    store.set_kill("alice", "100", True, reason="test")
    kill = store.kill_state("alice", "100")
    kill["active"] = False
    assert store.is_killed("alice", "100") is True


if __name__ == "__main__":
    failed = []
    for name, fn in sorted((n, f) for n, f in globals().items()
                           if n.startswith("test_") and callable(f)):
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, exc))
            print(f"  FAIL {name}: {exc!r}")
    print("\nFAILED: " + ", ".join(n for n, _ in failed) if failed else "\nALL OK")
    raise SystemExit(1 if failed else 0)
