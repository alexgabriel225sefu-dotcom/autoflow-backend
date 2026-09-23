"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

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
    router.push(params.get("next") || "/dashboard");
    router.refresh();
  }

  return (
    <main className="a4t">
      <div className="auth-wrap">
        <div className="auth-brand">
          <span className="side-mark" aria-hidden />
          Apex4Traders
        </div>
        <h1>Sign in</h1>
        <form onSubmit={onSubmit} className="card" style={{ marginTop: "1rem" }}>
          <label className="field">
            <span>Email</span>
            <input type="email" required value={email} autoComplete="email"
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" required value={password} autoComplete="current-password"
                   onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
          <button className="btn btn-lg" type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted">
          <a href="/auth/reset">Forgot your password?</a> · <a href="/signup">Create an account</a>
        </p>
      </div>
    </main>
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
