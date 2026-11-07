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
