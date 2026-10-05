/**
 * Dependency and build-configuration invariants.
 *
 * WHY THESE ARE TESTS AND NOT A CI STEP ALONE
 *
 * `npm audit` needs the network, so it belongs in release verification rather
 * than in a unit suite that has to pass offline and deterministically. What
 * CAN be asserted offline is the floor: the versions below are the ones that
 * fixed specific advisories, and dropping under them again would reintroduce
 * a known hole rather than risk an unknown one.
 *
 * Each floor carries the advisory that set it. A version number with no reason
 * beside it is a number somebody will "tidy up" later.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(__dirname, "..", "..");
const pkg = JSON.parse(readFileSync(join(WEB, "package.json"), "utf8")) as {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
};

/** "16.3.6" -> [16, 3, 6]; refuses a range, because a range is not a floor. */
function exact(spec: string): [number, number, number] {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(spec.trim());
  if (!m) throw new Error(`expected an exact version, got "${spec}"`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function atLeast(spec: string, floor: [number, number, number]): boolean {
  const v = exact(spec);
  for (let i = 0; i < 3; i++) {
    if (v[i] > floor[i]) return true;
    if (v[i] < floor[i]) return false;
  }
  return true;
}

describe("the framework is not one with a known hole in it", () => {
  /**
   * 16.3.3 fixed two unauthenticated RCEs:
   *   GHSA-p293-qw3h-jr36  path traversal on Windows-hosted servers
   *   GHSA-2xp9-vwfh-vxw4  Image Optimization API, AVIF
   * 16.2.11 fixed the one that matters most for THIS app:
   *   GHSA-6gpp-xcg3-4w24  middleware / proxy bypass in App Router
   * This product enforces authentication in middleware (src/middleware.ts),
   * so a middleware bypass is an authentication bypass here, not a generic
   * framework issue. 16.3.3 covers both floors.
   */
  const NEXT_FLOOR: [number, number, number] = [16, 3, 3];

  it("next is pinned to an exact version, not a range", () => {
    // A caret on the framework means a deploy can install a version nobody
    // reviewed. The rest of the tree may float; this one may not.
    expect(pkg.dependencies.next).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("next is at or above the version that fixed unauthenticated RCE", () => {
    expect(
      atLeast(pkg.dependencies.next, NEXT_FLOOR),
      `next ${pkg.dependencies.next} is below ${NEXT_FLOOR.join(".")}, which ` +
        `fixed GHSA-p293-qw3h-jr36, GHSA-2xp9-vwfh-vxw4 and (via 16.2.11) ` +
        `the middleware bypass GHSA-6gpp-xcg3-4w24`,
    ).toBe(true);
  });

  it("the lint config tracks the framework it lints", () => {
    // Different minors mean the lint rules describe a framework that is not
    // the one being built, which is how a real rule silently stops firing.
    const a = exact(pkg.dependencies.next);
    const b = exact(pkg.devDependencies["eslint-config-next"]);
    expect(
      `${b[0]}.${b[1]}`,
      "eslint-config-next drifted from next",
    ).toBe(`${a[0]}.${a[1]}`);
  });

  it("no dependency is pinned to a git URL or a local path", () => {
    // Either one means the deployment installs something that is not on the
    // registry and has not been through an audit.
    for (const [name, spec] of Object.entries({
      ...pkg.dependencies,
      ...pkg.devDependencies,
    })) {
      expect(spec, `${name} resolves outside the registry`).not.toMatch(
        /^(git|file:|link:|https?:)/,
      );
    }
  });
});

describe("the build knows which of the two products it is", () => {
  const config = readFileSync(join(WEB, "next.config.ts"), "utf8");

  it("the Turbopack workspace root is named, not inferred", () => {
    // The repository root has its own package.json and package-lock.json for
    // the legacy Express sales site. Turbopack walks upwards, finds that
    // lockfile and infers the repository root instead of this directory,
    // which changes module resolution and what the build traces. Naming it
    // removes the ambiguity.
    expect(config).toMatch(/turbopack\s*:/);
    expect(config).toMatch(/root\s*:/);
  });

  it("and the reason is written down next to it", () => {
    // A path with no explanation is a path somebody deletes while tidying.
    expect(config).toMatch(/lockfile/i);
  });
});
