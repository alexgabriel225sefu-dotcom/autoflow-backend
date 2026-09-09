"""Ask APEX — answers about YOUR account, from recorded state first.

Three rules shape this module, and each exists because the obvious
implementation gets it wrong.

**Scope is taken, never given.** Every query runs against the chat id the
Telegram signature proved. A question is text; it is never allowed to select
whose data is loaded. "Show me trades for 8963896517" is answered about the
asker's own account or refused — never resolved. This is the whole reason the
Copilot is a module rather than a prompt: an LLM that receives an account id in
its context will eventually use it.

**Read-only, with no path to the broker.** The Copilot cannot open, close or
modify a position, and cannot change a setting. It does not import
user_loop.force_close or any broker method. gates.authorize_order and
gates.authorize_close remain the only things that can permit an order, and this
module must not be able to reach them even by accident.

**Facts, or nothing.** Every answer is read off recorded state and labelled
FACT or OBSERVATION. Where nothing was recorded the answer is UNKNOWN, which is
a real answer and not a failure.

The AI assistant is deliberately NOT wired in. apex.assistant.chat() runs a
tool loop that can reach trading actions and answers by calling a send
function; using it here would hand a natural-language surface a path to things
§18 says it must never have. An honest "I don't know" is worth more than a
fluent sentence about someone's money.

The four kinds are carried on every reply, because a reader who cannot tell an
observation from a measurement will treat the weakest as the strongest.
"""

import re

# What each answer is. Rendered as a label, not decoration.
FACT = "FACT"                  # read from recorded state
OBSERVATION = "OBSERVATION"    # what the platform currently sees
ANALYSIS = "ANALYSIS"          # generated text. NOTHING produces this
                               # today: no generated answer is served (see
                               # the module docstring). Kept because the
                               # brief names four kinds, and a reply that
                               # ever IS generated must be labelled, not
                               # quietly passed off as a fact.
UNKNOWN = "UNKNOWN"            # nothing recorded — an answer, not an error
REFUSED = "REFUSED"            # asked for something the Copilot may not do

MAX_QUESTION_CHARS = 500

# Anything that would move money. Matched generously on purpose: a false
# positive costs a redirect to the right screen, a false negative would let a
# sentence start an execution path.
_ACTION = re.compile(
    r"\b(buy|sell|open|close|exit|enter|place|execute|liquidate|"
    r"double|increase|reduce)\b.{0,40}"
    r"\b(trades?|positions?|orders?|lots?|units?|now|it)\b"
    # A verb with a size after it is already an instruction, whatever noun
    # follows: "sell 0.5 gold" needs no object to be a request to trade.
    r"|\b(buy|sell)\b\s+[\d.]+"
    r"|\b(close|open) (my|the|this) (position|trade)\b"
    r"|\bgo (long|short)\b", re.I)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _reply(kind, text, **extra):
    """One answer.

    `facts` is the structured half the screen renders as labelled rows. It
    exists so a number on screen carries its own label and source instead of
    being read out of a sentence — a figure with no stated origin is
    indistinguishable from an invented one. Every fact here is a value the
    platform already recorded; nothing is derived to fill a row.
    """
    out = {"kind": kind, "text": text}
    out.update(extra)
    return out


# ── Intents answered from recorded state ────────────────────────────────

def _risk(chat_id):
    from apex import ui_state, user_loop, config as cfg
    state, reasons = ui_state.risk_state(chat_id)
    dash = user_loop.get_dash(chat_id) or {}
    guard = dash.get("riskGuard") or {}
    if state == "RISK_HOLDING" or guard.get("halted"):
        why = ", ".join(reasons or guard.get("reasons") or ["a risk limit"])
        return _reply(FACT, f"Trading is paused by the risk engine: {why}.",
                      screen="risk",
                      facts=[{"label": "Risk engine", "value": "Paused"},
                             {"label": "Reason", "value": why}])
    if state == "RISK_OK":
        limit = getattr(cfg, "MAX_DAILY_LOSS_PCT", None)
        tail = f" The daily loss limit is {limit}%." if limit is not None else ""
        return _reply(FACT, "The risk engine reports you are within limits." + tail,
                      screen="risk",
                      facts=[{"label": "Risk engine", "value": "Within limits"},
                             {"label": "Daily loss limit",
                              "value": None if limit is None else f"{limit}%"}])
    # Not OK and not holding. Saying "you're fine" here would be inventing the
    # reassuring half of a state we could not read.
    return _reply(UNKNOWN,
                  "The risk state could not be read just now, so I cannot tell "
                  "you whether you are within limits. New orders still pass the "
                  "same checks.", screen="risk")


def _positions(chat_id):
    from apex import user_loop
    dash = user_loop.get_dash(chat_id) or {}
    rows = [p for p in (dash.get("positions") or []) if p.get("symbol")]
    if not rows:
        return _reply(FACT, "You have no open positions.", screen="portfolio")
    parts = []
    for p in rows[:8]:
        pnl = _num(p.get("pnlUsd"))
        money = ("not yet priced" if pnl is None
                 else ("+" if pnl >= 0 else "−") + f"${abs(pnl):,.2f}")
        parts.append(f"{str(p['symbol']).replace('_', '/')} "
                     f"{p.get('side') or ''} · {money}")
    # `position` names the instrument the screen can open — the first one when
    # several are held, since a single button cannot mean all of them.
    return _reply(FACT, f"{len(rows)} open position"
                        f"{'s' if len(rows) != 1 else ''}:\n" + "\n".join(parts),
                  screen="portfolio",
                  position=(rows[0].get("symbol") if len(rows) == 1 else None),
                  symbol=(rows[0].get("symbol") if len(rows) == 1 else None),
                  facts=[{"label": "Open positions", "value": len(rows)}] +
                        [{"label": str(p["symbol"]).replace("_", "/"),
                          "value": ("not yet priced" if _num(p.get("pnlUsd")) is None
                                    else f"{_num(p.get('pnlUsd')):+,.2f} USD")}
                         for p in rows[:8]])


def _best_trade(chat_id, worst=False):
    from apex import user_store
    trades = [t for t in (user_store.load_trades(chat_id) or [])
              if _num(t.get("netPnl")) is not None]
    if not trades:
        return _reply(UNKNOWN, "No closed trades are recorded yet, so there is "
                               "no best or worst to show.", screen="history")
    pick = (min if worst else max)(trades, key=lambda t: _num(t.get("netPnl")))
    net = _num(pick.get("netPnl"))
    sign = "+" if net >= 0 else "−"
    return _reply(
        FACT,
        f"{'Worst' if worst else 'Best'} recorded trade: "
        f"{str(pick.get('symbol') or '?').replace('_', '/')} "
        f"{pick.get('side') or ''} {sign}${abs(net):,.2f} on "
        f"{str(pick.get('time') or '')[:16]}.",
        screen="history", tradeId=pick.get("positionId"),
        symbol=pick.get("symbol"),
        facts=[{"label": "Instrument",
                "value": str(pick.get("symbol") or "?").replace("_", "/")},
               {"label": "Direction", "value": pick.get("side")},
               {"label": "Net result", "value": f"{sign}${abs(net):,.2f}"},
               {"label": "Closed", "value": str(pick.get("time") or "")[:16]}])


def _why_no_trade(chat_id, symbol):
    from apex import trade_events
    rows = trade_events.declines(chat_id, symbol=symbol, limit=5)
    if not rows:
        # The distinction the brief insists on: nothing recorded is not the
        # same as nothing happened, and a reason must never be invented here.
        where = f" for {symbol}" if symbol else ""
        return _reply(UNKNOWN,
                      f"No recorded APEX decision{where} for this period. "
                      f"Decisions are logged as they are made — I do not "
                      f"reconstruct them afterwards.", screen="intelligence")
    lines = []
    for ev in rows:
        pl = ev.get("payload") or {}
        ver = f" (strategy v{ev['strategy_version']})" if ev.get("strategy_version") else ""
        lines.append(f"· {pl.get('reason') or 'reason not recorded'}{ver}")
    head = f"Recorded refusals for {symbol}:" if symbol else "Recorded refusals:"
    return _reply(FACT, head + "\n" + "\n".join(lines), screen="intelligence")


def _market(chat_id):
    from apex import user_loop
    dash = user_loop.get_dash(chat_id) or {}
    m = dash.get("market") or {}
    if not m:
        return _reply(UNKNOWN, "No market reading is available right now.",
                      screen="intelligence")
    bits = [f"{k}: {v}" for k, v in
            (("Trend", m.get("trend")), ("Momentum", m.get("momentum")),
             ("Volatility", m.get("volatility"))) if v]
    sym = str(dash.get("symbol") or "").replace("_", "/")
    return _reply(OBSERVATION,
                  f"What the platform currently sees on {sym} — "
                  + ", ".join(bits) + ". This is an observation, not a signal "
                  "and not a decision.", screen="intelligence",
                  symbol=dash.get("symbol"),
                  facts=[{"label": "Instrument", "value": sym},
                         {"label": "Trend", "value": m.get("trend")},
                         {"label": "Momentum", "value": m.get("momentum")},
                         {"label": "Volatility", "value": m.get("volatility")}])


# ── Routing ─────────────────────────────────────────────────────────────

_SYMBOL = re.compile(r"\b([A-Z]{6}|XAU\w{3}|XAG\w{3})\b")

_INTENTS = (
    (re.compile(r"\b(risk|exposure|daily limit|drawdown)\b", re.I), "risk"),
    (re.compile(r"\b(open positions?|positions?\b.{0,20}\bopen|"
                r"what.{0,25}\bopen\b|holding|am i in)\b", re.I), "positions"),
    (re.compile(r"\bworst\b.{0,20}\btrade\b", re.I), "worst"),
    (re.compile(r"\bbest\b.{0,20}\btrade\b", re.I), "best"),
    (re.compile(r"\bwhy\b.{0,30}\b(not|didn.?t|no trade|skip)\b", re.I), "whynot"),
    (re.compile(r"\b(market|trend|momentum|volatility)\b", re.I), "market"),
)


def answer(chat_id, question):
    """One reply, scoped to `chat_id` and nothing else.

    `chat_id` comes from the caller, which got it from a verified Telegram
    signature. Nothing in `question` can change it — that is the point.
    """
    chat_id = str(chat_id)
    q = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not q:
        return _reply(UNKNOWN, "Ask me about your account, your positions, your "
                               "risk, or why a trade did or did not happen.")

    # An instruction to trade is refused before anything else looks at it. The
    # Copilot has no execution path, and saying so plainly is better than a
    # generic answer that leaves the client wondering whether it acted.
    if _ACTION.search(q):
        return _reply(REFUSED,
                      "I can explain and show, but I cannot open, close or "
                      "change a position. Trading actions go through the "
                      "platform's own confirmation and the same risk checks "
                      "every order passes — use the position screen.",
                      screen="portfolio")

    sym_m = _SYMBOL.search(q.upper())
    symbol = sym_m.group(1) if sym_m else None

    for rx, intent in _INTENTS:
        if not rx.search(q):
            continue
        try:
            if intent == "risk":
                return _risk(chat_id)
            if intent == "positions":
                return _positions(chat_id)
            if intent == "best":
                return _best_trade(chat_id)
            if intent == "worst":
                return _best_trade(chat_id, worst=True)
            if intent == "whynot":
                return _why_no_trade(chat_id, symbol)
            if intent == "market":
                return _market(chat_id)
        except Exception as e:
            print(f"[Copilot] {intent} failed for {chat_id}: {e}")
            return _reply(UNKNOWN,
                          "I could not read that part of your account just now.")

    # A courtesy reply is the only canned text this module owns.
    # quick_answers.resolve() returns a handler KEY; the copy for it lives in
    # telegram.py. Echoing a key back as an answer produced "Handled." wearing
    # a FACT label — an invented answer about someone's account, which is the
    # exact thing this module exists to prevent.
    try:
        from apex import quick_answers
        if quick_answers.resolve(q) == "thanks":
            return _reply(FACT, "Any time.")
    except Exception as e:
        print(f"[Copilot] quick answer failed: {e}")

    # DELIBERATELY NOT the AI assistant.
    #
    # apex.assistant.chat() is an ACTOR: it runs a tool loop (_run_tool) that
    # can reach trading actions, and it answers asynchronously by calling a
    # send function rather than returning text. Wiring it in here would give a
    # natural-language surface a path to things §18 says it must never have,
    # and would do it through a code path built for a different contract.
    #
    # So the Copilot answers from recorded state or says it does not know.
    # That removes the whole class of "the AI decided something" rather than
    # trying to fence it, and an honest UNKNOWN is worth more than a fluent
    # sentence about someone's money.
    return _reply(UNKNOWN,
                  "I don't have a recorded answer for that. I can tell you "
                  "about your risk, your open positions, your best and worst "
                  "recorded trades, why a trade was refused, and what the "
                  "platform currently sees in the market.")


def suggestions():
    """The chips the screen offers. Every one maps to a fact route above."""
    return [
        "What is my current risk?",
        "What positions are open?",
        "Show me my best trade",
        "Why didn't APEX enter GBPUSD?",
        "What is the market doing?",
    ]
