"""Conversational AI trading assistant — natural-language chat + trade execution.

Any free-text message from a client (non-command) comes here. The assistant
understands the user's intent, fetches live market data, and can execute trades
directly. Falls back gracefully when AI providers are unavailable.

Provider priority (shared owner key covers ALL clients):
  2. Gemini              — FREE, full tool-use + execution
  3. Groq               — free chat + analysis only
  4. Local status       — always works, no AI needed
"""
import json
import threading
from apex import chat_memory
from apex import config as cfg

_lock = threading.Lock()

_TOOLS = [
    {
        "name": "analyze_market",
        "description": (
            "Fetch live technical analysis for a forex pair. "
            "Use when the user asks about market conditions, current signal, or whether to trade."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. EUR_USD, GBP_USD, USD_JPY"}
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "execute_trade",
        "description": (
            "Open a BUY or SELL position NOW. "
            "Use when the user explicitly says they want to enter, buy, sell, or go long/short. "
            "Confirmation can be in ANY language (yes, da, sí, oui, ja, evet, да, go, intru)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "side":   {"type": "string", "enum": ["BUY", "SELL"]},
                "symbol": {"type": "string", "description": "e.g. EUR_USD"},
            },
            "required": ["side", "symbol"],
        },
    },
    {
        "name": "close_position",
        "description": "Close the open position immediately. Use when the user asks to exit, close, or sell out.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_symbol",
        "description": "Change which forex pair the bot auto-trades.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. EUR_USD, GBP_JPY"}
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "set_risk",
        "description": "Change the risk per trade (percentage of balance).",
        "input_schema": {
            "type": "object",
            "properties": {
                "risk_pct": {"type": "number", "description": "Risk percent (0.5–10)"}
            },
            "required": ["risk_pct"],
        },
    },
    {
        "name": "pause_trading",
        "description": "Pause auto-trading (bot stops opening new positions).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "resume_trading",
        "description": "Resume auto-trading.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

_SYSTEM = """You are Apex, an intelligent forex trading assistant inside a Telegram bot.

You help users trade: analyze forex markets, execute trades, explain P&L, manage settings.

RULES:
- Be concise — Telegram messages, 2-4 sentences max unless analysis is requested
- LANGUAGE: ALWAYS reply in English, whatever language the user writes in.
  The bot's own messages (buttons, trade alerts, the daily summary) are all
  English, so mirroring the user's language made a single chat bilingual —
  an English "Position closed" next to a Romanian answer about it. One
  language throughout is clearer than each message being individually
  well-matched. If the user writes in another language, understand it fully
  and answer in English.
- Trade execution: show a brief analysis, then execute immediately without asking for confirmation.
  The user can always close manually. Do NOT ask "are you sure?" — just do it.
- Always cite real numbers: RSI, price, balance, P&L — never invent them
- Auto-trading runs 24/7 in the background — you only intervene when asked
- For errors: explain in plain language and suggest a fix
- Use HTML: <b>bold</b>, no markdown asterisks
- NEVER invent prices or indicators. Only use numbers from the account context below.
- Forex market hours: closed on weekends. Mention this if relevant.
- For manual entries: /buy EUR_USD or /sell EUR_USD also work

Current account context is injected after this system prompt."""


def _load_history(user_id: str):
    """Bounded history for this user, from the shared store (spec §8).

    Was a process-local dict: every deploy wiped every client's conversation,
    and during a deploy two instances answered the same user from two
    different halves of the history.
    """
    return chat_memory.load(user_id)


def _save_exchange(user_id: str, user_msg: str, assistant_msg: str):
    chat_memory.save_exchange(user_id, user_msg, assistant_msg)


def _build_context(user_id: str) -> str:
    """Inject live account state so the AI talks with real numbers."""
    from apex import user_loop, user_store, forex, indicators

    user = user_store.load(user_id)
    dash = user_loop.get_dash(user_id) or {}

    balance = dash.get("balance", user.get("paper_balance", cfg.PAPER_BALANCE))
    start_bal = dash.get("startBalance", balance)
    pnl_pct = ((balance - start_bal) / start_bal * 100) if start_bal else 0
    symbol = dash.get("symbol") or user.get("symbol", cfg.SYMBOL)
    paper = user.get("paper", cfg.PAPER_TRADING)
    open_pos = dash.get("openPosition")
    last_price = dash.get("currentPrice")
    ct_env = user.get("ctrader_env", "demo")

    lines = [
        f"Balance: ${balance:.2f} (start ${start_bal:.2f}, P&L: {pnl_pct:+.1f}%)",
        f"Symbol: {symbol}",
        f"Mode: {'Demo' if ct_env == 'demo' else 'LIVE'}",
        f"Market: {'OPEN' if forex.is_market_open() else 'CLOSED (weekend/holiday)'}",
        f"Sessions: {', '.join(forex.active_sessions()) or '—'}",
    ]
    if last_price:
        lines.append(f"Last price: {last_price:.5f}")

    try:
        # Market data via user_loop, which owns broker construction. This module
        # must not handle broker credentials: it is the one that talks to a
        # language model, and a credential path here is the kind that later
        # grows an order call.
        candles = user_loop.read_candles(user_id, symbol, 50)
        if candles:
            ind = indicators.analyze(candles)
            lines.append(
                f"Indicators: RSI={ind.get('rsi')}, "
                f"BB-pos={ind.get('bb_position')}%, "
                f"EMA trend={ind.get('emaTrend')}"
            )
    except Exception:
        pass

    if open_pos:
        entry = open_pos.get("entryPrice", 0)
        side = open_pos.get("side", "?")
        sl = open_pos.get("stopLoss", 0)
        tp = open_pos.get("takeProfit", 0)
        lines.append(
            f"Open position: {side} {open_pos.get('symbol', symbol)} "
            f"@ {entry:.5f} | SL: {sl:.5f} | TP: {tp:.5f}"
        )
    else:
        lines.append("Open position: None")

    trades = dash.get("trades", [])
    if trades:
        wins = sum(1 for t in trades if t.get("netPnl", 0) > 0)
        lines.append(f"Recent: {len(trades)} closed trades, {wins} wins")

    return "\n".join(lines)


def _run_tool(name: str, inp: dict, user_id: str, send_status) -> str:
    from apex import user_loop, user_store, forex, indicators
    send_status = send_status or (lambda _: None)

    if name == "analyze_market":
        symbol = inp.get("symbol", "EUR_USD").upper().replace("/", "_").replace("-", "_")
        # Show it the way every other message spells it. The status
        # line said "EUR_USD" one bubble above a reply saying
        # "EURUSD" — same instrument, two names, consecutive
        # messages. The underscore form stays internally because the
        # broker lookup wants it.
        send_status(f"🔍 Analyzing <b>{symbol.replace(chr(95), '')}</b>…")
        try:
            # Same rule as above: no broker credentials in this module.
            candles = user_loop.read_candles(user_id, symbol, 100)
            if not candles:
                return json.dumps({"error": "No market data available"})
            ind = indicators.analyze(candles)
            from apex import ai as ai_mod
            signal = ai_mod.mean_reversion_signal(ind, None)
            return json.dumps({
                "symbol": symbol,
                "price": candles[-1]["close"],
                "rsi": ind.get("rsi"),
                "bb_position": ind.get("bb_position"),
                "ema_trend": ind.get("emaTrend"),
                "signal": signal["action"],
                "confidence": signal["confidence"],
                "reasoning": signal.get("reasoning", ""),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    if name == "execute_trade":
        side = inp.get("side", "BUY").upper()
        symbol = inp.get("symbol", "EUR_USD").upper().replace("/", "_").replace("-", "_")
        send_status(f"⚡ Executing <b>{side} {symbol}</b>…")
        try:
            result = user_loop.force_trade(user_id, side, symbol)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "close_position":
        send_status("🔄 Closing position…")
        try:
            result = user_loop.force_close(user_id)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "set_symbol":
        symbol = inp.get("symbol", "EUR_USD").upper().replace("/", "_").replace("-", "_")
        try:
            user_store.update(user_id, {"symbol": symbol})
            return json.dumps({"ok": True, "symbol": symbol})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "set_risk":
        risk_pct = float(inp.get("risk_pct", 1.0))
        risk_pct = max(0.5, min(risk_pct, 10.0))
        try:
            user_store.update(user_id, {"risk": risk_pct / 100})
            return json.dumps({"ok": True, "risk_pct": risk_pct})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "pause_trading":
        try:
            user_loop.stop(user_id)
            return json.dumps({"ok": True, "status": "paused"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "resume_trading":
        try:
            if not user_loop.is_running(user_id):
                from apex.telegram import _user_alert
                user_loop.start(user_id, alert_fn=_user_alert)
            return json.dumps({"ok": True, "status": "active"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    return json.dumps({"error": f"Unknown tool: {name}"})


class _ProviderDown(Exception):
    pass


def _to_gemini_tools():
    decls = []
    for t in _TOOLS:
        decl = {"name": t["name"], "description": t["description"]}
        schema = t.get("input_schema") or {}
        if schema.get("properties"):
            decl["parameters"] = schema
        decls.append(decl)
    return [{"function_declarations": decls}]


def _chat_gemini(user_id: str, message: str, api_key: str, send_status=None) -> str:
    import requests
    send_status = send_status or (lambda _: None)
    model = getattr(cfg, "GEMINI_MODEL", "") or "gemini-2.5-flash"
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    context = _build_context(user_id)
    system = f"{_SYSTEM}\n\n--- ACCOUNT STATE ---\n{context}"

    history = _load_history(user_id)
    history.append({"role": "user", "content": message})

    contents = []
    for m in history[-chat_memory.MAX_HISTORY:]:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    tools = _to_gemini_tools()

    for _ in range(5):
        try:
            r = requests.post(
                url, params={"key": api_key},
                json={"system_instruction": {"parts": [{"text": system}]},
                      "contents": contents,
                      "tools": tools,
                      "generationConfig": {"maxOutputTokens": 600, "temperature": 0.3}},
                timeout=20,
            )
            if r.status_code == 429:
                raise _ProviderDown("gemini quota")
            r.raise_for_status()
        except _ProviderDown:
            raise
        except Exception as e:
            raise _ProviderDown(f"gemini {e}")

        data = r.json()
        cands = data.get("candidates", [])
        if not cands:
            raise _ProviderDown("gemini empty response")
        parts = cands[0].get("content", {}).get("parts", [])

        fcalls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not fcalls:
            reply = "".join(p.get("text", "") for p in parts).strip()
            if not reply:
                raise _ProviderDown("gemini empty text")
            _save_exchange(user_id, message, reply)
            return reply

        contents.append({"role": "model", "parts": parts})
        resp_parts = []
        for fc in fcalls:
            name = fc.get("name", "")
            args = fc.get("args", {}) or {}
            result = _run_tool(name, args, user_id, send_status)
            resp_parts.append({
                "functionResponse": {"name": name, "response": {"result": result}}
            })
        contents.append({"role": "user", "parts": resp_parts})

    return "⚠️ Could not complete the request. Please try again."


def _chat_openai_compatible(user_id, message, *, url, key, model, label,
                            timeout=15) -> str:
    """One chat turn against any OpenAI-compatible /chat/completions endpoint.

    Groq speaks this, and so does OmniRoute — which is the whole point of
    putting a gateway in front: it is the same wire format, so adding it costs
    a URL rather than a second copy of this function. A near-duplicate is how
    /ctaccount ended up with three formatters that slowly disagreed.
    """
    import requests
    if not url:
        raise _ProviderDown(f"no {label} url")

    context = _build_context(user_id)
    system = f"{_SYSTEM}\n\n--- ACCOUNT STATE ---\n{context}"

    history = _load_history(user_id)
    history.append({"role": "user", "content": message})
    messages = [{"role": "system", "content": system}] + history[-chat_memory.MAX_HISTORY:]

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = requests.post(
            url,
            json={"model": model, "messages": messages,
                  "max_tokens": 400, "temperature": 0.3},
            headers=headers, timeout=timeout,
        )
        if r.status_code == 429:
            raise _ProviderDown(f"{label} quota")
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"].strip()
        _save_exchange(user_id, message, reply)
        return reply
    except _ProviderDown:
        raise
    except Exception as e:
        raise _ProviderDown(f"{label} {e}")


def _chat_groq(user_id: str, message: str, api_key: str = "") -> str:
    key = api_key or cfg.GROQ_API_KEY
    if not key:
        raise _ProviderDown("no groq key")
    return _chat_openai_compatible(
        user_id, message,
        url="https://api.groq.com/openai/v1/chat/completions",
        key=key, model="llama-3.3-70b-versatile", label="groq")


def _chat_gateway(user_id: str, message: str) -> str:
    """OmniRoute (or any OpenAI-compatible gateway) in front of everything else.

    It fans one request out across hundreds of providers and re-routes on a
    quota or an outage, which is the problem this bot actually has: every
    client shares one Groq key, and the trading signal draws on the same quota.

    The longer timeout is deliberate. On Render's free plan the gateway sleeps
    after fifteen idle minutes and a cold start takes most of a minute — but a
    failure here is not a failure for the client, it just falls through to
    Gemini while the gateway wakes up behind them.
    """
    return _chat_openai_compatible(
        user_id, message,
        url=cfg.AI_GATEWAY_URL, key=cfg.AI_GATEWAY_KEY,
        model=cfg.AI_GATEWAY_MODEL, label="gateway",
        timeout=float(getattr(cfg, "AI_GATEWAY_TIMEOUT_S", 20)))


def _local_status(user_id: str) -> str:
    """Rule-based reply from real state — always works, no AI needed."""
    from apex import user_loop, user_store, forex
    user = user_store.load(user_id)
    dash = user_loop.get_dash(user_id) or {}
    balance = dash.get("balance", user.get("paper_balance", cfg.PAPER_BALANCE))
    start_bal = dash.get("startBalance", balance)
    pnl_pct = ((balance - start_bal) / start_bal * 100) if start_bal else 0
    symbol = dash.get("symbol") or user.get("symbol", cfg.SYMBOL)
    open_pos = dash.get("openPosition")
    market = "🟢 OPEN" if forex.is_market_open() else "🔴 CLOSED (weekend)"

    lines = [
        f"💼 <b>Balance:</b> ${balance:.2f} (start ${start_bal:.2f}, {pnl_pct:+.1f}%)",
        f"💱 <b>Pair:</b> {symbol} | {market}",
    ]
    if open_pos:
        entry = open_pos.get("entryPrice", 0)
        side = open_pos.get("side", "?")
        sl = open_pos.get("stopLoss", 0)
        tp = open_pos.get("takeProfit", 0)
        lines.append(
            f"📈 <b>Position:</b> {side} @ {entry:.5f}\n"
            f"   SL: {sl:.5f}  TP: {tp:.5f}\n"
            f"   Close with <code>/close</code>"
        )
    else:
        lines.append("📭 <b>No open position.</b> Bot is scanning automatically.")
        lines.append(f"<i>Force entry:</i> <code>/buy {symbol}</code> or <code>/sell {symbol}</code>")
    return "\n".join(lines)


def chat(user_id: str, message: str, send_fn, send_status=None) -> None:
    """Route to the best available AI, execute tools, send reply."""
    send_status = send_status or (lambda _: None)
    user_id = str(user_id)

    # Spec §10/§11: "unlimited" is a promise to the client, not to the
    # hardware. Every provider here draws on a shared free-tier quota, and the
    # trading signal draws on the same one — so an unbounded chat loop does
    # not just spam the assistant, it can starve the bot of its ability to
    # decide. Checked before any provider is touched, and before the work is
    # handed to a thread, so a flood costs one Redis INCR rather than a
    # thread and an API call.
    ok, why = chat_memory.allow(user_id)
    if not ok:
        send_fn(why)
        return

    def _run():
        try:
            # Per-user keys (the client pasted their own) take priority over the
            # shared admin keys, so every client can run AI chat on their own quota.
            from apex import user_store
            try:
                u = user_store.load(user_id)
            except Exception:
                u = {}
            gemini_key = u.get("gemini_key") or cfg.GEMINI_API_KEY
            groq_key = u.get("groq_key") or cfg.GROQ_API_KEY

            chain = []
            # The gateway goes first when configured: it is the only link that
            # can survive one provider's quota without the client noticing.
            # Everything below it stays as the backstop, so a gateway that is
            # down, cold or misconfigured costs a few seconds, never an answer.
            if cfg.AI_GATEWAY_URL:
                chain.append(("Gateway", lambda: _chat_gateway(user_id, message)))
            if gemini_key:
                chain.append(("Gemini", lambda: _chat_gemini(user_id, message, gemini_key, send_status)))
            if groq_key:
                chain.append(("Groq", lambda: _chat_groq(user_id, message, groq_key)))

            reply = None
            for name, prov in chain:
                try:
                    reply = prov()
                    if reply:
                        break
                except _ProviderDown as e:
                    print(f"[ForexAssistant:{user_id}] {name} down ({e}) → next")
                    continue
                except Exception as e:
                    print(f"[ForexAssistant:{user_id}] {name} error ({e}) → next")
                    continue

            if not reply:
                reply = (_local_status(user_id) +
                         "\n\n🧠 <b>Want AI chat to help you trade?</b>\n"
                         "It needs an API key — <b>your choice</b>, free or paid:\n"
                         "🥇 <b>Gemini</b> (free, 1,500/day) → aistudio.google.com/apikey\n"
                         "🥈 <b>Groq</b> (free, fast) → console.groq.com/keys\n"

                         "Then send <code>/ai</code> and paste your key. "
                         "<i>Trading runs fine without it — this only powers the chat.</i>")
            send_fn(reply)
        except Exception as e:
            print(f"[ForexAssistant:{user_id}] error: {e}")
            try:
                send_fn(_local_status(user_id))
            except Exception:
                send_fn("⚠️ Assistant error. Please try again.")

    threading.Thread(target=_run, daemon=True).start()


def _gemini_url() -> str:
    model = getattr(cfg, "GEMINI_MODEL", "") or "gemini-2.5-flash"
    return (f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent")


def test_groq_key(key: str):
    """Quick liveness check for a Groq key. Returns (ok, message)."""
    import requests
    key = (key or "").strip()
    if not key.startswith("gsk_"):
        return False, "Groq keys start with gsk_ — copy it from console.groq.com/keys"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                  "max_tokens": 5},
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=12,
        )
        if r.status_code == 401:
            return False, "Key rejected — recreate it at console.groq.com/keys"
        if r.status_code == 429:
            return True, "Key valid (was briefly rate-limited, that's fine)"
        r.raise_for_status()
        return True, "Key works"
    except Exception as e:
        return False, f"Could not verify key ({e})"


def test_gemini_key(key: str):
    """Quick liveness check for a Gemini key. Returns (ok, message)."""
    import requests
    key = (key or "").strip()
    if len(key) < 20:
        return False, "That doesn't look like a full API key — copy the whole thing from aistudio.google.com/apikey"
    try:
        r = requests.post(
            _gemini_url(), params={"key": key},
            json={"contents": [{"role": "user", "parts": [{"text": "Reply with the single word OK."}]}],
                  "generationConfig": {"maxOutputTokens": 5}},
            timeout=12,
        )
        if r.status_code == 429:
            return True, "Key valid (was briefly rate-limited, that's fine)"
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
                reason = next((d["reason"] for d in err.get("details", []) if d.get("reason")), "")
                msg = err.get("message", "")
            except Exception:
                reason, msg = "", r.text[:120]
            if reason == "API_KEY_INVALID":
                return False, "Google says the key is invalid. Recreate it at aistudio.google.com/apikey and copy the WHOLE key (starts with AIza)."
            if reason in ("SERVICE_DISABLED", "PERMISSION_DENIED"):
                return False, "The Generative Language API isn't enabled for this key's project. Create the key in a NEW project at aistudio.google.com/apikey."
            return False, f"Google rejected the key: {msg or reason or r.status_code}"
        r.raise_for_status()
        return True, "Key works"
    except Exception as e:
        return False, f"Could not verify key ({e})"


def clear_history(user_id: str) -> None:
    chat_memory.clear(user_id)
