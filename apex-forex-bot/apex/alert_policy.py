"""Which of the 22 alert types a client actually receives.

The bot grew 22 notification types and sent all of them to everybody. Most
are diagnostics written for whoever is debugging the bot, not for the person
whose money is in it, and the volume is the problem on its own: a client who
gets nine near-identical "stop moved" messages from ONE trade stops reading
any of them, including the two that mattered.

Three tiers:

  ESSENTIAL   what happened to your money, and whether the bot is running
  USEFUL      something changed that you might want to act on
  DIAGNOSTIC  how the bot is thinking — interesting to an operator, noise to
              a beginner

A client gets ESSENTIAL + USEFUL. /verbose adds DIAGNOSTIC.

STOP_MOVED is deliberately not merely demoted. A trailing stop moves many
times per trade, but exactly ONE of those moves is worth a sentence: the one
that takes the stop past the entry price, after which the trade can no longer
lose. That one is ESSENTIAL; the rest are silent even in verbose, because
repeating it is what taught clients to ignore the channel.
"""

ESSENTIAL = {
    "BUY", "SELL",                 # a position was opened
    "CLOSE", "BROKER_CLOSE", "BROKER_CLOSE_MULTI",
    "STOP",                        # the bot stopped itself
    "WEEKEND_CLOSE", "WEEKEND_REOPEN",
    # The bot tried to exit and could not: the client is still in the
    # trade and needs to know, whatever their alert preference.
    "EXIT_FAILED",
    "UNPROTECTED",           # a live position with no stop at the broker
    "DAILY_SUMMARY",
    "STOP_BREAKEVEN",              # "this trade can no longer lose"
}

USEFUL = {
    "NEWS_WARN",                   # standing aside for a release
    "FLASH_WARN",                  # violent candle
    "BROKER_HEALTH",               # the broker feed is degraded
    "SUGGEST",                     # approval-required proposal awaiting a tap
    # Signals-Only: the bot found a setup and placed nothing. For a client on
    # that level this message IS the product, so it must never be classed as
    # a diagnostic — muting diagnostics would mute the whole service.
    "SIGNAL",
}

DIAGNOSTIC = {
    "STOP_MOVED",                  # every trail after the breakeven one
    "SKIP_WARN", "MARKET_PULSE", "HEARTBEAT",
    "SENTINEL_BLOCK", "SENTINEL_FLIP",
    "SHADOW_OPEN", "SHADOW_MOVE", "SHADOW_RESULT",
    "AI_ERROR", "DATA_ERROR", "DUPLICATE_BLOCKED",
}


def verbose(user) -> bool:
    return bool((user or {}).get("verbose_alerts"))


def allowed(action, user) -> bool:
    """True when this client should see this alert.

    Unknown actions default to SENT. A new alert type is far more likely to
    be something worth seeing than something worth hiding, and silently
    swallowing an unclassified message is the failure mode that is hard to
    notice.
    """
    a = str(action or "").upper()
    if a in DIAGNOSTIC:
        return verbose(user)
    return True


def tier(action) -> str:
    a = str(action or "").upper()
    if a in ESSENTIAL:
        return "essential"
    if a in USEFUL:
        return "useful"
    if a in DIAGNOSTIC:
        return "diagnostic"
    return "unclassified"
