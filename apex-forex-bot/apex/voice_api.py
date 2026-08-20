"""Talk to the bot from a phone — Apple Shortcuts, or anything that can POST.

Siri cannot be replaced: iOS gives no third party the wake word or the side
button. What it does give is Shortcuts, which Siri *can* launch by name, so
"Hey Siri, Apex" runs a shortcut that dictates a question here and speaks the
answer back. That is the whole design.

The answer comes from `apex.assistant`, which already knows this account and
already carries the tools — nothing is reimplemented here. This module is the
door: who is asking, are they allowed, and does what they asked need confirming
before it touches money.

AUTHENTICATION. The phone holds a credential, so it is not the operator's
DASHBOARD_TOKEN — that one reads every account. It is per-client, revocable,
and stored only as a hash: the record leaking must not leak the token. The
token reads `<user_id>.<secret>`, which makes the lookup a direct load of one
record rather than a scan, and means a token can never resolve to an account
other than the one printed inside it.

CONFIRMATION. The owner asked for full control by voice, including trades, and
that is what this gives — with one step in front of the irreversible part.
Dictation mishears exactly the words that matter here: "close" and "closed",
"0.5" and "5", "buy" and "by". So a financial action is not executed on the
turn that asks for it: it is described back, and executed only when the caller
confirms the stored intent by id. Confirming runs THAT intent — it never feeds
the word "yes" back through the model to be interpreted a second time.

`voice_confirm: false` on the user record turns the step off. It is on by
default because the safe default for a market order is the one that asks.
"""
import hashlib
import hmac
import json
import secrets
import threading
import time

from apex import user_store

# A voice turn waits on the assistant, which calls an AI provider and may run
# tools. This was 45s, which is longer than a phone will hold a request open
# and far longer than anyone will stand there holding a phone: iOS Shortcuts
# reported "The request timed out" before the server had even finished
# waiting. The provider chain leads with the AI gateway, which carries its own
# 20s timeout and sleeps on Render's free plan, so a client with no Gemini key
# spent that whole budget waiting for a cold gateway before falling through to
# an answer it could have given immediately.
#
# So the budget is now what a person will tolerate out loud, and running out
# of it is not an error — see `ask`, which answers from live account state
# instead. Being fast and factual beats being slow and eloquent here.
_REPLY_TIMEOUT_S = 12

# Requests per window, per client. A voice assistant is a handful of turns a
# minute at most; this is high enough never to be felt and low enough that a
# leaked token cannot be used to grind through an AI quota.
_RATE_MAX = 30
_RATE_WINDOW_S = 300

# How long a described-but-unconfirmed trade stays confirmable. Long enough to
# say "yes", short enough that a stale confirmation cannot fire into a market
# that has moved.
_PENDING_TTL_S = 120

TOKEN_FIELD = "voice_token_hash"
ISSUED_FIELD = "voice_token_at"

# Everything that moves money or stops the bot from protecting it. Named here
# rather than inferred from the request text, because the model decides what to
# call and the text is only what the client said.
FINANCIAL_TOOLS = {"execute_trade", "close_position"}

_pending_local = {}
_lock = threading.Lock()


# ─── Tokens ───────────────────────────────────────────────

def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def mint(user_id) -> str:
    """Issue a token, replacing any previous one. Returned in full ONCE.

    Only the hash is stored, so this value cannot be recovered later — a lost
    token is re-minted, never looked up.
    """
    user_id = str(user_id)
    secret = secrets.token_urlsafe(32)
    user_store.update(user_id, {TOKEN_FIELD: _hash(secret),
                                ISSUED_FIELD: int(time.time())})
    return f"{user_id}.{secret}"


def revoke(user_id) -> bool:
    user_id = str(user_id)
    if not (user_store.load(user_id) or {}).get(TOKEN_FIELD):
        return False
    user_store.update(user_id, {TOKEN_FIELD: "", ISSUED_FIELD: 0})
    return True


def has_token(user) -> bool:
    return bool((user or {}).get(TOKEN_FIELD))


def identify(token):
    """The user this token belongs to, or None. Constant-time.

    The id is read from the token and then PROVED against that account's own
    stored hash, so a caller cannot present someone else's id: the secret has
    to match the record it names.
    """
    try:
        raw = str(token or "")
        if "." not in raw:
            return None
        user_id, _, secret = raw.partition(".")
        if not user_id or not secret:
            return None
        stored = (user_store.load(user_id) or {}).get(TOKEN_FIELD) or ""
        if not stored:
            return None
        if not hmac.compare_digest(stored, _hash(secret)):
            return None
        return user_id
    except Exception:
        return None


def _rate_ok(user_id) -> bool:
    """False only when the limit is provably exceeded.

    `incr` answers None where there is no shared backend, and an unanswerable
    question is not a breach — the same contract the rest of the codebase
    holds. Without Redis this degrades to no limit rather than to no service.
    """
    n = user_store.incr(f"voicerate:{user_id}", ttl_s=_RATE_WINDOW_S)
    return n is None or n <= _RATE_MAX


# ─── Pending financial intents ────────────────────────────

def confirm_required(user) -> bool:
    return bool((user or {}).get("voice_confirm", True))


# Words that mean "go ahead" and "don't", in both languages this bot is used
# in. Only ever consulted when something is actually pending — a bare "yes"
# with nothing waiting is just a word, and goes to the assistant like any
# other.
_YES = {"yes", "yeah", "yep", "yup", "ok", "okay", "confirm", "confirmed",
        "do it", "go ahead", "sure", "da", "sigur", "hai", "confirma",
        "confirmă", "bine"}
_NO = {"no", "nope", "cancel", "stop", "don't", "dont", "nu", "anuleaza",
       "anulează", "lasa", "lasă"}


def _pending_key(user_id, cid):
    return f"voicepending:{user_id}:{cid}"


def _latest_key(user_id):
    return f"voicelatest:{user_id}"


def _remember_latest(user_id, cid):
    """The id a spoken "yes" refers to.

    A phone cannot hold a confirmation id and hand it back — that needs an
    If-branch in the shortcut, and the point of this path is a shortcut with
    three actions and no branches. So the server remembers which trade it just
    described, and the NEXT thing said resolves it. That is also how the
    exchange sounds out loud: "Open a BUY on GBPUSD?" — "yes".
    """
    user_store.set_blob(_latest_key(user_id), cid, ttl_s=_PENDING_TTL_S)
    with _lock:
        _pending_local[_latest_key(user_id)] = (time.time() + _PENDING_TTL_S, cid)


def _take_latest(user_id):
    key = _latest_key(user_id)
    cid = None
    try:
        cid = user_store.get_blob(key)
    except Exception:
        cid = None
    with _lock:
        exp, local = _pending_local.pop(key, (0, None))
    if not cid and local and exp > time.time():
        cid = local
    if not cid:
        return None
    try:
        user_store.set_blob(key, "", ttl_s=1)
    except Exception:
        pass
    return cid


def stash(user_id, intent) -> str:
    """Record a described-but-unexecuted action and return its id."""
    cid = secrets.token_urlsafe(9)
    blob = json.dumps(intent)
    user_store.set_blob(_pending_key(user_id, cid), blob, ttl_s=_PENDING_TTL_S)
    with _lock:
        _pending_local[_pending_key(user_id, cid)] = (time.time() + _PENDING_TTL_S, blob)
    return cid


def take(user_id, cid):
    """The stored intent, consumed. None when unknown or expired.

    Consumed on read: "yes" said twice must not open two positions.
    """
    key = _pending_key(user_id, cid)
    raw = None
    try:
        raw = user_store.get_blob(key)
    except Exception:
        raw = None
    with _lock:
        exp, local = _pending_local.pop(key, (0, None))
    if raw is None and local is not None and exp > time.time():
        raw = local
    if raw is None:
        return None
    try:
        user_store.set_blob(key, "", ttl_s=1)
    except Exception:
        pass
    try:
        return json.loads(raw)
    except Exception:
        return None


def describe(intent) -> str:
    """What the client will hear before anything happens. Plain, no markup."""
    tool = (intent or {}).get("tool")
    inp = (intent or {}).get("input") or {}
    if tool == "execute_trade":
        side = str(inp.get("side", "BUY")).upper()
        sym = str(inp.get("symbol", "")).replace("_", "")
        return f"Open a {side} on {sym}?"
    if tool == "close_position":
        return "Close your open position?"
    return "Go ahead?"


# ─── Turns ────────────────────────────────────────────────

_TAGS = ("<b>", "</b>", "<i>", "</i>", "<code>", "</code>", "<pre>", "</pre>")


def speakable(text) -> str:
    """Telegram HTML reads badly out loud. Strip it back to words.

    The assistant writes for a chat bubble — bold, code spans, emoji. A phone
    reads the markup aloud, so "<b>Balance:</b>" becomes "less than b greater
    than Balance". This is the same answer, said rather than shown.
    """
    s = str(text or "")
    for t in _TAGS:
        s = s.replace(t, "")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    out = []
    for ch in s:
        # Emoji and box-drawing carry no meaning when spoken.
        out.append(" " if ord(ch) > 0x2100 else ch)
    s = "".join(out)
    return " ".join(s.split())


def _ask_assistant(user_id, text, guard):
    """One synchronous turn. `assistant.chat` is fire-and-forget by design."""
    from apex import assistant
    done = threading.Event()
    box = {}

    def _sink(reply):
        box["reply"] = reply
        done.set()

    # prefer_tools: this channel exists to act. See assistant.chat.
    assistant.chat(user_id, text, _sink, None, guard,
                   prefer_tools=True, voice=True)
    if not done.wait(_REPLY_TIMEOUT_S):
        return None
    return box.get("reply")


def _fallback(user_id):
    """Live account state, with no AI in the path. Always available.

    This is what a slow provider degrades TO. `_local_status` reads the same
    dashboard the trading loop writes, so it is current — it just cannot
    reason. For "what's my balance", which is most of what anyone asks a phone,
    it is the whole answer anyway.
    """
    try:
        from apex import assistant
        return speakable(assistant._local_status(user_id, voice=True))
    except Exception:
        return None


def ask(token, text):
    """A spoken question. Returns what to say back, and what is pending.

    Never raises: a phone gets a sentence it can read out, whatever went wrong
    underneath. The one thing it will not do is invent an answer — an assistant
    that could not reach its provider says so.
    """
    t0 = time.time()
    user_id = identify(token)
    if not user_id:
        # Logged because "nothing happens on my phone" is otherwise
        # undiagnosable from this side: without a line per turn there is no way
        # to tell a request that never arrived from one that arrived and was
        # refused. The token is never printed, and neither is the question —
        # only whether it resolved, and what came of it.
        print("[Voice] turn REFUSED — token did not resolve to an account")
        return {"ok": False, "status": 401,
                "reply": "That link is not valid any more. Send slash voice in "
                         "Telegram to set it up again."}
    print(f"[Voice] turn from {user_id} — {len(str(text or ''))} chars")
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "status": 400, "reply": "I did not catch that."}
    if len(text) > 1000:
        text = text[:1000]
    if not _rate_ok(user_id):
        return {"ok": False, "status": 429,
                "reply": "Too many requests just now. Try again in a minute."}

    user = user_store.load(user_id) or {}

    # A spoken answer to a question the bot just asked. Checked before the
    # assistant sees it, because "yes" carries no meaning on its own — it means
    # whatever was described a moment ago, and re-interpreting the word through
    # a model is exactly how a confirmation stops being one.
    spoken = text.strip().strip(".!?,").lower()
    if spoken in _YES or spoken in _NO:
        cid = _take_latest(user_id)
        if cid:
            return confirm(token, cid, agreed=spoken in _YES)

    held = {}

    def _guard(name, inp):
        if name not in FINANCIAL_TOOLS:
            return None
        intent = {"tool": name, "input": inp}
        held["intent"] = intent
        # What the model is told. It must ASK, not report success — a model
        # that thinks the trade is placed will say so, and the client will
        # believe the trade is placed.
        return json.dumps({
            "status": "awaiting_confirmation",
            "executed": False,
            "instruction": "Do NOT say this is done. Ask the user to confirm, "
                           "in one short sentence, and stop.",
            "question": describe(intent),
        })

    guard = _guard if confirm_required(user) else None
    try:
        reply = _ask_assistant(user_id, text, guard)
    except Exception as e:
        print(f"[Voice] turn failed for {user_id}: {e}")
        reply = None
    if not reply:
        # Do not hand a phone an apology when the facts are one read away.
        local = _fallback(user_id)
        print(f"[Voice] no assistant reply for {user_id} after "
              f"{time.time() - t0:.1f}s — "
              f"{'answered from account state' if local else 'nothing to fall back on'}")
        if local:
            return {"ok": True, "status": 200,
                    "reply": local + " I could not reach the assistant for "
                                     "anything more than that."}
        return {"ok": False, "status": 504,
                "reply": "I could not reach the assistant just now. "
                         "Your bot is unaffected."}

    out = {"ok": True, "status": 200, "reply": speakable(reply)}
    print(f"[Voice] answered {user_id} in {time.time() - t0:.1f}s "
          f"({len(out['reply'])} chars)")
    if held.get("intent"):
        cid = stash(user_id, held["intent"])
        _remember_latest(user_id, cid)
        out["needsConfirm"] = True
        out["confirmId"] = cid
        out["confirmQuestion"] = describe(held["intent"])
    return out


def confirm(token, confirm_id, agreed=True):
    """Run a previously described action — the stored one, by id.

    The word the client said is NOT re-interpreted here. The shortcut decides
    yes or no; this executes the intent that was already described back to
    them, so nothing can be understood differently the second time.
    """
    user_id = identify(token)
    if not user_id:
        return {"ok": False, "status": 401, "reply": "That link is not valid any more."}
    if not _rate_ok(user_id):
        return {"ok": False, "status": 429, "reply": "Too many requests just now."}
    intent = take(user_id, str(confirm_id or ""))
    if not intent:
        return {"ok": False, "status": 410,
                "reply": "That has expired. Ask me again."}
    if not agreed:
        return {"ok": True, "status": 200, "reply": "Cancelled. Nothing was placed."}

    from apex import assistant
    try:
        # Straight to the same tool runner Telegram uses, with no guard, so
        # there is exactly one execution path and no second interpretation.
        raw = assistant._run_tool(intent["tool"], intent.get("input") or {},
                                  user_id, None)
        res = json.loads(raw)
    except Exception as e:
        print(f"[Voice] confirm failed for {user_id}: {e}")
        return {"ok": False, "status": 502,
                "reply": "That did not go through. Check Telegram before trying again."}

    if res.get("ok") is False or res.get("error"):
        why = str(res.get("error") or "the broker refused it")
        return {"ok": False, "status": 200,
                "reply": f"That did not go through: {speakable(why)}"}
    if intent["tool"] == "execute_trade":
        side = str((intent.get("input") or {}).get("side", "")).upper()
        sym = str((intent.get("input") or {}).get("symbol", "")).replace("_", "")
        return {"ok": True, "status": 200, "reply": f"Done. {side} {sym} is open."}
    return {"ok": True, "status": 200, "reply": "Done. Your position is closed."}
