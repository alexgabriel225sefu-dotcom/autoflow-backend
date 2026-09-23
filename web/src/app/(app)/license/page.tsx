"use client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, LicencePill, Spinner } from "@/components/app/state";
import type { Me } from "@/lib/api";

export default function LicensePage() {
  const me = useRead<Me>("me");
  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Licence</h1>
          <span className="sub">What this account is entitled to do.</span>
        </div>
        {me.result?.ok ? <LicencePill state={me.result.data.licence.state} /> : null}
      </div>
      {me.loading && !me.result ? <Spinner /> : null}
      {me.result && !me.result.ok ? <ErrorNotice error={me.result} onRetry={me.reload} /> : null}
      {me.result?.ok ? (
        <section className="card">
          <table className="tbl tbl-kv">
            <tbody>
              <tr><th>Account</th><td>{me.result.data.user.email}</td></tr>
              <tr><th>Email confirmed</th><td>{me.result.data.user.emailVerified ? "Yes" : "No"}</td></tr>
              <tr><th>Plan</th><td>{me.result.data.licence.plan ?? "—"}</td></tr>
              <tr>
                <th>Expires</th>
                <td>{me.result.data.licence.expiresAt
                  ? new Date(me.result.data.licence.expiresAt * 1000).toLocaleString()
                  : "—"}</td>
              </tr>
            </tbody>
          </table>
          {me.result.data.licence.state !== "active" ? (
            <div className="notice notice-warn">
              {/* Stated here, before they build a rule and hit it at the end. */}
              <p>
                {me.result.data.licence.state === "expired"
                  ? "This licence has expired. Rules cannot be activated until it is renewed."
                  : "This account has no licence. Rules can be built and previewed, but not activated."}
              </p>
            </div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
