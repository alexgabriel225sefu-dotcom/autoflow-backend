import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * What a search engine may read. The public pages are open; every screen of
 * the product itself sits behind a sign-in and has nothing to index, so those
 * are closed off rather than left to be crawled into a login redirect.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/", "/pricing", "/faq", "/guide/test-a-rule-on-demo", "/signup", "/login"],
      disallow: [
        "/api/", "/auth/", "/admin/", "/dashboard", "/trade", "/accounts",
        "/connect", "/journal", "/license", "/live", "/notifications",
        "/orders", "/performance", "/replay", "/backtest", "/forward",
        "/risk", "/incidents", "/health", "/rule-layer", "/overfit",
        "/trades", "/positions", "/rules", "/settings", "/help",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
