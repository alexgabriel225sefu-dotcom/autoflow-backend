"""A platform client's loop must be able to refresh its broker token.

THE BUG THIS FILE EXISTS TO CATCH

`user_loop._refresh_ctrader_token` is the loop's self-heal: when the cTrader
access token expires, it swaps it for a fresh one and reconnects. It began:

    refresh = (getattr(cfg, "CTRADER_REFRESH_TOKEN", "")
               or user_store.load(user_id).get("ctrader_refresh_token", ""))
    if not refresh:
        return False

Both reads come from the USER RECORD. A platform client's credentials live in
the platform namespace keyed by Supabase id, and `ctrader_link` is deliberate
that nothing copies them across — one secret in two namespaces is two places
to rotate, revoke and leak. So both reads returned empty, the refresh always
returned False, and when the token expired the loop went blind against the
broker. Silently, for as long as the client left it running.

And the legacy branch PERSISTS the refreshed tokens to the user record, which
the platform does not read — so even a platform client who somehow had a
legacy refresh token would have had the new one written somewhere useless.

WHY THIS IS NOT A SECOND REFRESH IMPLEMENTATION

The platform already has the canonical path: `get_ctrader_connection` calls
`access_token_for`, which refreshes near expiry and writes the result to the
store that owns it. The loop now delegates to it. Two refresh paths that must
both stay correct forever is the thing `bridge.py` refuses for orders, and
the reasoning is the same for credentials.

Run: python3 tests/test_platform_token_refresh.py
"""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-refresh-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import user_loop                                  # noqa: E402
from apex.platform import ctrader_link as CTL               # noqa: E402
from apex.brokers import ctrader as CT                      # noqa: E402

USER = "11111111-2222-4333-8444-555555555555"
TG_USER = "99887766"


def cfg_with(token="stale-token"):
    return types.SimpleNamespace(CTRADER_ACCESS_TOKEN=token,
                                 CTRADER_REFRESH_TOKEN="",
                                 CTRADER_ACCOUNT_ID=47765456,
                                 CTRADER_ENV="demo")


class Stubs:
    """Patch the platform accessors and the connection pool, restore after."""

    def __init__(self, *, is_platform=True, conn=None, raises=None):
        self.is_platform, self.conn, self.raises = is_platform, conn, raises
        self.dropped = []

    def __enter__(self):
        self._real = (CTL.is_platform_account, CTL.get_ctrader_connection,
                      CT._drop_conn)
        CTL.is_platform_account = lambda uid: self.is_platform
        def _get(uid, **kw):
            if self.raises:
                raise self.raises
            return self.conn
        CTL.get_ctrader_connection = _get
        CT._drop_conn = lambda env, acct: self.dropped.append((env, acct))
        return self

    def __exit__(self, *a):
        (CTL.is_platform_account, CTL.get_ctrader_connection,
         CT._drop_conn) = self._real
        return False


# ── 1. the refresh actually happens ─────────────────────────────────────────
print("\n[1] a platform client's token IS refreshed")
cfg = cfg_with("stale-token")
with Stubs(conn={"accessToken": "fresh-token", "ctid": 47765456,
                 "mode": "demo"}) as s:
    ok = user_loop._refresh_ctrader_token(USER, cfg)
check("the refresh reports success", ok is True,
      "a platform loop could never refresh, and went blind when the token "
      "expired")
check("and the config carries the NEW token",
      cfg.CTRADER_ACCESS_TOKEN == "fresh-token", cfg.CTRADER_ACCESS_TOKEN)
check("and the pooled connection is dropped so the next tick re-authenticates",
      s.dropped == [("demo", 47765456)], str(s.dropped))

# ── 2. an unchanged token is NOT a successful self-heal ─────────────────────
# Reporting success here would have the loop retry the same dead connection
# forever while logging that it had fixed itself.
print("\n[2] an unchanged token is not reported as a fix")
cfg = cfg_with("same-token")
with Stubs(conn={"accessToken": "same-token", "ctid": 47765456,
                 "mode": "demo"}):
    ok = user_loop._refresh_ctrader_token(USER, cfg)
check("it does not claim to have healed anything", ok is False, str(ok))

# ── 3. a failed refresh is survivable ───────────────────────────────────────
print("\n[3] a refresh that fails says so rather than raising")
cfg = cfg_with()
with Stubs(raises=CTL.LinkError("REFRESH_FAILED", "cTrader said no")):
    ok = user_loop._refresh_ctrader_token(USER, cfg)
check("it returns False", ok is False)
check("and the loop keeps its old token rather than a blank one",
      cfg.CTRADER_ACCESS_TOKEN == "stale-token", cfg.CTRADER_ACCESS_TOKEN)

# ── 4. a Telegram account still takes the legacy path ───────────────────────
# The other product must be unaffected: no platform connection is consulted,
# and the legacy refresh-token read still decides.
print("\n[4] a Telegram account falls through to the legacy path")
cfg = cfg_with()
with Stubs(is_platform=False, conn={"accessToken": "should-not-be-used"}):
    ok = user_loop._refresh_ctrader_token(TG_USER, cfg)
check("no platform token is adopted",
      cfg.CTRADER_ACCESS_TOKEN == "stale-token", cfg.CTRADER_ACCESS_TOKEN)
check("and with no legacy refresh token it reports failure, as before",
      ok is False, str(ok))

# ── 5. the helper is reached from the real entry point ──────────────────────
# A helper nothing calls is the bug, not the fix — the lesson from the
# automation supervisor earlier today.
print("\n[5] the loop's self-heal actually calls it")
src = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
body = src.split("def _refresh_ctrader_token(")[1]
check("_refresh_ctrader_token delegates before the legacy read",
      "_refresh_platform_token(" in body
      and body.index("_refresh_platform_token(")
      < body.index("ctrader_refresh_token"),
      "the legacy read returns False first and the delegate never runs")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All platform token-refresh checks passed.")
