import Link from "next/link";
import { ContentShell } from "@/components/marketing/content-shell";
import { JsonLd } from "@/components/marketing/json-ld";
import { articleBySlug, articlePath, type Article } from "@/content/articles";
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

export function ArticleView({ article }: { article: Article }) {
  const related = article.related
    .map((slug) => articleBySlug(slug))
    .filter((a): a is Article => Boolean(a));
  return (
    <ContentShell>
      <JsonLd data={articleLd(article)} />
      <JsonLd data={articleFaqLd(article)} />
      <JsonLd data={breadcrumbLd([
        { name: "Home", path: "/" },
        { name: "Guides", path: "/guide" },
        { name: article.title, path: articlePath(article.slug) },
      ])} />
      <article className="mkt-article">
        <section className="mkt-section" aria-labelledby="article-title">
          <nav className="mkt-crumbs" aria-label="Breadcrumb">
            <Link href="/">Home</Link> <span aria-hidden>/</span> <Link href="/guide">Guides</Link>
          </nav>
          <h1 id="article-title">{article.title}</h1>
          <p className="mkt-meta">
            By the Apex4Traders team · Updated{" "}
            <time dateTime={article.updated}>{formatDate(article.updated)}</time> · {article.readingMinutes} min read
          </p>
          <p className="mkt-answer"><strong>Short answer</strong>{article.summary}</p>
        </section>

        {article.sections.map((s) => (
          <section className="mkt-section" key={s.heading}>
            <h2>{s.heading}</h2>
            {s.paragraphs.map((p) => <p key={p}>{p}</p>)}
            {s.bullets ? <ul>{s.bullets.map((b) => <li key={b}>{b}</li>)}</ul> : null}
            {s.steps ? <ol>{s.steps.map((b) => <li key={b}>{b}</li>)}</ol> : null}
            {s.table ? (
              <div className="mkt-table-wrap">
                <table className="mkt-table">
                  <caption>{s.table.caption}</caption>
                  <thead><tr>{s.table.head.map((h) => <th scope="col" key={h}>{h}</th>)}</tr></thead>
                  <tbody>
                    {s.table.rows.map((row) => (
                      <tr key={row[0]}>{row.map((cell, i) => <td key={i}>{cell}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        ))}

        <section className="mkt-section" aria-labelledby="article-faq">
          <h2 id="article-faq">Questions people ask</h2>
          {article.faq.map(({ question, answer }) => (
            <div key={question} style={{ marginTop: "1.1rem" }}>
              <h3 style={{ fontSize: "1.02rem", margin: 0 }}>{question}</h3>
              <p style={{ margin: ".35rem 0 0" }}>{answer}</p>
            </div>
          ))}
        </section>

        <section className="mkt-section" aria-labelledby="article-next">
          <h2 id="article-next">Keep reading</h2>
          <div className="mkt-related">
            {related.map((r) => <Link key={r.slug} href={articlePath(r.slug)}>{r.title}</Link>)}
            <Link href="/guide/test-a-rule-on-demo">How to test a trading rule on a demo account</Link>
            <Link href="/faq">Apex4Traders FAQ</Link>
          </div>
          <p className="mkt-about"><strong style={{ color: "var(--mkt-text)" }}>About Apex4Traders.</strong> {ABOUT_APEX}</p>
          <p style={{ marginTop: "1.2rem" }}>
            <Link href="/signup">Create your free account</Link> and try a rule on a demo account. The paid plan&apos;s
            price is on the <Link href="/pricing">pricing page</Link>.
          </p>
          <div className="mkt-risk">
            <strong style={{ color: "var(--mkt-text)" }}>Risk warning.</strong>{" "}
            This guide is educational and is not financial advice. Leveraged trading carries a high risk of loss.
            A demo result says nothing certain about what a live account would do.
          </div>
        </section>
      </article>
    </ContentShell>
  );
}

