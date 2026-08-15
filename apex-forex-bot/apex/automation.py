"""How much the bot is allowed to do on its own — one definition, two readers.

The bot shipped with two automation levels and named them after itself:
"Copilot" and "Autopilot". Neither says what happens to your money, they differ
by one letter in the middle of the word, and `/copilot off` — which reads like
turning something off — is the setting that lets the bot trade unattended. The
names are now what they do:

    signals    the bot posts the setup and does NOT execute
    approval   the bot proposes and waits for a tap  (the old copilot)
    full       the bot executes on its own            (the old autopilot)

`signals` is new. `approval` and `full` are the existing two behaviours under
honest names, so nothing about how a running account trades changes.

The mode has to be read in two places that cannot import each other: the
trading loop, which decides whether to execute, and Telegram, which decides
what to show. A second copy of this resolution would drift, and the direction
it would drift in is "the UI says Approval Required while the loop executes
unattended" — so it lives here, alone.

BACKWARD COMPATIBILITY. Every existing client has `copilot: true|false` and no
`automation` key at all; the MCP control plane and `/copilot` still write the
boolean. So the boolean stays authoritative whenever it CONTRADICTS the stored
mode, and the stored mode is what distinguishes `signals` from `full` (both of
which are copilot=False). An account is never left in a state where the two
disagree and the more permissive one wins.
"""

MODES = ("signals", "approval", "full")

LABEL = {
    "signals":  "📣 Signals Only",
    "approval": "✋ Approval Required",
    "full":     "🚀 Full Automation",
}

BLURB = {
    "signals":  "I tell you about every setup I find and place nothing. "
                "You trade it yourself, or not at all.",
    "approval": "I find the setup and ask. Nothing opens until you tap Approve.",
    "full":     "I open and manage trades on my own, inside the limits you set.",
}

# What each level does when a setup passes every check. Shown before a client
# hands over execution, because that is the moment the difference matters.
EXECUTES = {"signals": False, "approval": False, "full": True}


def mode(user) -> str:
    """This client's automation level. Never raises, never returns None.

    Unknown/absent settings resolve to the behaviour the account already had,
    which for every pre-existing record is the copilot boolean.
    """
    u = user or {}
    stored = str(u.get("automation") or "").strip().lower()
    legacy = bool(u.get("copilot"))
    if stored in MODES:
        # The boolean was written by something that only knows two levels. If
        # it disagrees with the stored mode, honour it — it is the more recent
        # instruction, and ignoring it would silently drop a client's
        # `/copilot on`.
        if legacy != (stored == "approval"):
            return "approval" if legacy else "full"
        return stored
    return "approval" if legacy else "full"


def patch(m) -> dict:
    """The user-record fields that set `m`, both keys kept in agreement.

    Writing only `automation` would leave a stale `copilot` behind for the
    control plane and the loop's older reads to trip over.
    """
    m = str(m or "").strip().lower()
    if m not in MODES:
        raise ValueError(f"unknown automation mode: {m!r}")
    return {"automation": m, "copilot": (m == "approval")}


def label(m) -> str:
    return LABEL.get(m, LABEL["full"])


def blurb(m) -> str:
    return BLURB.get(m, BLURB["full"])


def executes(user) -> bool:
    """True when a passing setup turns into a real order without a human."""
    return EXECUTES.get(mode(user), True)
