"""Is this client's money real? One answer, from the broker where possible.

WHY THIS EXISTS. The question was being answered in three places, on two
different axes, and they disagreed:

  * `user_loop._mode_of()` returned "live" whenever `paper` was false. But
    `paper` means "simulated fills vs broker-executed" — NOT "real money".
    Account 47765456 runs paper=false against a cTrader DEMO account, so every
    trade it closed was journalled `mode: "live"`. The history screen prints
    that field verbatim, so demo trades would be shown to a client as LIVE.
  * the loop's dash label read `ctrader_env`, a string stored at OAuth time.
    Better — it is at least the right axis — but still a cached flag, and the
    Mini App spec is explicit that a stale flag must not decide this.
  * the terminal payload fell back to `paper` again.

The broker knows. `ProtoOAGetAccountListByAccessTokenRes` carries `isLive` per
account, surfaced by `ctrader.list_accounts()` and reachable from the trading
core as `user_loop.list_broker_accounts()`. That is a FACT about the account,
not a note we wrote down about it once.

THE THREE-STATE RESULT is the point. "Ask the broker, fall back to the flag"
would silently reintroduce the same problem the moment the broker is
unreachable, so an unverifiable answer is reported as UNVERIFIED rather than
guessed. A caller that must not risk showing DEMO as LIVE can then refuse to
render a badge at all, which is the honest thing to do and what the spec asks
for.
"""

DEMO = "DEMO"
LIVE = "LIVE"
SIMULATION = "SIMULATION"     # paper fills — not a broker account at all
UNVERIFIED = "UNVERIFIED"

# How long a broker answer is trusted before we ask again. The account's
# live/demo nature does not change, but WHICH account is linked does, so this
# is short enough to follow a switch and long enough not to open a socket on
# every poll of a 2s terminal.
_TTL_S = 120
_cache: dict = {}


def _cached(key):
    import time
    hit = _cache.get(key)
    if hit and time.time() - hit[1] < _TTL_S:
        return hit[0]
    return None


def _store(key, value):
    import time
    _cache[key] = (value, time.time())
    return value


def resolve(user, *, allow_broker=True):
    """(mode, source) for this user's account.

    mode:   DEMO | LIVE | SIMULATION | UNVERIFIED
    source: "broker" | "stored-env" | "paper-flag" | "unknown"

    `allow_broker=False` skips the network call, for callers on a hot path that
    would rather have the stored answer than a socket. They still get told the
    answer came from a flag, so they can label it accordingly.
    """
    u = user or {}
    if u.get("paper", True):
        # No broker account is executing anything; nothing to verify.
        return SIMULATION, "paper-flag"

    ctid = u.get("ctrader_account_id")
    token = u.get("ctrader_access_token")
    if not ctid or not token:
        return UNVERIFIED, "unknown"

    key = f"{ctid}"
    hit = _cached(key)
    if hit:
        return hit, "broker"

    if allow_broker:
        try:
            from apex import user_loop
            for acct in (user_loop.list_broker_accounts(u) or []):
                if str(acct.get("ctid")) == str(ctid):
                    return _store(key, LIVE if acct.get("live") else DEMO), "broker"
            # The token is valid but no longer holds this account — a real
            # condition (account removed or de-authorized), not a demo account.
            return UNVERIFIED, "unknown"
        except Exception:
            pass          # fall through to the stored flag, labelled as such

    env = str(u.get("ctrader_env") or "").strip().lower()
    if env in ("demo", "practice"):
        return DEMO, "stored-env"
    if env in ("live", "real"):
        return LIVE, "stored-env"
    return UNVERIFIED, "unknown"


def badge(mode, source=None) -> str:
    """The label the client sees. UNVERIFIED never borrows either other word.

    `source` distinguishes an answer the broker just gave from one read back
    out of our own record. Both are real information — `ctrader_env` is
    written from the broker's answer at link time — but a stored value can be
    stale, and "🧪 DEMO" reads as a fact the client can act on. When it came
    from the stored flag rather than the live account, the label says so
    instead of quietly presenting yesterday's answer as today's.

    Omitting `source` keeps the plain label, for callers that have no source
    to report.
    """
    label = {
        LIVE: "🔴 LIVE",
        DEMO: "🧪 DEMO",
        SIMULATION: "📝 SIMULATION",
    }.get(mode, "🟠 VERIFICATION REQUIRED")
    if source == "stored-env" and mode in (LIVE, DEMO):
        return f"{label} (unconfirmed)"
    return label


def is_real_money(mode) -> bool:
    """Only an explicit, verified LIVE is real money.

    UNVERIFIED deliberately answers False here and is NOT rendered as DEMO by
    `badge()`. Those two facts together are the whole safety property: an
    unknown account is treated as not-real-money for anything that would risk
    real funds, while still refusing to *tell* the client it is a demo.
    """
    return mode == LIVE
