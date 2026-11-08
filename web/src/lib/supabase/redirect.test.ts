import { describe, expect, it } from "vitest";
import { authCallbackUrl, canonicalWebOrigin, CANONICAL_WEB_ORIGIN } from "./redirect";

describe("auth redirect origin", () => {
  it("keeps local development on its own origin", () => {
    expect(canonicalWebOrigin("http://localhost:3000")).toBe("http://localhost:3000");
    expect(authCallbackUrl("http://localhost:3000", { recovery: true }))
      .toBe("http://localhost:3000/auth/callback?mode=recovery");
  });

  it("sends hosted confirmation links to the public product origin", () => {
    expect(canonicalWebOrigin("https://apex4traders-web.onrender.com"))
      .toBe(CANONICAL_WEB_ORIGIN);
    expect(authCallbackUrl("https://preview.example.test", { next: "/connect" }))
      .toBe("https://www.apex4traders.com/auth/callback?next=%2Fconnect");
  });
});
