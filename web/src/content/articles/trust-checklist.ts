import type { Article } from "./types";

export const TRUST_CHECKLIST: Article = {
  slug: "questions-to-ask-before-trusting-an-automation-platform",
  title: "Questions to ask before trusting a trading automation platform",
  description:
    "A plain checklist for judging any trading automation platform: promises, broker access, testing, limits, support and price. Includes how Apex4Traders answers each.",
  summary:
    "Before you connect a trading account to any automation platform, check six things: whether it promises results, how it reaches your broker, how it explains testing, what limits you control, how you reach support and what it costs. Be wary of any claim about results and of any form that asks for your broker password. Here is each question and how Apex4Traders answers it.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 6,
  keywords: ["trading automation platform review", "is it safe to automate trading", "trading platform checklist", "automated trading red flags"],
  sections: [
    {
      heading: "Why a checklist helps",
      paragraphs: [
        "Public reviews of automation tools tend to repeat the same complaints: promises that did not hold, unclear fees, slow support, and results that looked good in a test and weak afterwards. A checklist turns those complaints into questions you can ask before you connect anything.",
      ],
    },
    {
      heading: "The six questions",
      paragraphs: ["Ask each one of any platform, ours included:"],
      table: {
        caption: "Six questions, and how Apex4Traders answers them",
        head: ["Question", "A good sign", "Apex4Traders"],
        rows: [
          ["Does it promise results?", "No promises of profit or returns", "No promises. Demo only, with a risk warning"],
          ["How does it reach your broker?", "The broker's own sign-in, never your password", "cTrader sign-in (OAuth); no broker password is asked for"],
          ["How does it explain testing?", "Says what a test can and cannot show", "Explains what demo shows and does not"],
          ["What can you limit?", "Risk per trade, daily stop, open positions", "All three are set in the wizard, before anything runs"],
          ["How do you reach a person?", "A published contact and a way to read what happened", "A journal of what the rule did; see the Help page"],
          ["What does it cost?", "A clear price before you commit", "Free for 14 days on demo; see the pricing page"],
        ],
      },
    },
    {
      heading: "Red flags worth walking away from",
      paragraphs: ["None of these proves a platform is bad, but each deserves a pause:"],
      bullets: [
        "Screenshots of profit used as a reason to sign up.",
        "A form that asks you to type your broker password.",
        "No explanation of how a test treats spreads, slippage and fees.",
        "Pressure to change settings or to deposit more.",
        "Pricing you cannot find before you register.",
      ],
    },
    {
      heading: "What this checklist cannot do",
      paragraphs: [
        "It cannot tell you whether a rule will make or lose money. No platform can. Use it to judge the platform's honesty and controls, and test any rule on a demo account first.",
      ],
    },
  ],
  faq: [
    {
      question: "Is it safe to connect a trading account to an automation platform?",
      answer:
        "It depends on how the connection works. Prefer a platform that sends you to your broker's own sign-in and never asks for your broker password, and one that lets you withdraw access without changing the password.",
    },
    {
      question: "Does Apex4Traders ask for my broker password?",
      answer: "No. You sign in on cTrader's own page and approve specific accounts. Apex4Traders receives a token for what you approved.",
    },
    {
      question: "Does Apex4Traders say what results to expect?",
      answer: "No. It states no expected results. Automation runs on demo accounts only. Leveraged trading carries a high risk of loss, and this is not financial advice.",
    },
  ],
  related: ["connect-ctrader-safely", "demo-vs-live-account", "what-a-demo-run-shows-and-what-it-does-not"],
};
