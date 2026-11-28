import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const signOut = vi.fn();
vi.mock("./client", () => ({ createClient: () => ({ auth: { signOut: (o: unknown) => signOut(o) } }) }));

import { clearSessionCookies, reauthUrl, signInAgain } from "./reauth";

beforeEach(() => { signOut.mockReset(); signOut.mockResolvedValue({ error: null }); });
afterEach(() => {
  for (const part of document.cookie.split(";")) {
    const n = part.split("=")[0]?.trim(); if (n) document.cookie = `${n}=; Max-Age=0; path=/`;
  }
  vi.unstubAllGlobals();
});

describe("reauthUrl", () => {
  it("returns to where the person was, keeping the query, and marks the visit", () => {
    expect(reauthUrl("/positions", "?x=1")).toBe("/login?reauth=1&next=%2Fpositions%3Fx%3D1");
  });
  it("never sends anyone to another site", () => {
    expect(reauthUrl("//evil.example", "")).toBe("/login?reauth=1&next=%2Fdashboard");
  });
});

describe("clearSessionCookies", () => {
  it("removes the session cookies and leaves every other cookie alone", () => {
    document.cookie = "sb-abc-auth-token.0=aaa; path=/";
    document.cookie = "sb-abc-auth-token.1=bbb; path=/";
    document.cookie = "theme=dark; path=/";
    clearSessionCookies();
    expect(document.cookie).not.toContain("sb-abc-auth-token");
    expect(document.cookie).toContain("theme=dark");
  });
});

describe("signInAgain", () => {
  it("signs out locally, clears the cookies and opens a login that is not bounced back", async () => {
    document.cookie = "sb-abc-auth-token=zzz; path=/";
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/dashboard", search: "", assign });
    await signInAgain();
    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(document.cookie).not.toContain("sb-abc-auth-token");
    expect(assign).toHaveBeenCalledWith("/login?reauth=1&next=%2Fdashboard");
  });
  it("still leaves when the sign-out itself fails", async () => {
    signOut.mockRejectedValue(new Error("no session"));
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/positions", search: "", assign });
    await signInAgain();
    expect(assign).toHaveBeenCalledWith("/login?reauth=1&next=%2Fpositions");
  });
});
