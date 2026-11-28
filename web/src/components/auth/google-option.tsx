"use client";
import { GoogleButton } from "./google-button";

/**
 * Whether the Google sign-in option is offered.
 *
 * The provider has to be switched on in the Supabase dashboard with a Google
 * OAuth client. While it is off, Supabase answers the button with "Unsupported
 * provider: provider is not enabled", so a visitor's first click on the
 * sign-in screen ended in an error. The option is therefore shown only when
 * the deployment says the provider is configured.
 */
export function googleSignInEnabled(): boolean {
  return process.env.NEXT_PUBLIC_GOOGLE_SIGN_IN === "true";
}

/** The Google button and the "or" divider above the password form, or nothing. */
export function GoogleOption({
  next, label, onError,
}: { next?: string | null; label?: string; onError: (message: string) => void }) {
  if (!googleSignInEnabled()) return null;
  return (
    <div className="auth-alt">
      <GoogleButton next={next} label={label} onError={onError} />
      <p className="auth-or"><span>or</span></p>
    </div>
  );
}
