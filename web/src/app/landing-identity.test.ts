import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const landing = readFileSync(join(__dirname, "page.tsx"), "utf8");

describe("landing provider roadmap", () => {
  it("keeps cTrader available and labels MT4 and MT5 as coming soon", () => {
    expect(landing).toContain("cTrader");
    expect(landing).toContain("Available now");
    expect(landing).toContain("MetaTrader 4");
    expect(landing).toContain("MetaTrader 5");
    expect((landing.match(/Coming soon/g) ?? []).length).toBe(2);
  });

  it("does not promise that the future connectors are install-free", () => {
    expect(landing).toContain("No install path promised yet");
  });
});
