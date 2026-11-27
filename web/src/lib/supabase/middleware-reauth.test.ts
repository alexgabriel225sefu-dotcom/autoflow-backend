import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

let user: { id: string } | null = { id: "u1" };
vi.mock("@supabase/ssr", () => ({
  createServerClient: () => ({ auth: { getUser: async () => ({ data: { user } }) } }),
}));

import { updateSession } from "./middleware";

beforeEach(() => {
  user = { id: "u1" };
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://x.supabase.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon");
});

const at = (path: string) => new NextRequest(`https://www.example.test${path}`);

describe("signed-in visitors on the sign-in pages", () => {
  it("are sent to the dashboard, as before", async () => {
    const res = await updateSession(at("/login"));
    expect(res.status).toBe(307);
    expect(new URL(res.headers.get("location")!).pathname).toBe("/dashboard");
  });

  it("are NOT bounced when they came from Sign in again (?reauth=1)", async () => {
    // The page said it had no session while this check says it has one; the
    // button clears the cookies and lands here, and must be allowed to stay.
    const res = await updateSession(at("/login?reauth=1&next=%2Fdashboard"));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("the exception does not open any app page to a signed-out visitor", async () => {
    user = null;
    const res = await updateSession(at("/positions?reauth=1"));
    expect(res.status).toBe(307);
    expect(new URL(res.headers.get("location")!).pathname).toBe("/login");
  });
});
