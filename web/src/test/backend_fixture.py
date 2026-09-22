"""Start the REAL Apex4Traders backend for the frontend's end-to-end test.

Only Supabase is stubbed, and only because this test has no Supabase project
to talk to. Everything else — the router, ownership, the licence store, the
rule store, the journal, the cTrader link — is the code that ships. A test
that mocked those would prove the frontend agrees with a mock.

The stub maps a bearer token to a user id, so the Node side can act as two
different clients and ownership is genuinely exercised.
"""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                    "..", "..", "..", "apex-forex-bot"))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="a4t-e2e-")
os.environ["DATA_DIR"] = TMP
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["DASHBOARD_TOKEN"] = "operator-token"
os.environ["CTRADER_REDIRECT_URI"] = "http://localhost/api/v1/ctrader/callback"
os.environ.pop("RENDER_EXTERNAL_URL", None)
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("ALLOW_PLAINTEXT_DEV_STORAGE", None)

ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
USERS = {
    "alice": {"id": ALICE, "email": "alice@example.com",
              "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "bob": {"id": BOB, "email": "bob@example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "unconfirmed": {"id": ALICE, "email": "alice@example.com"},
}

import requests  # noqa: E402
_real_get = requests.get


class _R:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def _fake_get(url, **kw):
    if "stub.supabase.co" in str(url):
        token = (kw.get("headers") or {}).get("Authorization", "")
        who = token.replace("Bearer ", "").strip()
        # An unknown token is a 401, exactly as Supabase would answer, so the
        # "expired session" path is the real one and not a special case.
        if who not in USERS:
            return _R(401, {})
        return _R(200, USERS[who])
    return _real_get(url, **kw)


requests.get = _fake_get

import socket  # noqa: E402
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
os.environ["PORT"] = str(PORT)

from apex import bot  # noqa: E402
from apex.platform import ctrader_link as link  # noqa: E402
from apex.platform import licence  # noqa: E402
from apex import user_loop, user_store  # noqa: E402

# The engine is not started for real: this test is about the web layer, and a
# live trading loop has no business inside it.
user_loop.start = lambda uid, alert_fn=None: True
user_loop.stop = lambda uid: None

# The BROKER is stubbed too, and only the broker. get_candles has no paper
# short-circuit the way get_all_positions does — trendbars are public market
# data, so the engine fetches them for real even on a paper account. That is
# correct, and it also means an unstubbed test would sit waiting on a cTrader
# socket it has no credentials for. Everything above the connector — routing,
# validation, ownership, the status contract — is still the shipping code.
import math as _math


class _StubBroker:
    def get_candles(self, instrument=None, interval=None, limit=None,
                    to_ts=None):
        out = []
        for i in range(int(limit or 200)):
            c = 1.1000 + 0.004 * _math.sin(2 * _math.pi * i / 41)
            out.append({"open": c, "high": c + 0.0006, "low": c - 0.0006,
                        "close": c, "time": 1758542400 + i * 3600})
        return out

    def get_all_positions(self):
        return []

    def get_pending_orders(self):
        return []

    def get_balance(self):
        return 5000.0


user_loop._make_broker = lambda user, user_id=None: (_StubBroker(), {})

bot._start_dashboard_server()


def seed(what):
    """Test-side setup the HTTP API deliberately does not expose."""
    if what == "licence":
        licence.grant(ALICE, plan="pro")
    elif what == "ctrader":
        user_store.save(ALICE, {"paper": True, "paper_balance": 5000})
        st = link.begin(ALICE)
        state = st["authorizeUrl"].split("state=")[1].split("&")[0]
        link.handle_callback({"code": "c", "state": state})
        link.complete(ALICE, st["nonce"],
                      exchanger=lambda c, u: {"accessToken": "CT-SECRET",
                                              "refreshToken": "R",
                                              "expiresIn": 2592000},
                      lister=lambda a: [{"ctid": 501, "live": False},
                                        {"ctid": 502, "live": True}])
        link.select_account(ALICE, 501)
    elif what == "reauth":
        rec = link._read_conn(ALICE)
        rec["expiresAt"] = 1.0
        rec["refreshToken"] = ""
        link._store._write(link._k_conn(ALICE), rec)


print(json.dumps({"port": PORT}), flush=True)
print("READY", flush=True)

for raw in sys.stdin:
    cmd = raw.strip()
    if not cmd:
        continue
    if cmd == "quit":
        break
    try:
        seed(cmd)
        print(json.dumps({"ok": True, "cmd": cmd}), flush=True)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}), flush=True)
