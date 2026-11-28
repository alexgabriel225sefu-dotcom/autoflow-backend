import { describe, it, expect } from "vitest";
import { inboxLink } from "./inbox-link";

describe("inboxLink", () => {
  it("knows the common providers", () => {
    expect(inboxLink("a@gmail.com")?.name).toBe("Gmail");
    expect(inboxLink("a@Outlook.com")?.name).toBe("Outlook");
  });
  it("returns nothing for an unknown or malformed address", () => {
    expect(inboxLink("a@company.ro")).toBeNull();
    expect(inboxLink("nope")).toBeNull();
  });
});
