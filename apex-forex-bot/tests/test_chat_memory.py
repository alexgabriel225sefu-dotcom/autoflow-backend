"""Client chat memory survives restarts, and one client cannot starve the rest.

Spec §8 (memory) and §10/§11 (24/7 performance, anti-abuse).

Memory used to live in a process-local dict. Two consequences, both live:
every deploy wiped every client's conversation mid-thread, and DURING a
deploy two Render instances serve the same users at once, each holding half
the history — so the assistant contradicted itself depending on which
container answered. Same defect as the refusal-alert throttle: state that has
to outlive a restart cannot live in memory.

Rate limiting did not exist. Every provider draws on a shared free-tier
quota, and the TRADING signal draws on the same one, so an unbounded chat
loop does not merely spam the assistant — it can starve the bot of its
ability to decide. That is why the limit exists, and why it fails OPEN: a
limiter that fails closed would mute the assistant for everyone the moment
Redis hiccups.

Run: python tests/test_chat_memory.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apex import chat_memory, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# ── a fake shared store, so "restart" means "drop the process state" ──
class FakeRedis:
    def __init__(self):
        self.blobs = {}
        self.counters = {}
        self.down = False

    def get_blob(self, key):
        if self.down:
            raise RuntimeError("redis down")
        return self.blobs.get(key)

    def set_blob(self, key, value, ttl_s=None):
        if self.down:
            raise RuntimeError("redis down")
        self.blobs[key] = value

    def incr(self, key, ttl_s=60):
        if self.down:
            return None
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


fake = FakeRedis()
user_store.get_blob = fake.get_blob
user_store.set_blob = fake.set_blob
user_store.incr = fake.incr


def restart():
    """Wipe process-local state, exactly as a deploy does."""
    chat_memory._local.clear()
    chat_memory._local_hits.clear()


print("\n── memory survives a deploy ──")
chat_memory.save_exchange("111", "cum merge botul?", "Merge bine.")
chat_memory.save_exchange("111", "si pozitiile?", "O poziție pe USDCHF.")
restart()
h = chat_memory.load("111")
check("history is still there after a restart", len(h) == 4, str(len(h)))
check("in order, oldest first", h[0]["content"] == "cum merge botul?", str(h[0]))
check("and the last reply is intact",
      h[-1]["content"] == "O poziție pe USDCHF.", str(h[-1]))
check("roles alternate user/assistant",
      [x["role"] for x in h] == ["user", "assistant", "user", "assistant"],
      str([x["role"] for x in h]))

print("\n── one client's history is never another's ──")
chat_memory.save_exchange("222", "secret plan", "ok")
check("user 111 does not see user 222",
      all("secret" not in x["content"] for x in chat_memory.load("111")))
check("user 222 does not see user 111",
      all("botul" not in x["content"] for x in chat_memory.load("222")))
check("their keys are distinct",
      "apex:ai:conversation:111" in fake.blobs
      and "apex:ai:conversation:222" in fake.blobs, str(list(fake.blobs)))

print("\n── history stays bounded ──")
for i in range(40):
    chat_memory.save_exchange("333", f"q{i}", f"a{i}")
h = chat_memory.load("333")
check(f"never exceeds {chat_memory.MAX_HISTORY}",
      len(h) <= chat_memory.MAX_HISTORY, str(len(h)))
check("keeps the NEWEST turns, not the oldest",
      h[-1]["content"] == "a39", str(h[-1]))

print("\n── clearing is real, not just local ──")
chat_memory.clear("111")
restart()
check("cleared history stays cleared across a restart",
      chat_memory.load("111") == [], str(chat_memory.load("111")))

print("\n── a corrupt blob does not break a reply ──")
fake.blobs["apex:ai:conversation:444"] = "{not json"
check("unparseable history reads as empty", chat_memory.load("444") == [])
fake.blobs["apex:ai:conversation:445"] = '{"role": "user"}'   # dict, not list
check("wrong shape reads as empty", chat_memory.load("445") == [])

print("\n── rate limit: generous for a human, immediate for a loop ──")
fake.counters.clear()
restart()
allowed = sum(1 for _ in range(chat_memory.PER_MIN) if chat_memory.allow("555")[0])
check(f"the first {chat_memory.PER_MIN} messages all pass",
      allowed == chat_memory.PER_MIN, str(allowed))
ok, why = chat_memory.allow("555")
check("the next one is refused", ok is False)
check("and the client is told why, in their language",
      "limita" in why.lower() or "prea multe" in why.lower(), why)
check("the refusal reassures them trading is unaffected",
      "tranzac" in why.lower(), why)

print("\n── one client's flood does not silence another ──")
ok, _ = chat_memory.allow("556")
check("a different user is unaffected", ok is True)

print("\n── the limiter fails OPEN, never closed ──")
fake.down = True
restart()
ok, _ = chat_memory.allow("557")
check("a dead Redis still lets a client talk", ok is True)
fake.down = False

print("\n── a dead store never loses the reply ──")
fake.down = True
try:
    chat_memory.save_exchange("558", "hello", "hi")
    crashed = False
except Exception:
    crashed = True
check("saving through a dead store does not raise", crashed is False)
fake.down = False

print("\n── credentials are never written to memory ──")
chat_memory.save_exchange("559", "my key is gsk_abc123", "I won't store that")
blob = fake.blobs["apex:ai:conversation:559"]
check("only message text is stored, no extra fields",
      set(chat_memory.load("559")[0]) == {"role", "content"},
      str(chat_memory.load("559")[0]))
check("the store holds exactly what was said, nothing appended",
      blob.count("role") == 2, blob[:120])

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL CHAT-MEMORY CHECKS PASSED.")
