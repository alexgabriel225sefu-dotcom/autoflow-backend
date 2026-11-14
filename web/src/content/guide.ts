/** The steps of /guide/test-a-rule-on-demo. */
export interface GuideStep {
  readonly title: string;
  readonly body: string;
}

export const GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "Create your account",
    body: "Sign up with your email address and a password. The 14-day demo is free.",
  },
  {
    title: "Confirm your email",
    body: "Open the confirmation message and follow its link. If nothing arrives, check your spam folder before you try again.",
  },
  {
    title: "Connect a cTrader demo account",
    body: "Start the connection and approve access on cTrader's own page. Tick every account you want to see, then pick a demo account to work with. Apex4Traders never asks for your broker password.",
  },
  {
    title: "Choose a ready-made strategy",
    body: "Pick one of the ready-made strategies as a starting point. You can change its conditions and limits later.",
  },
  {
    title: "Check the rule",
    body: "Read the rule back in plain language and confirm it says what you mean. The check tells you if something is missing or invalid.",
  },
  {
    title: "Preview a decision",
    body: "Run a preview to see which conditions passed, which failed and what the rule would decide. A preview never places an order.",
  },
  {
    title: "Start on demo",
    body: "Start the rule on your demo account. You can pause or stop it at any time. Live trading is not available in this release.",
  },
  {
    title: "Read the journal",
    body: "Open the journal to see each evaluation: what the rule saw, what it decided and why, including the times it waited.",
  },
];
