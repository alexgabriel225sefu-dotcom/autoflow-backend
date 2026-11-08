import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/middleware", () => ({
  updateSession: vi.fn(() => {
    throw new Error("session refresh must not run for /api");
  }),
}));

import { middleware } from "./middleware";

const RAW = '{"id":"evt_mw","type":"checkout.session.completed"}';

describe("webhook path and middleware", () => {
  it("does not read the POST body or start a session for /api", async () => {
    const request = new NextRequest(
      "https://www.apex4traders.com/api/v1/billing/webhook",
      {
        method: "POST",
        body: RAW,
        headers: {
          "content-type": "application/json",
          "stripe-signature": "t=1,v1=abc",
        },
      },
    );
    const response = await middleware(request);
    expect(response.headers.get("location")).toBeNull();
    expect(await request.text()).toBe(RAW);
  });
});
