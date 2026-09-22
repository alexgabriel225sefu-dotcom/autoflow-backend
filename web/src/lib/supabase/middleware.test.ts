import { describe, expect, it } from "vitest";
import { isPublic } from "./middleware";

/**
 * Route protection is convenience, not authorisation — every endpoint
 * re-checks the session and ownership server-side. What these check is that
 * the convenience does not accidentally expose an app screen to a visitor
 * with no session, which would fill with 401s and look broken.
 */
describe("route protection", () => {
  it("lets a signed-out visitor see the public pages", () => {
    for (const p of ["/", "/login", "/signup", "/auth/confirm", "/auth/reset", "/terms"]) {
      expect(isPublic(p)).toBe(true);
    }
  });

  it("keeps every app screen behind a session", () => {
    for (const p of [
      "/dashboard", "/rules", "/rules/new", "/rules/abc", "/positions",
      "/orders", "/journal", "/notifications", "/accounts", "/connect",
      "/license", "/settings",
    ]) {
      expect(isPublic(p)).toBe(false);
    }
  });

  it("does not treat a lookalike path as public", () => {
    // "/loginsomething" must not inherit "/login"'s exemption.
    expect(isPublic("/loginx")).toBe(false);
    expect(isPublic("/signup-admin")).toBe(false);
  });
});
