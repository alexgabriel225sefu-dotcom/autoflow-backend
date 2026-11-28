import type { Article } from "./types";
import { RULES_BASED_TRADING } from "./rules-based-trading";
import { CONNECT_CTRADER_SAFELY } from "./connect-ctrader-safely";
import { RULE_CONDITIONS } from "./rule-conditions";
import { DEMO_VS_LIVE } from "./demo-vs-live";
import { RISK_AND_STOPS } from "./risk-and-stops";
import { TRADING_JOURNAL } from "./trading-journal";

export type { Article, ArticleFaq, ArticleSection, ArticleTable } from "./types";

/** Every guide article, in the order the hub lists them. */
export const ARTICLES: readonly Article[] = [
  RULES_BASED_TRADING,
  CONNECT_CTRADER_SAFELY,
  RULE_CONDITIONS,
  DEMO_VS_LIVE,
  RISK_AND_STOPS,
  TRADING_JOURNAL,
];

export function articleBySlug(slug: string): Article | undefined {
  return ARTICLES.find((a) => a.slug === slug);
}

export function articlePath(slug: string): string {
  return `/guide/${slug}`;
}
