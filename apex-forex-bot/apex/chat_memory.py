"""Per-client conversation memory and chat rate limiting.

Spec §8 (memory) and §10 (24/7 performance) of the Dual-AI blueprint.

Two things stand between "the assistant replies" and "clients can chat with
it all day":

MEMORY. It lived in a process-local dict. Every deploy wiped every client's
conversation mid-sentence, and during a Render deploy two instances serve the
same users at once, each with its own half of the history — so the assistant
would contradict itself depending on which container answered. This is the
same defect class as the refusal-alert throttle: state that has to outlive a
restart cannot live in memory. Keyed per user_id, and never shared between
users (spec §8: "Nu amesteca niciodată istoricul unui client cu alt client").

RATE LIMITING. "Unlimited chat" is a promise about the client's experience,
not about the infrastructure — spec §11 says as much. Without a limit one
client (or one runaway loop) drains the shared free-tier quota, and the first
casualty is the trading signal, which draws on the same providers. The limit
exists to keep the bot trading, so it is deliberately generous for a human
typing and immediate for a script.

Credentials are never written here (spec §8), only message text.
"""
import json
import os
import threading
import time

from apex import user_store

# Spec §8 keeps a bounded history; 20 entries is 10 exchanges.
MAX_HISTORY = int(os.getenv("AI_CHAT_HISTORY") or 20)
# A conversation nobody has touched in a week is not context, it is clutter.
HISTORY_TTL_S = int(os.getenv("AI_CHAT_HISTORY_TTL") or 7 * 24 * 3600)

# Generous for a person, instant for a loop. A human sends a handful of
# messages a minute at most; anything past this is not someone typing.
PER_MIN = int(os.getenv("AI_CHAT_PER_MIN") or 12)
PER_HOUR = int(os.getenv("AI_CHAT_PER_HOUR") or 150)

_KEY = "apex:ai:conversation:{}"

# Fallback for local dev and for any moment Redis is unreachable. Bounded the
# same way so it cannot grow without limit.
_local: dict = {}
_local_hits: dict = {}
_lock = threading.Lock()


def _trim(history):
    return [h for h in history if isinstance(h, dict)][-MAX_HISTORY:]


def load(user_id):
    """This user's bounded history, oldest first. Never another user's."""
    user_id = str(user_id)
    raw = None
    try:
        raw = user_store.get_blob(_KEY.format(user_id))
    except Exception as e:
        print(f"[ChatMemory] load failed for {user_id}: {e}")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return _trim(data)
        except Exception:
            pass          # corrupt blob: start clean rather than crash a reply
    with _lock:
        return _trim(list(_local.get(user_id, [])))


def save_exchange(user_id, user_msg, assistant_msg):
    """Append one turn. Best-effort: losing memory must never lose the reply."""
    user_id = str(user_id)
    history = load(user_id)
    history.append({"role": "user", "content": str(user_msg)})
    history.append({"role": "assistant", "content": str(assistant_msg)})
    history = _trim(history)
    with _lock:
        _local[user_id] = history
    try:
        user_store.set_blob(_KEY.format(user_id), json.dumps(history),
                            ttl_s=HISTORY_TTL_S)
    except Exception as e:
        print(f"[ChatMemory] save failed for {user_id}: {e}")
    return history


def clear(user_id):
    user_id = str(user_id)
    with _lock:
        _local.pop(user_id, None)
    try:
        user_store.set_blob(_KEY.format(user_id), "[]", ttl_s=HISTORY_TTL_S)
    except Exception as e:
        print(f"[ChatMemory] clear failed for {user_id}: {e}")


def _window_count(user_id, window, limit):
    """Count this message against a fixed window. True when it is over limit.

    Falls back to an in-process counter when there is no shared store. On a
    backend ERROR it allows: a rate limiter that fails closed would silence
    the assistant for everyone the moment Redis hiccups, which is a worse
    outcome than briefly not counting.
    """
    bucket = int(time.time() // window)
    key = f"apex:ai:rate:{user_id}:{window}:{bucket}"
    n = None
    try:
        n = user_store.incr(key, ttl_s=window * 2)
    except Exception as e:
        print(f"[ChatMemory] rate check failed: {e}")
    if n is None:
        with _lock:
            slot = _local_hits.get(key, 0) + 1
            _local_hits[key] = slot
            # Drop buckets that can no longer be current.
            for k in [k for k in _local_hits if not k.endswith(f":{bucket}")]:
                _local_hits.pop(k, None)
            n = slot
    return n > limit


def allow(user_id):
    """(ok, message). `message` is client-facing text when ok is False."""
    user_id = str(user_id)
    if _window_count(user_id, 60, PER_MIN):
        return False, ("⏳ Prea multe mesaje pe minut. Așteaptă puțin — "
                       "limita există ca botul să aibă mereu resurse "
                       "pentru tranzacționare.")
    if _window_count(user_id, 3600, PER_HOUR):
        return False, ("⏳ Ai atins limita orară de mesaje. Se resetează în "
                       "cel mult o oră. Tranzacționarea nu e afectată.")
    return True, ""
