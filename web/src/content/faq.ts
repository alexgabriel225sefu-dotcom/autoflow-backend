/**
 * The questions on /faq. The page renders this array and the FAQPage JSON-LD
 * is built from it, so what a visitor reads and what a search engine is told
 * are one list. Answers are plain text.
 */
export interface FaqItem {
  readonly question: string;
  readonly answer: string;
}

export const FAQ_ITEMS: readonly FaqItem[] = [
  {
    question: "What is Apex4Traders?",
    answer:
      "Apex4Traders is software that runs trading rules you configure, on a cTrader account you connect yourself. " +
      "You build a rule from named conditions, preview what it would decide and test it on a demo account. " +
      "It is not financial advice, it does not supply signals and it never takes custody of your funds.",
  },
  {
    question: "What does the 14-day free demo cover?",
    answer:
      "Demo accounts are free for 14 days. During that time you can connect a cTrader demo account, choose or build a rule, " +
      "preview its decisions, run it on demo and read the journal. The price of the paid plan is shown on the pricing page.",
  },
  {
    question: "How do I connect my cTrader account?",
    answer:
      "You connect through cTrader's own authorisation (OAuth). You are sent to cTrader, sign in there and approve access, " +
      "so Apex4Traders never sees your broker password. Both demo and live accounts come back from that one authorisation: " +
      "tick every account you want to see in Apex4Traders. You can disconnect at any time. Automation runs on demo accounts only.",
  },
  {
    question: "What is a rule?",
    answer:
      "A rule is a set of named conditions, such as a moving-average cross, an RSI level, a MACD signal or a trading session, " +
      "together with your limits. The platform reads the rule back in plain language before you test it, " +
      "and shows which conditions passed, which failed and what the rule would decide.",
  },
  {
    question: "What does Risk Guard do?",
    answer:
      "Risk Guard checks your limits before every order. If a limit would be broken, or if the account state cannot be read, " +
      "the order does not go ahead and the screen says why. It protects the limits you set; it cannot remove the risk of loss that comes with trading.",
  },
  {
    question: "What does the journal record?",
    answer:
      "When automation starts, pauses and stops, and any signal found at the Signals Only level. " +
      "Orders and closed trades are listed in Positions and Closed trades. " +
      "The journal does not yet list each check where the rule decided to wait.",
  },
  {
    question: "Is checkout or live trading open?",
    answer:
      "No. Checkout is not open in this release, and live trading is not available in this release. " +
      "Today the platform is for demo accounts, and a preview never places an order.",
  },
  {
    question: "Which platforms does it work with?",
    answer:
      "cTrader works today. Support for more platforms is on the roadmap, but nothing besides cTrader is available now.",
  },
  {
    question: "Can I write my own rules?",
    answer:
      "Yes. You can start from a ready-made strategy or combine named conditions yourself, " +
      "then check the rule and preview a decision before you start it on demo.",
  },
  {
    question: "How do I reach support?",
    answer:
      "Sign in and open the Help page, which is where support is reached from. " +
      "If something cannot be read, the screen says so and names the next step.",
  },
];
