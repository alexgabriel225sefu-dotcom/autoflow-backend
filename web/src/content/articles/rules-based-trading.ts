import type { Article } from "./types";

export const RULES_BASED_TRADING: Article = {
  slug: "what-is-rules-based-trading",
  title: "What is rules-based trading? A plain-language guide",
  description:
    "Rules-based trading means writing down, before any order, when to enter, exit and stop. What a rule is, how it differs from discretion, and what it cannot do.",
  summary:
    "Rules-based trading is a way of trading in which entries, exits and limits are written down as conditions before any order is placed. A rule either passes or fails, so it does not depend on how you feel that day. That makes behaviour consistent and testable. It does not predict the market, improve results by itself or remove the risk of loss.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["rules-based trading", "trading rules", "systematic trading", "trading plan", "automated trading for beginners"],
  sections: [
    {
      heading: "What a trading rule is",
      paragraphs: [
        "A trading rule is a written instruction that a computer or a person can follow without improvising. It has two parts: conditions that decide whether to act, and limits that decide how much to risk.",
        "A rule is not a prediction. It says \"if these things are true, do this\", and it says nothing about whether the market will cooperate.",
      ],
      bullets: [
        "An entry condition, for example a moving average crossing another one.",
        "An exit condition, such as a target or the opposite crossing.",
        "A stop: the distance at which you accept being wrong.",
        "A size limit: the share of the account risked on one trade.",
        "A filter, such as only trading during a chosen session.",
      ],
    },
    {
      heading: "Rules-based versus discretionary trading",
      paragraphs: [
        "In discretionary trading the person decides in the moment. In rules-based trading the decision was made earlier, in writing, and the rule applies it.",
      ],
      table: {
        caption: "Rules-based and discretionary trading compared",
        head: ["Aspect", "Rules-based", "Discretionary"],
        rows: [
          ["Where the decision comes from", "A written rule applied the same way each time", "The trader's judgement at that moment"],
          ["Consistency", "High: the same inputs give the same decision", "Varies with attention, mood and fatigue"],
          ["Can it be tested?", "Yes, on past data and on a demo account", "Only loosely, because the judgement is not written down"],
          ["Flexibility", "Low: it does not react to anything it was not told about", "High: the trader can react to news or context"],
          ["Main weakness", "A badly written rule is executed badly, consistently", "Inconsistent decisions that are hard to review"],
        ],
      },
    },
    {
      heading: "What rules can and cannot do",
      paragraphs: [
        "Rules remove improvisation. They make a strategy reviewable, because you can read what it was supposed to do and compare it with what it did.",
        "They cannot remove risk. Markets change, a rule that fit one period can stop fitting the next, and no set of conditions guarantees a result. Leveraged trading carries a high risk of loss whether the decisions are written down or not.",
      ],
    },
    {
      heading: "How to write a rule you can read back",
      paragraphs: ["A useful test is whether you can read the rule aloud and agree with every sentence."],
      steps: [
        "State the idea in one sentence, in plain words.",
        "Split it into named conditions, each one a yes-or-no test.",
        "Add the limits: risk per trade, stop distance and how many positions may be open.",
        "Read the whole rule back in plain language and fix anything that is not what you meant.",
        "Preview it, so you can see which conditions pass and which fail before anything runs.",
        "Test it on a demo account before you trust it with anything else.",
      ],
    },
    {
      heading: "Where Apex4Traders fits",
      paragraphs: [
        "Apex4Traders is software that runs trading rules you configure, on a cTrader account you connect yourself. You build a rule from named conditions, read it back in plain language, preview what it would decide and test it on a demo account. A preview never places an order. It is not financial advice, it does not supply signals and it never takes custody of your funds. In this release it runs on demo accounts only.",
      ],
    },
  ],
  faq: [
    {
      question: "Is rules-based trading the same as algorithmic trading?",
      answer:
        "They overlap. Algorithmic trading is the broader term and includes quantitative models and high-frequency systems. Rules-based trading, as used here, means a trader writes explicit conditions and limits and a program applies them.",
    },
    {
      question: "Do I need to code to trade by rules?",
      answer:
        "Not necessarily. In Apex4Traders you build a rule from named conditions such as moving averages, RSI, MACD and trading sessions, so no programming is needed.",
    },
    {
      question: "Does a rule remove the risk of loss?",
      answer:
        "No. A rule makes decisions consistent and testable. It does not predict prices, and a loss can still happen on any trade.",
    },
    {
      question: "How many conditions should a rule have?",
      answer:
        "There is no fixed number. Each added condition makes a rule harder to test and easier to fit to the past by accident, so many traders keep rules short and add a condition only for a reason they can state.",
    },
  ],
  related: ["moving-average-rsi-macd-as-rule-conditions", "demo-vs-live-account", "risk-per-trade-and-stop-distance"],
};
