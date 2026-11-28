import type { Metadata } from "next";
import Link from "next/link";
import { ContentShell } from "@/components/marketing/content-shell";
import { JsonLd } from "@/components/marketing/json-ld";
import { ARTICLES, articlePath } from "@/content/articles";
import { breadcrumbLd, guideHubLd } from "@/lib/json-ld";

const TITLE = "Guides: rules-based trading, cTrader, risk and demo testing";
const DESCRIPTION =
  "Plain-language guides from Apex4Traders: what rules-based trading is, how to connect cTrader safely, how indicators work as conditions, risk per trade, demo testing and journals.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/guide" },
  openGraph: { type: "website", url: "/guide", siteName: "Apex4Traders", title: TITLE, description: DESCRIPTION },
};

export default function GuideHub() {
  return (
    <ContentShell>
      <JsonLd data={guideHubLd()} />
      <JsonLd data={breadcrumbLd([{ name: "Home", path: "/" }, { name: "Guides", path: "/guide" }])} />
      <section className="mkt-section mkt-article" aria-labelledby="hub-title">
        <span className="mkt-eyebrow">Guides</span>
        <h1 id="hub-title">Guides to trading by rules</h1>
        <p className="mkt-lede">
          Short, plain-language guides on writing rules, connecting your own cTrader account, setting limits and
          testing on demo. Educational only, and not financial advice.
        </p>
        <div className="mkt-hub">
          <Link className="mkt-hubcard" href="/guide/test-a-rule-on-demo">
            <h2>How to test a trading rule on a demo account</h2>
            <p>Eight short steps from sign-up to your first journal entry.</p>
            <span>Start here · step-by-step</span>
          </Link>
          {ARTICLES.map((a) => (
            <Link className="mkt-hubcard" key={a.slug} href={articlePath(a.slug)}>
              <h2>{a.title}</h2>
              <p>{a.description}</p>
              <span>{a.readingMinutes} min read</span>
            </Link>
          ))}
        </div>
        <p style={{ marginTop: "2rem" }}>
          <Link href="/signup">Create your free account</Link> to try a rule on a demo account. See the{" "}
          <Link href="/faq">FAQ</Link> and the <Link href="/pricing">pricing page</Link>.
        </p>
        <div className="mkt-risk">
          <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
          Leveraged trading carries a high risk of loss. A demo result says nothing certain about what a live account would do.
        </div>
      </section>
    </ContentShell>
  );
}
