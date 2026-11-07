"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

type SocialProvider = "google" | "apple";

/**
 * Starts a Supabase OAuth flow without putting provider credentials in the
 * browser. Provider configuration stays in the Supabase dashboard; if a
 * provider is disabled, the returned error is shown instead of pretending
 * that sign-in succeeded.
 */
export function SocialAuthButtons({ next = "/dashboard" }: { next?: string }) {
  const [busy, setBusy] = useState<SocialProvider | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function signIn(provider: SocialProvider) {
    setBusy(provider);
    setError(null);
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", next);
    const { error: authError } = await createClient().auth.signInWithOAuth({
      provider,
      options: { redirectTo: callback.toString() },
    });
    if (authError) {
      setBusy(null);
      setError(authError.message);
    }
  }

  return (
    <div className="social-auth" aria-label="Social sign in">
      <button className="social-auth-btn" type="button" onClick={() => signIn("google")} disabled={busy !== null}>
        <span className="social-auth-mark social-auth-google" aria-hidden>G</span>
        {busy === "google" ? "Connecting…" : "Continue with Google"}
      </button>
      <button className="social-auth-btn" type="button" onClick={() => signIn("apple")} disabled={busy !== null}>
        <span className="social-auth-mark social-auth-apple" aria-hidden>●</span>
        {busy === "apple" ? "Connecting…" : "Continue with Apple"}
      </button>
      {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
    </div>
  );
}
