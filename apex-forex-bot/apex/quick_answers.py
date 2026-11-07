"""The questions clients actually ask, answered without spending AI quota.

Every provider in the chat chain draws on a free-tier quota shared by every
client, and the trading signal draws on the same one. Most of what a client
types is not a conversation — it is "what's my balance", "is it running",
"why isn't it trading". The bot already holds those answers in its dashboard,
and routing them through a language model spends the budget that the trading
decision needs.

This maps such a message onto a handler the bot ALREADY has. It deliberately
returns a key rather than text: a second copy of /status would drift from the
real one, which is exactly how a promised /settings once shipped without
existing and how /ctaccount ended up with three formatters.

Matching is intentionally timid. A short, bare question is a lookup; anything
longer is a real question and belongs to the assistant, which can reason about
it. Answering "why did I lose on EURUSD and what should I change" with a canned
balance line would be worse than spending the quota.
"""
import re

# Above this, treat it as a real question and let the assistant have it. Bare
# lookups are short; "de ce am pierdut azi si ce ar trebui sa schimb" is not.
MAX_WORDS = 8

# (handler key, pattern). First match wins, so order is precedence: the
# specific questions come before the general ones they contain.
_INTENTS = (
    # "why isn't it trading" — before `status`, which its words overlap.
    ("why_no_trade", r"de\s?ce\s+nu\s+(tranzac|intr|deschid|face|cump|vind)"
                     r"|why\s+(is\s?n.?t|isn.?t|no|aren.?t|doesn.?t)\s+"
                     r"(it\s+|the\s+bot\s+|you\s+)?(trad|open|buy|sell|do)"
                     r"|nu\s+(mai\s+)?(tranzac|deschide)"
                     r"|not\s+trading"),
    ("news",    r"\b(stiri|știri|news|calendar|evenimente|events)\b"),
    ("market",  r"\b(piata|piața|market)\b.{0,12}\b(deschis\w*|open|inchis\w*|"
                r"închis\w*|closed)\b|\bis\s+the\s+market\b|se\s+tranzac\w*"),
    # Note the open right-hand side on every stem: a trailing \b after a
    # prefix is a contradiction, and it silently cost this table five of the
    # phrases it was built from — "balance", "strategia", "functioneaza".
    ("summary", r"\b(azi|today|ziua|zi)\b.{0,24}\b(rezultat\w*|result\w*|"
                r"tranzac\w*|trade\w*|c[âa][sș]tig\w*|pierd\w*|profit\w*|"
                r"f[aă]cut|fost|mers)\b"
                r"|\b(rezultat\w*|result\w*|tranzac\w*|trade\w*|c[âa][sș]tig\w*|"
                r"pierd\w*|f[aă]cut|fost|mers)\b.{0,24}\b(azi|today|ziua)\b"),
    ("strategy", r"\bstrateg\w*|\bmetod\w*|\bmethod\w*"),
    ("risk",    r"\brisc\w*|\brisk\w*"),
    ("status",  r"\bbalan(ce|ta|ța|ț[aă])\b|\bsold(ul)?\b|\bcont(ul)?\b"
                r"|\baccount\b|\bprofit\w*|\bpozi[țt]i\w*|\bposition\w*"
                r"|c[âa]t\s+(am|mai\s+am|e|are)"
                r"|how\s+(am\s+i|much\s+(do\s+)?i)\b"
                r"|\bhow.?s?\s+it\s+going\b|cum\s+(merge|st[aă]m|sunt)"
                r"|\b(pornit|oprit|running|active|online|alive)\b"
                r"|ce\s+face(\s+botul)?|what.?s?\s+(it|the\s+bot)\s+doing"),
    ("help",    r"\bajutor\b|\bhelp\b|cum\s+(func\w*|merge\s+asta|se\s+folos\w*)"
                r"|how\s+(does\s+(this|it)|do\s+i\s+(use|start))"
                r"|ce\s+po[țt]i|what\s+can\s+you"),
    ("greeting", r"^\s*(salut|buna|bună|hey|hi|hello|noroc|servus|"
                 r"good\s+(morning|evening|afternoon))\b"),
)

_COMPILED = tuple((key, re.compile(rx, re.IGNORECASE)) for key, rx in _INTENTS)

# A message that says thanks needs an answer, not a dashboard.
_THANKS = re.compile(r"^\s*(mul[țt]umesc|mersi|thanks|thank\s+you|thx|ok|okay|"
                     r"bine|got\s+it|perfect|super)\b[\s!.]*$", re.IGNORECASE)


def resolve(text):
    """A handler key for this message, "thanks", or None to let the AI have it.

    None is the safe answer and the default: a wrong lookup replaces a real
    answer with a canned one, while a needless AI call only costs quota.
    """
    t = (text or "").strip()
    if not t or t.startswith("/"):
        return None
    if _THANKS.match(t):
        return "thanks"
    if len(t.split()) > MAX_WORDS:
        return None
    for key, rx in _COMPILED:
        if rx.search(t):
            return key
    return None
