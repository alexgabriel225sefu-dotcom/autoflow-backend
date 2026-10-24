/**
 * Email confirmation and password recovery land here with a PKCE `code`.
 * getSession() alone never exchanges it, so confirmation used to dump the
 * visitor at /login and a reset's updateUser failed with no session.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let params = new URLSearchParams();
const exchangeCodeForSession = vi.fn();
const getSession = vi.fn();
const updateUser = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => params,
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      exchangeCodeForSession: (code: string) => exchangeCodeForSession(code),
      getSession: () => getSession(),
      updateUser: (body: { password: string }) => updateUser(body),
    },
  }),
}));

import CallbackPage from "./page";

beforeEach(() => {
  replace.mockReset();
  exchangeCodeForSession.mockReset();
  getSession.mockReset();
  updateUser.mockReset();
  params = new URLSearchParams();
  window.history.replaceState(null, "", "/auth/callback");
});

describe("auth callback", () => {
  it("shows a query error and does not redirect", async () => {
    params = new URLSearchParams("error=access_denied&error_description=Email+link+is+invalid");
    getSession.mockResolvedValue({ data: { session: null }, error: null });
    render(<CallbackPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Email link is invalid");
    expect(screen.getByRole("link", { name: /back to sign in/i }).getAttribute("href")).toBe("/login");
    expect(replace).not.toHaveBeenCalled();
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
  });

  it("exchanges a confirmation code and continues to the dashboard", async () => {
    params = new URLSearchParams("code=pkce-1");
    window.history.replaceState(null, "", "/auth/callback?code=pkce-1");
    exchangeCodeForSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    render(<CallbackPage />);
    await waitFor(() => expect(exchangeCodeForSession).toHaveBeenCalledWith("pkce-1"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(window.location.search).not.toContain("code=");
  });

  it("stays on the page with the Supabase message when exchange fails", async () => {
    params = new URLSearchParams("code=pkce-bad");
    window.history.replaceState(null, "", "/auth/callback?code=pkce-bad");
    exchangeCodeForSession.mockResolvedValue({ error: { message: "code expired" } });
    render(<CallbackPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("code expired");
    expect(screen.getByRole("link", { name: /back to sign in/i }).getAttribute("href")).toBe("/login");
    expect(replace).not.toHaveBeenCalled();
    expect(getSession).not.toHaveBeenCalled();
  });

  it("sends a confirmed visitor with no code straight to the dashboard", async () => {
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("sends a visitor with no session and no error to sign in", async () => {
    getSession.mockResolvedValue({ data: { session: null }, error: null });
    render(<CallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("does not show the password form until a recovery session exists", async () => {
    params = new URLSearchParams("mode=recovery&code=reset-1");
    window.history.replaceState(null, "", "/auth/callback?mode=recovery&code=reset-1");
    exchangeCodeForSession.mockResolvedValue({ error: { message: "invalid grant" } });
    render(<CallbackPage />);
    expect(await screen.findByText(/this link did not sign you in/i)).toBeTruthy();
    expect(screen.queryByLabelText(/new password/i)).toBeNull();
    expect(screen.getByRole("link", { name: /request a new reset link/i }).getAttribute("href")).toBe("/auth/reset");
    expect(replace).not.toHaveBeenCalled();
  });

  it("saves a new password only after the recovery session exists", async () => {
    params = new URLSearchParams("mode=recovery&code=reset-ok");
    window.history.replaceState(null, "", "/auth/callback?mode=recovery&code=reset-ok");
    exchangeCodeForSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    updateUser.mockResolvedValue({ error: null });
    render(<CallbackPage />);
    const input = await screen.findByLabelText(/new password/i);
    await userEvent.type(input, "new-password");
    await userEvent.click(screen.getByRole("button", { name: /save password/i }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith({ password: "new-password" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });
});
