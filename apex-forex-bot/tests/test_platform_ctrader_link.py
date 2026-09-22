"""Linking a cTrader account to an Apex4Traders account, with no Telegram.

THE ATTACK THE SHAPE OF THIS FLOW IS AGAINST

Signing the user id into `state` and binding tokens to whoever that state
names looks correct and is not. An attacker starts a connect flow for THEIR
account, sends the authorize link to a victim, and the victim's approval binds
the victim's live trading account to the attacker's dashboard. The state is
valid throughout — it is the attacker's own state.

So the callback here parks the code and finishes nothing; an authenticated
call completes the link, and that session must be the user who began it.
Section 4 is that attack, and it must fail.

Encryption is REAL in this file. A Fernet key is set before user_store is
imported, so "the token is stored encrypted" is a check that can fail rather
than one passing because encryption was quietly off.

Run: python tests/test_platform_ctrader_link.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-ctlink-")
os.environ["DATA_DIR"] = _TMP
os.environ["ALLOW_LOCAL_BACKEND_DEV"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/api/v1/ctrader/callback"
# A real key, so encryption is genuinely exercised.
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("ALLOW_PLAINTEXT_DEV_STORAGE", None)
# The whole point: no bot token anywhere in this flow.
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("APEX_ALLOW_LIVE_ACCOUNTS", None)

from apex import user_store  # noqa: E402
from apex.platform import ctrader_link as L  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def refuses(code, fn):
    """True when fn() raises a LinkError carrying exactly `code`."""
    try:
        fn()
        return False
    except L.LinkError as e:
        if e.code == code:
            return True
        print(f"       (refused with {e.code}, expected {code})")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"       (raised {type(e).__name__}: {e})")
        return False


ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"

ACCESS = "ctr-access-SECRET-0001"
REFRESH = "ctr-refresh-SECRET-0001"

DEMO_ACC = {"ctid": 111, "live": False, "label": "Demo 111"}
LIVE_ACC = {"ctid": 222, "live": True, "label": "Live 222"}


def exchanger(code, redirect_uri, *, token=None):
    return token or {"accessToken": ACCESS, "refreshToken": REFRESH,
                     "expiresIn": 2592000}


def lister(access, *, accounts=None):
    return accounts if accounts is not None else [DEMO_ACC, LIVE_ACC]


def connect(user_id, *, accounts=None, token=None, now=None):
    """The whole flow, end to end, with no network and no Telegram."""
    started = L.begin(user_id, now=now)
    state = started["authorizeUrl"].split("state=")[1].split("&")[0]
    L.handle_callback({"code": "auth-code-xyz", "state": state}, now=now)
    return started, L.complete(
        user_id, started["nonce"], now=now,
        exchanger=lambda c, u: exchanger(c, u, token=token),
        lister=lambda a: lister(a, accounts=accounts))


try:
    print("\n1. the happy path: begin -> callback -> complete")
    started, status = connect(ALICE)
    check("begin returns a cTrader authorize URL",
          started["authorizeUrl"].startswith("https://id.ctrader.com/"),
          started["authorizeUrl"][:40])
    check("the URL carries client_id, redirect_uri and state",
          all(k in started["authorizeUrl"]
              for k in ("client_id=", "redirect_uri=", "state=")))
    check("the authorize URL never carries the user id",
          ALICE not in started["authorizeUrl"])
    check("the account ends up connected", status["connected"] is True)
    check("both accounts are listed",
          {a["ctid"] for a in status["accounts"]} == {111, 222})
    check("and each is explicitly demo or live",
          {a["mode"] for a in status["accounts"]} == {"demo", "live"})
    check("nothing is selected just by connecting",
          status["selected"] is None)

    print("\n2. no token ever reaches anything a browser is handed")
    import json as _json
    blob = _json.dumps(status)
    check("the public status carries no access token", ACCESS not in blob)
    check("the public status carries no refresh token", REFRESH not in blob)
    check("nor any field named like a token",
          "accessToken" not in blob and "refreshToken" not in blob)

    print("\n3. tokens are encrypted at rest")
    raw = open(os.path.join(_TMP, "a4t",
                            L._k_conn(ALICE).replace(":", "__") + ".json")).read()
    check("the stored record does not contain the access token in the clear",
          ACCESS not in raw)
    check("nor the refresh token", REFRESH not in raw)
    check("and what is stored is marked as encrypted", "enc:" in raw)
    check("but it decrypts back to the real token, server-side",
          L.access_token_for(ALICE) == ACCESS)

    print("\n4. the account-injection attack fails")
    # Bob starts a flow. Alice approves in cTrader. Bob must not end up with
    # Alice's account, and Alice must not be able to finish Bob's attempt.
    bob_started = L.begin(BOB)
    bob_state = bob_started["authorizeUrl"].split("state=")[1].split("&")[0]
    L.handle_callback({"code": "alices-code", "state": bob_state})
    check("a different signed-in user cannot complete somebody else's attempt",
          refuses("STATE_UNKNOWN", lambda: L.complete(
              ALICE, bob_started["nonce"], exchanger=exchanger, lister=lister)))
    check("and the refusal is the same one a made-up nonce gets, so it "
          "confirms nothing",
          refuses("STATE_UNKNOWN", lambda: L.complete(
              ALICE, "not-a-real-nonce", exchanger=exchanger, lister=lister)))
    check("Alice's own connection is untouched",
          L.access_token_for(ALICE) == ACCESS)

    print("\n5. state is required, signed, single-use and time-limited")
    check("a callback with no state is refused",
          refuses("STATE_MISSING", lambda: L.handle_callback({"code": "x"})))
    check("a callback with an empty state is refused",
          refuses("STATE_MISSING",
                  lambda: L.handle_callback({"code": "x", "state": ""})))
    check("a made-up state is refused",
          refuses("STATE_MALFORMED",
                  lambda: L.handle_callback({"code": "x", "state": "garbage"})))
    s2 = L.begin(ALICE)
    st2 = s2["authorizeUrl"].split("state=")[1].split("&")[0]
    tampered = st2[:-2] + ("AA" if not st2.endswith("AA") else "BB")
    check("a tampered signature is refused",
          refuses("STATE_BAD_SIGNATURE",
                  lambda: L.handle_callback({"code": "x", "state": tampered})))
    s3 = L.begin(ALICE, now=1000.0)
    st3 = s3["authorizeUrl"].split("state=")[1].split("&")[0]
    check("a state older than its window is refused",
          refuses("STATE_EXPIRED", lambda: L.handle_callback(
              {"code": "x", "state": st3}, now=1000.0 + L.STATE_TTL_S + 1)))
    s4 = L.begin(ALICE)
    st4 = s4["authorizeUrl"].split("state=")[1].split("&")[0]
    L.handle_callback({"code": "c1", "state": st4})
    check("the same state cannot be used twice",
          refuses("STATE_REPLAYED",
                  lambda: L.handle_callback({"code": "c2", "state": st4})))
    # The check above exercises the development fallback: with no shared
    # backend user_store.claim returns None ("could not ask") and the record's
    # own status does the refusing. In production the atomic SET NX is what
    # holds, and that branch is unreachable here unless the claim is stubbed.
    _real_claim = user_store.claim
    try:
        s4b = L.begin(ALICE)
        st4b = s4b["authorizeUrl"].split("state=")[1].split("&")[0]
        user_store.claim = lambda key, ttl_s=120: False   # somebody has it
        check("with a shared backend, a second use loses the atomic claim",
              refuses("STATE_REPLAYED",
                      lambda: L.handle_callback({"code": "c", "state": st4b})))
        user_store.claim = lambda key, ttl_s=120: True    # first through
        s4c = L.begin(ALICE)
        st4c = s4c["authorizeUrl"].split("state=")[1].split("&")[0]
        out = L.handle_callback({"code": "c", "state": st4c})
        check("and the winner of the claim is let through",
              out["nonce"] == s4c["nonce"])
    finally:
        user_store.claim = _real_claim

    print("\n6. what cTrader refuses or omits is never papered over")
    s5 = L.begin(ALICE)
    st5 = s5["authorizeUrl"].split("state=")[1].split("&")[0]
    check("a callback carrying no code is refused",
          refuses("NO_CODE",
                  lambda: L.handle_callback({"state": st5, "code": ""})))
    s6 = L.begin(ALICE)
    st6 = s6["authorizeUrl"].split("state=")[1].split("&")[0]
    check("a provider-side error is surfaced, not swallowed",
          refuses("PROVIDER_REFUSED", lambda: L.handle_callback(
              {"state": st6, "error": "access_denied"})))
    s7 = L.begin(ALICE)
    st7 = s7["authorizeUrl"].split("state=")[1].split("&")[0]
    L.handle_callback({"code": "expired-code", "state": st7})

    def _expired(code, uri):
        raise RuntimeError("cTrader token error: INVALID_REQUEST — code expired")
    check("an expired authorization code refuses the connection",
          refuses("EXCHANGE_FAILED", lambda: L.complete(
              ALICE, s7["nonce"], exchanger=_expired, lister=lister)))
    s8 = L.begin(BOB)
    st8 = s8["authorizeUrl"].split("state=")[1].split("&")[0]
    L.handle_callback({"code": "c", "state": st8})
    check("a token response with no access token connects nothing",
          refuses("NO_TOKEN", lambda: L.complete(
              BOB, s8["nonce"], lister=lister,
              exchanger=lambda c, u: {"refreshToken": "r", "expiresIn": 10})))
    check("and Bob is still not connected afterwards",
          L.public_status(BOB)["connected"] is False)
    check("completing before cTrader has come back is refused",
          refuses("NOT_READY", lambda: L.complete(
              BOB, L.begin(BOB)["nonce"], exchanger=exchanger, lister=lister)))

    print("\n7. demo and live are separated, and live is blocked here")
    check("this environment does not allow live accounts",
          L.live_allowed() is False)
    st = L.select_account(ALICE, 111)
    check("a demo account can be selected",
          st["selected"] == {"ctid": 111, "mode": "demo"}, str(st["selected"]))
    check("a live account is refused in this environment",
          refuses("LIVE_BLOCKED", lambda: L.select_account(ALICE, 222)))
    check("the demo selection survives the refusal",
          L.public_status(ALICE)["selected"]["ctid"] == 111)
    check("an account that was never connected cannot be selected",
          refuses("NO_SUCH_ACCOUNT", lambda: L.select_account(ALICE, 999)))
    os.environ["APP_ENV"] = "production"
    check("production alone is still not enough", L.live_allowed() is False)
    os.environ["APEX_ALLOW_LIVE_ACCOUNTS"] = "true"
    check("production AND an explicit opt-in are both required",
          L.live_allowed() is True)
    os.environ["APP_ENV"] = "dev"
    os.environ.pop("APEX_ALLOW_LIVE_ACCOUNTS", None)
    check("back in development it is blocked again", L.live_allowed() is False)

    print("\n8. refreshing, and what happens when it cannot")
    conn = L._read_conn(ALICE)
    conn["expiresAt"] = 1.0                       # long expired
    L._store._write(L._k_conn(ALICE), conn)
    calls = {"n": 0}

    def _refresher(rt):
        calls["n"] += 1
        check("the refresh uses the stored refresh token, decrypted",
              rt == REFRESH, rt)
        return {"accessToken": "ctr-access-SECRET-0002",
                "refreshToken": "ctr-refresh-SECRET-0002", "expiresIn": 2592000}
    got = L.access_token_for(ALICE, refresher=_refresher)
    check("an expired token is refreshed rather than returned",
          got == "ctr-access-SECRET-0002", got)
    check("the refreshed token is stored encrypted too",
          "ctr-access-SECRET-0002" not in open(
              os.path.join(_TMP, "a4t",
                           L._k_conn(ALICE).replace(":", "__") + ".json")).read())
    got2 = L.access_token_for(ALICE, refresher=_refresher)
    check("a token still in date is not refreshed again",
          got2 == "ctr-access-SECRET-0002" and calls["n"] == 1,
          str(calls["n"]))
    conn = L._read_conn(ALICE)
    conn["expiresAt"] = 1.0
    conn["refreshToken"] = ""
    L._store._write(L._k_conn(ALICE), conn)
    check("an expired token with no refresh token asks for a reconnection",
          refuses("REFRESH_UNAVAILABLE", lambda: L.access_token_for(ALICE)))
    conn["refreshToken"] = user_store.encrypt_value(REFRESH)
    L._store._write(L._k_conn(ALICE), conn)

    def _bad_refresh(rt):
        raise RuntimeError("cTrader token error: INVALID_GRANT")
    check("a failed refresh refuses instead of returning a stale token",
          refuses("REFRESH_FAILED",
                  lambda: L.access_token_for(ALICE, refresher=_bad_refresh)))
    # Put Alice back in a healthy state. Section 8 left her token expired, and
    # a later call without an explicit refresher would fall through to the REAL
    # cTrader endpoint — a test must never reach the network.
    conn = L._read_conn(ALICE)
    conn["expiresAt"] = None
    conn["accessToken"] = user_store.encrypt_value(ACCESS)
    L._store._write(L._k_conn(ALICE), conn)
    check("and the restored token is the one section 9 reads",
          L.access_token_for(ALICE) == ACCESS)

    print("\n9. two clients cannot see each other's accounts")
    connect(BOB, accounts=[{"ctid": 333, "live": False, "label": "Bob demo"}],
            token={"accessToken": "bob-access-SECRET", "refreshToken": "bob-r",
                   "expiresIn": 2592000})
    a_ids = {a["ctid"] for a in L.public_status(ALICE)["accounts"]}
    b_ids = {a["ctid"] for a in L.public_status(BOB)["accounts"]}
    check("Alice sees only her accounts", a_ids == {111, 222}, str(a_ids))
    check("Bob sees only his", b_ids == {333}, str(b_ids))
    check("Bob cannot select an account of Alice's",
          refuses("NO_SUCH_ACCOUNT", lambda: L.select_account(BOB, 111)))
    check("their tokens are different and neither leaks into the other",
          L.access_token_for(BOB) == "bob-access-SECRET"
          and L.access_token_for(ALICE) != "bob-access-SECRET")
    L.disconnect(BOB)
    check("disconnecting Bob leaves Alice connected",
          L.public_status(BOB)["connected"] is False
          and L.public_status(ALICE)["connected"] is True)
    check("a disconnected client has no token to hand out",
          refuses("NOT_CONNECTED", lambda: L.access_token_for(BOB)))

    print("\n10. the flow has no Telegram in it at all")
    check("no TELEGRAM_BOT_TOKEN was set for any of the above",
          not os.getenv("TELEGRAM_BOT_TOKEN"))
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "apex", "platform",
                                       "ctrader_link.py")).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}"
                            for a in node.names)
    check("the module imports nothing from telegram",
          not any("telegram" in m.lower() for m in imported), str(imported))
    check("and no telegram module was loaded by running the flow",
          not any(m.startswith("apex.telegram") for m in sys.modules))
    check("nor the deprecated Telegram-era OAuth module",
          "apex.ctrader_oauth" not in sys.modules)
    check("the old module is marked deprecated so nobody extends it",
          open(os.path.join(ROOT, "apex", "ctrader_oauth.py")
               ).read().lstrip().startswith('"""DEPRECATED'))
    # The old module signs state with the bot token; this one must not, and
    # the surest way to show it is that the whole flow just ran without one.
    check("state signing works with no bot token present",
          L.parse_state(L.make_state("n1", 1000), now=1000)[0] == "n1")
    # And the key must not merely work without a bot token — it must not
    # DEPEND on one. If the old module's `TELEGRAM_BOT_TOKEN or ...` chain
    # ever came back, setting a bot token would change the derived key and
    # states issued a moment earlier would stop verifying.
    signed_before = L.make_state("n2", 1000)
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:a-bot-token-that-must-not-matter"
    try:
        check("introducing a bot token does not change the signing key",
              L.parse_state(signed_before, now=1000)[0] == "n2")
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
finally:
    shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
