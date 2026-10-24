"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, LicencePill, Spinner } from "@/components/app/state";
import type { CtraderStatus, Me } from "@/lib/api";
import { AppearanceControls } from "@/components/app/appearance-controls";

export default function SettingsPage() {
  const me = useRead<Me>("me");
  const ct = useRead<CtraderStatus>("ctrader/status");
  const router = useRouter();
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [resendNote, setResendNote] = useState<string | null>(null);
  const [resendError, setResendError] = useState<string | null>(null);
  const [resendBusy, setResendBusy] = useState(false);

  const email = me.result?.ok ? me.result.data.user.email : null;
  const unverified = me.result?.ok && me.result.data.user.emailVerified === false;

  async function resend() {
    if (!email) return;
    setResendBusy(true);
    setResendNote(null);
    setResendError(null);
    const { error } = await createClient().auth.resend({
      type: "signup",
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    setResendBusy(false);
    if (error) { setResendError(error.message); return; }
    setResendNote("If the address still needs confirming, another link is on its way.");
  }

  async function signOut() {
    setSignOutError(null);
    try {
      const result = await createClient().auth.signOut();
      if (result?.error) {
        setSignOutError(result.error.message || "Sign out failed.");
        return;
      }
    } catch (e) {
      setSignOutError(e instanceof Error ? e.message : "Sign out failed.");
      return;
    }
    router.push("/login");
    router.refresh();
  }

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <span className="sub">Your account, your broker link and your session.</span>
        </div>
      </div>
      {me.loading && !me.result ? <Spinner /> : null}
      {me.result && !me.result.ok ? <ErrorNotice error={me.result} onRetry={me.reload} /> : null}
      {me.result?.ok ? (
        <section className="card">
          <div className="card-head"><h2>Account</h2></div>
          <table className="tbl tbl-kv">
            <tbody>
              <tr><th>Email</th><td>{me.result.data.user.email}</td></tr>
              <tr><th>Confirmed</th><td>{me.result.data.user.emailVerified ? "Yes" : "No"}</td></tr>
              {unverified ? (
                <tr>
                  <th>Confirmation</th>
                  <td>
                    <button className="btn btn-ghost btn-sm" type="button" onClick={() => void resend()} disabled={resendBusy}>
                      {resendBusy ? "Sending…" : "Send another confirmation link"}
                    </button>
                    {resendError ? <p role="alert">{resendError}</p> : null}
                    {resendNote ? <p role="status">{resendNote}</p> : null}
                  </td>
                </tr>
              ) : null}
              <tr><th>Licence</th><td><LicencePill state={me.result.data.licence.state} /></td></tr>
              {/* The Supabase user id is shown because it is the id every
                  record here is filed under, and support questions are
                  unanswerable without it. It is not a secret. */}
              <tr><th>User ID</th><td className="mono">{me.result.data.user.userId}</td></tr>
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head"><h2>Appearance</h2></div>
        <AppearanceControls />
      </section>

      <section className="card">
        <div className="card-head"><h2>Broker</h2></div>
        {!ct.result ? <Spinner /> : null}
        {ct.result && !ct.result.ok ? <ErrorNotice error={ct.result} onRetry={ct.reload} /> : null}
        {ct.result?.ok ? (
          ct.result.data.connected
            ? <p style={{ fontSize: ".88rem" }}>Connected · <a href="/accounts">manage accounts</a></p>
            : <p className="muted" style={{ fontSize: ".88rem" }}>Not connected · <a href="/connect">connect cTrader</a></p>
        ) : null}
      </section>

      <section className="card">
        <div className="card-head"><h2>Password</h2></div>
        <a className="btn btn-ghost" href="/auth/reset">Send a reset link</a>
      </section>

      <section className="card">
        <div className="card-head"><h2>Session</h2></div>
        {signOutError ? <p role="alert">{signOutError}</p> : null}
        <button className="btn btn-danger" onClick={() => void signOut()}>Sign out</button>
      </section>
    </main>
  );
}
