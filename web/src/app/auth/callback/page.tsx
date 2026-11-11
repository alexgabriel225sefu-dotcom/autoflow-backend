"use client";
import { BrandLockup } from "@/components/brand/logo";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { EmailOtpType } from "@supabase/supabase-js";
import { createClient, createImplicitClient } from "@/lib/supabase/client";
import { safeNext } from "@/lib/supabase/middleware";

type BrowserClient = ReturnType<typeof createClient>;

interface EmailLink {
  /** `?token_hash=` — verified by Supabase directly, from any browser. */
  tokenHash: string | null;
  type: string | null;
  /** `?code=` — PKCE; only the browser that started the flow can finish it. */
  code: string | null;
  /** `#access_token=` — a session in the fragment, from any browser. */
  implicit: boolean;
}

const OTP_TYPES: readonly EmailOtpType[] = [
  "recovery", "signup", "email", "invite", "magiclink", "email_change",
];

function isOtpType(value: string | null): value is EmailOtpType {
  return OTP_TYPES.includes(value as EmailOtpType);
}

/**
 * Turns whatever the emailed link carried into a session on the cookie-backed
 * client. Resolves to null on success, or to the reason it failed.
 */
async function establishSession(supabase: BrowserClient, link: EmailLink): Promise<string | null> {
  if (link.implicit) {
    // The PKCE client refuses a fragment session, so a second, implicit
    // client reads it and the result is imported into the cookie-backed one.
    const { data, error } = await createImplicitClient().auth.getSession();
    if (error || !data.session) {
      return error?.message || "This confirmation link did not contain a valid session.";
    }
    const { error: sessionError } = await supabase.auth.setSession(data.session);
    return sessionError ? sessionError.message : null;
  }
  if (link.tokenHash) {
    if (!isOtpType(link.type)) return "This link is not valid.";
    const { error } = await supabase.auth.verifyOtp({ token_hash: link.tokenHash, type: link.type });
    return error ? error.message : null;
  }
  if (link.code) {
    // The browser client exchanges `?code=` by itself while it starts up, and
    // deletes the PKCE verifier when it does. Exchanging the same code again
    // then fails with "code verifier not found" although the visitor is
    // signed in. So: wait for startup, and exchange only a code it left alone.
    const { error: startupError } = await supabase.auth.initialize();
    const remaining = new URL(window.location.href).searchParams.get("code");
    if (!remaining) return null;
    if (startupError) return startupError.message;
    const { error } = await supabase.auth.exchangeCodeForSession(remaining);
    return error ? error.message : null;
  }
  return null;
}

/**
 * One attempt per link. Every one of these tokens is single-use, and React
 * runs an effect twice in development: the second run has to wait for the
 * first attempt instead of spending the token again and reporting a failure.
 */
let attempt: { key: string; result: Promise<string | null> } | null = null;

function establishSessionOnce(supabase: BrowserClient, link: EmailLink) {
  const key = link.implicit ? `fragment:${window.location.hash}`
    : link.tokenHash ? `token:${link.tokenHash}`
    : link.code ? `code:${link.code}` : null;
  if (!key) return Promise.resolve(null);
  if (attempt?.key !== key) attempt = { key, result: establishSession(supabase, link) };
  return attempt.result;
}

/** Single-use credentials do not stay in the address bar or the history. */
function removeCredentialsFromUrl(recovery: boolean) {
  const url = new URL(window.location.href);
  url.searchParams.delete("code");
  url.searchParams.delete("token_hash");
  // The fragment is dropped, and it may be what said this is a recovery.
  if (recovery) url.searchParams.set("mode", "recovery");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
}

function recoveryFailure(message: string) {
  if (/code verifier/i.test(message)) {
    return "This reset link was opened in a different browser from the one that requested it. "
      + "Request a new link: new links open in any browser.";
  }
  return `This link did not sign you in. ${message}`;
}

/**
 * Every emailed auth link lands here: confirmation, password recovery, and
 * the return from a social sign-in. Three link formats are accepted:
 * `?token_hash=&type=` and `#access_token=` work in any browser, `?code=`
 * (PKCE) only in the one that started the flow. A password reset must not
 * depend on the last one, because the email is usually opened elsewhere.
 * An error is shown; it is never a silent hop to /login.
 */
function CallbackPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const fragment = new URLSearchParams(
    typeof window !== "undefined" ? window.location.hash.replace(/^#/, "") : "",
  );
  const code = params.get("code");
  const tokenHash = params.get("token_hash");
  const type = params.get("type");
  const hasImplicitSession = fragment.has("access_token");
  const recovery = params.get("mode") === "recovery" || type === "recovery"
    || fragment.get("type") === "recovery";
  // Supabase reports an expired or reused link in the query, the fragment, or both.
  const queryError = params.get("error_description") || params.get("error")
    || fragment.get("error_description") || fragment.get("error");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(queryError);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [hasSession, setHasSession] = useState(false);
  const linkFailed = useRef(false);

  useEffect(() => {
    // A link that failed stays failed. Removing its credentials from the URL
    // can re-run this effect, and a second pass would find neither a link nor
    // a session and replace the real reason with a hop to /login.
    if (linkFailed.current) return;
    let cancelled = false;
    (async () => {
      const supabase = createClient();
      if (queryError) {
        if (!cancelled) setError(queryError);
      } else if (hasImplicitSession || tokenHash || code) {
        const failure = await establishSessionOnce(
          supabase, { tokenHash, type, code, implicit: hasImplicitSession });
        if (cancelled) return;
        if (failure) {
          linkFailed.current = true;
          setError(recovery ? recoveryFailure(failure) : failure);
          setHasSession(false);
          setReady(true);
        }
        removeCredentialsFromUrl(recovery);
        if (failure) return;
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
      if (session) router.replace(safeNext(params.get("next")));
      else router.replace("/login");
    })();
    return () => { cancelled = true; };
  }, [code, tokenHash, type, hasImplicitSession, queryError, recovery, router, params]);

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
            <p className="muted">
              If this was a confirmation link, request a fresh one and check
              your inbox again.
            </p>
            <div className="btn-row">
              <a className="btn" href="/signup">Request a new confirmation link</a>
              <a className="btn btn-ghost" href="/login">Back to sign in</a>
            </div>
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
