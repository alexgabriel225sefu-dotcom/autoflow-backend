/**
 * Settings must not spin forever when the broker read failed, must be able
 * to ask for another confirmation link, and must not pretend a failed
 * sign-out left the session.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const push = vi.fn();
const refresh = vi.fn();
const signOut = vi.fn(async (): Promise<{ error?: { message: string } }> => ({}));
const resend = vi.fn();
let routes: Record<string, ApiResult<unknown>> = {};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      signOut: () => signOut(),
      resend: (body: unknown) => resend(body),
    },
  }),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string) => routes[path] ?? {
      ok: false, status: 404, code: "NOT_FOUND", message: "no stub",
    }),
  };
});

import SettingsPage from "./page";

const ME = {
  ok: true as const,
  data: {
    user: { userId: "user-1", email: "ada@example.test", emailVerified: true },
    licence: { state: "active", expiresAt: null, plan: "demo" },
  },
};

beforeEach(() => {
  push.mockReset();
  refresh.mockReset();
  signOut.mockReset();
  signOut.mockResolvedValue({});
  resend.mockReset();
  resend.mockResolvedValue({ error: null });
  routes = {
    me: ME,
    "ctrader/status": { ok: true, data: { connected: false, accounts: [], selected: null, liveAllowed: false } },
  };
});

describe("settings broker block", () => {
  it("shows the broker error with a retry instead of spinning forever", async () => {
    routes["ctrader/status"] = {
      ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "broker status unread",
    };
    render(<SettingsPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("broker status unread");
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
    expect(screen.queryByText(/^Loading…$/)).toBeNull();
  });
});

describe("confirmation resend", () => {
  it("asks Supabase for another signup link and reports success without claiming the address exists", async () => {
    routes.me = {
      ok: true,
      data: {
        user: { userId: "user-1", email: "ada@example.test", emailVerified: false },
        licence: { state: "active", expiresAt: null, plan: "demo" },
      },
    };
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /send another confirmation link/i }));
    await waitFor(() => expect(resend).toHaveBeenCalledWith({
      type: "signup",
      email: "ada@example.test",
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    }));
    expect(await screen.findByText("If the address still needs confirming, another link is on its way.")).toBeTruthy();
  });

  it("shows the Supabase error when resend fails", async () => {
    routes.me = {
      ok: true,
      data: {
        user: { userId: "user-1", email: "ada@example.test", emailVerified: false },
        licence: { state: "active", expiresAt: null, plan: "demo" },
      },
    };
    resend.mockResolvedValue({ error: { message: "rate limit" } });
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /send another confirmation link/i }));
    expect((await screen.findByRole("alert")).textContent).toContain("rate limit");
  });
});

describe("settings sign out", () => {
  it("stays on the page and shows the error when sign-out fails", async () => {
    signOut.mockResolvedValue({ error: { message: "network down" } });
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /sign out/i }));
    expect((await screen.findByRole("alert")).textContent).toContain("network down");
    expect(push).not.toHaveBeenCalled();
  });
});
