import Link from "next/link";
import { ArticleCover } from "@/components/marketing/article-cover";
import { ArticleProgress } from "@/components/marketing/article-progress";
import { ArticleToc, type TocItem } from "@/components/marketing/article-toc";
import { ContentShell } from "@/components/marketing/content-shell";
import { JsonLd } from "@/components/marketing/json-ld";
import { articleBySlug, articlePath, type Article } from "@/content/articles";
import styles from "./article-view.module.css";
import { articleFaqLd, articleLd, breadcrumbLd } from "@/lib/json-ld";

/** "28 November 2026", fixed to UTC so the server and the browser agree. */
export function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}

/** What Apex4Traders is, in the same words everywhere it is described. */
export const ABOUT_APEX =
  "Apex4Traders is software that runs trading rules you configure, on a cTrader account you connect yourself. " +
  "It is not financial advice, it does not supply signals and it never takes custody of your funds. " +
  "In this release it runs on demo accounts only, and the demo is free for 14 days.";

function sectionId(index: number, heading: string): string {
  const slug = heading.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
  return `s${index + 1}-${slug}`;
}

function CtaCard() {
  return (
    <div className={styles.cta}>
      <p className={styles.ctaTitle}>Try it free for 14 days on a demo account</p>
      <Link className={`mkt-btn mkt-btn-lg ${styles.ctaBtn}`} href="/signup">Create your free account</Link>
      <p className={styles.ctaRisk}>
        Educational only, not financial advice. Leveraged trading carries a high risk of loss.
      </p>
    </div>
  );
}

export function ArticleView({ article }: { article: Article }) {
  const related = article.related
    .map((slug) => articleBySlug(slug))
    .filter((a): a is Article => Boolean(a));
  const toc: readonly TocItem[] = [
    ...article.sections.map((s, i) => ({ id: sectionId(i, s.heading), label: s.heading })),
    { id: "article-faq-section", label: "Questions people ask" },
  ];
  return (
    <ContentShell>
      <ArticleProgress targetId="article-body" />
      <JsonLd data={articleLd(article)} />
      <JsonLd data={articleFaqLd(article)} />
      <JsonLd data={breadcrumbLd([
        { name: "Home", path: "/" },
        { name: "Guides", path: "/guide" },
        { name: article.title, path: articlePath(article.slug) },
      ])} />
      <article className={styles.page}>
        <header className={styles.hero}>
          <nav className={styles.crumbs} aria-label="Breadcrumb">
            <Link href="/">Home</Link> <span aria-hidden>/</span> <Link href="/guide">Guides</Link>
          </nav>
          <h1 id="article-title" className={styles.title}>{article.title}</h1>
          <p className={styles.meta}>
            <span>By the Apex4Traders team</span>
            <span aria-hidden className={styles.dot} />
            <span>Updated <time dateTime={article.updated}>{formatDate(article.updated)}</time></span>
            <span aria-hidden className={styles.dot} />
            <span>{article.readingMinutes} min read</span>
          </p>
          <ArticleCover slug={article.slug} className={styles.cover} />
        </header>

        <aside className={styles.answer} aria-label="Short answer">
          <strong className={styles.answerLabel}>Short answer</strong>
          <p>{article.summary}</p>
        </aside>

        <div className={styles.layout}>
          <div className={styles.main} id="article-body">
            <details className={styles.tocMobile}>
              <summary>On this page</summary>
              <ArticleToc items={toc} />
            </details>

            {article.sections.map((s, i) => (
              <section className={styles.section} id={sectionId(i, s.heading)} aria-label={s.heading} key={s.heading}>
                <span className={styles.eyebrow} aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                <h2>{s.heading}</h2>
                {s.paragraphs.map((p) => <p key={p}>{p}</p>)}
                {s.bullets ? <ul className={styles.bullets}>{s.bullets.map((b) => <li key={b}>{b}</li>)}</ul> : null}
                {s.steps ? <ol className={styles.steps}>{s.steps.map((b) => <li key={b}>{b}</li>)}</ol> : null}
                {s.table ? (
                  <div className={styles.tableWrap} role="region" aria-label={s.table.caption} tabIndex={0}>
                    <table className={styles.table}>
                      <caption>{s.table.caption}</caption>
                      <thead><tr>{s.table.head.map((h) => <th scope="col" key={h}>{h}</th>)}</tr></thead>
                      <tbody>
                        {s.table.rows.map((row) => (
                          <tr key={row[0]}>{row.map((cell, ci) => <td key={ci}>{cell}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>
            ))}

            <section className={styles.section} id="article-faq-section" aria-labelledby="article-faq">
              <span className={styles.eyebrow} aria-hidden="true">FAQ</span>
              <h2 id="article-faq">Questions people ask</h2>
              <div className={styles.faq}>
                {article.faq.map(({ question, answer }) => (
                  <details key={question} className={styles.faqItem}>
                    <summary>{question}</summary>
                    <p>{answer}</p>
                  </details>
                ))}
              </div>
            </section>
          </div>

          <aside className={styles.rail} aria-label="Article navigation">
            <nav className={styles.toc} aria-label="On this page">
              <p className={styles.railLabel}>On this page</p>
              <ArticleToc items={toc} />
            </nav>
            <CtaCard />
          </aside>
        </div>

        <section className={styles.after} aria-labelledby="article-next">
          <h2 id="article-next" className={styles.afterTitle}>Related guides</h2>
          <div className={styles.cards}>
            {related.map((r) => (
              <Link key={r.slug} href={articlePath(r.slug)} className={styles.card}>
                <ArticleCover slug={r.slug} className={styles.cardCover} />
                <span className={styles.cardTitle}>{r.title}</span>
                <span className={styles.cardMeta}>{r.readingMinutes} min read</span>
              </Link>
            ))}
          </div>
          <p className={styles.moreLinks}>
            <Link href="/guide/test-a-rule-on-demo">How to test a trading rule on a demo account</Link>
            <Link href="/faq">Apex4Traders FAQ</Link>
          </p>
          <p className={styles.about}><strong>About Apex4Traders.</strong> {ABOUT_APEX}</p>
          <p className={styles.closing}>
            <Link href="/signup">Create your free account</Link> and try a rule on a demo account. The paid plan&apos;s
            price is on the <Link href="/pricing">pricing page</Link>.
          </p>
          <div className={styles.risk}>
            <strong>Risk warning.</strong>{" "}
            This guide is educational and is not financial advice. Leveraged trading carries a high risk of loss.
            A demo result says nothing certain about what a live account would do.
          </div>
        </section>
      </article>
    </ContentShell>
  );
}
