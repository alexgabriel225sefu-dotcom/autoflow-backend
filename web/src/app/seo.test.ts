import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import robots from "./robots";
import sitemap from "./sitemap";
import { config } from "../middleware";
import { SITE_URL } from "@/lib/site";

/** Whether the middleware's matcher would run for this path. */
function runsFor(path: string): boolean {
  const re = new RegExp(`^${config.matcher[0]}$`);
  return re.test(path);
}

describe("search engines can read the site", () => {
  it("robots.txt and sitemap.xml are not behind the sign-in", () => {
    // They were answered with a redirect to /login, so a crawler could not
    // read what it may index.
    expect(runsFor("/robots.txt")).toBe(false);
    expect(runsFor("/sitemap.xml")).toBe(false);
    // The matcher still guards the app and the landing page.
    expect(runsFor("/dashboard")).toBe(true);
    expect(runsFor("/")).toBe(true);
  });

  it("robots points at the sitemap on the one public origin", () => {
    const r = robots();
    expect(r.sitemap).toBe(`${SITE_URL}/sitemap.xml`);
    expect(SITE_URL).toBe("https://www.apex4traders.com");
  });

  it("robots keeps the product screens and the API out of search", () => {
    const rules = robots().rules as { allow: string[]; disallow: string[] };
    for (const p of ["/api/", "/dashboard", "/connect", "/accounts", "/rules"]) {
      expect(rules.disallow).toContain(p);
    }
    expect(rules.allow).toContain("/");
  });

  it("the sitemap lists the public pages and no unpublished legal draft", () => {
    const urls = sitemap().map((e) => e.url);
    expect(urls).toContain(`${SITE_URL}/`);
    expect(urls).toContain(`${SITE_URL}/pricing`);
    for (const legal of ["/terms", "/refunds", "/tax", "/privacy"]) {
      expect(urls).not.toContain(`${SITE_URL}${legal}`);
    }
  });
});

describe("link previews on phones", () => {
  it("the root layout declares a large preview image and the summary card", () => {
    const src = readFileSync(join(__dirname, "layout.tsx"), "utf8");
    expect(src).toMatch(/images: \[\{ url: "\/og-image\.png", width: 1200, height: 630/);
    expect(src).toMatch(/card: "summary_large_image"/);
    expect(src).toMatch(/images: \["\/og-image\.png"\]/);
  });

  it("the preview image is in the repo and is a 1200x630 PNG", () => {
    const buf = readFileSync(join(__dirname, "../../public/og-image.png"));
    expect(buf.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
    expect(buf.readUInt32BE(16)).toBe(1200);
    expect(buf.readUInt32BE(20)).toBe(630);
  });
});
