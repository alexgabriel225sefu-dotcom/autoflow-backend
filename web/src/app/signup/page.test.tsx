/**
 * A sign-up that already has a session (confirmation disabled, or the
 * address was confirmed before) must enter the app. No session keeps the
 * same "check your email" screen either way, so the page does not say
 * whether the address is already registered.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
const signUp = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signUp: (body: unknown) => signUp(body) } }),
}));

import SignUpPage from "./page";

beforeEach(() => {
  push.mockReset();
  refresh.mockReset();
  signUp.mockReset();
});

async function submit() {
  render(<SignUpPage />);
  await userEvent.type(screen.getByLabelText(/email/i), "ada@example.test");
  await userEvent.type(screen.getByLabelText(/^password$/i), "long-enough");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
}

describe("sign up", () => {
  it("opens the dashboard when sign-up already returned a session", async () => {
    signUp.mockResolvedValue({ data: { session: { access_token: "t" }, user: {} }, error: null });
    await submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByText(/check your email/i)).toBeNull();
  });

  it("keeps the check-your-email screen when there is no session", async () => {
    signUp.mockResolvedValue({ data: { session: null, user: {} }, error: null });
    await submit();
    expect(await screen.findByRole("heading", { name: /check your email/i })).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByText(/already registered|already exists/i)).toBeNull();
  });
});
