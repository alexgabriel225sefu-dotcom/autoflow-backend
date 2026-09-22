"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

/** Supabase redirects here after confirmation or recovery. */
function CallbackPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const recovery = params.get("mode") === "recovery";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!recovery) {
      createClient().auth.getSession().then(({ data }) => {
        router.replace(data.session ? "/dashboard" : "/login");
      });
    }
  }, [recovery, router]);

  async function setNewPassword(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.updateUser({ password });
    setBusy(false);
    if (error) return setError(error.message);
    router.replace("/dashboard");
  }

  if (!recovery) {
    return <main className="a4t"><div className="auth-wrap"><p className="muted" role="status">Signing you in…</p></div></main>;
  }
  return (
    <main className="a4t">
      <div className="auth-wrap">
        <h1>Choose a new password</h1>
        <form onSubmit={setNewPassword} className="card">
          <label className="field">
            <span>New password</span>
            <input type="password" required minLength={8} value={password}
                   autoComplete="new-password"
                   onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
          <button className="btn" type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Saving…" : "Save password"}
          </button>
        </form>
      </div>
    </main>
  );
}

/**
 * useSearchParams needs a Suspense boundary: without one Next cannot
 * prerender the page at all, and an auth screen that fails to build is an
 * auth screen nobody can reach.
 */
export default function CallbackPage() {
  return (
    <Suspense fallback={<main className="a4t"><div className="auth-wrap"><p className="muted" role="status">Loading…</p></div></main>}>
      <CallbackPageInner />
    </Suspense>
  );
}
