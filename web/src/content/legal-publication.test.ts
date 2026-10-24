import { describe, expect, it } from "vitest";
import {
  DRAFT_NOTICE,
  LEGAL_VERSION,
  PLACEHOLDERS,
  legalPublished,
} from "./legal-publication";

describe("legal publication stays off", () => {
  it("is unpublished when the variable is missing or not this version", () => {
    expect(legalPublished({})).toBe(false);
    expect(legalPublished({ A4T_LEGAL_PUBLISH: "" })).toBe(false);
    expect(legalPublished({ A4T_LEGAL_PUBLISH: "true" })).toBe(false);
    expect(legalPublished({ A4T_LEGAL_PUBLISH: "1" })).toBe(false);
    expect(legalPublished({ A4T_LEGAL_PUBLISH: "2020-01-01" })).toBe(false);
  });

  it("publishes only when the variable is exactly this draft version", () => {
    expect(legalPublished({ A4T_LEGAL_PUBLISH: LEGAL_VERSION })).toBe(true);
    expect(legalPublished({ A4T_LEGAL_PUBLISH: `  ${LEGAL_VERSION}  ` })).toBe(true);
  });

  it("marks the draft in words a reader can see", () => {
    expect(DRAFT_NOTICE).toBe("DRAFT - requires legal review");
  });

  it("names the placeholders the owner still has to fill", () => {
    expect(PLACEHOLDERS).toEqual([
      "COMPANY_NAME",
      "REGISTRATION_NUMBER",
      "ADDRESS",
      "JURISDICTION",
      "VAT",
    ]);
  });
});
