import type { Metadata } from "next";
import Link from "next/link";
import { ContentShell } from "@/components/marketing/content-shell";
import { JsonLd } from "@/components/marketing/json-ld";
import { FAQ_ITEMS } from "@/content/faq";
import { faqPageLd } from "@/lib/json-ld";

const TITLE = "FAQ: Apex4Traders questions answered";
const DESCRIPTION =
  "Answers about Apex4Traders: the 14-day free demo, connecting cTrader, rules, Risk Guard, the journal and what is not open in this release.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/faq" },
  openGraph: {
    type: "website",
    url: "/faq",
    siteName: "Apex4Traders",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export default function FaqPage() {
  return (
    <ContentShell>
      <JsonLd data={faqPageLd()} />
      <section className="mkt-section mkt-faq" aria-labelledby="faq-title">
        <span className="mkt-eyebrow">FAQ</span>
        <h1 id="faq-title" style={{ fontSize: "clamp(2rem, 6vw, 3rem)", margin: ".6rem 0 0" }}>
          Frequently asked questions
        </h1>
        <p className="mkt-lede">
          How Apex4Traders works, what the demo covers and what is not open yet.
        </p>
        <div className="mkt-faq-list">
          {FAQ_ITEMS.map(({ question, answer }) => (
            <details key={question}>
              <summary>
                <h2 style={{ display: "inline", font: "inherit", margin: 0 }}>{question}</h2>
              </summary>
              <p>{answer}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="mkt-section" aria-labelledby="next-title">
        <h2 id="next-title">Ready to try it on demo?</h2>
        <p>
          <Link href="/signup">Create a free account</Link> and follow the{" "}
          <Link href="/guide/test-a-rule-on-demo">step-by-step guide</Link>, or see the{" "}
          <Link href="/pricing">pricing page</Link> for the paid plan.
        </p>
        <div className="mkt-risk">
          <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
          Leveraged trading carries a high risk of loss. You are responsible for
          the rules you run.
        </div>
      </section>
    </ContentShell>
  );
}
