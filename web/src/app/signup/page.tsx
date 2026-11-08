"use client";
import { AuthShell } from "@/components/auth/auth-shell";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { PLAN_NOTICE } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { PasswordField } from "@/components/auth/password-field";
import { AuthSubmit } from "@/components/auth/auth-submit";
import { authCallbackUrl } from "@/lib/supabase/redirect";
import { authErrorMessage } from "@/lib/supabase/auth-error";
import { GoogleButton } from "@/components/auth/google-button";
import { inboxLink } from "@/lib/inbox-link";
import { ResendConfirmation } from "@/components/auth/resend-confirmation";

export default function SignUpPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  function validate() {
    const trimmed = email.trim();
    if (!trimmed || !/^\S+@\S+\.\S+$/.test(trimmed)) {
      return "Enter a valid email address.";
    }
    if (password.length < 8) return "Use at least 8 characters for your password.";
    return null;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    setBusy(true);
    setError(null);
    const { data, error } = await createClient().auth.signUp({
      email: email.trim(), password,
      options: { emailRedirectTo: authCallbackUrl(window.location.origin) },
    });
    setBusy(false);
    if (error) return setError(authErrorMessage(error.message, "signup"));
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
    const inbox = inboxLink(email);
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
        {inbox ? (
          <p className="auth-lead">
            <a className="btn" href={inbox.href} target="_blank" rel="noopener noreferrer">
              Open {inbox.name}
            </a>
          </p>
        ) : null}
        <p className="auth-lead">
          It comes from no-reply@apex4traders.com. Nothing arrived? Check your
          spam folder, then ask for another link.
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
        <p className="auth-or"><span>or</span></p>
      </div>
      <form onSubmit={onSubmit} className="card" noValidate>
        <label className="field">
          <span>Email</span>
          <input type="email" required value={email} autoComplete="email"
                 aria-invalid={Boolean(error && !/^\S+@\S+\.\S+$/.test(email.trim()))}
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
