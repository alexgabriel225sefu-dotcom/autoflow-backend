/**
 * getUser() failing, or returning nobody, is signed-out — not "this address
 * is not confirmed yet". Pending is only a signed-in user whose
 * email_confirmed_at is absent. The confirmation email lands on
 * /auth/callback, not here.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUser = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { getUser: () => getUser() } }),
}));

import ConfirmPage from "./page";

beforeEach(() => {
  getUser.mockReset();
  replace.mockReset();
  window.history.replaceState(null, "", "/auth/confirm");
});

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

  it("hands an emailed token_hash link to the callback, which verifies it", async () => {
    window.history.replaceState(null, "", "/auth/confirm?token_hash=hash-1&type=recovery");
    getUser.mockResolvedValue({ data: { user: null }, error: null });
    render(<ConfirmPage />);
    await waitFor(() => expect(replace)
      .toHaveBeenCalledWith("/auth/callback?token_hash=hash-1&type=recovery"));
    expect(getUser).not.toHaveBeenCalled();
    expect(screen.queryByText(/signed out/i)).toBeNull();
  });

  it("forwards only the token, its type and next", async () => {
    window.history.replaceState(null, "",
      "/auth/confirm?token_hash=hash-2&type=signup&next=%2Faccounts&mode=recovery&x=1");
    render(<ConfirmPage />);
    await waitFor(() => expect(replace)
      .toHaveBeenCalledWith("/auth/callback?token_hash=hash-2&type=signup&next=%2Faccounts"));
  });
});
