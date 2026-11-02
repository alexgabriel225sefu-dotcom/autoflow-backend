"use client";
import { BrandLockup } from "@/components/brand/logo";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type ConfirmState = "checking" | "confirmed" | "signed-out" | "pending";

/**
 * A signed-in check of whether Supabase has confirmed the address.
 * The confirmation email itself lands on /auth/callback, not here.
 */
export default function ConfirmPage() {
  const [state, setState] = useState<ConfirmState>("checking");
  const [email, setEmail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    createClient().auth.getUser().then(({ data, error: userError }) => {
      if (userError) {
        setError(userError.message);
        setState("signed-out");
        return;
      }
      if (!data.user) {
        setState("signed-out");
        return;
      }
      setEmail(data.user.email ?? null);
      setState(data.user.email_confirmed_at ? "confirmed" : "pending");
    });
  }, []);

  return (
    <main className="a4t">
      <div className="auth-wrap">
        <div className="auth-brand"><BrandLockup size={26} /></div>
        <h1>Email confirmation</h1>
        <div className="card">
          {state === "checking" ? <p className="muted" role="status">Checking…</p> : null}
          {state === "confirmed" ? (
            <>
              <p>{email} is confirmed.</p>
              <a className="btn" href="/dashboard">Go to dashboard</a>
            </>
          ) : null}
          {state === "signed-out" ? (
            <>
              {error ? <p role="alert">{error}</p> : null}
              <p>You are signed out.</p>
              <p className="muted">
                This page is not the email landing. The confirmation link from
                sign-up opens /auth/callback.
              </p>
              <a href="/login">Sign in</a>
            </>
          ) : null}
          {state === "pending" ? (
            <>
              <p>This address is not confirmed yet.</p>
              <p className="muted">
                Open the link we emailed you. Until then, connecting a cTrader
                account and activating a rule are both refused.
              </p>
            </>
          ) : null}
        </div>
      </div>
    </main>
  );
}
