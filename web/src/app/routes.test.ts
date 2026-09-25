/**
 * Route audit: every page is in exactly one protection class, on purpose.
 *
 * WHAT GOES WRONG WITHOUT THIS
 *
 * Protection comes from `PUBLIC_PATHS` in the auth middleware, which denies by
 * default — a page added under `(app)/` is protected because it is absent from
 * that list. That is the right default, and it makes the failure quiet in the
 * other direction: a page that SHOULD be public is gated, and nothing complains
 * until somebody reports a login wall.
 *
 * That happened. `/configurator` is the return URL the previous checkout used,
 * kept so that a paid customer following an old receipt lands somewhere sensible
 * rather than on a 404. It was not in `PUBLIC_PATHS`, so those visitors were
 * redirected to a login page for an account they do not have — the exact
 * failure the page exists to prevent.
 *
 * So this walks the filesystem and requires every route to be declared here.
 * A new page fails this test until somebody says which class it is in, and that
 * is the whole point: the decision gets made rather than inherited.
 */
import { describe, it, expect } from "vitest";
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { PUBLIC_PATHS, isPublic } from "@/lib/supabase/middleware";

const APP = join(__dirname);

/** Filesystem route -> URL path, dropping Next's `(group)` segments. */
function routes(dir = APP, prefix = ""): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      // A (group) does not appear in the URL.
      const seg = /^\(.*\)$/.test(entry) ? prefix : `${prefix}/${entry}`;
      out.push(...routes(full, seg));
    } else if (entry === "page.tsx") {
      out.push(prefix === "" ? "/" : prefix);
    }
  }
  return out;
}

/**
 * Every route, and why it is in the class it is in.
 *
 * PUBLIC means a signed-out visitor must be able to load it. PROTECTED means
 * the middleware must redirect a signed-out visitor to /login.
 */
const EXPECTED: Record<string, "public" | "protected"> = {
  "/": "public",                      // landing page
  "/login": "public",
  "/signup": "public",
  "/terms": "public",                 // has to be readable before signing up
  "/privacy": "public",               // same
  "/auth/callback": "public",         // arrives from the identity provider
  "/auth/confirm": "public",          // arrives from a confirmation e-mail
  "/auth/reset": "public",            // arrives from a reset e-mail
  "/configurator": "public",          // arrives from an OLD receipt, no session

  "/dashboard": "protected",
  "/accounts": "protected",
  "/connect": "protected",
  "/journal": "protected",
  "/license": "protected",
  "/notifications": "protected",
  "/orders": "protected",
  "/positions": "protected",
  "/rules": "protected",
  "/rules/new": "protected",
  "/rules/[id]": "protected",
  "/settings": "protected",
};

const FOUND = routes().sort();

describe("every route is classified deliberately", () => {
  it("no route exists that this audit has never been told about", () => {
    const unknown = FOUND.filter((r) => !(r in EXPECTED));
    expect(
      unknown,
      `add these to EXPECTED and decide whether each is public or protected: ` +
        `${unknown.join(", ")}`,
    ).toEqual([]);
  });

  it("no route is declared here that no longer exists", () => {
    // A stale entry is a decision about a page nobody can reach.
    const missing = Object.keys(EXPECTED).filter((r) => !FOUND.includes(r));
    expect(missing, `stale entries: ${missing.join(", ")}`).toEqual([]);
  });
});

describe("the middleware agrees with the classification", () => {
  for (const [route, want] of Object.entries(EXPECTED)) {
    it(`${route} is ${want}`, () => {
      // `[id]` is a placeholder in the filesystem; test a concrete instance,
      // because that is what a request carries.
      const path = route.replace("[id]", "some-rule-id");
      expect(
        isPublic(path),
        want === "public"
          ? `${route} should be reachable without a session but the ` +
            `middleware gates it — add it to PUBLIC_PATHS`
          : `${route} is reachable without a session — remove it from ` +
            `PUBLIC_PATHS`,
      ).toBe(want === "public");
    });
  }
});

describe("the public list itself stays honest", () => {
  it("every entry in PUBLIC_PATHS is a route that exists", () => {
    // An entry for a page that does not exist is a hole waiting for a page to
    // be created at that path.
    const ghosts = PUBLIC_PATHS.filter((p) => !FOUND.includes(p));
    expect(ghosts, `PUBLIC_PATHS names non-existent routes: ${ghosts}`)
      .toEqual([]);
  });

  it("the protected routes are the majority, or the default has inverted", () => {
    const protectedCount = Object.values(EXPECTED).filter(
      (v) => v === "protected",
    ).length;
    expect(protectedCount).toBeGreaterThan(PUBLIC_PATHS.length);
  });

  it("a path is not made public by prefix accident", () => {
    // isPublic matches `p` or `${p}/`. "/" must not therefore make everything
    // public, which a naive startsWith would.
    expect(isPublic("/dashboard")).toBe(false);
    expect(isPublic("/loginsomething")).toBe(false);
    expect(isPublic("/termsandconditions")).toBe(false);
    expect(isPublic("/auth/confirm/extra")).toBe(true); // a real sub-path
  });
});
