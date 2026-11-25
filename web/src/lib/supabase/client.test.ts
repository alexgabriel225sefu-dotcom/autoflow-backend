import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient, createImplicitClient } from "./client";

afterEach(() => vi.restoreAllMocks());

describe("supabase browser clients", () => {
  it("hands back one implicit client, not a new GoTrueClient on every call", () => {
    // Every resend, reset and sign-up call used to build another instance, each
    // one starting its own session listeners.
    expect(createImplicitClient()).toBe(createImplicitClient());
  });

  it("does not trip the 'Multiple GoTrueClient instances' warning next to the cookie client", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    createClient();
    createImplicitClient();
    createImplicitClient();
    const multiple = warn.mock.calls.filter((c) => /Multiple GoTrueClient/i.test(String(c[0])));
    expect(multiple).toHaveLength(0);
  });
});
