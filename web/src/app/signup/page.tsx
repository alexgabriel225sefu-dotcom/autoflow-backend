"use client";
import { AuthShell } from "@/components/auth/auth-shell";
import { useState } from "react";
import { PLAN_NOTICE } from "@/lib/api";
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
      <AuthShell
        title="Check your email."
        lead={`We sent a confirmation link to ${email}.`}
        footer={<a href="/login">Back to sign in</a>}
      >
        {/* Said plainly here rather than discovered at the broker step:
            the backend refuses to connect an account or activate a rule
            until the address is confirmed. */}
        <p className="auth-lead" style={{ marginTop: "1.2rem" }}>
          You will need to confirm it before connecting a cTrader account
          or activating a rule.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create your account."
      lead="Rule-based automation on your own cTrader account."
      footer={<a href="/login">Already have an account?</a>}
    >
      {/* Before the form, not after it. Somebody entering an email address
          is entitled to know whether it will end in a payment screen. */}
      <p className="muted" style={{ fontSize: ".84rem", marginTop: "1rem" }}>{PLAN_NOTICE}</p>
      <form onSubmit={onSubmit} className="card">
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
        <button className="btn btn-lg" type="submit" disabled={busy} style={{ width: "100%" }}>
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="muted" style={{ fontSize: ".8rem", marginTop: "1.2rem" }}>
        Apex4Traders executes rules you configure on a cTrader account you
        connect yourself.
      </p>
    </AuthShell>
  );
}
