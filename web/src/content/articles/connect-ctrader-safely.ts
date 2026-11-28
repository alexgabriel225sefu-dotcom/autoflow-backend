import type { Article } from "./types";

export const CONNECT_CTRADER_SAFELY: Article = {
  slug: "connect-ctrader-safely",
  title: "How to connect your cTrader account safely",
  description:
    "Connect cTrader through OAuth: you sign in on cTrader's own page and approve access, so the platform never sees your broker password. How it works and what to check.",
  summary:
    "Connect a cTrader account to a trading platform through cTrader's own authorisation (OAuth), not by typing your broker password into the platform. With OAuth you sign in on cTrader's page, approve a specific set of accounts and can withdraw that approval at any time. Apex4Traders connects this way and never asks for your broker password.",
  published: "2026-11-28",
  updated: "2026-11-28",
  readingMinutes: 5,
  keywords: ["connect cTrader", "cTrader OAuth", "cTrader third-party platform", "broker password safety", "cTrader demo account"],
  sections: [
    {
      heading: "What OAuth means, in one paragraph",
      paragraphs: [
        "OAuth is a standard way to let one service act on your account at another service without handing over your password. You are sent to the account's own sign-in page, you log in there, and you approve what the other service may do. The other service receives a token, not your password.",
        "For a cTrader account this means the sign-in happens on cTrader's page. The platform you are connecting never types or stores your broker password.",
      ],
    },
    {
      heading: "Sharing a password versus authorising with OAuth",
      paragraphs: ["The two ways of connecting differ in what the platform holds and what you can undo."],
      table: {
        caption: "Password sharing compared with OAuth authorisation",
        head: ["Question", "Sharing your password", "OAuth authorisation"],
        rows: [
          ["Where do you sign in?", "On the platform's own form", "On cTrader's own page"],
          ["What does the platform hold?", "Your password", "A token for the access you approved"],
          ["Can access be limited to chosen accounts?", "Usually not", "Yes, you choose which accounts to approve"],
          ["How do you stop access?", "Change your password, which also affects everything else that uses it", "Withdraw the approval, without changing your password"],
        ],
      },
    },
    {
      heading: "What to check before you approve",
      paragraphs: ["A short checklist before you press approve on any connection:"],
      bullets: [
        "The page asking for your sign-in is cTrader's own, not a look-alike inside the platform.",
        "You can see which accounts the approval covers, and you tick only the ones you want to use.",
        "You know whether each account is a demo or a live account.",
        "The platform says plainly what it will do with the access.",
        "The platform states that it does not take custody of your funds, and tells you how to disconnect.",
      ],
    },
    {
      heading: "How the connection works in Apex4Traders",
      paragraphs: ["The steps are the same for everyone:"],
      steps: [
        "Create an account and confirm your email address.",
        "Start the connection. You are sent to cTrader.",
        "Sign in on cTrader and approve access.",
        "Back in Apex4Traders, tick every account you want to see, then pick a demo account to work with.",
      ],
    },
    {
      heading: "What happens after you connect",
      paragraphs: [
        "Both demo and live accounts come back from the one authorisation, so you can see them side by side. In this release automation runs on demo accounts only, and live trading is not available. You can disconnect at any time.",
        "cTrader also lets you review the applications you have authorised from your cTrader ID account. Check cTrader's own help for the current steps, since they can change.",
      ],
    },
  ],
  faq: [
    {
      question: "Does Apex4Traders see my broker password?",
      answer:
        "No. You sign in on cTrader's own page and approve access there, so the password is never typed into Apex4Traders.",
    },
    {
      question: "Does Apex4Traders hold my money?",
      answer:
        "No. Apex4Traders never takes custody of your funds. Your money stays with your broker.",
    },
    {
      question: "Will my live account be traded?",
      answer:
        "No. Live accounts can appear in the list after authorisation, but automation runs on demo accounts only and live trading is not available in this release.",
    },
    {
      question: "How do I disconnect?",
      answer:
        "You can disconnect your cTrader account in Apex4Traders at any time. You can also review authorised applications from your cTrader ID account.",
    },
  ],
  related: ["demo-vs-live-account", "what-is-rules-based-trading", "trading-journal-what-to-record"],
};
