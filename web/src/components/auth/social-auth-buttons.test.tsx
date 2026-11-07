import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const signInWithOAuth = vi.fn().mockResolvedValue({ data: {}, error: null });

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signInWithOAuth } }),
}));

import { SocialAuthButtons } from "./social-auth-buttons";

describe("SocialAuthButtons", () => {
  it("starts Google OAuth with a same-origin callback and the requested route", async () => {
    render(<SocialAuthButtons next="/connect?n=abc" />);
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    await waitFor(() => expect(signInWithOAuth).toHaveBeenCalledWith({
      provider: "google",
      options: { redirectTo: "http://localhost:3000/auth/callback?next=%2Fconnect%3Fn%3Dabc" },
    }));
  });

  it("offers Apple separately and shows provider errors", async () => {
    signInWithOAuth.mockResolvedValueOnce({ data: {}, error: new Error("Apple is not enabled") });
    render(<SocialAuthButtons />);
    fireEvent.click(screen.getByRole("button", { name: /continue with apple/i }));
    expect((await screen.findByRole("alert")).textContent).toContain("Apple is not enabled");
    expect(signInWithOAuth).toHaveBeenCalledWith(expect.objectContaining({ provider: "apple" }));
  });
});
