/**
 * A reset link is normally opened somewhere other than the tab that asked for
 * it: another browser, a phone, a mail app's web view. A request made by the
 * PKCE client produces a link only the requesting browser can finish, so the
 * request has to go through the implicit client, like sign-up confirmation.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pkceReset = vi.fn();
const implicitReset = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { resetPasswordForEmail: (...args: unknown[]) => pkceReset(...args) },
  }),
  createImplicitClient: () => ({
    auth: { resetPasswordForEmail: (...args: unknown[]) => implicitReset(...args) },
  }),
}));

import ResetPage from "./page";

beforeEach(() => {
  pkceReset.mockReset();
  implicitReset.mockReset();
  pkceReset.mockResolvedValue({ error: null });
  implicitReset.mockResolvedValue({ error: null });
});

async function submit() {
  render(<ResetPage />);
  await userEvent.type(screen.getByLabelText(/email/i), "ada@example.test");
  await userEvent.click(screen.getByRole("button", { name: /send reset link/i }));
}

describe("password reset request", () => {
  it("asks for a link that does not depend on a PKCE verifier in this browser", async () => {
    await submit();
    await waitFor(() => expect(implicitReset).toHaveBeenCalledTimes(1));
    expect(implicitReset).toHaveBeenCalledWith("ada@example.test", {
      redirectTo: `${window.location.origin}/auth/callback?mode=recovery`,
    });
    expect(pkceReset).not.toHaveBeenCalled();
    expect(await screen.findByText(/a reset link is on its way/i)).toBeTruthy();
  });

  it("shows a provider error and stays on the form", async () => {
    implicitReset.mockResolvedValue({ error: { message: "email rate limit exceeded" } });
    await submit();
    expect((await screen.findByRole("alert")).textContent).toMatch(/too many requests/i);
    expect(screen.queryByText(/a reset link is on its way/i)).toBeNull();
  });
});
