"""OAuth persistence failures must be explicit, redacted and recoverable."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TEMP = tempfile.TemporaryDirectory(prefix="a4t-oauth-store-")
os.environ.update(DATA_DIR=_TEMP.name, ALLOW_LOCAL_BACKEND_DEV="true",
                  APP_ENV="dev", PRODUCT="forex",
                  CTRADER_REDIRECT_URI="https://api.example.test/api/v1/ctrader/callback",
                  CTRADER_CLIENT_ID="test-app", CTRADER_CLIENT_SECRET="test-secret")
from cryptography.fernet import Fernet
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
from apex import user_store as U
from apex.platform import ctrader_link as L
from apex.platform import api as A

USER = "storage-test-user"
TOKENS = {"accessToken": "test-access", "refreshToken": "test-refresh",
          "expiresIn": 3600}
ACCOUNTS = [{"ctid": 111, "live": False, "label": "Demo"},
            {"ctid": 222, "live": True, "label": "Live"}]


class OAuthStorageTests(unittest.TestCase):
    def setUp(self):
        self.blobs = {}
        self.deny = lambda key: False
        self.stale = False
        self.read_down = False
        self.claims = set()
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        for name, value in (("_USE_REDIS", True), ("set_blob", self.write),
                            ("get_blob", lambda key: None if self.read_down else self.read(key)),
                            ("get_blob_strict", self.read),
                            ("claim", self.claim)):
            self.stack.enter_context(patch.object(U, name, value))

    def write(self, key, value):
        if self.deny(key):
            return False
        if not self.stale:
            self.blobs[key] = value
        return True

    def read(self, key):
        if self.read_down:
            raise U.StoreUnavailable("private-key:" + key)
        return self.blobs.get(key)

    def claim(self, key, ttl_s):
        if key in self.claims:
            return False
        self.claims.add(key)
        return True

    def begin(self):
        return L.begin(USER)

    def callback(self, started):
        state = parse_qs(urlparse(started["authorizeUrl"]).query)["state"][0]
        return L.handle_callback({"code": "test-code", "state": state},
                                 exchanger=lambda *a: TOKENS)

    def pending(self):
        started = self.begin()
        self.callback(started)
        return started

    def connected(self):
        started = self.pending()
        L.complete(USER, started["nonce"], lister=lambda *a: ACCOUNTS)
        return started

    def refuses_store(self, fn):
        with self.assertRaises(L.LinkConfigError) as caught:
            fn()
        self.assertEqual(caught.exception.code, "STORE_UNAVAILABLE")
        self.assertNotIn("private-key", str(caught.exception))
        return caught.exception

    def test_begin_refuses_lost_pending_write(self):
        self.deny = lambda key: True
        authorize = Mock()
        self.refuses_store(lambda: L.begin(USER, authorize_url_fn=authorize))
        authorize.assert_not_called()
        self.assertNotIn("[link] begin ", self.output.getvalue())

    def test_callback_read_outage_does_not_consume_nonce(self):
        started = self.begin()
        self.read_down = True
        err = self.refuses_store(lambda: self.callback(started))
        self.assertEqual(err.attempt, L._log.attempt_id(started["nonce"]))
        self.assertFalse(self.claims)
        self.assertNotIn(started["nonce"], self.output.getvalue() + str(err))
        self.read_down = False
        self.assertEqual(self.callback(started)["nonce"], started["nonce"])

    def test_shared_claim_outage_never_uses_local_fallback(self):
        started = self.begin()
        with patch.object(U, "claim", return_value=None):
            self.refuses_store(lambda: self.callback(started))
        self.assertNotIn("exchange.attempt", self.output.getvalue())

    def test_callback_refuses_lost_token_write(self):
        started = self.begin()
        self.deny = lambda key: True
        self.refuses_store(lambda: self.callback(started))
        self.assertNotIn("callback.pending_write", self.output.getvalue())
        rec = json.loads(self.blobs[L._k_pending(started["nonce"])])
        self.assertEqual(rec["status"], "awaiting_callback")
        # The exchange outcome is uncertain; never release the claim to retry it.
        self.assertIn(L._k_consume(started["nonce"]), self.claims)

    def test_complete_read_outage_is_not_state_unknown(self):
        started = self.pending()
        self.read_down = True
        self.refuses_store(lambda: L.complete(USER, started["nonce"]))

    def test_complete_write_loss_preserves_pending_tokens_and_can_retry(self):
        started = self.pending()
        pending_key = L._k_pending(started["nonce"])
        before = self.blobs[pending_key]
        self.deny = lambda key: key == L._k_conn(USER)
        self.refuses_store(lambda: L.complete(USER, started["nonce"],
                                            lister=lambda *a: ACCOUNTS))
        self.assertEqual(self.blobs[pending_key], before)
        self.assertNotIn("complete.connected", self.output.getvalue())
        self.deny = lambda key: False
        status = L.complete(USER, started["nonce"], lister=lambda *a: ACCOUNTS)
        self.assertTrue(status["connected"])
        self.assertEqual([a["mode"] for a in status["accounts"]], ["demo", "live"])
        self.assertFalse(status["liveAllowed"])

    def test_completed_marker_write_loss_is_not_reported_as_success(self):
        started = self.pending()
        self.deny = lambda key: key == L._k_pending(started["nonce"])
        self.refuses_store(lambda: L.complete(USER, started["nonce"],
                                            lister=lambda *a: ACCOUNTS))
        self.assertNotIn("complete.connected", self.output.getvalue())
        self.deny = lambda key: False
        self.assertTrue(L.complete(USER, started["nonce"],
                                   lister=lambda *a: ACCOUNTS)["connected"])

    def test_selection_and_disconnect_refuse_lost_write(self):
        self.connected()
        before = self.blobs[L._k_conn(USER)]
        self.deny = lambda key: True
        self.refuses_store(lambda: L.select_account(USER, 111))
        self.refuses_store(lambda: L.disconnect(USER))
        self.assertEqual(self.blobs[L._k_conn(USER)], before)

    def test_refresh_does_not_return_token_that_failed_to_save(self):
        self.connected()
        self.deny = lambda key: True
        self.refuses_store(lambda: L.access_token_for(
            USER, now=10**12, refresher=lambda *a: TOKENS))

    def test_stale_readback_is_not_a_confirmed_write(self):
        self.connected()
        self.stale = True
        self.refuses_store(lambda: L.select_account(USER, 111))
        self.refuses_store(lambda: L.disconnect(USER))

    def test_callback_api_returns_safe_503_and_diagnostic_id(self):
        started = self.begin()
        state = parse_qs(urlparse(started["authorizeUrl"]).query)["state"][0]
        self.read_down = True
        with patch.object(A._rl, "check", return_value=(True, None, 0)):
            status, body = A.handle("GET", "/api/v1/ctrader/callback?code=test-code&state=" + state)
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "STORE_UNAVAILABLE")
        self.assertEqual(body["error"]["diagnosticId"], L._log.attempt_id(started["nonce"]))
        public = json.dumps(body) + self.output.getvalue()
        for secret in (started["nonce"], state, "test-code", "private-key", USER):
            self.assertNotIn(secret, public)

    def test_corrupt_pending_is_a_safe_storage_failure(self):
        started = self.begin()
        self.blobs[L._k_pending(started["nonce"]) ] = "not-json"
        err = self.refuses_store(lambda: self.callback(started))
        self.assertNotIn(started["nonce"], str(err))
        self.assertFalse(self.claims)

    def test_refresh_storage_failure_reaches_api_as_503(self):
        from apex.platform import broker_read as B
        from types import SimpleNamespace
        self.connected()
        L.select_account(USER, 111)
        rec = json.loads(self.blobs[L._k_conn(USER)])
        rec["expiresAt"] = 1
        self.blobs[L._k_conn(USER)] = json.dumps(rec)
        self.deny = lambda key: True
        def connection(*args, **kwargs):
            return L.get_ctrader_connection(*args, **kwargs, refresher=lambda *a: TOKENS)
        with patch.object(B._link, "access_token_for", wraps=L.access_token_for):
            broker = Mock()
            self.refuses_store(lambda: B.positions(USER, connection_fn=connection, broker_fn=broker))
            broker.assert_not_called()
        from apex.brokers import ctrader
        with patch.object(ctrader, "refresh_access_token", return_value=TOKENS), \
             patch.object(A, "_authenticate", return_value=SimpleNamespace(user_id=USER)), \
             patch.object(A._rl, "check", return_value=(True, None, 0)):
            status, body = A.handle("GET", "/api/v1/positions")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "STORE_UNAVAILABLE")

    def test_redis_failures_log_no_key_or_exception_payload(self):
        sentinel = "test-private-storage-payload"
        driver = Mock()
        driver.set.side_effect = RuntimeError(sentinel)
        with patch.object(U, "_BACKEND", "redis"), patch.object(U, "_r", driver):
            self.assertFalse(U._redis_set(sentinel, sentinel))
            # Reach the real claim implementation, restored from module globals below.
            self.assertIsNone(REAL_CLAIM(sentinel))
        with patch.object(U, "_BACKEND", "upstash"), patch.object(U, "_upstash_post", return_value=None):
            self.assertFalse(U._redis_set(sentinel, sentinel))
        with patch.object(U._req, "post", side_effect=RuntimeError(sentinel)):
            self.assertIsNone(U._upstash_post(["SET", sentinel, sentinel]))
        self.assertNotIn(sentinel, self.output.getvalue())


REAL_CLAIM = U.claim
if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _TEMP.cleanup()
