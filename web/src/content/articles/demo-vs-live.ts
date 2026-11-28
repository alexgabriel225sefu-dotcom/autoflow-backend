import type { Article } from "./types";

export const DEMO_VS_LIVE: Article = {
  slug: "demo-vs-live-account",
  title: "Demo account vs live account: why test a rule on demo first",
  description:
    "A demo account runs a trading rule with virtual funds. What demo testing shows, what it cannot show, and how to read a demo result without fooling yourself.",
  summary:
    "A demo account trades with virtual funds in a broker's practice environment, so a rule can run without risking real money. Demo testing shows whether the rule does what you wrote and whether your limits behave. It cannot fully show how a live account would perform, because execution, spreads and your own behaviour can differ. Treat a demo result as a check, not a forecast.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["demo account", "demo vs live trading", "test a trading strategy", "forex demo account", "cTrader demo"],
  sections: [
    {
      heading: "What a demo account is",
      paragraphs: [
        "A demo account is a practice account that uses virtual money and the broker's practice environment. Orders are handled the way the broker handles them for demo, and nothing you win or lose is real.",
        "Its purpose is to let you operate a platform, and run a rule, with no financial exposure.",
      ],
    },
    {
      heading: "What demo testing can show",
      paragraphs: ["Used properly, a demo run answers practical questions about the rule itself:"],
      bullets: [
        "Does each condition fire when you meant it to, and not when you did not?",
        "Do the limits behave: is the stop distance sensible and does the size match your risk setting?",
        "Does the rule act in the session you chose and stay quiet outside it?",
        "Can you read the journal afterwards and understand what happened?",
        "Does the setup survive a few days without needing constant attention?",
      ],
    },
    {
      heading: "What demo cannot show",
      paragraphs: ["A demo run is a weaker guide to money questions than it feels:"],
      bullets: [
        "Execution quality. Fills, slippage and spreads on a live account can differ from the practice environment.",
        "Size and liquidity. A position that fills easily on demo may not fill the same way live.",
        "Your own behaviour. Real money changes how people react, including whether they leave a rule alone.",
        "Changing markets. A short demo period covers one slice of conditions only.",
        "Luck. A small number of trades can look good or bad by chance.",
      ],
    },
    {
      heading: "Demo and live side by side",
      paragraphs: ["The differences that matter most when you read a result:"],
      table: {
        caption: "Demo account compared with live account",
        head: ["Aspect", "Demo account", "Live account"],
        rows: [
          ["Funds", "Virtual", "Real money"],
          ["Risk of loss", "None in money terms", "Real, and can exceed what you expected"],
          ["Execution", "Broker's practice environment", "Real market execution, which can differ"],
          ["Emotion", "Low pressure", "Real pressure"],
          ["In Apex4Traders", "Available now; free for 14 days", "Not available in this release"],
        ],
      },
    },
    {
      heading: "How to read a demo result honestly",
      paragraphs: ["A few habits keep the result useful:"],
      steps: [
        "Decide what you are checking before you start: the logic of the rule, not its profit.",
        "Let enough time pass for the rule's timeframe to produce several events.",
        "Read the journal, not only the balance.",
        "Do not change the rule after each loss. Change it, if at all, once you have a reason you can write down.",
        "Remember that a good demo run says little with certainty about a live account.",
      ],
    },
  ],
  faq: [
    {
      question: "Does a profitable demo mean a live account will be profitable?",
      answer:
        "No. Demo results depend on conditions that may not repeat, and live execution and behaviour can differ. A demo result is a check on the rule, not a forecast.",
    },
    {
      question: "How long should I test on demo?",
      answer:
        "There is no fixed answer. Test long enough for the rule's timeframe to produce several events, and avoid drawing conclusions from a handful of trades. Apex4Traders' free demo lasts 14 days.",
    },
    {
      question: "Does Apex4Traders place live orders?",
      answer:
        "No. Automation runs on demo accounts only, and live trading is not available in this release. A preview never places an order.",
    },
  ],
  related: ["connect-ctrader-safely", "trading-journal-what-to-record", "what-is-rules-based-trading"],
};
