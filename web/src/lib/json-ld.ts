import { SITE_URL } from "@/lib/site";
import { FAQ_ITEMS } from "@/content/faq";
import { ARTICLES, articlePath, type Article } from "@/content/articles";

/**
 * Serialises structured data for a <script type="application/ld+json"> tag.
 * `<` is escaped so that no string in the payload can close the tag.
 */
export function jsonLdString(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

export const ORGANIZATION_LD = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "Apex4Traders",
  url: SITE_URL,
} as const;

export const WEBSITE_LD = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Apex4Traders",
  url: SITE_URL,
} as const;

/** Built from the same array that renders /faq, so the two cannot drift. */
export function faqPageLd() {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ_ITEMS.map(({ question, answer }) => ({
      "@type": "Question",
      name: question,
      acceptedAnswer: { "@type": "Answer", text: answer },
    })),
  };
}

const PUBLISHER = {
  "@type": "Organization",
  name: "Apex4Traders",
  url: SITE_URL,
  logo: { "@type": "ImageObject", url: `${SITE_URL}/apex4traders-logo.png` },
} as const;

/** One guide article. Dates and text come from the same data that renders the page. */
export function articleLd(a: Article) {
  const url = `${SITE_URL}${articlePath(a.slug)}`;
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: a.title,
    description: a.description,
    datePublished: a.published,
    dateModified: a.updated,
    inLanguage: "en",
    keywords: a.keywords.join(", "),
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    author: { "@type": "Organization", name: "Apex4Traders", url: SITE_URL },
    publisher: PUBLISHER,
  };
}

/** The article's own questions, so an assistant can lift a question with its answer. */
export function articleFaqLd(a: Article) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: a.faq.map(({ question, answer }) => ({
      "@type": "Question",
      name: question,
      acceptedAnswer: { "@type": "Answer", text: answer },
    })),
  };
}

export function breadcrumbLd(items: readonly { name: string; path: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: it.name,
      item: `${SITE_URL}${it.path}`,
    })),
  };
}

/** The hub: a collection page that lists every guide. */
export function guideHubLd() {
  return {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "Apex4Traders guides",
    url: `${SITE_URL}/guide`,
    inLanguage: "en",
    publisher: PUBLISHER,
    mainEntity: {
      "@type": "ItemList",
      itemListElement: ARTICLES.map((a, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: `${SITE_URL}${articlePath(a.slug)}`,
        name: a.title,
      })),
    },
  };
}
