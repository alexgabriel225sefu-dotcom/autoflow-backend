/**
 * The shape of a guide article.
 *
 * One array of these feeds the page, the hub, the sitemap, the JSON-LD and
 * llms.txt, so what a visitor reads, what a search engine is told and what an
 * AI assistant is shown cannot drift apart.
 *
 * Writing rules (the copy tests enforce most of them):
 *  - the `summary` answers the title's question in 40-75 words, first;
 *  - no profit, return or win-rate claims, no prices, no advice;
 *  - say "demo" where the product only runs on demo.
 */
export interface ArticleTable {
  readonly caption: string;
  readonly head: readonly string[];
  readonly rows: readonly (readonly string[])[];
}

export interface ArticleSection {
  readonly heading: string;
  readonly paragraphs: readonly string[];
  readonly bullets?: readonly string[];
  readonly steps?: readonly string[];
  readonly table?: ArticleTable;
}

export interface ArticleFaq {
  readonly question: string;
  readonly answer: string;
}

export interface Article {
  readonly slug: string;
  readonly title: string;
  readonly description: string;
  /** The direct answer, shown first and used as the snippet. */
  readonly summary: string;
  /** ISO dates, YYYY-MM-DD. */
  readonly published: string;
  readonly updated: string;
  readonly readingMinutes: number;
  readonly keywords: readonly string[];
  readonly sections: readonly ArticleSection[];
  readonly faq: readonly ArticleFaq[];
  /** Slugs of other articles to link to. */
  readonly related: readonly string[];
}
