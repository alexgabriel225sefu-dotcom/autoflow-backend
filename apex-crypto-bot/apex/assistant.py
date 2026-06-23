"""Conversational AI trading assistant — Claude tool-use via Telegram.

Users send free-text messages; Claude understands context, analyzes markets,
and executes trades through structured tools. Falls back to Groq chat if no
Anthropic key is configured.
"""
import json
import time
import threading
from apex import config as cfg

_clients: dict = {}     # api_key → anthropic.Anthropic client (cached per key)
_conv: dict = {}        # user_id → [{"role", "content"}]
_MAX_HISTORY = 12
_lock = threading.Lock()

_TOOLS = [
    {
        "name": "analyze_market",
        "description": (
            "Run fresh technical + AI analysis on a symbol. "
            "Use when asked about market conditions, signals, or whether to trade."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. BTCUSDT, ETHUSDT, AVAXUSDT"}
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "execute_trade",
        "description": (
            "Open a BUY or SELL position. "
            "Only call AFTER the user explicitly confirms they want to trade. "
            "Romanian confirmations: da, intră, execută, go."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "side":   {"type": "string", "enum": ["BUY", "SELL"]},
                "symbol": {"type": "string", "description": "e.g. BTCUSDT"},
            },
            "required": ["side", "symbol"],
        },
    },
    {
        "name": "close_position",
        "description": "Close the open position immediately. Only call when user asks to exit/close.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_symbol",
        "description": "Change the trading pair the bot auto-trades.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. BTCUSDT"}
            },
            "required": ["symbol"],
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

_SYSTEM = """You are Apex, an intelligent crypto trading assistant inside a Telegram bot.

You help users trade smarter: analyze markets, execute trades, explain results, fix issues.

RULES:
- Be concise — Telegram messages, 2-4 sentences max unless detailed analysis is needed
- Reply in the same language the user writes (Romanian or English)
- Before executing a trade: show signal analysis and ask for confirmation
  EXCEPTION: if user says "da" / "yes" / "go" / "execută" / "intră" — execute immediately
- Always cite real numbers: RSI, confidence %, price, P&L
- Auto-trading runs in background 24/7 — you only intervene when asked
- For errors: explain what happened in plain language and suggest a fix
- Use HTML for Telegram: <b>bold</b>, numbers, no markdown asterisks
- CRITICAL: NEVER invent or guess prices, RSI, or any market numbers.
  Use ONLY the live price from the account context below.
  If you don't have a number in the context, say "I don't have that data right now."

Current account context is injected below the system prompt."""


def _load_history(user_id: str):
    """Return conversation history, restoring from persistent store on first use."""
    with _lock:
        if user_id in _conv:
            return list(_conv[user_id])
    try:
        from apex import user_store
        hist = user_store.load_chat(user_id)
    except Exception:
        hist = []
    with _lock:
        _conv[user_id] = list(hist)
    return list(hist)


def _save_exchange(user_id: str, user_msg: str, assistant_msg: str):
    """Append a user+assistant turn to memory AND persist it (survives redeploys)."""
    with _lock:
        conv = list(_conv.get(user_id, []))
        conv.append({"role": "user", "content": user_msg})
        conv.append({"role": "assistant", "content": assistant_msg})
        conv = conv[-_MAX_HISTORY:]
        _conv[user_id] = conv
    try:
        from apex import user_store
        user_store.save_chat(user_id, conv)
    except Exception:
        pass


def _get_client(api_key: str):
    """Cache one Anthropic client per distinct API key (per-user keys supported)."""
    with _lock:
        client = _clients.get(api_key)
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        with _lock:
            _clients[api_key] = client
    return client


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


def _build_context(user_id: str) -> str:
    """Return a short account snapshot to inject into the system prompt."""
    from apex import user_loop, binance
    u = user_loop._ensure_user(user_id)
    state = u.get("state", {})
    settings = u.get("settings", {})

    balance = state.get("paperBalance", 0)
    start_bal = state.get("startBalance", 100)
    pnl_pct = ((balance - start_bal) / start_bal * 100) if start_bal else 0
    pos = state.get("openPosition")
    sig = state.get("lastSignal")
    trades = state.get("trades", [])

    symbol = settings.get("SYMBOL", "BTCUSDT")
    try:
        live_price = binance.get_price(symbol)
    except Exception:
        live_price = None

    # Live technical indicators so the assistant talks with REAL numbers
    # (works for both Claude and the Groq fallback, no tool call needed).
    indi = None
    try:
        from apex import indicators
        candles = binance.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES)
        if candles:
            indi = indicators.analyze(candles)
    except Exception:
        indi = None

    lines = [
        f"Balance: ${balance:.2f} USDT (start: ${start_bal:.2f}, P&L: {pnl_pct:+.1f}%)",
        f"Symbol: {symbol}",
        f"Live price: ${live_price:.4f}" if live_price else "Live price: unavailable",
        f"Auto-trading: {'PAUSED' if settings.get('PAUSED') else 'ACTIVE'}",
        f"Mode: {'Paper (testnet)' if u.get('paper', True) else 'LIVE'}",
    ]
    if indi:
        macd_h = float(indi.get("macdHist") or 0)
        lines.append(
            f"Live indicators ({cfg.TIMEFRAME}): RSI(14)={indi.get('rsi')}, "
            f"MACD={'bullish' if macd_h > 0 else 'bearish'} ({indi.get('macdHist')}), "
            f"EMA trend={indi.get('emaTrend')}, "
            f"volume ratio={indi.get('volumeRatio')}x, ATR={indi.get('atrPct')}%"
        )
    if pos:
        try:
            price = binance.get_price(pos["symbol"])
            pnl = pos.get("currentPnl", 0)
            lines.append(
                f"Open position: {pos['side']} {pos['symbol']} @ ${pos['entryPrice']:.4f} | "
                f"Now: ${price:.4f} | PnL: {pnl:+.4f} USDT | "
                f"SL: ${pos['stopLoss']:.4f} | TP: ${pos['takeProfit']:.4f}"
            )
        except Exception:
            lines.append(f"Open position: {pos['side']} {pos['symbol']}")
    else:
        lines.append("Open position: None")

    if sig:
        lines.append(
            f"Last signal: {sig['action']} {sig['confidence']:.0f}% — {sig.get('reasoning', '')[:80]}"
        )
    if trades:
        wins = sum(1 for t in trades if t.get("win"))
        lines.append(f"Recent trades: {len(trades)} total, {wins} wins")

    return "\n".join(lines)


def _run_tool(name: str, inp: dict, user_id: str, send_status) -> str:
    """Execute a tool and return the result as a JSON string for Claude."""
    from apex import user_loop, binance, indicators, strategies, ai

    if name == "analyze_market":
        symbol = inp.get("symbol", "BTCUSDT").upper()
        send_status(f"🔍 Analyzing <b>{symbol}</b>…")
        try:
            candles = binance.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES)
            if not candles:
                return json.dumps({"error": "No market data"})
            ind = indicators.analyze(candles)
            u = user_loop._ensure_user(user_id)
            strat = strategies.analyze(candles, u["state"].get("session", {}))
            signal = ai.get_signal(
                ind, u["state"].get("paperBalance", 100),
                u["state"].get("openPosition"), strat,
                symbol=symbol, timeframe=cfg.TIMEFRAME,
                user_key=u.get("groq_key") or None,
            )
            return json.dumps({
                "symbol": symbol,
                "price": ind.get("price"),
                "rsi": ind.get("rsi"),
                "macd": "bullish" if float(ind.get("macdHist") or 0) > 0 else "bearish",
                "trend": ind.get("emaTrend"),
                "volume_ratio": ind.get("volumeRatio"),
                "signal": signal["action"],
                "confidence": signal["confidence"],
                "criteria_score": signal.get("criteriaScore", 0),
                "reasoning": signal.get("reasoning", ""),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    if name == "execute_trade":
        side = inp.get("side", "BUY").upper()
        symbol = inp.get("symbol", "BTCUSDT").upper()
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
        symbol = inp.get("symbol", "BTCUSDT").upper()
        try:
            from apex import user_store
            u = user_loop._ensure_user(user_id)
            u["settings"]["SYMBOL"] = symbol
            user_store.save(user_id, u)
            return json.dumps({"ok": True, "symbol": symbol})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "pause_trading":
        try:
            from apex import user_store
            u = user_loop._ensure_user(user_id)
            u["settings"]["PAUSED"] = True
            user_store.save(user_id, u)
            return json.dumps({"ok": True, "status": "paused"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    if name == "resume_trading":
        try:
            user_loop.reset_risk(user_id)  # clears pause + risk counters
            if not user_loop.is_running(user_id):
                user_loop.start(user_id)
            return json.dumps({"ok": True, "status": "active"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    return json.dumps({"error": f"Unknown tool: {name}"})


def _chat_anthropic(user_id: str, message: str, api_key: str, send_fn, send_status) -> str:
    """Full Claude tool-use conversation loop."""
    client = _get_client(api_key)
    context = _build_context(user_id)
    system = f"{_SYSTEM}\n\n--- ACCOUNT STATE ---\n{context}"

    history = _load_history(user_id)
    history.append({"role": "user", "content": message})

    messages = history[-_MAX_HISTORY:]
    max_loops = 5

    for _ in range(max_loops):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system,
            messages=messages,
            tools=_TOOLS,
        )

        if response.stop_reason != "tool_use":
            # Final text response
            text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
            _save_exchange(user_id, message, text)
            return text

        # Execute all tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _run_tool(block.name, block.input, user_id, send_status)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        # Build next messages with tool results (raw blocks passed back to the API)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "⚠️ Could not complete request. Please try again."


def _chat_groq(user_id: str, message: str) -> str:
    """Simple Groq chat fallback (no tool execution — conversational only)."""
    import requests
    key = cfg.GROQ_API_KEY
    u_data = None
    try:
        from apex import user_loop
        u_data = user_loop._ensure_user(user_id)
        key = u_data.get("groq_key") or key
    except Exception:
        pass

    if not key:
        return "⚠️ No AI key configured. Add ANTHROPIC_API_KEY or GROQ_API_KEY to enable the assistant."

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
            return ("⏳ <b>Groq rate limit hit.</b> Asteapta 1-2 minute si incearca din nou.\n"
                    "Sfat: adauga <code>ANTHROPIC_API_KEY</code> in Render pentru asistent fara limite.")
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"].strip()
        _save_exchange(user_id, message, reply)
        return reply
    except requests.HTTPError as e:
        return f"⚠️ Asistent indisponibil momentan. Incearca din nou."
    except Exception as e:
        return f"⚠️ Eroare asistent: {e}"


def _gemini_url():
    """Build the Gemini endpoint from the configured model (default 2.5-flash)."""
    model = getattr(cfg, "GEMINI_MODEL", "") or "gemini-2.5-flash"
    return ("https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent")


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
            # A 429 only happens AFTER auth succeeds — the key is valid, save it.
            return True, "Key valid (was briefly rate-limited, that's fine)"
        if r.status_code >= 400:
            # Surface Google's real reason so we know exactly what's wrong
            try:
                err = r.json().get("error", {})
                reason = ""
                for d in err.get("details", []):
                    if d.get("reason"):
                        reason = d["reason"]
                        break
                msg = err.get("message", "")
            except Exception:
                reason, msg = "", r.text[:120]
            if reason == "API_KEY_INVALID":
                return False, "Google says the key is invalid. Recreate it at aistudio.google.com/apikey and copy the WHOLE key (starts with AIza, ~39 chars)."
            if reason in ("SERVICE_DISABLED", "PERMISSION_DENIED"):
                return False, "The Generative Language API isn't enabled for this key's project. Create the key in a NEW project at aistudio.google.com/apikey."
            if reason == "FAILED_PRECONDITION":
                return False, "Gemini API isn't available for your account's country/billing setup yet."
            return False, f"Google rejected the key: {msg or reason or r.status_code}"
        r.raise_for_status()
        return True, "Key works"
    except Exception as e:
        return False, f"Could not verify key ({e})"


def _to_gemini_tools():
    """Convert our Anthropic-style _TOOLS to Gemini function_declarations."""
    decls = []
    for t in _TOOLS:
        decl = {"name": t["name"], "description": t["description"]}
        schema = t.get("input_schema") or {}
        # Gemini rejects empty parameter objects — omit params for no-arg tools.
        if schema.get("properties"):
            decl["parameters"] = schema
        decls.append(decl)
    return [{"function_declarations": decls}]


def _chat_gemini(user_id: str, message: str, key: str, send_status=None) -> str:
    """Gemini path with function calling — FREE chat + real trade execution."""
    import requests
    send_status = send_status or (lambda _: None)
    context = _build_context(user_id)
    system = f"{_SYSTEM}\n\n--- ACCOUNT STATE ---\n{context}"

    history = _load_history(user_id)
    history.append({"role": "user", "content": message})

    # Map our history to Gemini's contents format (role "model" not "assistant")
    contents = []
    for m in history[-_MAX_HISTORY:]:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    tools = _to_gemini_tools()

    for _ in range(5):  # tool-use loop
        try:
            r = requests.post(
                _gemini_url(), params={"key": key},
                json={"system_instruction": {"parts": [{"text": system}]},
                      "contents": contents,
                      "tools": tools,
                      "generationConfig": {"maxOutputTokens": 600, "temperature": 0.3}},
                timeout=20,
            )
            if r.status_code == 429:
                return ("⏳ <b>Gemini limita zilnica atinsa.</b> Se reseteaza maine (1500/zi gratis).")
            r.raise_for_status()
        except requests.HTTPError:
            return "⚠️ Asistent (Gemini) indisponibil momentan. Incearca din nou."
        except Exception as e:
            return f"⚠️ Eroare asistent: {e}"

        data = r.json()
        cands = data.get("candidates", [])
        if not cands:
            return "⚠️ Gemini nu a returnat raspuns. Incearca din nou."
        parts = cands[0].get("content", {}).get("parts", [])

        # Collect any function calls Gemini wants to make
        fcalls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not fcalls:
            reply = "".join(p.get("text", "") for p in parts).strip()
            if not reply:
                return "⚠️ Gemini a returnat un raspuns gol. Incearca din nou."
            _save_exchange(user_id, message, reply)
            return reply

        # Echo the model's function-call turn, then append our results
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

    return "⚠️ Nu am putut finaliza cererea. Incearca din nou."


def chat(user_id: str, message: str, send_fn, send_status=None) -> None:
    """Main entry: route to the best available AI per user, send reply.

    Priority (owner's shared key covers ALL clients — clients need nothing):
      1. Anthropic key (user or shared) → Claude, full trade EXECUTION
      2. Gemini key (user or shared)    → FREE, full trade EXECUTION (function calling)
      3. Groq key (user or shared)      → free chat + analysis (no execution)
    """
    send_status = send_status or (lambda _: None)
    user_id = str(user_id)

    def _run():
        try:
            from apex import user_loop
            u = user_loop._ensure_user(user_id)
            anthropic_key = u.get("anthropic_key") or cfg.ANTHROPIC_API_KEY
            gemini_key = u.get("gemini_key") or cfg.GEMINI_API_KEY
            if anthropic_key:
                reply = _chat_anthropic(user_id, message, anthropic_key, send_fn, send_status)
            elif gemini_key:
                reply = _chat_gemini(user_id, message, gemini_key, send_status)
            else:
                reply = _chat_groq(user_id, message)
            if reply:
                send_fn(reply)
        except Exception as e:
            print(f"[Assistant:{user_id}] error: {e}")
            send_fn("⚠️ Assistant error. Please try again.")

    threading.Thread(target=_run, daemon=True).start()


def clear_history(user_id: str) -> None:
    user_id = str(user_id)
    with _lock:
        _conv.pop(user_id, None)
    try:
        from apex import user_store
        user_store.clear_chat(user_id)
    except Exception:
        pass
