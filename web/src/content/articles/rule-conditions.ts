import type { Article } from "./types";

export const RULE_CONDITIONS: Article = {
  slug: "moving-average-rsi-macd-as-rule-conditions",
  title: "Moving averages, RSI and MACD as rule conditions",
  description:
    "How a moving-average cross, an RSI level and a MACD signal work as conditions in a trading rule, what each one measures, and where each one misleads.",
  summary:
    "A rule condition is a yes-or-no test on market data. A moving average smooths price to show direction, RSI measures the speed of recent price changes on a scale from 0 to 100, and MACD compares two moving averages of price. Each is simple to state and each has known weaknesses, so rules usually add a session filter and limits.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 6,
  keywords: ["moving average crossover", "RSI trading rule", "MACD signal", "trading rule conditions", "technical indicators explained"],
  sections: [
    {
      heading: "What a condition is",
      paragraphs: [
        "A condition turns a chart into a question with a yes-or-no answer. \"Is the fast average above the slow average?\" is a condition. \"Is RSI below 30?\" is another. A rule is a set of such conditions plus limits, so you can read it back and know exactly when it would act.",
        "Indicators describe past price. They do not predict the next move, and none of them works in every market condition.",
      ],
    },
    {
      heading: "Moving averages",
      paragraphs: [
        "A moving average is the average of the last N closing prices, recalculated on every new bar. A simple moving average weights all bars equally; an exponential one weights recent bars more. A common condition compares a fast average with a slow one: when the fast one crosses above the slow one, the condition for an upward move is met.",
        "Because an average uses past prices it lags. In a steady trend it keeps you on the right side; in a sideways market the two averages cross back and forth, which produces repeated false signals, often called whipsaws.",
      ],
    },
    {
      heading: "RSI",
      paragraphs: [
        "The Relative Strength Index, introduced by J. Welles Wilder, compares recent gains with recent losses and expresses the result between 0 and 100. A period of 14 is the usual default. By convention a reading above 70 is called overbought and below 30 oversold.",
        "Those labels describe a condition, not a certainty. In a strong trend RSI can stay near an extreme for a long time, so a rule that treats every extreme as a turning point can keep acting against the trend.",
      ],
    },
    {
      heading: "MACD",
      paragraphs: [
        "MACD is the difference between two exponential moving averages, commonly 12 and 26 bars, with a signal line that is a 9-bar average of that difference. A condition might ask whether MACD has crossed above its signal line, or whether the histogram has changed sign.",
        "MACD is built from moving averages, so it inherits their lag. It also tends to agree with the averages it came from, which matters when you combine it with them.",
      ],
    },
    {
      heading: "Trading sessions as a condition",
      paragraphs: [
        "A session condition limits a rule to chosen hours, such as the London or New York session. Activity and spreads differ across the day, so a rule written for one session can behave differently in another.",
      ],
    },
    {
      heading: "Putting the conditions side by side",
      paragraphs: ["Each condition has a clear job and a clear weakness:"],
      table: {
        caption: "Common rule conditions and their known weaknesses",
        head: ["Condition", "What it measures", "Typical use", "Known weakness"],
        rows: [
          ["Moving-average cross", "Direction, by comparing a fast and a slow average", "Trend following", "Lags; repeated false crosses in sideways markets"],
          ["RSI level", "Speed of recent price changes, 0 to 100", "Spotting stretched moves", "Can stay at an extreme in a strong trend"],
          ["MACD signal", "Momentum, from two moving averages", "Confirming a change of direction", "Lags and overlaps with moving averages"],
          ["Session", "Time of day", "Trading only when you choose", "Says nothing about direction"],
        ],
      },
    },
    {
      heading: "Combining conditions without over-fitting",
      paragraphs: [
        "Adding conditions can make a rule look better on past data while making it worse on new data, because it has been shaped to fit what already happened. Keep the number of conditions small, add one only for a reason you can state, prefer conditions that measure different things, and test on a demo account before you rely on a rule.",
        "In Apex4Traders you combine moving averages, RSI, MACD, sessions and more, read the rule back in plain language and preview which conditions pass and which fail. A preview never places an order.",
      ],
    },
  ],
  faq: [
    {
      question: "Which indicator is best for a trading rule?",
      answer:
        "None is best in every market. Each measures something different and fails in some conditions, which is why rules pair a condition with limits and are tested before use.",
    },
    {
      question: "What RSI period should I use?",
      answer:
        "14 is the most common default, set by the indicator's author. A shorter period reacts faster and produces more extremes; a longer one is smoother. The right value depends on your timeframe.",
    },
    {
      question: "Can one rule use several indicators?",
      answer:
        "Yes. A rule can require several conditions to pass together, for example a moving-average cross, an RSI level and a trading session. More conditions make a rule more selective, but also harder to test.",
    },
    {
      question: "Do indicators predict price?",
      answer:
        "No. Indicators are calculated from past prices and describe what has already happened.",
    },
  ],
  related: ["what-is-rules-based-trading", "risk-per-trade-and-stop-distance", "demo-vs-live-account"],
};
