import type { Article } from "./types";

export const RISK_AND_STOPS: Article = {
  slug: "risk-per-trade-and-stop-distance",
  title: "Risk per trade and stop distance: set limits before you automate",
  description:
    "How risk per trade, stop distance and position size connect, with a worked example in plain numbers, and why limits belong before a rule runs, not after a loss.",
  summary:
    "Risk per trade is the share of your account you accept losing if a trade reaches its stop. Stop distance is how far price must move against the trade to get there. Position size follows from the two: the wider the stop, the smaller the position for the same risk. Set both before a rule runs, not after a loss.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 6,
  keywords: ["risk per trade", "stop distance", "position sizing", "stop loss", "risk management for automated trading"],
  sections: [
    {
      heading: "Three numbers that belong together",
      paragraphs: [
        "Risk per trade, stop distance and position size are one decision seen from three sides. Fix any two and the third is determined.",
      ],
      bullets: [
        "Risk per trade: the amount you accept losing if the stop is hit, usually written as a share of the account.",
        "Stop distance: how far, in price, the market must move against you to reach the stop.",
        "Position size: how many units you trade.",
      ],
    },
    {
      heading: "A worked example in plain numbers",
      paragraphs: [
        "These numbers are illustrations, not recommendations. Take an account of 10,000 units of your account currency and a risk per trade of 1%. The amount at risk is 100 units.",
        "Suppose the stop is 50 points away. The position size must be chosen so that a 50-point move costs 100 units, which means each point must be worth 2 units. If you widen the stop to 100 points and keep the same risk, each point may be worth only 1 unit, so the position is half as large.",
      ],
      table: {
        caption: "Same risk, different stop distance",
        head: ["Risk per trade", "Amount at risk", "Stop distance", "Value allowed per point"],
        rows: [
          ["1%", "100 units", "50 points", "2 units"],
          ["1%", "100 units", "100 points", "1 unit"],
          ["2%", "200 units", "100 points", "2 units"],
        ],
      },
    },
    {
      heading: "Why wide stops mean smaller positions",
      paragraphs: [
        "The loss at the stop is roughly the stop distance multiplied by the position size. To keep that product at your chosen risk, a larger distance forces a smaller size. A rule that widens its stop without reducing size has quietly raised its risk.",
      ],
    },
    {
      heading: "Limits beyond a single trade",
      paragraphs: ["Single-trade risk is only one limit. Rules usually also need:"],
      bullets: [
        "A daily stop: a point at which the rule stops trading for the day.",
        "A cap on open positions, so risk does not pile up unnoticed.",
        "A target or exit condition, so a trade has a defined end.",
      ],
    },
    {
      heading: "What limits cannot do",
      paragraphs: [
        "A stop is an instruction, not a guarantee. If the market gaps or moves very fast, a position can close at a worse price than the stop, and the loss can be larger than planned. Limits reduce how much a rule can lose under normal conditions; they do not remove the risk of loss.",
        "In Apex4Traders the setup asks for risk per trade, stop distance, target, a daily stop and the number of open positions, and shows its own starting values, which you can change. They are a starting point, not advice. Risk Guard checks your limits before every order, and if a limit would be broken or the account state cannot be read, the order does not go ahead.",
      ],
    },
  ],
  faq: [
    {
      question: "What is a sensible risk per trade?",
      answer:
        "There is no universal answer. Educational material often uses 1% as an example, but the right figure depends on your account, your rule and how much loss you can accept. Nothing here is advice.",
    },
    {
      question: "Does a stop-loss guarantee my loss is limited?",
      answer:
        "No. A stop is an instruction. Gaps and fast markets can cause the position to close at a worse price than the stop.",
    },
    {
      question: "What does Risk Guard do in Apex4Traders?",
      answer:
        "Risk Guard checks your limits before every order. If a limit would be broken, or the account state cannot be read, the order does not go ahead and the screen says why. It protects the limits you set; it cannot remove the risk of loss.",
    },
  ],
  related: ["moving-average-rsi-macd-as-rule-conditions", "demo-vs-live-account", "trading-journal-what-to-record"],
};
