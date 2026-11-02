import { describe, expect, it } from "vitest";
import { plainError, plainErrorTitle } from "./plain";

describe("plainError", () => {
  it("leads with a plain sentence and keeps the server's wait text", () => {
    const s = plainError({ code: "RATE_LIMITED", message: "Try again in 42 seconds." });
    expect(s).toContain("Too many requests");
    expect(s).toContain("Try again in 42 seconds.");
    expect(s).not.toContain("RATE_LIMITED");
  });

  it.each(["AUTH_UNAVAILABLE", "ACCOUNTS_FAILED", "STORE_UNAVAILABLE"])(
    "maps %s without printing the code", (code) => {
      expect(plainErrorTitle(code)).toBeTruthy();
      const s = plainError({ code, message: "reason from server" });
      expect(s).not.toContain(code);
      expect(s).toContain("reason from server");
    });

  it("passes an unknown code's message through, never the bare code", () => {
    expect(plainError({ code: "WEIRD_THING", message: "Because." })).toBe("Because.");
    expect(plainError({ code: "WEIRD_THING", message: "" })).not.toContain("WEIRD_THING");
  });
});
