"""What this account actually IS, right now — resolved once, read everywhere.

Telegram had four different answers to "is this demo or live" and none of them
asked the broker. `_mode_label` read `user["ctrader_env"]`, `_screen_account`
read it again, `_handle_paper` read it a third time, and the onboarding wizard
asked the CLIENT to pick one before an account existed. Every one of those is a
cached or user-supplied flag, and the failure they share is the only failure
that matters here: a real-money account rendered as a simulation.

THE RULE THIS MODULE EXISTS FOR:

    The connected broker account decides the environment. Nothing else does.

`ctrader_accounts` is the broker's own answer to "which accounts does this
token hold, and is each one live", written by `ctrader.list_accounts`. When the
selected account id appears in that list, the environment is PROVEN and this
module says so. When it does not — a record written before the list existed, a
partial read, an account removed at the broker — the environment is UNPROVEN,
and an unproven environment is labelled as such rather than quietly resolved to
the comfortable answer.

Unproven does not mean silent. It resolves in the direction that cannot hurt
anyone:

  * a `live` hint with no proof still reads LIVE. Softening real money into
    "unverified, probably fine" is the exact mistake this module replaces.
  * `paper=False` with no environment evidence at all also reads LIVE, because
    the record says real orders are intended and we cannot show that as demo.
  * only a genuinely contentless record reads VERIFICATION REQUIRED.

WHAT THIS MODULE IS NOT. It decides nothing financial. `gates.authorize_order`
and `gates.authorize_close` remain the only things that can permit an order;
`live_orders_offered` here governs whether the INTERFACE offers one, which is a
strictly weaker and separate question. A UI that hides a button has not made
the account safe — the gate did that — it has stopped lying about what will
happen if the button is pressed.
"""
import time

# ── Environments. Strings, so they survive a JSON round trip unchanged. ──
DEMO = "demo"
LIVE = "live"
UNKNOWN = "unknown"
DISCONNECTED = "disconnected"

# The three badges the specification requires, verbatim, plus the one it
# implies: an account that was never connected is not a failed verification.
BADGE = {
    DEMO: "🧪 DEMO",
    LIVE: "🔴 LIVE",
    UNKNOWN: "🟠 VERIFICATION REQUIRED",
    DISCONNECTED: "🔌 NOT CONNECTED",
}

# How long a broker account-list read stays fresh enough to reuse. The spec
# names the moments a refresh is required; this stops two of them landing in
# the same second (a /start that renders the dashboard) from opening two
# broker sockets.
REFRESH_MIN_INTERVAL_S = 45


def _accounts(u):
    a = (u or {}).get("ctrader_accounts")
    return a if isinstance(a, list) else []


def _selected(u):
    return str((u or {}).get("ctrader_account_id") or "").strip()


def account_entry(user):
    """The broker's own record for the account this bot is bound to, or None."""
    ctid = _selected(user)
    if not ctid:
        return None
    for a in _accounts(user):
        if isinstance(a, dict) and str(a.get("ctid")) == ctid:
            return a
    return None


def environment(user):
    """→ (env, proven, detail). Total: never raises, never returns None.

    `proven` is the whole point of the return shape. A caller that only wants
    a badge can ignore it; a caller deciding whether to OFFER a live action
    must not.
    """
    if user is None:
        # Not an empty account — an unread one. `{}.get("paper", True)` is
        # True, which is why "treat a failed read as a blank record" is the
        # one shortcut this module refuses to take.
        return (UNKNOWN, False,
                "your account could not be read just now, so which account "
                "this is remains unknown")
    u = user or {}
    acc = account_entry(u)
    if acc is not None:
        env = LIVE if acc.get("live") else DEMO
        return env, True, "confirmed by the account you connected"
    hint = str(u.get("ctrader_env") or "").strip().lower()
    token = bool(u.get("ctrader_access_token"))
    if hint == "live":
        return LIVE, False, "not re-confirmed with your broker yet"
    if hint in ("demo", "practice"):
        return DEMO, False, "not re-confirmed with your broker yet"
    if u.get("paper") is False and (token or _selected(u)):
        # The record says real orders are intended and offers no evidence of
        # where. The only safe reading is the expensive one.
        return LIVE, False, "not re-confirmed with your broker yet"
    if token or _selected(u):
        return (UNKNOWN, False,
                "your broker has not confirmed this account, so whether it is "
                "demo or real money is unknown")
    return DISCONNECTED, True, "no broker account is connected"


def badge(env, proven=True):
    """The environment, in a form nobody can misread at a glance."""
    b = BADGE.get(env, BADGE[UNKNOWN])
    if env in (DEMO, LIVE) and not proven:
        return f"{b} · ⚠️ unverified"
    return b


def refresh(chat_id, user=None, force=False):
    """Re-ask the BROKER which accounts this token holds, and re-derive.

    Called at every moment the specification names: /start, connect, reconnect,
    account switch, dashboard refresh, before live activation and before a live
    financial action. Best-effort by construction — a broker that does not
    answer must not take the screen down with it — but a failure is REPORTED
    rather than absorbed, because "we could not confirm" is the fact the client
    is entitled to instead of a badge that looks confirmed.

    Returns (user, refreshed, detail). `user` is always a usable record.
    """
    from apex import user_store
    try:
        u = user if user is not None else user_store.load(chat_id)
    except Exception as e:
        return None, False, f"account could not be read ({str(e)[:60]})"
    token = (u or {}).get("ctrader_access_token")
    if not token:
        return u, False, "no broker account is connected"
    last = 0.0
    try:
        last = float(u.get("ctrader_accounts_ts") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if not force and _accounts(u) and (time.time() - last) < REFRESH_MIN_INTERVAL_S:
        return u, False, "checked moments ago"
    try:
        # Through the trading core, never around it. This module must not
        # import a broker: the architectural invariant is that broker
        # construction lives in one place and every other layer asks it.
        from apex import user_loop
        accounts = user_loop.list_broker_accounts(u) or []
    except Exception as e:
        print(f"[UIState] account refresh failed for {chat_id}: {e}")
        return u, False, "your broker did not answer just now"
    if not accounts:
        return u, False, "your broker reported no trading accounts"
    updates = {"ctrader_accounts": accounts, "ctrader_accounts_ts": time.time()}
    merged = dict(u)
    merged.update(updates)
    # Keep the legacy hint in step with the proof so nothing downstream that
    # still reads `ctrader_env` can disagree with what is on screen.
    entry = account_entry(merged)
    if entry is not None:
        updates["ctrader_env"] = "live" if entry.get("live") else "demo"
        merged["ctrader_env"] = updates["ctrader_env"]
    try:
        user_store.update(chat_id, updates)
    except Exception as e:
        print(f"[UIState] could not store refreshed accounts for {chat_id}: {e}")
        return merged, True, "confirmed with your broker (not saved)"
    return merged, True, "confirmed with your broker"


# ── Risk, as the LOOP published it ────────────────────────
#
# Never recomputed here. `strategies.should_stop()` advances peak-balance and
# daily-reset state, so asking it in order to draw a badge would move the thing
# the badge is describing.

RISK_OK = "ok"
RISK_HOLDING = "holding"
RISK_UNKNOWN = "unknown"


def risk_state(chat_id):
    """→ (state, reasons). RISK_UNKNOWN is not RISK_OK and never renders as it."""
    try:
        from apex import user_loop
        g = (user_loop.get_dash(chat_id) or {}).get("riskGuard")
    except Exception as e:
        print(f"[UIState] risk guard unreadable for {chat_id}: {e}")
        return RISK_UNKNOWN, []
    if not isinstance(g, dict):
        return RISK_UNKNOWN, []
    if g.get("halted"):
        return RISK_HOLDING, [str(r) for r in (g.get("reasons") or [])] or ["risk limit"]
    return RISK_OK, []


class UiState:
    """Everything a screen needs, resolved once so no two screens disagree."""

    __slots__ = ("chat_id", "user", "env", "proven", "env_detail", "connected",
                 "simulating", "entitlement", "entitlement_why", "risk",
                 "risk_reasons", "running", "emergency", "automation")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    # ── the three questions every screen asks ──

    @property
    def env_badge(self):
        return badge(self.env, self.proven)

    @property
    def is_live(self):
        return self.env == LIVE

    @property
    def is_demo(self):
        return self.env == DEMO

    @property
    def unknown_facts(self):
        """Named, client-readable, in the order they block things."""
        out = []
        if self.env == UNKNOWN:
            out.append("which account this is")
        elif not self.proven and self.env in (DEMO, LIVE):
            out.append("confirmation of the account from your broker")
        if self.is_live and self.entitlement != "allowed":
            out.append("your access to real-money trading")
        if self.is_live and self.risk == RISK_UNKNOWN:
            out.append("your safety limits")
        return out

    @property
    def live_orders_offered(self):
        """Whether the INTERFACE may offer to open a new real-money position.

        Not permission — `gates.authorize_order` holds that and is the only
        thing that can grant it. This answers the narrower question of whether
        the screen is allowed to imply the answer will be yes.
        """
        return bool(self.connected and self.is_live and self.proven
                    and self.entitlement == "allowed"
                    and self.risk == RISK_OK
                    and self.running
                    and not self.emergency)

    @property
    def state(self):
        """The A–H letter.

        Ordered by what the client can DO about it, not by severity. A
        disconnected account outranks a paused one because "the bot is off" is
        the symptom and "no account is connected" is the cause — showing the
        symptom sends the client to a Resume button that cannot help them.
        """
        if self.emergency:
            return "H"
        if not self.connected:
            return "E" if self.is_live else "F"
        if not self.running:
            return "G"
        if self.is_live and self.risk == RISK_UNKNOWN:
            return "D"
        # An account whose environment we could not establish is NOT state A.
        # Falling through to the demo screen is exactly the failure this whole
        # module exists to prevent: "nothing here can cost you anything" is a
        # sentence we cannot write over an account we cannot identify.
        if self.env == UNKNOWN or (self.is_live and self.entitlement != "allowed"):
            return "C"
        if self.is_live:
            return "B"
        return "A"


def resolve(chat_id, user=None, refresh_broker=False, force=False):
    """The one call every screen makes. Total — a store outage degrades it,
    it never raises into a screen or an alert."""
    from apex import user_store
    u = user
    if refresh_broker:
        u, _ok, _why = refresh(chat_id, user=u, force=force)
    if u is None:
        try:
            u = user_store.load(chat_id)
        except Exception as e:
            print(f"[UIState] user unreadable for {chat_id}: {e}")
            u = None
    env, proven, detail = environment(u)
    ent, ent_why = "unknown", "not checked"
    try:
        from apex import gates
        ent, ent_why = gates.live_entitlement(chat_id, u)
    except Exception as e:
        print(f"[UIState] entitlement unreadable for {chat_id}: {e}")
    risk, reasons = risk_state(chat_id)
    try:
        from apex import user_loop
        running = bool(user_loop.is_running(chat_id))
    except Exception:
        running = False
    try:
        from apex import automation
        auto = automation.mode(u or {})
    except Exception:
        auto = "approval"
    return UiState(
        chat_id=chat_id, user=u, env=env, proven=proven, env_detail=detail,
        connected=bool((u or {}).get("ctrader_access_token")
                       and (u or {}).get("ctrader_account_id")),
        simulating=bool((u or {}).get("paper", True)) if u is not None else None,
        entitlement=ent, entitlement_why=ent_why, risk=risk,
        risk_reasons=reasons, running=running,
        emergency=bool((u or {}).get("emergency_stop")), automation=auto)


def automation_label(state):
    """The automation level, never overclaimed.

    "🟢 Full Automation" on an account whose entitlement cannot be read is a
    promise the gate will refuse to keep. The level is still shown — hiding
    the client's own setting would be its own lie — but the claim that it is
    ACTIVE is withheld until every prerequisite is known.
    """
    from apex import automation
    label = automation.label(state.automation)
    if state.automation != "full":
        return label
    if state.live_orders_offered or (state.is_demo and state.connected):
        return label
    blocked = state.unknown_facts
    if state.emergency:
        return f"{label} · ⏸ held by emergency stop"
    if not state.running:
        return f"{label} · ⏸ bot is off"
    if blocked:
        return f"{label} · ⏸ waiting on {blocked[0]}"
    return f"{label} · ⏸ not active yet"
