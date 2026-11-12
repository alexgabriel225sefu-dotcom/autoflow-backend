/**
 * What a visitor reads on /terms, /privacy, /refunds and /tax.
 *
 * These pages used to print their own to-do list: bracket markers, and
 * template tokens in double braces. A visitor cannot act on either. The
 * owner's facts now live in lib/legal-facts.ts. A fact that is unset is
 * stated as missing in one plain sentence, and a fact that is set is shown.
 */
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LEGAL_FACTS,
  OWNER_FACT_REQUESTS,
  PLACEHOLDER_FACTS,
  hasFact,
  missingLegalFacts,
  type LegalFacts,
} from "@/lib/legal-facts";
import { DRAFT_NOTICE, PLACEHOLDERS } from "@/content/legal-publication";

const PAGES = ["terms", "privacy", "refunds", "tax"] as const;
type PageName = (typeof PAGES)[number];

/** Strings no visitor should ever be shown. */
const LEAKS = ["{{", "}}", "TO BE CONFIRMED", '"}]', "&quot;}]"];

async function render(page: PageName, facts?: Partial<LegalFacts>): Promise<string> {
  vi.resetModules();
  if (facts) {
    vi.doMock("@/lib/legal-facts", async (original) => {
      const actual = await original<typeof import("@/lib/legal-facts")>();
      return { ...actual, LEGAL_FACTS: { ...actual.LEGAL_FACTS, ...facts } };
    });
  }
  const mod = (await import(`./${page}/page.tsx`)) as { default: ComponentType };
  return renderToStaticMarkup(createElement(mod.default));
}

afterEach(() => {
  vi.doUnmock("@/lib/legal-facts");
  vi.resetModules();
});

const FILLED: LegalFacts = {
  productName: "Apex4Traders",
  siteUrl: "https://www.apex4traders.com",
  companyName: "Test Fixture Operator Ltd",
  registeredAddress: "1 Fixture Street, Testville",
  registrationNumber: "FIXTURE-REG-0001",
  vatNumber: "FIXTURE-VAT-0002",
  jurisdiction: "Fixtureland",
  governingLaw: "the law of Fixtureland",
  disputeForum: "the courts of Testville",
  supportEmail: "support@fixture.test",
  privacyEmail: "privacy@fixture.test",
  approvedVersionDate: "1 January 2099",
  retentionAccountData: "fixture-retention-accounts",
  retentionJournal: "fixture-retention-journal",
  retentionBrokerLinks: "fixture-retention-links",
  dataSubjectRights: "fixture-rights-statement",
  authProvider: "FixtureAuth",
  paymentProvider: "FixturePay",
  hostingProvider: "FixtureHost",
  emailProvider: "FixtureMail",
  dataRegion: "fixture-region",
  subProcessorList: "fixture-sub-processor-list",
  taxTreatment: "fixture-tax-treatment",
};

describe("the legal pages as a visitor reads them today", () => {
  it.each(PAGES)("/%s shows no bracket marker and no template token", async (page) => {
    const html = await render(page);
    for (const leak of LEAKS) expect(html, `/${page} shows ${leak}`).not.toContain(leak);
  });

  it.each(PAGES)("/%s says plainly what is missing, and that it is not final", async (page) => {
    const html = await render(page);
    expect(missingLegalFacts().length).toBeGreaterThan(0);
    expect(html).toContain("data-legal-pending=");
    expect(html).toMatch(/not (published|stated|decided|set) yet|not been (set|decided|approved)/);
    expect(html).toMatch(/not final/i);
  });

  it.each(["terms", "refunds", "tax"] as const)(
    "/%s is still an unpublished draft", async (page) => {
      expect(await render(page)).toContain(DRAFT_NOTICE);
    });

  it("the sources carry no marker or token for a later edit to print", () => {
    const files = [
      ...PAGES.map((p) => join(__dirname, p, "page.tsx")),
      join(__dirname, "..", "components", "legal", "draft-shell.tsx"),
      join(__dirname, "..", "components", "legal", "pending.tsx"),
      join(__dirname, "..", "lib", "legal-facts.ts"),
    ];
    for (const file of files) {
      const body = readFileSync(file, "utf8");
      expect(body, file).not.toContain("TO BE CONFIRMED");
      expect(body, file).not.toMatch(/\{\{[A-Z_]+\}\}/);
    }
  });
});

describe("the one place the owner's facts are entered", () => {
  it("states only what the repository can verify", () => {
    expect(LEGAL_FACTS.productName).toBe("Apex4Traders");
    expect(LEGAL_FACTS.siteUrl).toBe("https://www.apex4traders.com");
    expect(LEGAL_FACTS.authProvider).toBe("Supabase");
    expect(LEGAL_FACTS.paymentProvider).toBe("Stripe");
    // A data region is the owner's to state. No file here can verify one.
    expect(LEGAL_FACTS.dataRegion).toBeNull();
  });

  it("tells the owner what to supply for every field that can be unset", () => {
    for (const key of missingLegalFacts(
      Object.fromEntries(Object.keys(FILLED).map((k) => [k, null])) as unknown as LegalFacts,
    )) {
      expect(OWNER_FACT_REQUESTS[key], key).toMatch(/\w{3,}/);
    }
    expect(missingLegalFacts(FILLED)).toEqual([]);
  });

  it("maps every old placeholder token to a field", () => {
    expect(Object.keys(PLACEHOLDER_FACTS)).toEqual([...PLACEHOLDERS]);
    for (const key of Object.values(PLACEHOLDER_FACTS)) expect(FILLED).toHaveProperty(key);
  });

  it("treats an empty value or a pasted template token as unset", () => {
    expect(hasFact(null)).toBe(false);
    expect(hasFact("   ")).toBe(false);
    expect(hasFact("{{COMPANY_NAME}}")).toBe(false);
    expect(hasFact("[TO BE CONFIRMED]")).toBe(false);
    expect(hasFact("Fixture Ltd")).toBe(true);
  });
});

describe("filling a fact makes it appear", () => {
  const SHOWN: Record<PageName, (keyof LegalFacts)[]> = {
    terms: ["companyName", "registeredAddress", "registrationNumber", "vatNumber",
            "jurisdiction", "governingLaw", "disputeForum", "supportEmail",
            "approvedVersionDate"],
    privacy: ["companyName", "registeredAddress", "privacyEmail", "approvedVersionDate",
              "retentionAccountData", "retentionJournal", "retentionBrokerLinks",
              "dataSubjectRights", "authProvider", "paymentProvider", "hostingProvider",
              "emailProvider", "dataRegion", "subProcessorList"],
    refunds: ["companyName", "registeredAddress", "registrationNumber", "vatNumber",
              "jurisdiction", "supportEmail", "approvedVersionDate"],
    tax: ["companyName", "vatNumber", "jurisdiction", "taxTreatment",
          "approvedVersionDate"],
  };

  it.each(PAGES)("/%s shows every supplied value and nothing pending", async (page) => {
    const html = await render(page, FILLED);
    for (const key of SHOWN[page]) {
      expect(html, `/${page} does not show ${key}`).toContain(FILLED[key] as string);
    }
    expect(html).not.toContain("data-legal-pending=");
    for (const leak of LEAKS) expect(html).not.toContain(leak);
  });

  it("one supplied fact appears while the rest stay stated as missing", async () => {
    const html = await render("terms", { companyName: "Solo Fixture Ltd" });
    expect(html).toContain("Solo Fixture Ltd");
    expect(html).toContain("data-legal-pending=");
    expect(html).not.toContain("No company is registered");
  });

  it("supplying facts does not publish the documents", async () => {
    for (const page of ["terms", "refunds", "tax"] as const) {
      expect(await render(page, FILLED)).toContain(DRAFT_NOTICE);
    }
  });
});
