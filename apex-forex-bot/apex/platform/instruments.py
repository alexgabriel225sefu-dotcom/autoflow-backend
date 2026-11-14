"""What a broker lists, and which of it this engine can trade today.

A client's broker lists far more than the engine can size a position for:
forex crosses, indices, stocks, crypto. Showing a short list of the ones that
work hides what the broker offers; showing everything as selectable would put
a refusal far from where the choice was made. So the whole list is shown, and
each entry says whether it can be traded now and, when it cannot, why.

`tradeable` is the engine's own allowlist (`forex.is_tradeable`), asked, not
copied: a second list here would eventually disagree with the one that actually
refuses an order. The reasons are the engine's own, from the notes beside that
function: a cross has no USD leg to value a position with, and an index or a
stock needs an exchange calendar the engine does not have.

Pure: no I/O, no broker, nothing that can trade.
"""

import re

from apex import forex

FOREX = "forex"
METAL = "metal"
CROSS = "forex_cross"
INDEX = "index"
CRYPTO = "crypto"
STOCK = "stock"
OTHER = "other"

# The same index names `forex.pip_size` recognises, so a broker's index is
# called one by the same rule that prices it.
INDEX_PREFIXES = ("US30", "US500", "USTEC", "NAS100", "SPX500", "GER40", "DE40",
                  "UK100", "JPN225", "AUS200", "HK50", "FRA40", "EUSTX50",
                  "US2000", "DJ30", "STOXX50")

# Prefixes only, to NAME the class in the reason. No coin is ever offered, and
# a coin missing from this list is shown as "other", not as tradeable.
_CRYPTO = ("BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE", "BNB", "DOT",
           "AVAX", "LINK", "MATIC", "TRX", "XLM", "BCH")

REASONS = {
    CROSS: "A cross has no USD leg, so the engine cannot value a position in "
           "it yet. Forex pairs with a USD leg and metals are supported.",
    INDEX: "Indices need exchange trading calendars the engine does not have "
           "yet.",
    STOCK: "Stocks need exchange trading calendars the engine does not have "
           "yet.",
    CRYPTO: "Crypto is outside what this platform trades.",
    OTHER: "The engine cannot size a position in this instrument yet.",
}


def _norm(name):
    return re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


def classify(name):
    """One broker symbol, as {id, class, tradeable, reason}.

    `reason` is None for something tradeable. The id is the normalised name, the
    same form a rule stores and `forex.is_tradeable` reads.
    """
    sid = _norm(name)
    if not sid:
        return {"id": "", "class": OTHER, "tradeable": False,
                "reason": REASONS[OTHER]}
    if forex.is_tradeable(sid):
        cls = METAL if sid[:3] in forex._METALS else FOREX
        return {"id": sid, "class": cls, "tradeable": True, "reason": None}
    if sid.startswith(INDEX_PREFIXES):
        cls = INDEX
    elif len(sid) == 6 and sid.isalpha() and sid[:3] in forex._CCY \
            and sid[3:] in forex._CCY:
        cls = CROSS
    elif sid.startswith(_CRYPTO):
        cls = CRYPTO
    elif sid.isalpha() and 1 <= len(sid) <= 5:
        cls = STOCK
    else:
        cls = OTHER
    return {"id": sid, "class": cls, "tradeable": False, "reason": REASONS[cls]}


def describe(names):
    """A broker's symbol names as a sorted, de-duplicated list of classified
    entries. Tradeable first within a class, so the usable ones are not buried.
    """
    seen, out = set(), []
    for n in names or []:
        c = classify(n)
        if c["id"] and c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    out.sort(key=lambda c: (not c["tradeable"], c["class"], c["id"]))
    return out
