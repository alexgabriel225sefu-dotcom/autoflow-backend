"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

/** Where Supabase lands after an email confirmation link. */
export default function ConfirmPage() {
  const [state, setState] = useState<"checking" | "confirmed" | "pending">("checking");
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    createClient().auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
      // The backend is the authority on whether the address is confirmed;
      // this only reports what Supabase says, and never claims confirmation
      // the session does not show.
      setState(data.user?.email_confirmed_at ? "confirmed" : "pending");
    });
  }, []);

  return (
    <main className="a4t">
      <div className="auth-wrap">
        <h1>Email confirmation</h1>
        <div className="card">
          {state === "checking" ? <p className="muted" role="status">Checking…</p> : null}
          {state === "confirmed" ? (
            <>
              <p>{email} is confirmed.</p>
              <a className="btn" href="/dashboard">Go to dashboard</a>
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
