import type { Article } from "./types";

export const RISK_GUARD: Article = {
  slug: "risk-guard-explained",
  title: "Risk guard explained: limits that stop a rule from acting",
  description:
    "The risk guard checks account state before a rule acts and blocks when a limit is reached or when the data cannot be read. What it checks and why it fails closed.",
  summary:
    "The risk guard is a set of checks on account state that run before a rule is allowed to act. It blocks on consecutive losses, the number of trades today and observed slippage. It also blocks when it cannot read the data, because an unknown state is treated as unsafe. A block means the rule waits; it does not change the rule.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["risk guard", "trading risk limits", "daily trade limit", "fail closed trading", "automated trading safeguards"],
  sections: [
    {
      heading: "What the risk guard is",
      paragraphs: [
        "The risk guard looks at the account's measured state and decides whether a rule may act right now. It is separate from the rule: the rule says what it wants, and the guard says whether the account is in a state where that is allowed.",
      ],
    },
    {
      heading: "What it checks",
      paragraphs: ["Three checks block a rule from acting:"],
      table: {
        caption: "Risk guard checks and what a block means",
        head: ["Check", "It blocks when", "What it means for you"],
        rows: [
          ["Consecutive losses", "The count is at its limit, or cannot be read", "The rule pauses until the state allows it"],
          ["Trade count today", "The daily count is at its limit, or cannot be read", "No more orders today"],
          ["Slippage", "Observed slippage is above the configured limit", "The rule waits and shows the reason"],
        ],
      },
    },
    {
      heading: "Why it fails closed",
      paragraphs: [
        "If the guard cannot read the data it needs, it does not assume everything is fine. It reports the state as unknown and blocks. That can feel strict, but acting on a guess is worse than waiting.",
        "An account with no closed trades is a different case: a successful read that finds none is a real zero, not an unknown, and the guard treats it that way.",
      ],
    },
    {
      heading: "Reading a block",
      paragraphs: ["When the guard blocks, the reason is shown. Use it like this:"],
      steps: [
        "Read which check blocked and the reason given.",
        "If it names a limit, decide whether that limit is where you want it.",
        "If it says the data could not be read, retry later and check the account connection.",
        "Do not widen a limit only to make a rule act.",
      ],
    },
  ],
  faq: [
    {
      question: "Does a risk guard block mean my rule is wrong?",
      answer: "No. The rule and the guard are separate. A block means the account state does not allow an order right now.",
    },
    {
      question: "Why does the guard block when it cannot read my data?",
      answer: "An unknown state is treated as unsafe, so the guard waits rather than guessing.",
    },
    {
      question: "Does the risk guard guarantee that I will not lose money?",
      answer: "No. It limits when a rule can act. Leveraged trading carries a high risk of loss, and this is not financial advice.",
    },
  ],
  related: ["risk-per-trade-and-stop-distance", "why-did-my-rule-not-open-a-trade", "demo-vs-live-account"],
};
