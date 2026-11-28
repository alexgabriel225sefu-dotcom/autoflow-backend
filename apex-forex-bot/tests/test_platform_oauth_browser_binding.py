"""The cTrader callback cannot be completed from a different browser."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp(prefix="a4t-oauth-binding-")
os.environ.update({
    "DATA_DIR": _tmp,
    "ALLOW_LOCAL_BACKEND_DEV": "true",
    "APP_ENV": "dev",
    "PRODUCT": "forex",
    "CTRADER_REDIRECT_URI": "https://api.example.test/api/v1/ctrader/callback",
})
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from apex.platform import api  # noqa: E402
from apex.platform import ctrader_link as link  # noqa: E402

USER = "browser-binding-user"
ACCOUNTS = [{"ctid": 501, "live": False}]


def _pending():
    started = link.begin(
        USER, now=1000,
        authorize_url_fn=lambda uri, state: f"https://broker.test?state={state}")
    state = parse_qs(urlparse(started["authorizeUrl"]).query)["state"][0]
    callback = link.handle_callback(
        {"code": "code-for-browser", "state": state},
        now=1001,
        exchanger=lambda *_: {"accessToken": "access", "refreshToken": "refresh"},
    )
    return started, callback


def test_callback_issues_a_finish_token_and_wrong_browser_is_refused():
    started, callback = _pending()
    assert callback["finishToken"]
    raw = json.dumps(link._pending(started["nonce"]))
    assert callback["finishToken"] not in raw
    try:
        link.complete(USER, started["nonce"], proof="wrong-proof", now=1002,
                      lister=lambda *_: ACCOUNTS)
    except link.LinkError as exc:
        assert exc.code == "BROWSER_BINDING_INVALID"
    else:
        raise AssertionError("a different browser completed the link")


def test_correct_callback_browser_can_complete():
    started, callback = _pending()
    result = link.complete(USER, started["nonce"], now=1002,
                           proof=callback["finishToken"],
                           lister=lambda *_: ACCOUNTS)
    assert result["connected"] is True


def test_public_complete_requires_browser_proof():
    started, _callback = _pending()
    with patch.object(api, "_authenticate",
                      return_value=SimpleNamespace(user_id=USER,
                                                   email_verified=True)):
        status, body = api._dispatch(
            "POST", "ctrader/complete", {},
            json.dumps({"nonce": started["nonce"]}), {})
    assert status == 400
    assert body["error"]["code"] == "BROWSER_BINDING_REQUIRED"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK: {name}")
