import type { Article } from "./types";

export const PREVIEW_VS_RUN: Article = {
  slug: "preview-vs-run-what-each-does",
  title: "Preview vs run: what each does in Apex4Traders",
  description:
    "A preview shows what a rule would decide right now and never places an order. A run evaluates the rule on a demo account on a schedule. How they differ and when to use each.",
  summary:
    "A preview shows what your rule would decide on current data and never places an order. A run starts the automation on a connected demo account, which then evaluates the rule on its timeframe and can place demo orders within your limits. Use preview to check the logic and the explanation, and start a run only when you are happy with both.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 4,
  keywords: ["preview a trading rule", "run a trading rule on demo", "dry run trading", "trading rule explanation"],
  sections: [
    {
      heading: "Preview: look without acting",
      paragraphs: [
        "A preview evaluates your rule on the latest data and shows the result with the reason. It never places an order, so it is safe to repeat as often as you like.",
        "Use it to see whether each condition passes, why the rule would act or stay out, and whether your limits would block it.",
      ],
    },
    {
      heading: "Run: let the rule work on demo",
      paragraphs: [
        "A run starts the automation on the demo account you connected. The rule is evaluated on its timeframe and, when its conditions and your limits allow, a demo order can be placed.",
        "You can pause or stop it. Live trading is not available in this release.",
      ],
    },
    {
      heading: "Side by side",
      paragraphs: ["The practical differences:"],
      table: {
        caption: "Preview compared with run",
        head: ["Aspect", "Preview", "Run"],
        rows: [
          ["Places orders", "Never", "Demo orders, within your limits"],
          ["When it evaluates", "When you ask", "On the rule's timeframe"],
          ["Leaves a record", "Shows the explanation", "Writes to the journal"],
          ["Best for", "Checking the logic", "Observing the rule over time"],
        ],
      },
    },
    {
      heading: "A sensible order",
      paragraphs: ["Follow these steps before you trust a rule:"],
      steps: [
        "Preview it a few times and read the explanation.",
        "Check the limits: risk per trade, daily stop, open positions.",
        "Start a run on demo.",
        "Read the journal after a few events.",
      ],
    },
  ],
  faq: [
    {
      question: "Can a preview place an order?",
      answer: "No. A preview never places an order.",
    },
    {
      question: "Can I stop a run?",
      answer: "Yes. A run can be paused or stopped, and the journal shows what the rule did.",
    },
    {
      question: "Does a preview predict what a run will do?",
      answer: "It shows what the rule decides on the data at that moment. Later data can lead to a different result.",
    },
  ],
  related: ["trading-journal-what-to-record", "why-did-my-rule-not-open-a-trade", "what-is-rules-based-trading"],
};
