import { describe, expect, it } from "vitest";
import { authErrorMessage } from "./auth-error";

describe("auth provider error messages", () => {
  it("turns a provider cooldown into a wait time", () => {
    expect(authErrorMessage("For security purposes, you can only request this after 47 seconds.", "resend"))
      .toBe("Please wait 47 seconds before trying again.");
  });

  it("gives existing-account and unconfirmed sign-in errors an action", () => {
    expect(authErrorMessage("User already registered", "signup"))
      .toMatch(/signing in|reset/i);
    expect(authErrorMessage("Email not confirmed", "signin"))
      .toMatch(/inbox|confirmation/i);
  });
});
