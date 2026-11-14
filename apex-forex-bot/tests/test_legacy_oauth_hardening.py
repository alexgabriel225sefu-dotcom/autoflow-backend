"""The deprecated Telegram cTrader callback fails closed in production."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-legacy-oauth-")

from apex import ctrader_oauth as oauth  # noqa: E402


def test_legacy_callback_is_retired_in_production():
    original = oauth._production
    try:
        oauth._production = lambda: True
        status, body = oauth.handle_callback({"code": "victim-code", "state": "state"})
    finally:
        oauth._production = original
    assert status == 410
    assert "retired" in body.lower()
    assert "victim-code" not in body


def test_legacy_error_text_is_escaped():
    status, body = oauth.handle_callback({"error": ["<script>alert(1)</script>"]})
    assert status == 400
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "Content-Security-Policy" in body


def test_legacy_exchange_exception_is_escaped_and_bounded():
    original_prod = oauth._production
    original_exchange = oauth.ctrader.exchange_code
    original_parse_state = oauth.parse_state
    original_consume_state = oauth._consume_state
    try:
        oauth._production = lambda: False
        oauth.parse_state = lambda _state: "chat-1"
        oauth._consume_state = lambda _state: True
        oauth.ctrader.exchange_code = lambda *_: (_ for _ in ()).throw(
            RuntimeError("<img src=x onerror=alert(1)>" * 100))
        status, body = oauth.handle_callback({"code": "code", "state": "state"})
    finally:
        oauth._production = original_prod
        oauth.ctrader.exchange_code = original_exchange
        oauth.parse_state = original_parse_state
        oauth._consume_state = original_consume_state
    assert status == 502
    assert "<img" not in body
    assert "&lt;img" in body
    assert len(body) < 3000


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK: {name}")
