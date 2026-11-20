import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * The pages a visitor can open without an account and that say something
 * about the product. The legal pages are left out on purpose: they stay
 * unpublished drafts until the owner publishes them, and a draft should not
 * be what a search result shows.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/pricing`, changeFrequency: "monthly", priority: 0.7 },
    { url: `${SITE_URL}/faq`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/guide/test-a-rule-on-demo`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/signup`, changeFrequency: "monthly", priority: 0.6 },
  ];
}
