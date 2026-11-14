import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import sitemap from "./sitemap";
import robots from "./robots";
import { isPublic } from "@/lib/supabase/middleware";
import { SITE_URL } from "@/lib/site";
import { FAQ_ITEMS } from "@/content/faq";
import { GUIDE_STEPS } from "@/content/guide";
import { faqPageLd, jsonLdString } from "@/lib/json-ld";
import { metadata as faqMeta } from "./faq/page";
import { metadata as guideMeta } from "./guide/test-a-rule-on-demo/page";
import FaqPage from "./faq/page";
import GuidePage from "./guide/test-a-rule-on-demo/page";

const PATHS = ["/faq", "/guide/test-a-rule-on-demo"];

describe("public content pages", () => {
  it.each(PATHS)("%s is public, in the sitemap and allowed by robots", (p) => {
    expect(isPublic(p)).toBe(true);
    expect(sitemap().map((e) => e.url)).toContain(`${SITE_URL}${p}`);
    const rules = robots().rules as { allow: string[]; disallow: string[] };
    expect(rules.allow).toContain(p);
    expect(rules.disallow).not.toContain(p);
  });

  it("each page has its own canonical, title, description and openGraph", () => {
    const pairs: [typeof faqMeta, string][] = [
      [faqMeta, "/faq"],
      [guideMeta, "/guide/test-a-rule-on-demo"],
    ];
    for (const [m, path] of pairs) {
      expect(m.alternates?.canonical).toBe(path);
      expect(String(m.title).length).toBeGreaterThan(10);
      expect(String(m.description).length).toBeGreaterThan(50);
      expect(m.openGraph?.title).toBe(m.title);
    }
    expect(faqMeta.title).not.toBe(guideMeta.title);
  });

  it("each page has exactly one h1 and links to /signup and /pricing", () => {
    for (const Page of [FaqPage, GuidePage]) {
      const html = renderToStaticMarkup(createElement(Page));
      expect(html.match(/<h1[ >]/g)?.length).toBe(1);
      expect(html).toContain('href="/signup"');
      expect(html).toContain('href="/pricing"');
    }
  });
});

describe("FAQPage JSON-LD", () => {
  it("is built from the same array that renders the page", () => {
    const ld = faqPageLd();
    expect(ld["@type"]).toBe("FAQPage");
    expect(ld.mainEntity.map((q) => q.name)).toEqual(FAQ_ITEMS.map((q) => q.question));
    const html = renderToStaticMarkup(createElement(FaqPage));
    for (const q of ld.mainEntity) {
      expect(html).toContain(q.name.replace(/'/g, "&#x27;"));
    }
    expect(html).toContain('type="application/ld+json"');
    expect(FAQ_ITEMS.length).toBeGreaterThanOrEqual(8);
  });

  it("escapes < so the payload cannot close the script tag", () => {
    const out = jsonLdString({ a: "</script><b>" });
    expect(out).not.toContain("<");
    expect(out).toContain("\\u003c");
  });
});

describe("copy rules for the new pages", () => {
  const copy = [
    ...FAQ_ITEMS.flatMap((i) => [i.question, i.answer]),
    ...GUIDE_STEPS.flatMap((s) => [s.title, s.body]),
  ].join("\n");

  it.each([
    [/guaranteed/i, "guaranteed"],
    [/risk[-\s]?free/i, "risk-free"],
    [/crypto/i, "crypto"],
    [/\bMT[45]\b|metatrader/i, "MT4/MT5"],
    [/\bbots?\b/i, "bot"],
    [/[$€£]\s?\d|\b\d+\s?(usd|eur|gbp)\b/i, "a price"],
    [/profit/i, "profit"],
  ])("does not contain %s", (pattern) => {
    expect(copy).not.toMatch(pattern);
  });

  it("states that live trading is not available", () => {
    expect(copy).toMatch(/live trading is not available in this release/i);
  });
});
