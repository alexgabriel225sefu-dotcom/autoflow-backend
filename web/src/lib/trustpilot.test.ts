import { afterEach, describe, expect, it } from "vitest";
import { contentSecurityPolicy } from "../../next.config";
import { trustpilotConfig, trustpilotLinks } from "./trustpilot";

const KEYS = [
  "NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID",
  "NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID",
  "NEXT_PUBLIC_TRUSTPILOT_DOMAIN",
] as const;

afterEach(() => {
  for (const k of KEYS) delete process.env[k];
});

describe("trustpilotConfig", () => {
  it("is off until both ids are set, so no stars can appear that Trustpilot did not issue", () => {
    expect(trustpilotConfig({})).toBeNull();
    expect(trustpilotConfig({ NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID: "5f1a2b3c4d5e6f7a8b9c0d1e" })).toBeNull();
    expect(trustpilotConfig({ NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID: "5419b6a8b0d04a076446a9ad" })).toBeNull();
  });

  it("rejects ids that are not plain identifiers", () => {
    expect(trustpilotConfig({
      NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID: '"><script>',
      NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID: "5419b6a8b0d04a076446a9ad",
    })).toBeNull();
  });

  it("builds the profile and the write-a-review links for the domain", () => {
    const c = trustpilotConfig({
      NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID: "5f1a2b3c4d5e6f7a8b9c0d1e",
      NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID: "5419b6a8b0d04a076446a9ad",
    });
    expect(c?.profileUrl).toBe("https://www.trustpilot.com/review/apex4traders.com");
    expect(c?.reviewUrl).toBe("https://www.trustpilot.com/evaluate/apex4traders.com");
  });

  it("takes only the host from a configured domain", () => {
    const c = trustpilotConfig({
      NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID: "5f1a2b3c4d5e6f7a8b9c0d1e",
      NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID: "5419b6a8b0d04a076446a9ad",
      NEXT_PUBLIC_TRUSTPILOT_DOMAIN: "https://www.example.test/some/path",
    });
    expect(c?.profileUrl).toBe("https://www.trustpilot.com/review/www.example.test");
  });
});

describe("trustpilotLinks", () => {
  it("gives the profile and write-a-review links with no ids, no script and no plan", () => {
    expect(trustpilotLinks({})).toEqual({
      profileUrl: "https://www.trustpilot.com/review/apex4traders.com",
      reviewUrl: "https://www.trustpilot.com/evaluate/apex4traders.com",
    });
  });
});

describe("the Content-Security-Policy and Trustpilot", () => {
  it("names no Trustpilot host and keeps frame-src 'none' when it is not configured", () => {
    const csp = contentSecurityPolicy();
    expect(csp).not.toContain("trustpilot");
    expect(csp).toContain("frame-src 'none'");
  });

  it("opens exactly the Trustpilot hosts when it is configured", () => {
    process.env.NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID = "5f1a2b3c4d5e6f7a8b9c0d1e";
    process.env.NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID = "5419b6a8b0d04a076446a9ad";
    const csp = contentSecurityPolicy();
    expect(csp).toContain("script-src 'self' 'unsafe-inline' 'unsafe-eval' https://widget.trustpilot.com");
    expect(csp).toContain("frame-src https://widget.trustpilot.com https://*.trustpilot.com");
    expect(csp).toContain("img-src 'self' data: blob: https://*.trustpilot.com");
    expect(csp).not.toContain("frame-src 'none'");
    // Only the framing and the scripts of the public page change: nothing else is relaxed.
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
  });
});
