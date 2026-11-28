import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { ARTICLES, articleBySlug, articlePath } from "@/content/articles";
import { articleFaqLd, articleLd, breadcrumbLd, guideHubLd } from "@/lib/json-ld";
import { llmsFullTxt, llmsTxt } from "@/lib/llms";
import { SITE_URL } from "@/lib/site";
import { isPublic } from "@/lib/supabase/middleware";
import sitemap from "./sitemap";
import robots from "./robots";
import GuideHub, { metadata as hubMeta } from "./guide/page";
import GuideArticlePage, { generateMetadata, generateStaticParams, dynamicParams } from "./guide/[slug]/page";
import { GET as getLlms } from "./llms.txt/route";
import { GET as getLlmsFull } from "./llms-full.txt/route";

const words = (s: string) => s.trim().split(/\s+/).length;

describe("the guide articles are well formed", () => {
  it("has at least six articles with unique slugs", () => {
    expect(ARTICLES.length).toBeGreaterThanOrEqual(6);
    expect(new Set(ARTICLES.map((a) => a.slug)).size).toBe(ARTICLES.length);
    for (const a of ARTICLES) expect(a.slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
  });

  it.each(ARTICLES.map((a) => [a.slug, a] as const))("%s: answer first, sized for search and for assistants", (_s, a) => {
    expect(a.title.length).toBeLessThanOrEqual(70);
    expect(a.description.length).toBeGreaterThanOrEqual(100);
    expect(a.description.length).toBeLessThanOrEqual(175);
    // The direct answer comes first and is short enough to be quoted whole.
    expect(words(a.summary)).toBeGreaterThanOrEqual(40);
    expect(words(a.summary)).toBeLessThanOrEqual(75);
    expect(a.published).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(a.updated >= a.published).toBe(true);
    expect(a.sections.length).toBeGreaterThanOrEqual(4);
    expect(a.faq.length).toBeGreaterThanOrEqual(3);
    expect(a.keywords.length).toBeGreaterThanOrEqual(3);
    expect(a.readingMinutes).toBeGreaterThan(0);
  });

  it("every related slug exists and none points at itself", () => {
    for (const a of ARTICLES) {
      expect(a.related.length).toBeGreaterThan(0);
      for (const r of a.related) {
        expect(articleBySlug(r), `${a.slug} -> ${r}`).toBeTruthy();
        expect(r).not.toBe(a.slug);
      }
    }
  });

  it("titles and descriptions are not reused", () => {
    expect(new Set(ARTICLES.map((a) => a.title)).size).toBe(ARTICLES.length);
    expect(new Set(ARTICLES.map((a) => a.description)).size).toBe(ARTICLES.length);
  });

  it("each article states the demo-only limit and the risk, in its own text or page", () => {
    // The page adds the risk warning; the article text must not contradict it.
    for (const a of ARTICLES) {
      const text = JSON.stringify(a).toLowerCase();
      expect(text, a.slug).not.toMatch(/live trading is (open|available now)/);
      expect(text, a.slug).not.toMatch(/guarantee[sd]? (a )?(profit|returns?|income)/);
    }
  });
});

describe("the pages", () => {
  it("the hub lists the existing guide and every article, with one h1", () => {
    const html = renderToStaticMarkup(createElement(GuideHub));
    expect(html.match(/<h1[ >]/g)?.length).toBe(1);
    expect(html).toContain('href="/guide/test-a-rule-on-demo"');
    for (const a of ARTICLES) expect(html).toContain(`href="${articlePath(a.slug)}"`);
    expect(html).toContain("Risk warning");
    expect(html).toContain('href="/signup"');
    expect(html).toContain('href="/pricing"');
    expect(hubMeta.alternates?.canonical).toBe("/guide");
  });

  it.each(ARTICLES.map((a) => [a.slug, a] as const))("%s renders answer-first with structured data", async (_s, a) => {
    const el = await GuideArticlePage({ params: Promise.resolve({ slug: a.slug }) });
    const html = renderToStaticMarkup(el);
    expect(html.match(/<h1[ >]/g)?.length).toBe(1);
    expect(html.indexOf("Short answer")).toBeGreaterThan(-1);
    // The answer sits before the first section heading.
    expect(html.indexOf("Short answer")).toBeLessThan(html.indexOf("<h2"));
    expect(html).toContain(`dateTime="${a.updated}"`);
    expect(html.match(/application\/ld\+json/g)?.length).toBe(3);
    expect(html).toContain("Risk warning");
    expect(html).toContain("About Apex4Traders");
    expect(html).toContain('href="/signup"');
    expect(html).toContain('href="/pricing"');
    for (const s of a.sections) expect(html).toContain(`<h2>${s.heading.replace(/'/g, "&#x27;")}</h2>`);
    for (const t of a.sections.flatMap((s) => (s.table ? [s.table] : []))) {
      expect(html).toContain("<caption>");
      expect(html).toContain(`<th scope="col">${t.head[0]}</th>`);
    }
  });

  it("each article has its own canonical, title, description and article openGraph", async () => {
    const seen = new Set<string>();
    for (const a of ARTICLES) {
      const m = await generateMetadata({ params: Promise.resolve({ slug: a.slug }) });
      expect(m.alternates?.canonical).toBe(articlePath(a.slug));
      expect(m.title).toBe(a.title);
      expect(m.description).toBe(a.description);
      expect((m.openGraph as { type?: string }).type).toBe("article");
      expect(m.openGraph?.title).toBe(m.title);
      seen.add(String(m.title));
    }
    expect(seen.size).toBe(ARTICLES.length);
  });

  it("only the listed slugs exist", async () => {
    expect(dynamicParams).toBe(false);
    expect(generateStaticParams().map((p) => p.slug)).toEqual(ARTICLES.map((a) => a.slug));
    expect(await generateMetadata({ params: Promise.resolve({ slug: "nope" }) })).toEqual({});
  });
});

describe("structured data", () => {
  const a = ARTICLES[0];

  it("Article carries dates, an organisation author, a publisher logo and a canonical id", () => {
    const ld = articleLd(a);
    expect(ld["@type"]).toBe("Article");
    expect(ld.headline).toBe(a.title);
    expect(ld.datePublished).toBe(a.published);
    expect(ld.dateModified).toBe(a.updated);
    expect(ld.author["@type"]).toBe("Organization");
    expect(ld.publisher.logo.url).toBe(`${SITE_URL}/apex4traders-logo.png`);
    expect(ld.mainEntityOfPage["@id"]).toBe(`${SITE_URL}${articlePath(a.slug)}`);
  });

  it("the article FAQ is the visible FAQ", () => {
    const ld = articleFaqLd(a);
    expect(ld.mainEntity.map((q) => q.name)).toEqual(a.faq.map((q) => q.question));
    expect(ld.mainEntity.map((q) => q.acceptedAnswer.text)).toEqual(a.faq.map((q) => q.answer));
  });

  it("breadcrumbs are numbered from 1 and absolute", () => {
    const ld = breadcrumbLd([{ name: "Home", path: "/" }, { name: "Guides", path: "/guide" }]);
    expect(ld.itemListElement.map((i) => i.position)).toEqual([1, 2]);
    expect(ld.itemListElement[1].item).toBe(`${SITE_URL}/guide`);
  });

  it("the hub item list names every article in order", () => {
    const ld = guideHubLd();
    expect(ld.mainEntity.itemListElement.map((i) => i.url)).toEqual(
      ARTICLES.map((x) => `${SITE_URL}${articlePath(x.slug)}`),
    );
  });
});

describe("search engines and assistants can find them", () => {
  it("the hub and every article are public, in the sitemap with a date, and allowed by robots", () => {
    const entries = sitemap();
    const urls = entries.map((e) => e.url);
    const rules = robots().rules as { allow: string[]; disallow: string[] };
    for (const p of ["/guide", ...ARTICLES.map((x) => articlePath(x.slug))]) {
      expect(isPublic(p), p).toBe(true);
      expect(urls, p).toContain(`${SITE_URL}${p}`);
      expect(rules.disallow.some((d) => p.startsWith(d)), p).toBe(false);
    }
    expect(rules.allow).toContain("/guide");
    for (const x of ARTICLES) {
      const e = entries.find((s) => s.url === `${SITE_URL}${articlePath(x.slug)}`);
      expect(e?.lastModified).toBe(x.updated);
    }
  });

  it("llms.txt lists the product facts and every article URL", () => {
    const t = llmsTxt();
    expect(t.startsWith("# Apex4Traders")).toBe(true);
    expect(t).toContain("demo accounts only");
    expect(t).toContain("never takes custody");
    for (const x of ARTICLES) expect(t).toContain(`${SITE_URL}${articlePath(x.slug)}`);
    expect(t).toContain(`${SITE_URL}/llms-full.txt`);
  });

  it("llms-full.txt carries every article's answer and every FAQ question", () => {
    const t = llmsFullTxt();
    for (const x of ARTICLES) {
      expect(t).toContain(`# ${x.title}`);
      expect(t).toContain(x.summary);
      for (const q of x.faq) expect(t).toContain(q.question);
    }
    expect(t).toContain("| ---");
  });

  it("both files are served as plain text", async () => {
    for (const get of [getLlms, getLlmsFull]) {
      const res = get();
      expect(res.headers.get("content-type")).toContain("text/plain");
      expect((await res.text()).length).toBeGreaterThan(500);
    }
  });
});
