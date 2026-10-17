"use client";
import { BrandLockup } from "@/components/brand/logo";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function ResetPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?mode=recovery`,
    });
    setBusy(false);
    if (error) return setError(error.message);
    setSent(true);
  }

  return (
    <main className="a4t">
      <div className="auth-wrap">
        <div className="auth-brand"><BrandLockup size={26} /></div>
        <h1>Reset your password</h1>
        {sent ? (
          <div className="card">
            {/* Deliberately the same message whether or not the address is
                registered: a different one would tell a stranger which email
                addresses have accounts here. */}
            <p>If that address has an account, a reset link is on its way.</p>
            <a className="btn btn-ghost" href="/login">Back to sign in</a>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="card">
            <label className="field">
              <span>Email</span>
              <input type="email" required value={email}
                     onChange={(e) => setEmail(e.target.value)} />
            </label>
            {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
            <button className="btn btn-lg" type="submit" disabled={busy} style={{ width: "100%" }}>
              {busy ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
