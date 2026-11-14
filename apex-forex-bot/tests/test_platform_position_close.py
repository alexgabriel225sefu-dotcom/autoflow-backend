"""The web close path is demo-only, position-id based, and retry-safe."""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")

from apex.platform import api  # noqa: E402
from apex.platform import position_close as close  # noqa: E402


class _Broker:
    def __init__(self, result):
        self.result = result
        self.position_ids = []

    def close_position_by_id(self, position_id):
        self.position_ids.append(position_id)
        return dict(self.result)


class _MonkeyPatch:
    def __init__(self):
        self._old = []

    def setattr(self, obj, name, value):
        self._old.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self._old):
            setattr(obj, name, value)


def _gate(*_args, rid="rid-1", **_kwargs):
    return SimpleNamespace(allowed=True, reason="AUTHORIZED", detail=""), rid


def _connected(mode="demo"):
    return {"accounts": [{"ctid": 501, "mode": mode}]}


def _run(monkeypatch, result, *, mode="demo"):
    broker = _Broker(result)
    releases = []
    records = []
    monkeypatch.setattr(close._link, "_read_conn", lambda _uid: _connected(mode))
    monkeypatch.setattr(close._gates, "authorize_platform_demo_close", _gate)
    monkeypatch.setattr(close._read, "_open",
                        lambda *_a, **_kw: (broker, {"ctid": 501, "mode": mode,
                                                    "accessToken": "redacted"}))
    monkeypatch.setattr(close._ledger, "release", lambda rid: releases.append(rid))
    monkeypatch.setattr(close._ledger, "record",
                        lambda rid, value: records.append((rid, value)))
    return close.close_demo("user-1", ctid="501", position_id="77"), broker, releases, records


def test_live_account_is_refused_before_gate(monkeypatch):
    monkeypatch.setattr(close._link, "_read_conn", lambda _uid: _connected("live"))
    called = []
    monkeypatch.setattr(close._gates, "authorize_platform_demo_close",
                        lambda *a, **k: called.append(True))
    try:
        close.close_demo("user-1", ctid="501", position_id="77")
    except close.CloseRefused as e:
        assert e.code == "DEMO_ONLY"
    else:
        raise AssertionError("live close was accepted")
    assert not called


def test_partial_close_reports_remaining_and_never_books_full_pnl(monkeypatch):
    result, broker, releases, records = _run(
        monkeypatch,
        {"status": "PARTIAL", "remainingVolume": 250,
         "sentence": "Position partially closed; remaining volume: 250."},
    )
    assert result["status"] == "PARTIAL"
    assert result["remainingVolume"] == 250
    assert "netPnl" not in result
    assert releases == ["rid-1"]
    assert records == []
    assert broker.position_ids == ["77"]


def test_already_flat_books_no_pnl(monkeypatch):
    result, _broker, releases, records = _run(
        monkeypatch,
        {"status": "ALREADY_CLOSED", "sentence": "Position already closed."},
    )
    assert result["status"] == "ALREADY_CLOSED"
    assert "netPnl" not in result
    # Nothing was sent to the broker, so nothing a retry could duplicate: the
    # claim is RELEASED, not recorded. It used to be held for minutes, and when
    # the broker had only briefly listed no positions, "not there a moment ago"
    # turned the retry of a still-open position into DUPLICATE_CLOSE.
    assert releases == ["rid-1"]
    assert records == []


def test_close_is_refused_when_the_connection_in_hand_is_not_demo(monkeypatch):
    """The mode is read from the link record first; the connection that will
    carry the close is a separate read, and it is the one that is judged."""
    broker = _Broker({"status": "FILLED", "sentence": "Position closed."})
    releases = []
    monkeypatch.setattr(close._link, "_read_conn", lambda _uid: _connected("demo"))
    monkeypatch.setattr(close._gates, "authorize_platform_demo_close", _gate)
    monkeypatch.setattr(close._read, "_open",
                        lambda *_a, **_kw: (broker, {"ctid": 501, "mode": "live",
                                                     "accessToken": "redacted"}))
    monkeypatch.setattr(close._ledger, "release", lambda rid: releases.append(rid))
    try:
        close.close_demo("user-1", ctid="501", position_id="77")
    except close.CloseRefused as e:
        assert e.code == "DEMO_ONLY"
    else:
        raise AssertionError("a close was accepted on a connection that is not demo")
    assert broker.position_ids == [], "nothing may reach the broker"
    assert releases == ["rid-1"]


def test_definite_rejection_releases_claim(monkeypatch):
    broker = _Broker({"status": "REJECTED",
                       "sentence": "The broker rejected the close request."})
    releases = []
    monkeypatch.setattr(close._link, "_read_conn", lambda _uid: _connected("demo"))
    monkeypatch.setattr(close._gates, "authorize_platform_demo_close", _gate)
    monkeypatch.setattr(close._read, "_open",
                        lambda *_a, **_kw: (broker, {"ctid": 501,
                                                     "mode": "demo",
                                                     "accessToken": "redacted"}))
    monkeypatch.setattr(close._ledger, "release", lambda rid: releases.append(rid))
    try:
        close.close_demo("user-1", ctid="501", position_id="77")
    except close.CloseRefused as e:
        assert e.code == "CLOSE_REJECTED"
    else:
        raise AssertionError("rejected close was reported as success")
    assert releases == ["rid-1"]


def test_refresh_failure_releases_claim(monkeypatch):
    releases = []
    monkeypatch.setattr(close._link, "_read_conn", lambda _uid: _connected("demo"))
    monkeypatch.setattr(close._gates, "authorize_platform_demo_close", _gate)
    monkeypatch.setattr(close._read, "_open",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            close._link.LinkError("REFRESH_FAILED", "refresh failed")))
    monkeypatch.setattr(close._ledger, "release", lambda rid: releases.append(rid))
    try:
        close.close_demo("user-1", ctid="501", position_id="77")
    except close._link.LinkError as e:
        assert e.code == "REFRESH_FAILED"
    else:
        raise AssertionError("refresh failure did not surface")
    assert releases == ["rid-1"]


def test_api_route_uses_position_id_and_returns_sentence(monkeypatch):
    monkeypatch.setattr(api, "_authenticate",
                        lambda _headers, **_kwargs: SimpleNamespace(
                            user_id="user-1"))
    seen = {}

    def fake_close(user_id, **kwargs):
        seen.update(user_id=user_id, **kwargs)
        return {"status": "FILLED", "sentence": "Position closed."}

    monkeypatch.setattr(api._close, "close_demo", fake_close)
    status, payload = api._dispatch(
        "POST", "accounts/501/positions/77/close", {}, None, {})
    assert status == 200
    assert seen == {"user_id": "user-1", "ctid": "501", "position_id": "77"}
    assert payload["sentence"] == "Position closed."


if __name__ == "__main__":
    failures = []
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        patcher = _MonkeyPatch()
        try:
            fn(patcher)
            print(f"OK: {name}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: {e}")
            print(f"FAIL: {name}: {e}")
        finally:
            patcher.undo()
    if failures:
        raise SystemExit("\n".join(failures))
