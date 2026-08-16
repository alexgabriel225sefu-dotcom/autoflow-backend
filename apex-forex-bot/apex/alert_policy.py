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
    # Reports what the weekend flatten actually did — including which
    # positions it could NOT close, which is a different fact from "the
    # market shut" and is why this stays essential while WEEKEND_REOPEN
    # (below) does not.
    "WEEKEND_CLOSE",
    # The market session itself. MARKET_OPEN carries the result of the
    # reconnect, so it is the message that says "your account answered and the
    # bot can trade today" — or that it could not, which is the whole reason
    # the check exists. Neither is optional information.
    "MARKET_OPEN", "MARKET_CLOSE",
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
    # Superseded by MARKET_OPEN, which fires at the same minute. Both were
    # essential and the client got two messages a week apart by seconds. The
    # one that survives is the one that PROVES the account answered; this one
    # asked the client to send /ctrader "as a precaution" — manual work the
    # reconnect now does and verifies on their behalf.
    "WEEKEND_REOPEN",
    "SKIP_WARN", "MARKET_PULSE", "HEARTBEAT",
    "SENTINEL_BLOCK", "SENTINEL_FLIP",
    "SHADOW_OPEN", "SHADOW_MOVE", "SHADOW_RESULT",
    "AI_ERROR", "DATA_ERROR", "DUPLICATE_BLOCKED",
}

# Infrastructure events. These go to the operator's event log and NEVER to a
# client, not even with /verbose — unlike DIAGNOSTIC, which is merely quiet.
#
# A client received `⚡ OWNERSHIP_LOST — EUR_USD` three times in twenty minutes.
# Nothing had happened to their money: every deploy hands the account from the
# retiring container to the new one, the retiring one notices within a renewal
# interval, and standing down is exactly what it should do. The message was the
# handover working. But it reads like a failure, names their instrument, and
# offers nothing to act on — and there is no version of it a client could act
# on, because the correct response is "the other container already has it".
#
# That is the distinction this tier draws: DIAGNOSTIC is information a curious
# client may opt into, OPERATOR is information that is not about them at all.
OPERATOR = {
    "OWNERSHIP_LOST",              # a deploy handed this account to a new container
    "OWNERSHIP_BLOCKED",           # an order deferred to the owning container
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
    if a in OPERATOR:
        return False               # not about this client, at any verbosity
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
    if a in OPERATOR:
        return "operator"
    return "unclassified"
