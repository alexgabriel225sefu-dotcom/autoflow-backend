import { SITE_URL } from "@/lib/site";
import { FAQ_ITEMS } from "@/content/faq";

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
