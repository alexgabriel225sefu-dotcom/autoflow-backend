/**
 * The browser Supabase client. Supabase owns the session, not this app.
 *
 * Nothing here writes a token to localStorage by hand: the Supabase client
 * manages its own storage and refresh, and a second copy kept by us would be
 * one more place for a credential to go stale or leak. No cTrader token ever
 * reaches this file — those live server-side only, and the backend has no
 * endpoint that would return one.
 */
import { createBrowserClient } from "@supabase/ssr";
import { createClient as createImplicitSupabaseClient } from "@supabase/supabase-js";

export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    // Refused rather than defaulted. A client pointed at nothing would fail
    // later with an error about the session, sending whoever debugs it after
    // an authentication bug that does not exist.
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set",
    );
  }
  return createBrowserClient(url, key);
}

/**
 * Email confirmation links must also work when the inbox opens them in a new
 * tab or on a different device. The SSR browser client deliberately uses
 * PKCE, whose verifier only exists on the browser that started the request.
 * For signup confirmation and password reset we use Supabase's implicit
 * redirect once, then the callback exchanges that session into the normal
 * cookie-backed client.
 */
// One instance for the page. Resend, reset and sign-up each used to build a new
// client per call, and every instance starts its own session listeners.
let implicitClient: ReturnType<typeof createImplicitSupabaseClient> | null = null;

export function createImplicitClient() {
  if (implicitClient) return implicitClient;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set",
    );
  }
  implicitClient = createImplicitSupabaseClient(url, key, {
    auth: {
      flowType: "implicit",
      detectSessionInUrl: true,
      persistSession: true,
      autoRefreshToken: true,
      // Its own storage key. It used the default, the same one the cookie-backed
      // client above uses, which is what made Supabase log "Multiple GoTrueClient
      // instances detected" and let two clients write one session slot.
      storageKey: "a4t-implicit-auth",
    },
  });
  return implicitClient;
}
