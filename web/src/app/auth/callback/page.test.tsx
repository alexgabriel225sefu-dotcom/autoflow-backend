/**
 * Email confirmation and password recovery land here with a PKCE `code`.
 * getSession() alone never exchanges it, so confirmation used to dump the
 * visitor at /login and a reset's updateUser failed with no session.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { safeNext } from "@/lib/supabase/middleware";

const replace = vi.fn();
let params = new URLSearchParams();
const exchangeCodeForSession = vi.fn();
const getSession = vi.fn();
const setSession = vi.fn();
const updateUser = vi.fn();
const implicitGetSession = vi.fn();
const initialize = vi.fn();
const verifyOtp = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => params,
}));

vi.mock("@/lib/supabase/client", () => ({
  createImplicitClient: () => ({ auth: { getSession: () => implicitGetSession() } }),
  createClient: () => ({
    auth: {
      initialize: () => initialize(),
      verifyOtp: (body: unknown) => verifyOtp(body),
      exchangeCodeForSession: (code: string) => exchangeCodeForSession(code),
      getSession: () => getSession(),
      setSession: (session: unknown) => setSession(session),
      updateUser: (body: { password: string }) => updateUser(body),
    },
  }),
}));

import CallbackPage from "./page";

beforeEach(() => {
  replace.mockReset();
  exchangeCodeForSession.mockReset();
  getSession.mockReset();
  setSession.mockReset();
  implicitGetSession.mockReset();
  updateUser.mockReset();
  initialize.mockReset();
  initialize.mockResolvedValue({ error: null });
  verifyOtp.mockReset();
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

  it("imports a confirmation session from an email link opened in another tab", async () => {
    window.history.replaceState(null, "", "/auth/callback#access_token=implicit-session");
    implicitGetSession.mockResolvedValue({
      data: { session: { access_token: "implicit", refresh_token: "refresh" } }, error: null,
    });
    setSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "implicit" } }, error: null });
    render(<CallbackPage />);
    await waitFor(() => expect(implicitGetSession).toHaveBeenCalled());
    await waitFor(() => expect(setSession).toHaveBeenCalledWith({ access_token: "implicit", refresh_token: "refresh" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
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

  it("sends a code plus a safe next path there, and refuses a protocol-relative next", async () => {
    params = new URLSearchParams("code=pkce-next&next=/accounts");
    window.history.replaceState(null, "", "/auth/callback?code=pkce-next&next=/accounts");
    exchangeCodeForSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    const { unmount } = render(<CallbackPage />);
    await waitFor(() => expect(exchangeCodeForSession).toHaveBeenCalledWith("pkce-next"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith(safeNext("/accounts")));
    unmount();

    replace.mockReset();
    exchangeCodeForSession.mockReset();
    params = new URLSearchParams("code=pkce-evil&next=//evil.example");
    window.history.replaceState(null, "", "/auth/callback?code=pkce-evil&next=//evil.example");
    exchangeCodeForSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    render(<CallbackPage />);
    await waitFor(() => expect(exchangeCodeForSession).toHaveBeenCalledWith("pkce-evil"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith(safeNext("//evil.example")));
    expect(safeNext("//evil.example")).toBe("/dashboard");
    expect(replace).not.toHaveBeenCalledWith("//evil.example");
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

  it("offers a way to request a fresh confirmation link after an expired link", async () => {
    params = new URLSearchParams("code=expired");
    window.history.replaceState(null, "", "/auth/callback?code=expired");
    exchangeCodeForSession.mockResolvedValue({ error: { message: "code expired" } });
    render(<CallbackPage />);
    await screen.findByRole("alert");
    expect(screen.getByRole("link", { name: /request a new confirmation link/i })
      .getAttribute("href")).toBe("/signup");
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

  /**
   * The production bug: the browser client exchanges `?code=` by itself while
   * it starts up and deletes the PKCE verifier. A second, explicit exchange
   * then fails with "PKCE code verifier not found in storage" even though the
   * visitor is signed in.
   */
  it("does not exchange a code the client already exchanged while starting up", async () => {
    params = new URLSearchParams("mode=recovery&code=auto-1");
    window.history.replaceState(null, "", "/auth/callback?mode=recovery&code=auto-1");
    initialize.mockImplementation(async () => {
      window.history.replaceState(null, "", "/auth/callback?mode=recovery");
      return { error: null };
    });
    exchangeCodeForSession.mockResolvedValue({
      error: { message: "PKCE code verifier not found in storage." },
    });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    render(<CallbackPage />);
    expect(await screen.findByLabelText(/new password/i)).toBeTruthy();
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(screen.queryByText(/code verifier/i)).toBeNull();
  });

  it("reports the startup exchange failure instead of retrying without a verifier", async () => {
    params = new URLSearchParams("mode=recovery&code=auto-bad");
    window.history.replaceState(null, "", "/auth/callback?mode=recovery&code=auto-bad");
    initialize.mockResolvedValue({ error: { message: "flow state expired" } });
    render(<CallbackPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("flow state expired");
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/new password/i)).toBeNull();
    expect(window.location.search).not.toContain("code=");
  });

  it("explains a reset link opened in a browser that holds no verifier", async () => {
    params = new URLSearchParams("mode=recovery&code=other-device");
    window.history.replaceState(null, "", "/auth/callback?mode=recovery&code=other-device");
    exchangeCodeForSession.mockResolvedValue({
      error: { message: "PKCE code verifier not found in storage. This can happen if..." },
    });
    render(<CallbackPage />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/different browser/i);
    expect(alert.textContent).not.toMatch(/PKCE/);
    expect(screen.getByRole("link", { name: /request a new reset link/i }).getAttribute("href")).toBe("/auth/reset");
  });

  it("verifies a recovery token_hash from any browser, then saves the password and signs in", async () => {
    params = new URLSearchParams("token_hash=hash-1&type=recovery");
    window.history.replaceState(null, "", "/auth/callback?token_hash=hash-1&type=recovery");
    verifyOtp.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    updateUser.mockResolvedValue({ error: null });
    render(<CallbackPage />);
    const input = await screen.findByLabelText(/new password/i);
    expect(verifyOtp).toHaveBeenCalledTimes(1);
    expect(verifyOtp).toHaveBeenCalledWith({ token_hash: "hash-1", type: "recovery" });
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(window.location.search).not.toContain("token_hash");
    expect(replace).not.toHaveBeenCalled();
    await userEvent.type(input, "new-password");
    await userEvent.click(screen.getByRole("button", { name: /save password/i }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith({ password: "new-password" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows why a recovery token_hash failed and offers a new link", async () => {
    params = new URLSearchParams("token_hash=hash-old&type=recovery");
    window.history.replaceState(null, "", "/auth/callback?token_hash=hash-old&type=recovery");
    verifyOtp.mockResolvedValue({ error: { message: "Email link is invalid or has expired" } });
    render(<CallbackPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("invalid or has expired");
    expect(screen.queryByLabelText(/new password/i)).toBeNull();
    expect(screen.getByRole("link", { name: /request a new reset link/i }).getAttribute("href")).toBe("/auth/reset");
    expect(getSession).not.toHaveBeenCalled();
  });

  it("refuses a token_hash with an unknown type without calling Supabase", async () => {
    params = new URLSearchParams("token_hash=hash-x&type=admin");
    window.history.replaceState(null, "", "/auth/callback?token_hash=hash-x&type=admin");
    render(<CallbackPage />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(verifyOtp).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("verifies a sign-up token_hash and continues to the dashboard", async () => {
    params = new URLSearchParams("token_hash=hash-su&type=signup");
    window.history.replaceState(null, "", "/auth/callback?token_hash=hash-su&type=signup");
    verifyOtp.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    render(<CallbackPage />);
    await waitFor(() => expect(verifyOtp).toHaveBeenCalledWith({ token_hash: "hash-su", type: "signup" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the password form for a recovery session carried in the URL fragment", async () => {
    params = new URLSearchParams("mode=recovery");
    window.history.replaceState(null, "",
      "/auth/callback?mode=recovery#access_token=recovery-session&type=recovery");
    implicitGetSession.mockResolvedValue({
      data: { session: { access_token: "rec", refresh_token: "refresh" } }, error: null,
    });
    setSession.mockResolvedValue({ error: null });
    getSession.mockResolvedValue({ data: { session: { access_token: "rec" } }, error: null });
    render(<CallbackPage />);
    expect(await screen.findByLabelText(/new password/i)).toBeTruthy();
    expect(setSession).toHaveBeenCalledWith({ access_token: "rec", refresh_token: "refresh" });
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });

  it("shows an expiry error that Supabase put in the URL fragment", async () => {
    params = new URLSearchParams("mode=recovery");
    window.history.replaceState(null, "",
      "/auth/callback?mode=recovery#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired");
    getSession.mockResolvedValue({ data: { session: null }, error: null });
    render(<CallbackPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("invalid or has expired");
    expect(screen.getByRole("link", { name: /request a new reset link/i })).toBeTruthy();
    expect(screen.queryByLabelText(/new password/i)).toBeNull();
  });
});
