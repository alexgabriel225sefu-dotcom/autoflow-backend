import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The rule page prints the server's explanation and decides nothing itself.
const src = readFileSync(join(process.cwd(), "src/app/(app)/rules/[id]/page.tsx"), "utf8");

describe("rule page explanation", () => {
  it("renders the server's explanation block", () => {
    expect(src).toContain("<WhyBlock e={p.explanation} />");
    expect(src).toContain("Stopped by:");
  });
  it("does not classify a refusal in the browser", () => {
    expect(src).not.toMatch(/SPREAD_LIMIT_EXCEEDED|MODE_UNVERIFIED|LEDGER_UNAVAILABLE/);
  });
});
