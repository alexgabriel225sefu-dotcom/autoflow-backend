"use client";
import { AuthShell } from "@/components/auth/auth-shell";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { safeNext } from "@/lib/supabase/middleware";
import { createClient } from "@/lib/supabase/client";
import { PasswordField } from "@/components/auth/password-field";
import { AuthSubmit } from "@/components/auth/auth-submit";
import { GoogleButton } from "@/components/auth/google-button";

function LoginPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    setBusy(false);
    // Supabase's own message, not a friendlier one we wrote. "Email not
    // confirmed" and "Invalid credentials" need different actions from the
    // person reading them, and collapsing both into "Sign-in failed" hides
    // which one it was.
    if (error) return setError(error.message);
    // Validated, never used raw: this value comes from the address bar and
    // this line navigates to it, which is an open redirect waiting to be
    // pointed at a phishing page.
    router.push(safeNext(params.get("next")));
    router.refresh();
  }

  return (
    <AuthShell
      title="Welcome back."
      lead="Sign in to your control panel."
      footer={<><a href="/auth/reset">Forgot your password?</a><a href="/signup">Create an account</a></>}
    >
      <div className="auth-alt">
        <GoogleButton next={params.get("next")} onError={(m) => setError(m || null)} />
        <p className="auth-or"><span>or with email</span></p>
      </div>
      <form onSubmit={onSubmit} className="card">
        <label className="field">
          <span>Email</span>
          <input type="email" required value={email} autoComplete="email"
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <PasswordField label="Password" value={password} onChange={setPassword}
                       autoComplete="current-password" />
        {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
        <AuthSubmit busy={busy} idle="Sign in" busyLabel="Signing in…" />
      </form>
    </AuthShell>
  );
}

/**
 * useSearchParams needs a Suspense boundary: without one Next cannot
 * prerender the page at all, and an auth screen that fails to build is an
 * auth screen nobody can reach.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<main className="a4t"><div className="auth-wrap"><p className="muted" role="status">Loading…</p></div></main>}>
      <LoginPageInner />
    </Suspense>
  );
}
