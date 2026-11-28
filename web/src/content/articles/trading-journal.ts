import type { Article } from "./types";

export const TRADING_JOURNAL: Article = {
  slug: "trading-journal-what-to-record",
  title: "What a trading journal should record and how to use it",
  description:
    "A trading journal turns what happened into something you can review. What to record for each trade, what an automation journal adds, and how to review it.",
  summary:
    "A trading journal is a dated record of what you did, what the market looked like and why. For a rule that runs automatically it should show when the rule started, paused and stopped, what it found, and which orders and closed trades followed. Reviewing it on a schedule, rather than after each trade, shows whether the rule behaves the way it was written.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["trading journal", "what to record in a trading journal", "review trades", "automated trading log", "trade review checklist"],
  sections: [
    {
      heading: "Why keep a journal",
      paragraphs: [
        "Memory is selective. A journal replaces how you remember a period with what was written at the time, which is the only version you can check.",
        "For a rule, the journal answers a concrete question: did the system do what you meant it to do?",
      ],
    },
    {
      heading: "What to record for each trade",
      paragraphs: ["A useful entry is short and consistent. These fields cover most needs:"],
      table: {
        caption: "Fields for a trade journal entry",
        head: ["Field", "Why it matters"],
        rows: [
          ["Date and time", "Lets you link a trade to the session and the market conditions"],
          ["Instrument, side and size", "The basic facts of the position"],
          ["Entry, stop and target", "Shows whether the trade followed its limits"],
          ["Rule and version", "Tells you which rule produced it, so changes can be compared"],
          ["Reason", "The condition or idea behind the trade, in a sentence"],
          ["Result", "What happened, without commentary"],
          ["Notes", "Anything unusual: news, a missed fill, a manual change"],
        ],
      },
    },
    {
      heading: "What an automation journal adds",
      paragraphs: [
        "When a rule runs on its own you also need a record of the system's state: when automation started, paused and stopped, what it found, and any problem it hit. Without that you cannot tell a quiet market from a rule that was not running.",
        "In Apex4Traders the journal records when automation starts, pauses and stops, and any signal found at the Signals Only level. Orders and closed trades are listed in Positions and Closed trades. The journal does not yet list each check where the rule decided to wait.",
      ],
    },
    {
      heading: "A weekly review checklist",
      paragraphs: ["Review on a schedule, not trade by trade, so one outcome does not steer your view:"],
      steps: [
        "Confirm the rule ran when it should have: starts, pauses and stops match what you intended.",
        "Compare each trade's entry, stop and target with the rule. Note any that do not match.",
        "Check that the limits held: risk per trade, open positions and any daily stop.",
        "Look for patterns in time of day or session rather than in single results.",
        "Write down one change to consider, with the reason, and leave it until the next review.",
      ],
    },
    {
      heading: "Mistakes to avoid",
      paragraphs: ["The same few habits spoil most journals:"],
      bullets: [
        "Recording only the trades you are pleased with.",
        "Changing the rule after each loss instead of after a review.",
        "Drawing conclusions from a very small number of trades.",
        "Writing explanations afterwards that the rule did not actually contain.",
      ],
    },
  ],
  faq: [
    {
      question: "Does the Apex4Traders journal list each check?",
      answer:
        "Not yet. It records when automation starts, pauses and stops and any signal found at the Signals Only level. Orders and closed trades are listed in Positions and Closed trades. It does not yet list each check where the rule decided to wait.",
    },
    {
      question: "How often should I review my journal?",
      answer:
        "A fixed, regular review, for example weekly, works better than reviewing after each trade, because it stops a single result from steering your view.",
    },
    {
      question: "Is a spreadsheet enough for a journal?",
      answer:
        "For manual trading a spreadsheet is enough if you fill the same fields every time. For a rule that runs automatically you also need a record of when it ran and stopped.",
    },
  ],
  related: ["demo-vs-live-account", "risk-per-trade-and-stop-distance", "what-is-rules-based-trading"],
};
