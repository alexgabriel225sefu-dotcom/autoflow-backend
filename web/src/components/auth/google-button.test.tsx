/**
 * The Google button hands Supabase a validated return address and shows
 * Supabase's own refusal when the provider is not switched on.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const signInWithOAuth = vi.fn();
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signInWithOAuth } }),
}));

import { GoogleButton } from "./google-button";

afterEach(() => signInWithOAuth.mockReset());

describe("GoogleButton", () => {
  it("asks for the google provider and returns through the callback", async () => {
    signInWithOAuth.mockResolvedValue({ error: null });
    render(<GoogleButton next="/rules" onError={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    await waitFor(() => expect(signInWithOAuth).toHaveBeenCalledTimes(1));
    const arg = signInWithOAuth.mock.calls[0][0];
    expect(arg.provider).toBe("google");
    expect(arg.options.redirectTo).toBe(
      `${window.location.origin}/auth/callback?next=${encodeURIComponent("/rules")}`);
  });

  it.each(["https://evil.example/x", "//evil.example", "/\\evil.example"])(
    "never forwards a hostile next (%s)", async (next) => {
      signInWithOAuth.mockResolvedValue({ error: null });
      render(<GoogleButton next={next} onError={() => {}} />);
      fireEvent.click(screen.getByRole("button"));
      await waitFor(() => expect(signInWithOAuth).toHaveBeenCalled());
      expect(signInWithOAuth.mock.calls[0][0].options.redirectTo)
        .toBe(`${window.location.origin}/auth/callback?next=${encodeURIComponent("/dashboard")}`);
    });

  it("shows the provider's own refusal and becomes usable again", async () => {
    signInWithOAuth.mockResolvedValue({ error: { message: "Unsupported provider: provider is not enabled" } });
    const onError = vi.fn();
    render(<GoogleButton onError={onError} />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    await waitFor(() => expect(onError).toHaveBeenLastCalledWith(
      "Unsupported provider: provider is not enabled"));
    await waitFor(() => expect((btn as HTMLButtonElement).disabled).toBe(false));
  });
});
