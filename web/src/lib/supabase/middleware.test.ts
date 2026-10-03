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

/**
 * Where a signed-out visitor is sent back to after signing in.
 *
 * WHY THIS MATTERS HERE, OF ALL PLACES
 *
 * The cTrader callback sends people to /connect?n=<nonce>. cTrader was opened
 * in a NEW tab, so that tab's sessionStorage is empty and the ?n= is the only
 * copy of which attempt this is. If the session has lapsed during the round
 * trip — which is exactly when a broker connection takes longest — the
 * middleware bounces them to /login, and if `next` carries only the pathname
 * the nonce is gone for good. They come back to a page offering to start
 * over, having already approved at cTrader.
 *
 * The obvious fix, putting the whole URL in `next`, is also how an open
 * redirect gets built: `next` is client-controllable and the login page
 * pushes it. So both halves are checked — it must carry the query, and it
 * must refuse to leave this origin.
 */
import { nextTarget, safeNext } from "./middleware";

describe("signing in returns you to where you were going", () => {
  it("keeps the query string, not just the path", () => {
    expect(safeNext("/connect?n=abc123")).toBe("/connect?n=abc123");
  });

  it("which is what stops a broker connection being lost at the last step", () => {
    const back = safeNext("/connect?n=rIeFVSuL7_7GOW5NvO5Kuj75X3LmGAAB");
    expect(back).toContain("n=rIeFVSuL7_7GOW5NvO5Kuj75X3LmGAAB");
  });

  it("allows an ordinary path with no query", () => {
    expect(safeNext("/journal")).toBe("/journal");
  });
});

describe("but it cannot be used to send somebody off the site", () => {
  it("refuses an absolute URL", () => {
    expect(safeNext("https://evil.example/phish")).toBe("/dashboard");
    expect(safeNext("http://evil.example")).toBe("/dashboard");
  });

  it("refuses a protocol-relative URL, which a naive check misses", () => {
    // "//evil.example" starts with "/" and is still off-site. A check that
    // only asks "does it start with a slash" lets this through.
    expect(safeNext("//evil.example/phish")).toBe("/dashboard");
    expect(safeNext("/\\evil.example")).toBe("/dashboard");
  });

  it("refuses anything that is not a path at all", () => {
    for (const bad of ["javascript:alert(1)", "", "   ", "dashboard",
                       "data:text/html,<script>"]) {
      expect(safeNext(bad)).toBe("/dashboard");
    }
  });

  it("refuses a null or missing value", () => {
    expect(safeNext(null)).toBe("/dashboard");
    expect(safeNext(undefined)).toBe("/dashboard");
  });

  it("does not let a crafted query smuggle a scheme", () => {
    expect(safeNext("/connect?next=https://evil.example"))
      .toBe("/connect?next=https://evil.example");   // still same-origin
  });
});

describe("the string that actually goes into next=", () => {
  // safeNext() was correct while the middleware threw the query away before
  // calling it, so these test the join, which is where the bug lived.
  it("joins the path and the query the browser arrived with", () => {
    expect(nextTarget("/connect", "?n=abc123")).toBe("/connect?n=abc123");
  });

  it("handles a path with no query", () => {
    expect(nextTarget("/journal", "")).toBe("/journal");
    expect(nextTarget("/journal", undefined)).toBe("/journal");
  });

  it("still refuses to leave the origin", () => {
    expect(nextTarget("//evil.example", "?x=1")).toBe("/dashboard");
  });

  it("and the middleware uses it rather than the bare pathname", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "middleware.ts"), "utf8");
    // Matched as a CALL with both arguments: the failure being guarded
    // against is passing the pathname alone.
    expect(src).toMatch(/nextTarget\(\s*pathname\s*,\s*request\.nextUrl\.search\s*\)/);
    expect(src).not.toMatch(/set\("next",\s*pathname\s*\)/);
  });
});
