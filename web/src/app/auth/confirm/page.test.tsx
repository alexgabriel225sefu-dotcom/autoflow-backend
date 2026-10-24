/**
 * getUser() failing, or returning nobody, is signed-out — not "this address
 * is not confirmed yet". Pending is only a signed-in user whose
 * email_confirmed_at is absent. The confirmation email lands on
 * /auth/callback, not here.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUser = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { getUser: () => getUser() } }),
}));

import ConfirmPage from "./page";

beforeEach(() => { getUser.mockReset(); });

describe("confirm page", () => {
  it("shows a confirmed address and a way to the dashboard", async () => {
    getUser.mockResolvedValue({
      data: { user: { email: "ada@example.test", email_confirmed_at: "2026-01-01T00:00:00Z" } },
      error: null,
    });
    render(<ConfirmPage />);
    expect(await screen.findByText("ada@example.test is confirmed.")).toBeTruthy();
    expect(screen.getByRole("link", { name: /go to dashboard/i }).getAttribute("href")).toBe("/dashboard");
    expect(screen.queryByText(/not confirmed yet/i)).toBeNull();
  });

  it("is pending only when a signed-in user has no confirmation timestamp", async () => {
    getUser.mockResolvedValue({
      data: { user: { email: "ada@example.test", email_confirmed_at: null } },
      error: null,
    });
    render(<ConfirmPage />);
    expect(await screen.findByText(/this address is not confirmed yet/i)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
  });

  it("treats no user as signed out, not as an unconfirmed address", async () => {
    getUser.mockResolvedValue({ data: { user: null }, error: null });
    render(<ConfirmPage />);
    expect(await screen.findByText(/signed out/i)).toBeTruthy();
    expect(screen.getByText(/not the email landing/i)).toBeTruthy();
    expect(screen.getByText(/\/auth\/callback/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /sign in/i }).getAttribute("href")).toBe("/login");
    expect(screen.queryByText(/not confirmed yet/i)).toBeNull();
  });

  it("shows the Supabase error instead of the pending sentence", async () => {
    getUser.mockResolvedValue({
      data: { user: null },
      error: { message: "session missing" },
    });
    render(<ConfirmPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("session missing");
    expect(screen.queryByText(/not confirmed yet/i)).toBeNull();
    expect(screen.getByRole("link", { name: /sign in/i }).getAttribute("href")).toBe("/login");
  });
});
