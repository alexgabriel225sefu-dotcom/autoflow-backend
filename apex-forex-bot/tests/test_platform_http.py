"""The platform API over real HTTP, mounted in the real server.

Every other platform test calls handle() directly, which is the right way to
test decisions. This one exists for the things only a socket can show: that
the mount actually happened, that the Authorization header survives the trip,
that a request body is read from the wire, and — the part that would be easy
to break silently — that the routes which were already in this server still
answer exactly as they did.

That last one is why /health is checked here. Reading the request body before
knowing whether the path is ours would starve whichever existing handler the
request was really for, and nothing in the platform's own tests would notice.

Run: python tests/test_platform_http.py
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-http-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
# A real key: the OAuth state is signed with material derived from it, and
# without one the connect endpoint correctly answers 503 rather than signing
# with something weaker.
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("ALLOW_PLAINTEXT_DEV_STORAGE", None)
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["DASHBOARD_TOKEN"] = "operator-token-for-the-old-routes"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/api/v1/ctrader/callback"
os.environ.pop("RENDER_EXTERNAL_URL", None)     # no keepalive thread
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0))
    PORT = _s.getsockname()[1]
os.environ["PORT"] = str(PORT)

import requests  # noqa: E402

ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
_USERS = {
    ALICE: {"id": ALICE, "email": "alice@example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z"},
    BOB: {"id": BOB, "email": "bob@example.com",
          "email_confirmed_at": "2026-01-01T00:00:00Z"},
}
_WHO = {"id": ALICE}


class _Resp:
    status_code = 200

    def json(self):
        return _USERS[_WHO["id"]]


_real_get = requests.get


def _fake_get(url, **kw):
    if "supabase" in str(url):
        return _Resp()
    return _real_get(url, **kw)


requests.get = _fake_get

from apex import bot  # noqa: E402
from apex.platform import identity as I  # noqa: E402

# The HTTP callback exchanges the authorization code itself — cTrader's code
# lives one minute and cannot wait for a second request — so every test that
# drives the real endpoint would otherwise reach cTrader. Stubbed here, before
# the server starts, rather than beside the first section that happens to need
# it: installing it later left an earlier callback test talking to the live
# token endpoint, which is how this comment came to be written. The token a
# section expects is set just before its own callback.
from apex.brokers import ctrader as _ct_broker  # noqa: E402

# ── the broker, standing in for cTrader ─────────────────────────────────────
# `automation.start` re-verifies the account mode against the broker rather
# than trusting the record written at link time (live spec §3), so a test that
# starts automation has to have a broker to ask. This is the same stand-in the
# `lister=` arguments below are, hoisted to module level so every start sees a
# consistent answer — `verify_selected_mode` resolves it at call time.
from apex.brokers import ctrader as _ct_broker            # noqa: E402

_BROKER_ACCOUNTS = [{"ctid": 501, "live": False}, {"ctid": 502, "live": True}]
_ct_broker.list_accounts = lambda token: list(_BROKER_ACCOUNTS)
