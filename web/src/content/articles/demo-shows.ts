import type { Article } from "./types";

export const DEMO_SHOWS: Article = {
  slug: "what-a-demo-run-shows-and-what-it-does-not",
  title: "What a demo run shows, and what it does not",
  description:
    "A demo run on Apex4Traders sends orders to a broker's practice account. What that proves about a rule, and what it cannot say about live execution.",
  summary:
    "On Apex4Traders a demo run connects to a cTrader demo account, so orders go to the broker's practice environment with virtual funds. That shows whether your conditions fire, whether limits hold and whether the journal explains what happened. It does not show live fills, slippage or spreads, how you would act with real money, or how the rule copes in other markets.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["demo trading limits", "demo vs live execution", "slippage on demo", "test a trading rule", "cTrader demo account"],
  sections: [
    {
      heading: "What actually runs on a demo account",
      paragraphs: [
        "Apex4Traders connects to a demo account you approve on cTrader. The rule you built is evaluated on that account's market data and any resulting order goes to the broker's practice environment.",
        "Nothing here uses real money, and live trading is not available in this release.",
      ],
    },
    {
      heading: "What the run can tell you",
      paragraphs: ["These are questions about the rule, and a demo run can answer them:"],
      bullets: [
        "Did each condition fire when you meant it to?",
        "Did the stop distance and position size match the risk you set?",
        "Did the rule stay quiet outside the session you chose?",
        "Do the daily stop and the open-position limit behave as written?",
        "Does the journal explain, in words, why something happened or did not?",
      ],
    },
    {
      heading: "What it cannot tell you",
      paragraphs: ["Money questions are where a demo result is weakest:"],
      table: {
        caption: "Demo run compared with what live trading can add",
        head: ["Topic", "On a demo run", "What can differ live"],
        rows: [
          ["Fills", "Handled in the practice environment", "Real fills can arrive at different prices"],
          ["Slippage", "May understate it", "Can be larger in fast markets"],
          ["Spread", "As the practice feed shows it", "Can widen, for example around news"],
          ["Your behaviour", "Low pressure", "Real money changes how people react"],
          ["Sample size", "A short period, a few events", "One slice of conditions says little about the next"],
        ],
      },
    },
    {
      heading: "How to use the result",
      paragraphs: ["Treat a demo run as a check on the rule's logic, not as a forecast."],
      steps: [
        "Write down what you are checking before you start.",
        "Let enough time pass for the rule's timeframe to produce several events.",
        "Read the journal, not only the balance.",
        "Change the rule only for a reason you can write down.",
      ],
    },
  ],
  faq: [
    {
      question: "Is the demo a simulation made by Apex4Traders?",
      answer:
        "No. Orders go to the broker's own demo account through the cTrader connection you approved. Apex4Traders does not simulate fills itself.",
    },
    {
      question: "Why can demo and live results differ?",
      answer:
        "Execution, spreads, slippage and your own behaviour can all differ with real money. A demo run does not measure those reliably.",
    },
    {
      question: "Does Apex4Traders trade live accounts?",
      answer: "No. Automation runs on demo accounts only, and live trading is not available in this release.",
    },
  ],
  related: ["demo-vs-live-account", "trading-journal-what-to-record", "risk-per-trade-and-stop-distance"],
};
