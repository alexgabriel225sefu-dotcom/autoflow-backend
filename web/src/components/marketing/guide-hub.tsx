import Link from "next/link";
import { ArticleCover } from "@/components/marketing/article-cover";
import { ARTICLES, articlePath } from "@/content/articles";
import styles from "./guide-hub.module.css";

interface HubItem {
  readonly slug: string;
  readonly href: string;
  readonly title: string;
  readonly description: string;
  readonly meta: string;
}

const STEP_GUIDE: HubItem = {
  slug: "test-a-rule-on-demo",
  href: "/guide/test-a-rule-on-demo",
  title: "How to test a trading rule on a demo account",
  description: "Eight short steps from sign-up to your first journal entry.",
  meta: "Step by step",
};

const FEATURED_SLUG = "what-is-rules-based-trading";

const GROUPS: readonly { readonly label: string; readonly slugs: readonly string[] }[] = [
  { label: "Start here", slugs: [FEATURED_SLUG, "connect-ctrader-safely", STEP_GUIDE.slug] },
  {
    label: "Rules and testing",
    slugs: [
      "moving-average-rsi-macd-as-rule-conditions",
      "demo-vs-live-account",
      "what-a-demo-run-shows-and-what-it-does-not",
      "preview-vs-run-what-each-does",
    ],
  },
  {
    label: "Risk and limits",
    slugs: ["risk-per-trade-and-stop-distance", "risk-guard-explained", "why-did-my-rule-not-open-a-trade"],
  },
  {
    label: "Read before you trust",
    slugs: ["questions-to-ask-before-trusting-an-automation-platform", "trading-journal-what-to-record"],
  },
];

function Arrow() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Card({ item }: { item: HubItem }) {
  return (
    <li>
      <Link className={styles.card} href={item.href}>
        <ArticleCover slug={item.slug} className={styles.cover} />
        <span className={styles.cardBody}>
          <h3>{item.title}</h3>
          <p>{item.description}</p>
          <span className={styles.meta}>
            <span>{item.meta}</span>
            <span className={styles.arrow}>Read<Arrow /></span>
          </span>
        </span>
      </Link>
    </li>
  );
}

export function GuideHub({ lede }: { lede: string }) {
  const items: readonly HubItem[] = [
    ...ARTICLES.map((a) => ({
      slug: a.slug,
      href: articlePath(a.slug),
      title: a.title,
      description: a.description,
      meta: `${a.readingMinutes} min read`,
    })),
    STEP_GUIDE,
  ];
  const bySlug = new Map(items.map((i) => [i.slug, i] as const));
  const mapped = new Set(GROUPS.flatMap((g) => g.slugs));
  const extras = items.filter((i) => !mapped.has(i.slug));
  const sections = [
    ...GROUPS.map((g) => ({
      label: g.label,
      items: g.slugs.map((s) => bySlug.get(s)).filter((i): i is HubItem => Boolean(i)),
    })),
    { label: "More guides", items: extras },
  ].filter((s) => s.items.length > 0);
  const featured = bySlug.get(FEATURED_SLUG);

  return (
    <div className={styles.hub}>
      <section className={styles.hero} aria-labelledby="hub-title">
        <p className={styles.eyebrow}>Guides</p>
        <h1 id="hub-title">Guides to trading by rules</h1>
        <p className={styles.lede}>{lede}</p>
        <ul className={styles.stats} aria-label="At a glance">
          <li><b>{items.length}</b><span>guides</span></li>
          <li><b>Demo</b><span>accounts only</span></li>
          <li><b>Educational</b><span>not advice</span></li>
        </ul>
      </section>

      {featured ? (
        <Link className={styles.featured} href={featured.href}>
          <ArticleCover slug={featured.slug} className={styles.cover} />
          <span className={styles.featBody}>
            <span className={styles.badge}>The starting point</span>
            <h2>{featured.title}</h2>
            <p>{featured.description}</p>
            <span className={styles.meta}>
              <span>{featured.meta}</span>
              <span className={styles.arrow}>Read the guide<Arrow /></span>
            </span>
          </span>
        </Link>
      ) : null}

      {sections.map((s) => (
        <section key={s.label} className={styles.section} aria-labelledby={`g-${s.label.replace(/\W+/g, "-").toLowerCase()}`}>
          <div className={styles.secHead}>
            <h2 id={`g-${s.label.replace(/\W+/g, "-").toLowerCase()}`}>{s.label}</h2>
            <span>{s.items.length}</span>
          </div>
          <ul className={styles.grid}>
            {s.items.map((i) => <Card key={i.slug} item={i} />)}
          </ul>
        </section>
      ))}

      <section className={styles.cta} aria-labelledby="hub-cta">
        <h2 id="hub-cta">Try it free for 14 days on a demo account</h2>
        <p>Write a rule, preview what it would decide, and run it on demo before anything else.</p>
        <Link className={styles.ctaBtn} href="/signup">Create your free account</Link>
        <p className={styles.links}>
          See the <Link href="/faq">FAQ</Link> and the <Link href="/pricing">pricing page</Link>.
        </p>
        <p className={styles.risk}>
          <strong>Risk warning.</strong> Leveraged trading carries a high risk of loss. A demo result says nothing
          certain about what a live account would do.
        </p>
      </section>
    </div>
  );
}
