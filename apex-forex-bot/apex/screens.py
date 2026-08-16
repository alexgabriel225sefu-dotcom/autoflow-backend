"""The screens, as text and buttons — one bot, eight states, no dead ends.

Pure by design: every function here takes a resolved `ui_state.UiState` and
returns strings and button rows. Nothing in this module sends a message, reads
a store, or touches a broker, which is what makes the state matrix testable at
all — the previous arrangement could only be checked by driving a live chat.

TWO RULES RUN THROUGH ALL OF IT.

  1. Say the environment, always, in a form nobody can misread. 🧪 DEMO,
     🔴 LIVE, 🟠 VERIFICATION REQUIRED. Never a bare balance with no answer to
     "is this my real money".

  2. Never fill a gap with a comfortable number. A balance that could not be
     read is "not available", not $0.00. A win rate over three trades is not a
     win rate. An order the broker did not confirm either way is not a success
     and not a failure — it gets its own screen, and that screen does not offer
     a retry button, because retrying an order that may have filled is how one
     position becomes two.

Language: nothing in here names `entitlement`, `oauth_state`, `redis`, a
traceback, `None` or `UNKNOWN`. The client is told what is true about their
account, in the words they would use for it.
"""
from apex import ui_state as U

DIV = "━━━━━━━━━━━━━━━━━━━━"


def _fmt_money(v, currency="$"):
    """A number, or an honest blank. Never a zero standing in for a gap."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "<i>not available</i>"
    return f"{currency}{v:,.2f}"


def env_line(state):
    """The badge plus, when it matters, why it is not confirmed."""
    line = f"<b>{state.env_badge}</b>"
    if state.env == U.LIVE and state.simulating:
        line += "  ·  <i>simulating — no real orders yet</i>"
    if state.env in (U.DEMO, U.LIVE, U.UNKNOWN) and not state.proven:
        line += f"\n<i>{state.env_detail}.</i>"
    return line


def banner(state, guard=True):
    """The always-visible state block. Three facts, none of them optimistic."""
    lines = [env_line(state), U.automation_label(state)]
    if guard:
        if state.risk == U.RISK_HOLDING:
            why = "; ".join(state.risk_reasons) or "risk limit hit"
            lines.append(f"🛑 Risk Guard: <b>HOLDING</b> — {why}")
        elif state.risk == U.RISK_OK:
            lines.append("🛡 Risk Guard: <b>active</b>")
        else:
            # Not "active". A guard that has not reported is not a guard that
            # said yes, and this is the line that must never imply it did.
            lines.append("🛡 Risk Guard: <i>no report yet</i>")
    return "\n".join(lines)


# ── The state matrix ──────────────────────────────────────
#
# Each entry is (title, body). The buttons come from `home_rows` so that a
# state can never be described one way and offered another.

def _blocked_note(state):
    facts = state.unknown_facts
    if not facts:
        return ""
    if len(facts) == 1:
        what = facts[0]
    else:
        what = ", ".join(facts[:-1]) + f" and {facts[-1]}"
    return (f"\n\n⚠️ <b>New real-money trades are switched off</b> until we can "
            f"confirm {what}. Anything already open keeps its stop at your "
            f"broker.")


def home_head(state):
    """The header block for whichever of A–H this account is in."""
    s = state.state
    if s == "H":
        return ("🚨 <b>Emergency stop</b>",
                "The bot is holding. No new positions will be opened on this "
                "account until you resume it.\n\nAnything still open is listed "
                "under Positions and keeps its stop at your broker.")
    if s == "G":
        return ("⏸ <b>Bot is off</b>",
                "It is not looking for setups and will not open anything.\n\n"
                "Open positions are untouched and still protected by their "
                "stops at your broker. Tap Resume when you want it watching "
                "again.")
    if s == "E":
        return ("🔌 <b>Your live account is not connected</b>",
                "The bot cannot see your balance, your positions or the market "
                "through this account, so it will not place anything.\n\n"
                "Reconnect below and it picks up exactly where it was — your "
                "settings are unchanged.")
    if s == "F":
        return ("🔌 <b>No demo account connected</b>",
                "Connect an account and the bot can start showing you what it "
                "would do, with no money at risk.")
    if s == "D":
        return ("🟠 <b>Safety limits not confirmed</b>",
                "This is a real-money account and the bot has not yet reported "
                "your daily-loss and drawdown limits.\n\nUntil it does, no new "
                "real-money position will be opened. That is deliberate: the "
                "limits are what cap how fast a bad day can get worse, and "
                "trading without knowing them is not something we will do on "
                "your behalf.")
    if s == "C":
        if state.env == U.UNKNOWN:
            # Deliberately says nothing reassuring. We do not know whether this
            # account is a simulation, so we must not write a sentence that is
            # only true if it is one.
            return ("🟠 <b>Verification required</b>",
                    "We could not confirm with your broker whether this "
                    "account is a demo or real money.\n\nUntil we can, the bot "
                    "will not open a new position on it — and we will not "
                    "guess on screen either. Everything already open keeps its "
                    "stop at your broker.")
        return ("🟠 <b>Verification required</b>",
                "This is a real-money account, and we could not confirm your "
                "access to real-money trading just now.\n\nNew live positions "
                "stay switched off until we can. Everything else — your "
                "positions, your history, your settings — is unaffected.")
    if s == "B":
        return ("🔴 <b>Live trading</b>",
                "Real orders on your real account. Every position is sized "
                "from your stop and your risk setting, and every one carries a "
                "stop at the broker.")
    return ("🧪 <b>Demo trading</b>",
            "Real prices, simulated money. Nothing here can cost you anything "
            "— it is the same engine, the same rules and the same screens you "
            "will see live.")


def home(state, balance=None, open_count=None):
    """The dashboard, state-aware. DEMO and LIVE differ in what they claim,
    never in which facts they show."""
    title, body = home_head(state)
    parts = [title, banner(state), DIV, body]
    money = []
    if state.connected:
        money.append(f"💰 Balance: <b>{_fmt_money(balance)}</b>")
        if open_count is None:
            money.append("📈 Open positions: <i>not reported yet</i>")
        else:
            money.append(f"📈 Open positions: <b>{open_count}</b>")
    if money:
        parts.append("\n".join(money))
    # An unidentified account gets the same warning a live one does. It might
    # be one.
    note = _blocked_note(state) if not state.is_demo else ""
    return "\n\n".join(parts) + note


def home_rows(state):
    """Buttons for the current state. Every screen reachable, no dead ends."""
    s = state.state
    if s in ("E", "F"):
        return [[("🔗 Connect my account", "go:connect")],
                [("❓ Help", "nav:help")],
                [("☰ Menu", "nav:menu")]]
    rows = []
    if s == "H":
        rows.append([("▶️ Resume trading", "nav:resume")])
    elif s == "G":
        rows.append([("▶️ Resume trading", "nav:resume")])
    else:
        rows.append([("⏸ Pause trading", "nav:pause")])
    rows.append([("📈 Positions", "nav:pos"), ("📒 Performance", "nav:perf")])
    rows.append([("🎯 Strategy", "nav:strat"), ("🛡 Risk", "nav:risk")])
    rows.append([("🤖 Automation", "nav:auto"), ("👤 Account", "nav:acct")])
    if s == "C":
        rows.insert(1, [("🔄 Re-check my access", "acct:recheck")])
    if s == "D":
        rows.insert(1, [("🛡 Safety limits", "nav:risk")])
    if state.is_demo and state.connected:
        rows.append([("🔴 Go live", "live:start")])
    rows.append([("☰ Menu", "nav:menu")])
    return rows


# ── Account ───────────────────────────────────────────────

def account(state, account_id=None, account_count=None, balance=None):
    lines = ["👤 <b>Account</b>", banner(state, guard=False), DIV]
    if not state.connected:
        lines.append("No broker account is connected yet.")
        return "\n".join(lines)
    lines.append(f"Environment: <b>{state.env_badge}</b>")
    lines.append(f"Account: <code>{account_id or '—'}</code>")
    lines.append(f"Balance: <b>{_fmt_money(balance)}</b>")
    if isinstance(account_count, int) and account_count > 1:
        lines.append(f"\nYou have <b>{account_count}</b> accounts linked to "
                     "this bot. Switching between them changes which one the "
                     "bot trades — and the screens change with it.")
    if state.is_live and state.simulating:
        lines.append("\n<i>This is a real account, but the bot is still "
                     "simulating on it. Nothing you see has touched your "
                     "money.</i>")
    return "\n".join(lines)


def account_rows(state):
    rows = [[("🔄 Switch account", "acct:switch")],
            [("🔁 Re-check with my broker", "acct:refresh")]]
    if state.is_live and state.simulating:
        rows.insert(0, [("🔴 Activate real-money trading", "live:start")])
    rows.append([("☰ Menu", "nav:menu")])
    return rows


def account_switch(accounts, current_id):
    """The list. Every row states the environment before the number, because
    the number is the part nobody reads."""
    head = ("🔄 <b>Switch account</b>\n" + DIV + "\n\n"
            "The bot trades exactly one account at a time. Whichever you pick "
            "becomes the account every screen is about.\n\n"
            "<i>🧪 DEMO — simulated money · 🔴 LIVE — real money</i>")
    rows = []
    for a in accounts or []:
        if not isinstance(a, dict) or a.get("ctid") is None:
            continue
        tag = "🔴 LIVE" if a.get("live") else "🧪 DEMO"
        here = "  ✓ current" if str(a.get("ctid")) == str(current_id or "") else ""
        rows.append([(f"{tag} · {a['ctid']}{here}", f"acct:use:{a['ctid']}")])
    rows.append([("🔗 Connect a different account", "acct:new")])
    rows.append([("← Back", "nav:acct")])
    return head, rows


# ── The order whose outcome nobody knows ──────────────────

# Rejected: a "Try again" button. The whole premise of this screen is that the
# order may already be live at the broker, and a retry is how a client ends up
# holding twice the position they asked for. The bot's own idempotency claim
# already blocks an identical retry, but the button would still teach the wrong
# reflex — and the right action is to look, not to press.

def order_unknown(state, side=None, symbol=None, detail=""):
    what = f"{side} {symbol}".strip() if (side or symbol) else "your order"
    return (
        "⚠️ <b>ORDER STATUS UNKNOWN</b>\n"
        f"{banner(state, guard=False)}\n{DIV}\n\n"
        f"The bot sent <b>{what}</b> to your broker and did not get an answer "
        "back.\n\n"
        "<b>This does not mean it failed.</b> The order may have been filled, "
        "and it may not have been. We will not guess, and we will not send it "
        "again — a second order on top of one that filled is the worse "
        "mistake.\n\n"
        "<b>What to do:</b> open your broker's own platform and look at your "
        "positions. That is the only place with the real answer right now.\n\n"
        "The bot re-reads your account on its next check and this screen will "
        "settle by itself."
        + (f"\n\n<i>Reported: {detail}</i>" if detail else ""))


def order_unknown_rows():
    return [[("📈 Positions", "nav:pos")],
            [("👤 Account", "nav:acct"), ("❓ Help", "nav:help")],
            [("☰ Menu", "nav:menu")]]


def close_unknown(state, symbol=None, detail=""):
    return (
        "⚠️ <b>CLOSE STATUS UNKNOWN</b>\n"
        f"{banner(state, guard=False)}\n{DIV}\n\n"
        f"The bot asked your broker to close <b>{symbol or 'your position'}</b> "
        "and did not get an answer.\n\n"
        "<b>You may still be in this trade.</b> Open your broker's platform and "
        "check. If it is still open, close it there.\n\n"
        "The bot will not send the request again on its own — repeating a close "
        "that already went through can close a position you opened afterwards."
        + (f"\n\n<i>Reported: {detail}</i>" if detail else ""))


# ── Position detail and the close confirmation ────────────

def position_detail(state, pos):
    p = pos or {}
    side = "🟢 LONG" if p.get("side") == "BUY" else "🔴 SHORT"
    pnl, pips = p.get("pnlUsd"), p.get("pnlPips")
    if pnl is None:
        pnl_txt = "<i>not priced yet</i>" if pips is None else f"{pips:+.1f} pips"
    else:
        pnl_txt = f"{'+' if pnl >= 0 else '−'}${abs(pnl):.2f}"
        if pips is not None:
            pnl_txt += f"  ({pips:+.1f} pips)"
    sl = p.get("stopLoss")
    return (
        f"📈 <b>{p.get('symbol', 'Position')}</b>\n"
        f"{banner(state)}\n{DIV}\n\n"
        f"{side}\n"
        f"Entry: <b>{p.get('entryPrice', '—')}</b>   Size: {p.get('units', '—')}\n"
        f"Stop: <b>{sl if sl else '⚠️ none at your broker'}</b>   "
        f"Target: {p.get('takeProfit') or '—'}\n"
        f"P&amp;L: <b>{pnl_txt}</b>\n\n"
        "<i>The stop lives at your broker, so it protects this position even "
        "if the bot is off.</i>")


def close_confirm(state, symbol=None):
    return (
        f"🔒 <b>Close {symbol or 'this position'}?</b>\n"
        f"{banner(state)}\n{DIV}\n\n"
        "This closes at the current market price, immediately. Whatever it is "
        "showing right now — profit or loss — <b>becomes real</b>, and a closed "
        "trade cannot be reopened at its entry.\n\n"
        "<i>Tapping twice does not close it twice.</i>")


def close_confirm_rows(token):
    return [[("🔒 Yes — close it now", f"pos:goclose:{token}")],
            [("↩️ Leave it open", "nav:pos")],
            [("☰ Menu", "nav:menu")]]


# ── Things we refuse to invent ────────────────────────────

def unavailable(state, what, why="", back="nav:menu"):
    """One screen for every "we do not have this". Used instead of a zero.

    A screen that prints 0 trades, $0.00 or a 0% win rate when the real answer
    is "not loaded yet" is worse than an empty one: it is a number the client
    will act on.
    """
    return (f"📭 <b>{what} is not available right now</b>\n"
            f"{banner(state, guard=False)}\n{DIV}\n\n"
            + (f"{why}\n\n" if why else "")
            + "The bot will not show you a made-up figure in its place. Try "
              "again in a moment — this usually settles on the next check.")


def stale_action(what="That button"):
    """What a client sees when they press something that has moved on."""
    return (f"⌛ <b>{what} has expired</b>\n\n"
            "Nothing was done, and nothing changed on your account. Open the "
            "screen again and it will be current.")
