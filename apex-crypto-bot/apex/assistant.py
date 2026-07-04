"""Conversational AI trading assistant — natural-language chat + trade execution.

Any free-text message from a client (non-command) comes here. The assistant
understands the user's intent, fetches live market data, and can execute trades
directly. Falls back gracefully when AI providers are unavailable.

Provider priority (shared owner key covers ALL clients):
  1. Claude (Anthropic) — full tool-use + execution
  2. Gemini              — FREE, full tool-use + execution
  3. Groq               — free chat + analysis only
  4. Local status       — always works, no AI needed
"""
import json
import threading
from apex import config as cfg

_conv: dict = {}       # user_id → [{"role", "content"}]
_clients: dict = {}    # api_key → anthropic.Anthropic client (cached)
_MAX_HISTORY = 10
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
- LANGUAGE: Detect the user's language and ALWAYS reply in that EXACT language.
  Romanian, English, Spanish, French, Italian, Portuguese, German, Arabic, Russian — any.
  Never default to a fixed language; mirror whatever the user wrote.
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
    with _lock:
        return list(_conv.get(user_id, []))


def _save_exchange(user_id: str, user_msg: str, assistant_msg: str):
    with _lock:
        conv = list(_conv.get(user_id, []))
        conv.append({"role": "user", "content": user_msg})
        conv.append({"role": "assistant", "content": assistant_msg})
        _conv[user_id] = conv[-_MAX_HISTORY:]


def _get_anthropic_client(api_key: str):
    with _lock:
        client = _clients.get(api_key)
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        with _lock:
            _clients[api_key] = client
    return client


def _build_context(user_id: str) -> str:
    """Inject live account state so the AI talks with real numbers."""
    from apex import user_loop, user_store, forex, indicators
    from apex.brokers import yahoo
    from apex.brokers.oanda import OandaBroker
    import types

    user = user_store.load(user_id)
    dash = user_loop.get_dash(user_id) or {}

    balance = dash.get("balance", user.get("paper_balance", cfg.PAPER_BALANCE))
    start_bal = dash.get("startBalance", balance)
    pnl_pct = ((balance - start_bal) / start_bal * 100) if start_bal else 0
    symbol = dash.get("symbol") or user.get("symbol", cfg.SYMBOL)
    paper = user.get("paper", cfg.PAPER_TRADING)
    open_pos = dash.get("openPosition")
    last_price = dash.get("currentPrice")

    lines = [
        f"Balance: ${balance:.2f} (start ${start_bal:.2f}, P&L: {pnl_pct:+.1f}%)",
        f"Symbol: {symbol}",
        f"Mode: {'Paper (simulated)' if paper else 'LIVE OANDA'}",
        f"Market: {'OPEN' if forex.is_market_open() else 'CLOSED (weekend/holiday)'}",
        f"Sessions: {', '.join(forex.active_sessions()) or '—'}",
    ]
    if last_price:
        lines.append(f"Last price: {last_price:.5f}")

    try:
        fake_cfg = types.SimpleNamespace(
            OANDA_API_TOKEN=user.get("oanda_token", ""),
            OANDA_ACCOUNT_ID=user.get("oanda_account_id", ""),
            OANDA_ENV=user.get("oanda_env", "practice"),
            SYMBOL=symbol, TIMEFRAME=cfg.TIMEFRAME, CANDLES=50,
            PAPER_TRADING=paper, PAPER_BALANCE=balance,
            STOP_LOSS_PIPS=float(user.get("sl_pips", cfg.STOP_LOSS_PIPS)),
            TAKE_PROFIT_PIPS=float(user.get("tp_pips", cfg.TAKE_PROFIT_PIPS)),
            RISK_PER_TRADE=float(user.get("risk", cfg.RISK_PER_TRADE)),
            LEVERAGE=float(user.get("leverage", cfg.LEVERAGE)),
            MARGIN_CAP=0.5, MAX_SPREAD_PIPS=3.0,
            MIN_CONFIDENCE=int(user.get("min_confidence", cfg.MIN_CONFIDENCE)),
        )
        broker = yahoo if (paper and not user.get("oanda_token")) else OandaBroker(fake_cfg)
        candles = broker.get_candles(symbol, cfg.TIMEFRAME, 50)
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
        send_status(f"🔍 Analyzing <b>{symbol}</b>…")
        try:
            from apex.brokers import yahoo
            from apex.brokers.oanda import OandaBroker
            import types
            user = user_store.load(user_id)
            paper = user.get("paper", True)
            fake_cfg = types.SimpleNamespace(
                OANDA_API_TOKEN=user.get("oanda_token", ""),
                OANDA_ACCOUNT_ID=user.get("oanda_account_id", ""),
                OANDA_ENV="practice", SYMBOL=symbol, TIMEFRAME=cfg.TIMEFRAME,
                CANDLES=100, PAPER_TRADING=paper, PAPER_BALANCE=1000,
                STOP_LOSS_PIPS=cfg.STOP_LOSS_PIPS, TAKE_PROFIT_PIPS=cfg.TAKE_PROFIT_PIPS,
                RISK_PER_TRADE=cfg.RISK_PER_TRADE, LEVERAGE=cfg.LEVERAGE,
                MARGIN_CAP=0.5, MAX_SPREAD_PIPS=3.0, MIN_CONFIDENCE=cfg.MIN_CONFIDENCE,
            )
            broker = yahoo if (paper and not user.get("oanda_token")) else OandaBroker(fake_cfg)
            candles = broker.get_candles(symbol, cfg.TIMEFRAME, 100)
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


def _chat_anthropic(user_id: str, message: str, api_key: str, send_fn, send_status) -> str:
    client = _get_anthropic_client(api_key)
    context = _build_context(user_id)
    system = f"{_SYSTEM}\n\n--- ACCOUNT STATE ---\n{context}"

    history = _load_history(user_id)
    history.append({"role": "user", "content": message})
    messages = history[-_MAX_HISTORY:]

    for _ in range(5):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=system,
                messages=messages,
                tools=_TOOLS,
            )
        except Exception as e:
            raise _ProviderDown(f"claude: {e}")

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
            _save_exchange(user_id, message, text)
            return text

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _run_tool(block.name, block.input, user_id, send_status)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "⚠️ Could not complete request. Please try again."


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
    for m in history[-_MAX_HISTORY:]:
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


def _chat_groq(user_id: str, message: str, api_key: str = "") -> str:
    import requests
    key = api_key or cfg.GROQ_API_KEY
    if not key:
        raise _ProviderDown("no groq key")

    context = _build_context(user_id)
    system = f"{_SYSTEM}\n\n--- ACCOUNT STATE ---\n{context}"

    history = _load_history(user_id)
    history.append({"role": "user", "content": message})
    messages = [{"role": "system", "content": system}] + history[-_MAX_HISTORY:]

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={"model": "llama-3.3-70b-versatile", "messages": messages,
                  "max_tokens": 400, "temperature": 0.3},
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code == 429:
            raise _ProviderDown("groq quota")
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"].strip()
        _save_exchange(user_id, message, reply)
        return reply
    except _ProviderDown:
        raise
    except Exception as e:
        raise _ProviderDown(f"groq {e}")


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

    def _run():
        try:
            # Per-user keys (the client pasted their own) take priority over the
            # shared admin keys, so every client can run AI chat on their own quota.
            from apex import user_store
            try:
                u = user_store.load(user_id)
            except Exception:
                u = {}
            anthropic_key = u.get("anthropic_key") or cfg.ANTHROPIC_API_KEY
            gemini_key = u.get("gemini_key") or cfg.GEMINI_API_KEY
            groq_key = u.get("groq_key") or cfg.GROQ_API_KEY

            chain = []
            if anthropic_key:
                chain.append(("Claude", lambda: _chat_anthropic(user_id, message, anthropic_key, send_fn, send_status)))
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
                         "🥉 <b>Claude</b> (paid, smartest) → console.anthropic.com\n"
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


def test_key(key: str):
    """Quick liveness check for a client's Anthropic key. Returns (ok, message)."""
    if not key or not key.startswith("sk-ant-"):
        return False, "Key must start with sk-ant-"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with the single word OK."}],
        )
        return True, "Key works"
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 401:
            return False, "Key rejected (401) — copy it again from console.anthropic.com"
        if status == 429:
            return False, "Key is valid but out of credits/rate-limited"
        return False, f"Could not verify key ({e})"


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
    user_id = str(user_id)
    with _lock:
        _conv.pop(user_id, None)
