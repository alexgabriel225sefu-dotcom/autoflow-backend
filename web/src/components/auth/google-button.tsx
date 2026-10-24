"use client";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { safeNext } from "@/lib/supabase/middleware";

/**
 * "Continue with Google", shared by sign-in and sign-up.
 *
 * Google sign-in and account creation are the same act on Supabase's side: a
 * first visit creates the user, a later one signs them in. So one button
 * serves both screens and neither has to guess which it is.
 *
 * `next` is validated before it goes into the redirect for the same reason
 * the password form validates it: it comes from the address bar.
 *
 * The provider has to be switched on in the Supabase dashboard (Authentication,
 * Providers, Google) with a Google OAuth client. Until it is, Supabase answers
 * with its own error and this shows it unchanged, rather than a friendlier line
 * that would hide why nothing happened.
 */
export function GoogleButton({
  next, label = "Continue with Google", onError,
}: { next?: string | null; label?: string; onError: (message: string) => void }) {
  const [busy, setBusy] = useState(false);

  async function go() {
    setBusy(true);
    onError("");
    const target = safeNext(next ?? null);
    const { error } = await createClient().auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(target)}`,
      },
    });
    // On success the browser is already leaving for Google; only a failure
    // comes back here.
    if (error) {
      setBusy(false);
      onError(error.message);
    }
  }

  return (
    <button type="button" className="btn btn-ghost btn-lg btn-google" onClick={go} disabled={busy}>
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden focusable="false">
        <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
        <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
        <path fill="#FBBC05" d="M10.5 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.9-6.1z" />
        <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
      </svg>
      <span>{busy ? "Opening Google…" : label}</span>
    </button>
  );
}
