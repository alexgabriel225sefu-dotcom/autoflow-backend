"""Apex4Traders platform contracts.

The five objects a client's automation passes through, in order:

    RuleDoc         what the client configured        (immutable once active)
    MarketSnapshot  what the market looked like       (no I/O, no clock)
    RuleDecision    what the rule concluded           (pure function of the two)
    ExecutionRequest what we would ask the broker for (refused, never degraded)
    JournalEntry    what actually happened            (answers "why?")

WHY THIS PACKAGE IS SEPARATE FROM apex/

The engine in apex/ decides by running indicator code. This package decides by
EVALUATING A DOCUMENT THE CLIENT WROTE. The difference matters for the product:
the client can read their own RuleDoc, and every decision names the conditions
it evaluated. Keeping it in its own package means the two cannot quietly merge
— a rule cannot start calling an engine, and an engine cannot start reading a
RuleDoc, without that showing up as a new import.

NOTHING HERE TOUCHES THE BROKER. ExecutionRequest is a request, not an order:
it still goes through gates.authorize_order like everything else. There is no
second path to the broker and this package does not create one.
"""
