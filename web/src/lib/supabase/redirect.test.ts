import { describe, expect, it } from "vitest";
import { authCallbackUrl, canonicalWebOrigin, CANONICAL_WEB_ORIGIN } from "./redirect";

describe("auth redirect origin", () => {
  it("keeps local development on its own origin", () => {
    expect(canonicalWebOrigin("http://localhost:3000")).toBe("http://localhost:3000");
    expect(authCallbackUrl("http://localhost:3000", { recovery: true }))
      .toBe("http://localhost:3000/auth/callback?mode=recovery");
  });

  it("sends an unknown host (a preview deployment) to the public product origin", () => {
    expect(canonicalWebOrigin("https://preview.example.test")).toBe(CANONICAL_WEB_ORIGIN);
    expect(canonicalWebOrigin("http://www.apex4traders.com")).toBe(CANONICAL_WEB_ORIGIN);
    expect(authCallbackUrl("https://preview.example.test", { next: "/connect" }))
      .toBe("https://www.apex4traders.com/auth/callback?next=%2Fconnect");
  });

  it("keeps a flow on the product host that started it (PKCE verifier cookie)", () => {
    // Rewriting these to www sends the browser back without the verifier.
    expect(canonicalWebOrigin("https://apex4traders-web.onrender.com"))
      .toBe("https://apex4traders-web.onrender.com");
    expect(authCallbackUrl("https://apex4traders-web.onrender.com", { recovery: true }))
      .toBe("https://apex4traders-web.onrender.com/auth/callback?mode=recovery");
    expect(canonicalWebOrigin("https://apex4traders.com")).toBe("https://apex4traders.com");
    expect(canonicalWebOrigin(CANONICAL_WEB_ORIGIN)).toBe(CANONICAL_WEB_ORIGIN);
  });

  it("does not trust a look-alike host", () => {
    expect(canonicalWebOrigin("https://apex4traders.com.evil.example")).toBe(CANONICAL_WEB_ORIGIN);
    expect(canonicalWebOrigin("https://www.apex4traders.com@evil.example")).toBe(CANONICAL_WEB_ORIGIN);
  });
});
