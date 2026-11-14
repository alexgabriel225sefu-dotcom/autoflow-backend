import type { Metadata } from "next";
import Link from "next/link";
import { ContentShell } from "@/components/marketing/content-shell";
import { GUIDE_STEPS } from "@/content/guide";

const TITLE = "How to test a trading rule on a demo account";
const DESCRIPTION =
  "A step-by-step guide: create an account, connect a cTrader demo account, choose a ready-made strategy, preview a decision, start on demo and read the journal.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/guide/test-a-rule-on-demo" },
  openGraph: {
    type: "article",
    url: "/guide/test-a-rule-on-demo",
    siteName: "Apex4Traders",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export default function TestARuleOnDemoGuide() {
  return (
    <ContentShell>
      <section className="mkt-section" aria-labelledby="guide-title">
        <span className="mkt-eyebrow">Guide</span>
        <h1 id="guide-title" style={{ fontSize: "clamp(2rem, 6vw, 3rem)", margin: ".6rem 0 0" }}>
          Test a rule on a demo account
        </h1>
        <p className="mkt-lede">
          Eight short steps from sign-up to your first journal entry. Everything
          here runs on a demo account.
        </p>
        <ol className="mkt-plain" style={{ marginTop: "1.6rem", paddingLeft: "1.3rem", display: "grid", gap: "1.2rem" }}>
          {GUIDE_STEPS.map(({ title, body }) => (
            <li key={title}>
              <h2 style={{ fontSize: "1.1rem", margin: 0 }}>{title}</h2>
              <p style={{ margin: ".35rem 0 0" }}>{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mkt-section" aria-labelledby="guide-next">
        <h2 id="guide-next">Start now</h2>
        <p>
          <Link href="/signup">Create your free account</Link>. The demo is free
          for 14 days; the paid plan&apos;s price is on the{" "}
          <Link href="/pricing">pricing page</Link>. Questions first? Read the{" "}
          <Link href="/faq">FAQ</Link>.
        </p>
        <div className="mkt-risk">
          <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
          Leveraged trading carries a high risk of loss. A demo result says
          nothing certain about what a live account would do.
        </div>
      </section>
    </ContentShell>
  );
}
