/**
 * The public terms and refunds pages state the decided rule.
 * They must not still say that whether a refund exists is unconfirmed.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import TermsPage from "@/app/terms/page";
import RefundsPage from "@/app/refunds/page";
import {
  DEMO_CONDITIONS_NOTE,
  DURABLE_MEDIUM,
  PURCHASE_NOTE,
  WITHDRAWAL_CONSENT_LABEL,
} from "@/content/refund-policy";

const PY = readFileSync(
  join(__dirname, "..", "..", "..", "apex-forex-bot", "apex", "platform", "refund_policy.py"),
  "utf8",
);

describe("the server and the pages use one refund rule", () => {
  it("keeps the Python sentences identical to the web copy", () => {
    for (const sentence of [
      PURCHASE_NOTE, DEMO_CONDITIONS_NOTE, WITHDRAWAL_CONSENT_LABEL, DURABLE_MEDIUM,
      "2026-11-09",
    ]) {
      expect(PY, sentence).toContain(sentence);
    }
  });

  it.each([
    ["terms", TermsPage],
    ["refunds", RefundsPage],
  ])("the %s page states the final rule and the waiver", (_name, Page) => {
    const html = renderToStaticMarkup(createElement(Page));
    expect(html).toContain(PURCHASE_NOTE);
    expect(html).toContain(DEMO_CONDITIONS_NOTE);
    expect(html).toContain(WITHDRAWAL_CONSENT_LABEL);
    expect(html).toContain("2011/83/EU");
    expect(html).toContain("article 16(m)");
    expect(html).toContain("The free 14-day demo is the trial.");
    expect(html).not.toMatch(/identical to live/i);
    expect(html).not.toContain("TO BE CONFIRMED — refund");
    expect(html).not.toContain("TO BE CONFIRMED — whether a customer may request a refund");
    expect(html).not.toMatch(/refund policy is a draft/i);
    // Company identity is still unfinished. That is not the refund rule.
    expect(html).toContain("TO BE CONFIRMED");
    expect(html).toContain("not final");
  });
});
