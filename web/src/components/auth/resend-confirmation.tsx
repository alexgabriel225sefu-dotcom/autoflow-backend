"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

/** Seconds before another link may be requested. */
export const RESEND_COOLDOWN_SEC = 60;

export type ResendOutcome = { ok: true; message: string } | { ok: false; message: string };

/**
 * Ask Supabase to send the signup confirmation link again.
 *
 * The one implementation, used by Settings and by the sign-up screen. The
 * success sentence is deliberately about the address "if it still needs
 * confirming": the answer is the same whether or not the address exists, so
 * it must not reveal which.
 */
export async function resendConfirmation(email: string): Promise<ResendOutcome> {
  try {
    const { error } = await createClient().auth.resend({
      type: "signup",
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    if (error) return { ok: false, message: error.message || "The link could not be sent." };
    return { ok: true, message: "If the address still needs confirming, another link is on its way." };
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : "The link could not be sent." };
  }
}

/**
 * A resend button with a cooldown and a plain success or failure line.
 * The cooldown starts only after a send that succeeded; a failure leaves the
 * button available so it can be tried again.
 */
export function ResendConfirmation({ email, cooldownSec = RESEND_COOLDOWN_SEC }: {
  email: string; cooldownSec?: number;
}) {
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState(0);
  const [outcome, setOutcome] = useState<ResendOutcome | null>(null);

  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);

  async function send() {
    setBusy(true);
    setOutcome(null);
    const r = await resendConfirmation(email);
    setBusy(false);
    setOutcome(r);
    if (r.ok) setLeft(cooldownSec);
  }

  return (
    <div style={{ marginTop: "1rem" }}>
      <button className="btn btn-ghost btn-sm" type="button" onClick={() => void send()}
              disabled={busy || left > 0}>
        {busy ? "Sending…" : left > 0 ? `Resend available in ${left}s` : "Resend the link"}
      </button>
      {outcome ? (
        <p role={outcome.ok ? "status" : "alert"} className="muted" style={{ fontSize: ".82rem" }}>
          {outcome.message}
        </p>
      ) : null}
    </div>
  );
}
