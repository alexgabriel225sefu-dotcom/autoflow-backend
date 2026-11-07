"""Voice control from a phone: who is asking, and what may they do.

Siri cannot be replaced — iOS gives no third party the wake word — so this is
a Shortcut that Siri launches by name, posting a dictated question here. The
answer comes from the existing assistant; this module is the door.

The owner asked for full control including trades, and reaffirmed it. So the
tests here are not about narrowing that. They are about the two things that
can go wrong once a phone holds a credential to an account that trades real
money:

  * the token must identify exactly one account, and must not be recoverable
    from anything we store;
  * a misheard word must not become a market order. Dictation confuses
    precisely the words that matter — "close"/"closed", 0.5/5, "buy"/"by" —
    so a financial action is described back and executed by ID, never by
    re-interpreting whatever the client said the second time.

Run: python tests/test_voice_api.py
"""
import inspect
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-voice-")

from apex import voice_api, user_store, assistant  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


user_store.update("500", {"active": True})
user_store.update("501", {"active": True})

print("\n🧪 VOICE CONTROL — the door, and the step before the market order\n")

print("1. The token names one account and proves it")
tok = voice_api.mint("500")
check("it resolves to its owner", voice_api.identify(tok) == "500")
check("a token for another account does not open this one",
      voice_api.identify(voice_api.mint("501")) == "501")
check("garbage is refused", voice_api.identify("nonsense") is None)
check("an empty token is refused", voice_api.identify("") is None
      and voice_api.identify(None) is None)
check("a well-formed guess at someone else's id is refused",
      voice_api.identify("500.notthesecret") is None,
      "the id is only a lookup — the secret still has to match that record")
# The id in the token cannot be swapped for another account's.
forged = "501." + tok.partition(".")[2]
check("one account's secret does not unlock another",
      voice_api.identify(forged) is None,
      "this is the IDOR: same secret, different id in front of it")

print("\n2. What we store cannot be turned back into a key")
rec = user_store.load("500")
check("the raw token is nowhere in the record",
      tok.partition(".")[2] not in json.dumps(rec),
      "a leaked record must not be a leaked credential")
check("only a hash is kept", len(rec.get(voice_api.TOKEN_FIELD, "")) == 64)
check("the record knows a key exists", voice_api.has_token(rec) is True)

print("\n3. Revoking is immediate, and re-issuing invalidates the old key")
old_tok = voice_api.mint("500")
new_tok = voice_api.mint("500")
check("the previous key stops working", voice_api.identify(old_tok) is None,
      "'I lost my phone' has to be answerable")
check("the new one works", voice_api.identify(new_tok) == "500")
check("revoke reports it did something", voice_api.revoke("500") is True)
check("and the key is dead", voice_api.identify(new_tok) is None)
check("revoking twice is honest about it", voice_api.revoke("500") is False)

print("\n4. A financial action is never executed on the turn that asks for it")
tok = voice_api.mint("500")
ran = []
seen_prefs = []


def fake_run_tool(name, inp, user_id, send_status, guard=None):
    if guard is not None:
        held = guard(name, inp or {})
        if held is not None:
            return held
    ran.append((name, inp))
    return json.dumps({"ok": True, "positionId": 1})


def fake_chat(user_id, message, send_fn, send_status=None, guard=None,
              prefer_tools=False, voice=False):
    seen_prefs.append(prefer_tools)
    # Stands in for the model deciding to place a trade.
    out = fake_run_tool("execute_trade", {"side": "BUY", "symbol": "GBP_USD"},
                        user_id, None, guard)
    send_fn("Confirm?" if "awaiting_confirmation" in out else "Placed.")


_real_chat, _real_run = assistant.chat, assistant._run_tool
assistant.chat, assistant._run_tool = fake_chat, fake_run_tool
try:
    res = voice_api.ask(tok, "buy gbpusd")
    check("nothing was executed", ran == [], ran)
    check("the caller is told a confirmation is needed",
          res.get("needsConfirm") is True, res)
    check("it comes with an id to confirm by", bool(res.get("confirmId")))
    check("and a sentence the phone can read out",
          res.get("confirmQuestion") == "Open a BUY on GBPUSD?", res)
    # The gateway and Groq send plain completions with no function
    # declarations, so on those paths "close my position" comes back as a
    # fluent sentence with nothing behind it. A control channel must ask for
    # the providers that can actually act.
    check("the channel asks for a provider that can actually call a tool",
          seen_prefs == [True], seen_prefs)

    print("\n5. Confirming runs the stored intent, not the words said again")
    cid = res["confirmId"]
    done = voice_api.confirm(tok, cid, agreed=True)
    check("the trade goes through", done.get("ok") is True, done)
    check("it is the intent that was described back",
          ran == [("execute_trade", {"side": "BUY", "symbol": "GBP_USD"})], ran)
    check("the reply says what happened", "BUY" in done.get("reply", ""), done)

    print("\n6. 'Yes' twice must not open two positions")
    again = voice_api.confirm(tok, cid, agreed=True)
    check("the id is spent", again.get("ok") is False, again)
    check("and nothing ran a second time", len(ran) == 1, ran)

    print("\n7. Saying no places nothing")
    ran.clear()
    res2 = voice_api.ask(tok, "buy gbpusd")
    no = voice_api.confirm(tok, res2["confirmId"], agreed=False)
    check("cancelled cleanly", no.get("ok") is True and "Cancelled" in no["reply"], no)
    check("nothing was placed", ran == [], ran)
    check("and the cancelled id cannot be used after",
          voice_api.confirm(tok, res2["confirmId"], agreed=True).get("ok") is False)

    print("\n8. An unknown or expired id is refused, not guessed at")
    check("a made-up id does nothing",
          voice_api.confirm(tok, "not-a-real-id").get("ok") is False)
    check("one account cannot confirm another's pending trade",
          voice_api.confirm(voice_api.mint("501"),
                            voice_api.ask(tok, "buy")["confirmId"]).get("ok") is False,
          "pending intents are scoped to the account that raised them")

    print("\n9. The owner can switch the step off — it is a default, not a wall")
    ran.clear()
    user_store.update("500", {"voice_confirm": False})
    res3 = voice_api.ask(tok, "buy gbpusd")
    check("the trade goes straight through", len(ran) == 1, ran)
    check("and nothing is left pending", not res3.get("needsConfirm"), res3)
    user_store.update("500", {"voice_confirm": True})

    print("\n10. Non-financial questions are never held back")
    ran.clear()

    def read_only_chat(user_id, message, send_fn, send_status=None, guard=None,
                       prefer_tools=False, voice=False):
        out = fake_run_tool("analyze_market", {"symbol": "EUR_USD"},
                            user_id, None, guard)
        send_fn("<b>RSI</b> is 60. 📈")

    assistant.chat = read_only_chat
    r = voice_api.ask(tok, "how is eurusd looking")
    check("a read-only tool runs immediately", len(ran) == 1, ran)
    check("no confirmation is asked for", not r.get("needsConfirm"), r)
    check("the answer is stripped of chat markup for speech",
          r["reply"] == "RSI is 60.", r)
finally:
    assistant.chat, assistant._run_tool = _real_chat, _real_run

print("\n10b. A spoken \"yes\" resolves the trade that was just described")
# Apple refuses to import unsigned .shortcut files, so the shortcut has to be
# assembled by hand — which means it must be as short as possible, which means
# no If-branch to carry a confirmation id back. The server remembers what it
# just described, and the next thing said resolves it. That is also how it
# sounds out loud: "Open a BUY on GBPUSD?" — "yes".
assistant.chat, assistant._run_tool = fake_chat, fake_run_tool
try:
    ran.clear()
    tok2 = tok          # NOT a fresh mint: that would revoke the token the
                        # sections below still use.
    asked = voice_api.ask(tok2, "buy gbpusd")
    check("the trade is described, not placed", ran == [] and asked["needsConfirm"])
    done2 = voice_api.ask(tok2, "Yes.")
    check("a bare yes places it", len(ran) == 1, ran)
    check("and says so", "BUY" in done2.get("reply", ""), done2)
    check("saying yes again does nothing", voice_api.ask(tok2, "yes") is not None
          and len(ran) == 1, ran)

    ran.clear()
    voice_api.ask(tok2, "buy gbpusd")
    stopped = voice_api.ask(tok2, "nu")
    check("Romanian \"nu\" cancels", ran == [] and "Cancelled" in stopped["reply"], stopped)

    ran.clear()
    voice_api.ask(tok2, "buy gbpusd")
    ok_ro = voice_api.ask(tok2, "da")
    check("Romanian \"da\" confirms", len(ran) == 1, ran)

    # With nothing pending, "yes" is just a word and goes to the assistant
    # like any other turn, rather than being swallowed as a confirmation.
    ran.clear()
    seen_text = []

    def echo_chat(user_id, message, send_fn, send_status=None, guard=None,
                  prefer_tools=False, voice=False):
        seen_text.append(message)
        send_fn("Nothing is pending.")

    assistant.chat = echo_chat
    plain = voice_api.ask(tok2, "yes")
    check("a yes with nothing pending reaches the assistant",
          seen_text == ["yes"], seen_text)
    check("and nothing is executed",
          ran == [] and not plain.get("needsConfirm"), plain)
finally:
    assistant.chat, assistant._run_tool = _real_chat, _real_run

print("\n11. A slow provider degrades to facts, it does not hang the phone")
# iOS Shortcuts answered "The request timed out" against the first version of
# this, which waited 45s: the provider chain leads with the AI gateway, which
# carries its own 20s timeout and sleeps on Render's free plan. A phone will
# not hold a request open that long and neither will a person standing there
# holding it. Running out of budget must produce the account state, which
# needs no AI at all, rather than an apology or a dead socket.
_real_chat2, _real_local = assistant.chat, assistant._local_status
_slow_budget = voice_api._REPLY_TIMEOUT_S
try:
    voice_api._REPLY_TIMEOUT_S = 0.2
    assistant.chat = lambda *a, **k: None          # never calls back
    assistant._local_status = (lambda uid, voice=False:
                               "<b>Balance:</b> $3,214. 📭 No position.")
    import time as _t
    t0 = _t.time()
    slow = voice_api.ask(tok, "what's my balance")
    took = _t.time() - t0
    check("the caller is answered, not left waiting", slow.get("ok") is True, slow)
    check("and answered quickly", took < 3, f"{took:.1f}s")
    check("with real account state", "Balance: $3,214" in slow["reply"], slow)
    check("the voice channel asks for the spoken variant",
          "voice=True" in inspect.getsource(voice_api._fallback),
          "the chat copy recites URLs and command syntax")
    check("and told the reasoning was unavailable",
          "could not reach the assistant" in slow["reply"], slow)
    check("the budget is short enough for a phone to wait",
          _slow_budget <= 15, f"{_slow_budget}s")

    # Only when even that fails is there nothing to say.
    assistant._local_status = (lambda uid, voice=False:
                               (_ for _ in ()).throw(RuntimeError("no dash")))
    dead = voice_api.ask(tok, "what's my balance")
    check("a total failure is still a sentence, not a crash",
          dead.get("status") == 504 and "unaffected" in dead["reply"], dead)
finally:
    voice_api._REPLY_TIMEOUT_S = _slow_budget
    assistant.chat, assistant._local_status = _real_chat2, _real_local

print("\n12. A dead or missing key gets a sentence, not a stack trace")
check("no token is 401", voice_api.ask("", "hello").get("status") == 401)
check("a revoked token is 401",
      (voice_api.revoke("500"), voice_api.ask(tok, "hi").get("status"))[1] == 401)
check("the refusal is speakable",
      "Telegram" in voice_api.ask("", "hi")["reply"])
tok = voice_api.mint("500")
check("an empty question is refused", voice_api.ask(tok, "  ").get("status") == 400)

print("\n13. Speech cleanup")
check("markup is removed", voice_api.speakable("<b>Balance:</b> $10") == "Balance: $10")
check("entities are decoded", voice_api.speakable("A &amp; B") == "A & B")
check("nothing crashes on None", voice_api.speakable(None) == "")

print("\n14. Wired end to end")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
AS = open(os.path.join(ROOT, "apex", "assistant.py"), encoding="utf-8").read()
check("the route exists", '"/api/voice"' in BOT)
# Scope the read to the branch's own body. A substring check against the whole
# file — or even the text after the route — matches the COMMENT explaining why
# the operator token is not used here, so it would pass on prose alone.
# The end marker used to be the /api/mt/sync branch. That route was removed —
# it was an execution path for a broker this build no longer supports — so the
# slice now ends at the do_POST handler's final `else`, which is structural
# rather than a route name that can disappear again.
VOICE_BRANCH = BOT.split('elif self.path == "/api/voice":')[1].split(
    "            else:\n                self.send_response(404)")[0]
check("identity comes from the per-client voice token",
      "voice_api.ask(" in VOICE_BRANCH and "voice_api.confirm(" in VOICE_BRANCH,
      VOICE_BRANCH[:200])
check("the operator's dashboard gate does not stand in for it",
      "_authorized()" not in VOICE_BRANCH,
      "DASHBOARD_TOKEN reads every account; this route must read exactly one")
check("a confirmation is routed by id, never by re-reading the words",
      'req.get("confirmId")' in VOICE_BRANCH)
# A GET used to fall through to the dashboard gate and answer "503 — dashboard
# disabled", which is true of the dashboard and says nothing about the endpoint
# asked for, and wrote no log line at all — so a shortcut misconfigured to send
# GET was indistinguishable from a request that never left the phone.
check("a GET on the voice endpoint is answered as method-not-allowed",
      'self.path.startswith("/api/voice")' in BOT
      and "405" in BOT.split('self.path.startswith("/api/voice")')[1][:900],
      "a POST-only endpoint must say so, not blame the dashboard")
check("and it is logged, so the two silences are told apart",
      "[Voice] GET on /api/voice" in BOT)
check("/voice is routed with its argument", "_handle_voice(chat_id, args)" in TG)
# Apple refuses to import unsigned .shortcut files — "Importing unsigned
# shortcut files is not supported" — so a ready-built file cannot be handed
# over, and there is no point serving one. The instructions build the SHORT
# version instead: three actions, added top to bottom into an empty shortcut
# so each lands at the end and nothing is ever dragged, and no variable wired
# into Speak Text. Dragging an action and wiring that variable are the two
# things that went wrong every time this was assembled by hand.
check("nothing offers a downloadable shortcut file",
      "voice/shortcut" not in TG and "voice/shortcut" not in BOT,
      "iOS cannot import it, so it must not be advertised")
check("the instructions point at the plain-text endpoint",
      "/api/voice/say" in TG)
check("they say to start from an empty shortcut",
      "empty" in TG.split("Build it")[1][:600])
# (that Speak Text needs no wiring is asserted on the RENDERED text in
# section 18 — a source check breaks on a string split across two lines)
check("the guard reaches the tool runner", "def _run_tool(name: str, inp: dict, user_id: str, send_status, guard=None)" in AS)
check("Telegram still calls the assistant unguarded, unchanged",
      "assistant.chat(" in TG)
check("only tool-capable providers are preferred for acting",
      assistant.TOOL_CAPABLE == ("Gemini",), assistant.TOOL_CAPABLE)
SAY = BOT.split('elif self.path == "/api/voice/say":')[1].split(
    'elif self.path == "/api/voice":')[0]
check("there is a plain-text endpoint for a three-action shortcut",
      'elif self.path == "/api/voice/say":' in BOT)
check("it answers text, not JSON", "text/plain" in SAY and "json.dumps" not in SAY,
      "plain text is what lets Speak Text chain itself with nothing to wire")
check("and always 200, so a refusal is spoken rather than swallowed",
      "self.send_response(200)" in SAY and "out.get(\"status\"" not in SAY)
check("a non-JSON body is taken as the question itself",
      "tok, said = hdr_tok, raw" in SAY,
      "this is the shape that needs no variable picked by hand")
check("and its key comes from the Authorization header",
      "hdr_tok" in SAY and "Bearer" in SAY)
check("JSON still wins when it is JSON", "if req:" in SAY)
check("both money tools are guarded",
      voice_api.FINANCIAL_TOOLS == {"execute_trade", "close_position"},
      voice_api.FINANCIAL_TOOLS)

print("\n15. /ai reads the key you typed with it")
# `/ai <key>` is the obvious thing to type. It used to be read as a bare /ai:
# the key was dropped, the instructions came back, and the key sat in the chat
# history. Reported live, with a Google ephemeral token (AQ.…) that also is
# not an API key — so the refusal has to say what it actually saw.
from apex import telegram  # noqa: E402

_sent = []
_real_send, _real_del = telegram.send_to, telegram._delete_message
try:
    telegram.send_to = lambda cid, text, *a, **k: _sent.append(text)
    telegram._delete_message = lambda *a, **k: None

    telegram._handle_ai_setup("900", "abc123", 1)
    wrong = _sent[-1]
    check("a truncated key is rejected, not silently ignored",
          "doesn't look like a full key" in wrong, wrong[:120])
    check("and the refusal says what it actually got",
          "abc1" in wrong and "6 characters" in wrong, wrong[:200])
    check("it names both places to copy a real one",
          "aistudio.google.com/apikey" in wrong and "console.groq.com" in wrong)

    _sent.clear()
    telegram._handle_ai_setup("900", "", 1)
    check("a bare /ai still shows the setup screen",
          "Activate AI chat" in _sent[-1], _sent[-1][:80])
finally:
    telegram.send_to, telegram._delete_message = _real_send, _real_del

print("\n16. Key formats change; a prefix list must not be the gate")
# Google AI Studio issued keys beginning AIza for years and now issues them
# beginning AQ. — reported live by a client whose brand-new Gemini key was
# refused as "not an AI key" while working perfectly everywhere else. Any
# hard-coded prefix list goes stale the same way, so where the client has
# SAID they are handing over a key, Google decides, not us.
check("the historic Gemini format still works",
      telegram._detect_ai_key("AIzaSyABCDEFGHIJKLMNOPQRSTUV") == "gemini")
check("the current Gemini format works",
      telegram._detect_ai_key("AQ.Ab8RN6I8FYogIlADmgnaJNnDxNDD") == "gemini")
check("Groq's prefix still wins outright",
      telegram._detect_ai_key("gsk_abcdefghijklmnopqrstuvwxyz01") == "groq")
check("an unrecognised format is accepted when offered explicitly",
      telegram._detect_ai_key("zz9PlaskFooBarBaz1234567890abcdefXYZ",
                              explicit=True) == "gemini",
      "the next format change must not need a deploy")
check("but a bare message is never swallowed as a secret",
      telegram._detect_ai_key("zz9PlaskFooBarBaz1234567890abcdefXYZ") is None,
      "a bare paste is deleted from the chat — that must need a known prefix")
check("ordinary chat is not mistaken for a key even when explicit",
      telegram._detect_ai_key("cum merge botul meu azi", explicit=True) is None)
check("nor is something far too short",
      telegram._detect_ai_key("abc123", explicit=True) is None)

ROUTE = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
check("the /ai command passes its argument through",
      "_handle_ai_setup(chat_id, args, msg_id)" in ROUTE)
check("the explicit path lets the provider decide",
      "_detect_ai_key(key, explicit=True)" in ROUTE)

print("\n17. A key check must test the KEY, not a model that may be gone")
# Reported live: a valid Groq key was refused. The check sent a chat
# completion to a hard-coded model, so the day Groq retires that model every
# valid key starts failing — and it was reported as "Key rejected — recreate
# it", sending people off to regenerate a credential that was fine. The check
# now runs against /models, which is authentication-only.
import inspect  # noqa: E402

check("a voice turn never gets the sign-up pitch",
      'if voice:' in inspect.getsource(assistant.chat)
      and "_local_status(user_id, voice=True)" in inspect.getsource(assistant.chat),
      "Siri read the whole Gemini/Groq pitch aloud after a one-line answer")

GROQ_SRC = inspect.getsource(assistant.test_groq_key)
check("the Groq check calls the models endpoint",
      "/openai/v1/models" in GROQ_SRC, GROQ_SRC[:200])
check("and does not post a completion to a named model",
      "chat/completions" not in GROQ_SRC,
      "a model name in a key check is the bug being fixed")
check("a non-gsk_ string is refused before any network call",
      assistant.test_groq_key("AQ.Ab8")[0] is False)
check("the chat model is a setting, not a literal",
      assistant.groq_model() == assistant.GROQ_DEFAULT_MODEL)
os.environ["GROQ_MODEL"] = "some-newer-model"
check("and the setting is honoured without a deploy",
      assistant.groq_model() == "some-newer-model")
del os.environ["GROQ_MODEL"]

ASRC = open(os.path.join(ROOT, "apex", "assistant.py"), encoding="utf-8").read()
check("the Groq chat path uses the same setting",
      "model=groq_model()" in ASRC)
check("Gemini's model is a setting too", "_gemini_model_name()" in ASRC)
check("a retired Gemini model is not reported as a bad key",
      'r.status_code == 404 and "model" in' in ASRC)

print("\n17b. The no-AI answer must survive a trade that is winning")
# `.get(key, 0)` falls back only when the key is ABSENT. `takeProfit` is
# present and null the moment ride-winners clears the fixed target to let a
# trade run, so the default never applied and f"{None:.5f}" raised. That crash
# landed in the LAST fallback of chat() — which calls this same function again,
# fails again, and answers "Assistant error. Please try again." The one reply
# guaranteed to work without any AI was the one guaranteed to fail on a winner.
_real_dash = assistant.__dict__.get("_dash_probe")
from apex import user_loop as _ul  # noqa: E402

_keep = _ul.get_dash
try:
    _ul.get_dash = lambda uid: {
        "balance": 3214.0, "startBalance": 3214.0, "symbol": "GBPUSD",
        "openPosition": {"side": "BUY", "entryPrice": 1.36078,
                         "stopLoss": 1.36178, "takeProfit": None,
                         "pnlPips": 23.8, "pnlUsd": 11.9}}
    out17 = assistant._local_status("500")
    check("a trailing trade with no take profit does not crash it",
          "BUY" in out17, out17[:120])
    check("it says the target is gone because it is trailing",
          "trailing" in out17, out17)
    check("and leads with what the trade is actually doing",
          "+23.8 pips" in out17 and "11.90" in out17, out17)

    _ul.get_dash = lambda uid: {"balance": 3214.0, "symbol": "GBPUSD",
                                "openPosition": {"side": None, "entryPrice": None,
                                                 "stopLoss": None,
                                                 "takeProfit": None}}
    check("a position with no numbers at all is still answerable",
          "Position" in assistant._local_status("500"))

    _ul.get_dash = lambda uid: {"balance": 3214.0, "symbol": "GBPUSD"}
    check("no position reads cleanly too",
          "No open position" in assistant._local_status("500"))

    # Spoken, command syntax is noise: "Force entry, slash buy GBPUSD" read
    # aloud to someone holding a phone and talking to it. Reported live.
    spoken = assistant._local_status("500", voice=True)
    check("spoken, it does not recite command syntax",
          "/buy" not in spoken and "/sell" not in spoken, spoken)
    check("but the chat still offers them", "/buy" in assistant._local_status("500"))

    _ul.get_dash = lambda uid: {
        "balance": 3214.0, "symbol": "GBPUSD",
        "openPosition": {"side": "BUY", "entryPrice": 1.36078,
                         "stopLoss": 1.36178, "takeProfit": None}}
    check("nor how to close it", "/close" not in assistant._local_status("500", voice=True))
    check("while the chat still says how", "/close" in assistant._local_status("500"))
finally:
    _ul.get_dash = _keep

print("\n18. One button, and it upgrades itself when the link exists")
# Apple refuses unsigned .shortcut files and only an Apple device can sign
# one, so the first copy has to be built on an iPhone and shared — which
# yields a permanent iCloud link every later client installs with one tap.
# The button must not have to change when that link appears: setting
# VOICE_SHORTCUT_URL has to upgrade everyone at once.
from apex import config as _cfg  # noqa: E402

os.environ["RENDER_EXTERNAL_URL"] = "https://example.invalid"
_shots = []
_rs, _rd = telegram.send_to, telegram._delete_message
_was_url = getattr(_cfg, "VOICE_SHORTCUT_URL", "")
try:
    telegram.send_to = lambda cid, text, *a, **k: _shots.append(text)
    telegram._delete_message = lambda *a, **k: None

    _cfg.VOICE_SHORTCUT_URL = ""
    telegram._handle_voice("700")
    screen = _shots[-1]
    check("the screen exists before anything is set up",
          "Voice control" in screen, screen[:80])

    telegram._handle_voice("700", "new")
    manual = _shots[-1]
    check("with no published link, it explains the three steps",
          "3 steps" in manual and "/api/voice/say" in manual, manual[:120])
    check("and says to start from an EMPTY shortcut", "empty" in manual)
    check("and that Speak Text needs no variable wired into it",
          "fills itself in" in manual,
          "wiring that variable is what kept silently coming undone")

    _cfg.VOICE_SHORTCUT_URL = "https://www.icloud.com/shortcuts/EXAMPLE"
    _shots.clear()
    telegram._handle_voice("700", "new")
    oneTap = _shots[-1]
    check("once published, the same button is a one-tap install",
          "icloud.com/shortcuts/EXAMPLE" in oneTap, oneTap[:120])
    check("and no longer asks anyone to build anything",
          "3 steps" not in oneTap and "Get Contents of URL" not in oneTap)
    check("the key is still handed over separately, once",
          any("copy it now" in m for m in _shots))

    check("both routes explain how to HEAR alerts, not just read them",
          "Announce Notifications" in manual and "Announce Notifications" in oneTap,
          "spoken alerts are an iOS setting, not something the bot can switch on")
finally:
    telegram.send_to, telegram._delete_message = _rs, _rd
    _cfg.VOICE_SHORTCUT_URL = _was_url

check("the menu carries it, so it is reachable without knowing a command",
      '("🎙 Voice control", "nav:voice")' in TG)
check("the screen offers activation as a button",
      '"voice:new"' in TG and "Activate voice control" in TG)
check("and the buttons are routed",
      'if data == "nav:voice"' in TG and 'if data == "voice:new"' in TG
      and 'if data == "voice:off"' in TG)
check("the link is a setting, so publishing it needs no deploy",
      "VOICE_SHORTCUT_URL" in open(
          os.path.join(ROOT, "apex", "config.py"), encoding="utf-8").read())

print("\n⏳  A voice token expires")
# It never did. `voice_token_at` was written every time one was minted and
# read nowhere, so a token that can place and close real trades stayed valid
# forever — and it lives in a URL the client pastes into a phone shortcut,
# which survives phone backups, screenshots and a shared device.
import time as _t                                            # noqa: E402

_VU = "voice-exp-1"
_tok = voice_api.mint(_VU)
_now = int(_t.time())
for label, issued, want in (
        ("a fresh token works", _now, True),
        ("just inside the window still works", _now - 89 * 86400, True),
        ("past the window is refused", _now - 91 * 86400, False),
        ("no issue time is refused, not grandfathered", 0, False),
        ("a corrupt issue time is refused", "not-a-number", False)):
    user_store.update(_VU, {voice_api.ISSUED_FIELD: issued})
    check(label, (voice_api.identify(_tok) == _VU) is want,
          f"identify -> {voice_api.identify(_tok)!r}")

user_store.update(_VU, {voice_api.ISSUED_FIELD: _now})
check("a wrong secret is still refused first",
      voice_api.identify(f"{_VU}.wrong-secret") is None)
check("revoke still works", (voice_api.revoke(_VU) or True)
      and voice_api.identify(_tok) is None,
      "expiry must not have replaced revocation")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — one account, one intent, one execution.")
