import type { Article } from "./types";

export const NO_TRADE: Article = {
  slug: "why-did-my-rule-not-open-a-trade",
  title: "Why did my rule not open a trade? The reasons, in plain words",
  description:
    "When a rule opens nothing, the journal gives a reason. The difference between a hold, a limit, a data gap and a configuration problem, and what to do about each.",
  summary:
    "A rule that opens nothing is usually working as written. A hold means the conditions were not met. A limit means something you set, such as a spread ceiling, the session or the open-position cap, stopped it. A data gap means there were not enough bars. A configuration error means the rule cannot run until you fix it. The journal names which one it was.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["why no trade opened", "trading rule hold", "spread limit", "automated trading not trading", "trading journal reasons"],
  sections: [
    {
      heading: "No trade is an answer, not an error",
      paragraphs: [
        "Most of the time a rule has nothing to do. Its conditions are not met, so it holds. The useful question is not whether it traded but which kind of reason stopped it, and the journal records that.",
      ],
    },
    {
      heading: "Four kinds of reason",
      paragraphs: ["They look similar on screen and mean different things:"],
      table: {
        caption: "Reasons a rule did not act and what to do",
        head: ["Kind", "Example", "What to do"],
        rows: [
          ["Hold", "The conditions were not met", "Nothing. The rule ran and stayed out"],
          ["Limit", "Spread ceiling, outside the session, open-position cap, side not allowed", "Nothing to fix; check the limit is where you want it"],
          ["Data gap", "Not enough bars for an indicator", "Often fixes itself; if it persists, shorten the indicator period"],
          ["Configuration", "The rule is invalid, or the symbol or timeframe does not match", "Fix the rule; it cannot run until you do"],
        ],
      },
    },
    {
      heading: "Why they are kept apart",
      paragraphs: [
        "A broken rule must not look like a quiet market, and a limit doing its job must not look like a bug. Keeping the kinds apart means a real problem is shown clearly instead of being lost among normal holds.",
      ],
    },
    {
      heading: "A quick way to check",
      paragraphs: ["When nothing opens for a while:"],
      steps: [
        "Open the journal and read the latest reason.",
        "Decide which of the four kinds it is.",
        "If it is a limit or a hold, wait for the market to meet the conditions.",
        "If it is a data gap or a configuration reason, act on the detail given.",
        "Check the risk guard if the reason mentions account state.",
      ],
    },
  ],
  faq: [
    {
      question: "Is it a problem if my rule has not traded for days?",
      answer: "Not necessarily. Many rules wait for specific conditions. Read the journal to see whether it is a hold, a limit, a data gap or a configuration reason.",
    },
    {
      question: "What is the difference between a hold and a rejection?",
      answer: "A hold means the rule ran and its conditions were not met. A rejection means the rule could not run at all and needs fixing.",
    },
    {
      question: "Can I make a rule trade more often?",
      answer: "You can change its conditions, but do it for a reason you can write down. Widening a limit only to force a trade removes the protection it gave.",
    },
  ],
  related: ["risk-guard-explained", "trading-journal-what-to-record", "preview-vs-run-what-each-does"],
};
