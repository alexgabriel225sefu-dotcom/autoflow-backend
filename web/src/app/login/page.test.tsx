import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
const signIn = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { signInWithPassword: (b: unknown) => signIn(b), signInWithOAuth: vi.fn() },
  }),
}));

import LoginPage from "./page";

beforeEach(() => {
  push.mockReset(); refresh.mockReset(); signIn.mockReset(); search = "";
});

async function submit() {
  render(<LoginPage />);
  await userEvent.type(await screen.findByLabelText(/email/i), "ada@example.test");
  await userEvent.type(screen.getByLabelText(/^password$/i), "hunter22");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
}

describe("login", () => {
  it("renders the form, the Google option and the way to sign up or reset", async () => {
    render(<LoginPage />);
    expect(await screen.findByRole("heading", { name: /welcome back/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /google/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /forgot your password/i }).getAttribute("href")).toBe("/auth/reset");
    expect(screen.getByRole("link", { name: /create an account/i }).getAttribute("href")).toBe("/signup");
  });

  it("signs in and opens the dashboard by default", async () => {
    signIn.mockResolvedValue({ error: null });
    await submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
    expect(signIn).toHaveBeenCalledWith({ email: "ada@example.test", password: "hunter22" });
    expect(refresh).toHaveBeenCalled();
  });

  it("returns to a same-site next path, keeping its query", async () => {
    search = "next=" + encodeURIComponent("/connect?n=abc");
    signIn.mockResolvedValue({ error: null });
    await submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/connect?n=abc"));
  });

  it("refuses to be sent to another site", async () => {
    search = "next=" + encodeURIComponent("//evil.example/x");
    signIn.mockResolvedValue({ error: null });
    await submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the provider's error and does not navigate", async () => {
    signIn.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    await submit();
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid login credentials");
    expect(push).not.toHaveBeenCalled();
  });
});
