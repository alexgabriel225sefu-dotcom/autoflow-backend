"use client";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, LicencePill, Spinner } from "@/components/app/state";
import type { CtraderStatus, Me } from "@/lib/api";

export default function SettingsPage() {
  const me = useRead<Me>("me");
  const ct = useRead<CtraderStatus>("ctrader/status");
  const router = useRouter();

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
        <div className="card-head"><h2>Broker</h2></div>
        {ct.result?.ok ? (
          ct.result.data.connected
            ? <p style={{ fontSize: ".88rem" }}>Connected · <a href="/accounts">manage accounts</a></p>
            : <p className="muted" style={{ fontSize: ".88rem" }}>Not connected · <a href="/connect">connect cTrader</a></p>
        ) : <Spinner />}
      </section>

      <section className="card">
        <div className="card-head"><h2>Password</h2></div>
        <a className="btn btn-ghost" href="/auth/reset">Send a reset link</a>
      </section>

      <section className="card">
        <div className="card-head"><h2>Session</h2></div>
        <button className="btn btn-danger" onClick={async () => {
          await createClient().auth.signOut();
          router.push("/login");
          router.refresh();
        }}>Sign out</button>
      </section>
    </main>
  );
}
