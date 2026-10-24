"use client";
import { BrandLockup } from "@/components/brand/logo";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

/**
 * Supabase email confirmation and password recovery land here with `?code=`
 * (PKCE). The code has to be exchanged for a session before getSession or
 * updateUser can succeed. A query error is shown; it is never a silent hop
 * to /login.
 */
function CallbackPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const recovery = params.get("mode") === "recovery";
  const code = params.get("code");
  const queryError = params.get("error_description") || params.get("error");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(queryError);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const supabase = createClient();
      if (queryError) {
        if (!cancelled) setError(queryError);
      }
      if (code) {
        const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
        const url = new URL(window.location.href);
        url.searchParams.delete("code");
        window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
        if (exchangeError) {
          if (!cancelled) {
            setError(recovery
              ? `This link did not sign you in. ${exchangeError.message}`
              : exchangeError.message);
            setHasSession(false);
            setReady(true);
          }
          return;
        }
      }
      const { data, error: sessionError } = await supabase.auth.getSession();
      if (cancelled) return;
      if (sessionError) {
        setError(recovery
          ? `This link did not sign you in. ${sessionError.message}`
          : sessionError.message);
        setHasSession(false);
        setReady(true);
        return;
      }
      const session = Boolean(data.session);
      setHasSession(session);
      setReady(true);
      if (queryError) return;
      if (recovery) {
        if (!session) setError("This link did not sign you in.");
        return;
      }
      if (session) router.replace("/dashboard");
      else router.replace("/login");
    })();
    return () => { cancelled = true; };
  }, [code, queryError, recovery, router]);

  async function setNewPassword(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error: updateError } = await createClient().auth.updateUser({ password });
    setBusy(false);
    if (updateError) return setError(updateError.message);
    router.replace("/dashboard");
  }

  if (!ready) {
    return (
      <main className="a4t">
        <div className="auth-wrap"><p className="muted" role="status">Signing you in…</p></div>
      </main>
    );
  }

  if (recovery && !hasSession) {
    return (
      <main className="a4t">
        <div className="auth-wrap">
          <div className="auth-brand"><BrandLockup size={26} /></div>
          <h1>Reset link</h1>
          <div className="card">
            <p role="alert">{error ?? "This link did not sign you in."}</p>
            <a href="/auth/reset">Request a new reset link</a>
          </div>
        </div>
      </main>
    );
  }

  if (recovery && hasSession) {
    return (
      <main className="a4t">
        <div className="auth-wrap">
          <div className="auth-brand"><BrandLockup size={26} /></div>
          <h1>Choose a new password</h1>
          <form onSubmit={setNewPassword} className="card">
            <label className="field">
              <span>New password</span>
              <input type="password" required minLength={8} value={password}
                     autoComplete="new-password"
                     onChange={(e) => setPassword(e.target.value)} />
            </label>
            {error ? <div className="notice notice-error" role="alert">{error}</div> : null}
            <button className="btn btn-lg" type="submit" disabled={busy} style={{ width: "100%" }}>
              {busy ? "Saving…" : "Save password"}
            </button>
          </form>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="a4t">
        <div className="auth-wrap">
          <div className="auth-brand"><BrandLockup size={26} /></div>
          <h1>Could not sign you in</h1>
          <div className="card">
            <p role="alert">{error}</p>
            <a href="/login">Back to sign in</a>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="a4t">
      <div className="auth-wrap"><p className="muted" role="status">Signing you in…</p></div>
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
