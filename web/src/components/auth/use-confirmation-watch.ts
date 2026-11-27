"use client";
import { useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";

/** How often the open "check your email" page asks whether it was confirmed. */
export const WATCH_INTERVAL_MS = 12_000;
/** The least time between two asks, whatever triggers them. */
export const WATCH_MIN_GAP_MS = 3_000;
/** After this the timer stops; coming back to the tab still asks once. */
export const WATCH_TIMER_LIFETIME_MS = 20 * 60_000;
/** After a rate limit, only a return to the tab asks, and not more often than this. */
export const WATCH_RATE_LIMITED_GAP_MS = 30_000;

type AuthErrorLike = { message?: string; code?: string; status?: number } | null | undefined;

const textOf = (e: AuthErrorLike) =>
  `${e?.message ?? ""} ${e?.code ?? ""}`.toLowerCase();

/** The address exists and the password is right, but the link was not opened yet. */
export function isUnconfirmed(e: AuthErrorLike): boolean {
  const t = textOf(e);
  return t.includes("email not confirmed") || t.includes("email_not_confirmed");
}

export function isRateLimited(e: AuthErrorLike): boolean {
  const t = textOf(e);
  return e?.status === 429 || t.includes("rate limit") || t.includes("too many");
}

/**
 * Lets the sign-up page carry on by itself once the address is confirmed.
 *
 * The confirmation link is usually opened somewhere else: the mail app's own
 * browser, another tab, a phone. That place gets signed in; the page the person
 * started on stayed on "Check your email" for ever, and they had to find their
 * way back. While that page is open it now asks, with the email and password
 * still in memory from the form, whether sign-in works yet. "Not confirmed"
 * means keep waiting. Anything else (a wrong password, a network error) stops
 * the asking rather than hammering the sign-in endpoint.
 *
 * Asks every WATCH_INTERVAL_MS, and at once when the person returns to the tab,
 * which is the moment it is most likely to have worked.
 */
export function useConfirmationWatch(opts: {
  enabled: boolean; email: string; password: string; onConfirmed: () => void;
}) {
  const { enabled, email, password } = opts;
  const onConfirmed = useRef(opts.onConfirmed);
  // Kept current from an effect, not during render, so the timer below always
  // calls the latest callback without being rebuilt each time it changes.
  useEffect(() => { onConfirmed.current = opts.onConfirmed; });

  useEffect(() => {
    if (!enabled || !email || !password) return;
    let stopped = false;
    let inFlight = false;
    let lastAt = 0;
    let gap = WATCH_MIN_GAP_MS;
    let timer: ReturnType<typeof setInterval> | null = null;

    const stopTimer = () => { if (timer) { clearInterval(timer); timer = null; } };

    async function ask() {
      const now = Date.now();
      if (stopped || inFlight || now - lastAt < gap) return;
      inFlight = true;
      lastAt = now;
      try {
        const { error } = await createClient().auth.signInWithPassword({ email, password });
        if (stopped) return;
        if (!error) {
          stopped = true;
          stopTimer();
          onConfirmed.current();
        } else if (isUnconfirmed(error)) {
          // not yet: keep waiting
        } else if (isRateLimited(error)) {
          stopTimer();
          gap = WATCH_RATE_LIMITED_GAP_MS;
        } else {
          stopped = true;
          stopTimer();
        }
      } catch {
        stopped = true;
        stopTimer();
      } finally {
        inFlight = false;
      }
    }

    const onVisible = () => { if (document.visibilityState === "visible") void ask(); };
    const onFocus = () => { void ask(); };

    timer = setInterval(() => { void ask(); }, WATCH_INTERVAL_MS);
    const lifetime = setTimeout(stopTimer, WATCH_TIMER_LIFETIME_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onFocus);
    return () => {
      stopped = true;
      stopTimer();
      clearTimeout(lifetime);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onFocus);
    };
  }, [enabled, email, password]);
}
