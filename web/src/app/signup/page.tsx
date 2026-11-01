"use client";
import { AuthShell } from "@/components/auth/auth-shell";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { PLAN_NOTICE } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { PasswordField } from "@/components/auth/password-field";
import { AuthSubmit } from "@/components/auth/auth-submit";
import { GoogleButton } from "@/components/auth/google-button";
import { ResendConfirmation } from "@/components/auth/resend-confirmation";

export default function SignUpPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { data, error } = await createClient().auth.signUp({
      email, password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    setBusy(false);
    if (error) return setError(error.message);
    // A session means the address is already confirmed, or confirmation is
    // off. Say nothing about whether the address existed: the no-session
    // screen is the same either way.
    if (data.session) {
      router.push("/dashboard");
      router.refresh();
      return;
    }
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
        <p className="auth-lead">
          Nothing arrived? Check your spam folder, then ask for another link.
        </p>
        <ResendConfirmation email={email} />
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
      <div className="auth-alt">
        <GoogleButton label="Sign up with Google" onError={(m) => setError(m || null)} />
        <p className="auth-or"><span>or with email</span></p>
      </div>
      <form onSubmit={onSubmit} className="card">
        <label className="field">
          <span>Email</span>
          <input type="email" required value={email} autoComplete="email"
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <PasswordField label="Password" value={password} onChange={setPassword}
                       autoComplete="new-password" minLength={8} />
        {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
        <AuthSubmit busy={busy} idle="Create account" busyLabel="Creating…" />
      </form>
      <p className="muted" style={{ fontSize: ".8rem", marginTop: "1.2rem" }}>
        Apex4Traders executes rules you configure on a cTrader account you
        connect yourself.
      </p>
    </AuthShell>
  );
}
