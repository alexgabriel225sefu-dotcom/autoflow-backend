"use client";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function SignUpPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.signUp({
      email, password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    setBusy(false);
    if (error) return setError(error.message);
    setSent(true);
  }

  if (sent) {
    return (
      <main className="a4t">
        <div className="auth-wrap">
          <h1>Check your email</h1>
          <div className="card">
            <p>We sent a confirmation link to <strong>{email}</strong>.</p>
            {/* Said plainly here rather than discovered at the broker step:
                the backend refuses to connect an account or activate a rule
                until the address is confirmed. */}
            <p className="muted">
              You will need to confirm it before connecting a cTrader account
              or activating a rule.
            </p>
          </div>
          <p className="muted"><a href="/login">Back to sign in</a></p>
        </div>
      </main>
    );
  }

  return (
    <main className="a4t">
      <div className="auth-wrap">
        <h1>Create your account</h1>
        <p className="muted">Apex4Traders — rule-based automation on your own cTrader account.</p>
        <form onSubmit={onSubmit} className="card" style={{ marginTop: "1rem" }}>
          <label className="field">
            <span>Email</span>
            <input type="email" required value={email} autoComplete="email"
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" required minLength={8} value={password}
                   autoComplete="new-password"
                   onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
          <button className="btn" type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Creating…" : "Create account"}
          </button>
        </form>
        <p className="muted">
          Trading carries risk. Apex4Traders executes rules you configure on a
          cTrader account you connect yourself. It is not financial advice.
        </p>
        <p className="muted"><a href="/login">Already have an account?</a></p>
      </div>
    </main>
  );
}
