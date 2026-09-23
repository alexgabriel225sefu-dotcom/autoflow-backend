"use client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, ExecutionBadge, LicencePill, PlanNotice, Spinner } from "@/components/app/state";
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
          {/* Access, as the server decided it. A page that told the client
              what they may do by reading the licence state alone would have
              been wrong from the moment demo access became free — this reads
              the verdict instead of reconstructing it. */}
          <table className="tbl tbl-kv">
            <tbody>
              <tr>
                <th>Access</th>
                <td>
                  {me.result.data.execution.entitlement === "paid_live"
                    ? "Paid plan"
                    : "Free demo"}
                </td>
              </tr>
              <tr>
                <th>Connected account</th>
                <td><ExecutionBadge execution={me.result.data.execution} /></td>
              </tr>
              <tr>
                <th>Demo automation</th>
                <td>{me.result.data.execution.canAutomate
                  ? "Available"
                  : me.result.data.execution.message}</td>
              </tr>
              <tr>
                <th>Live execution</th>
                <td>
                  {me.result.data.execution.liveExecutionEnabled
                    ? "Enabled"
                    : "Not enabled in this release"}
                </td>
              </tr>
            </tbody>
          </table>

          <PlanNotice execution={me.result.data.execution} />

          {me.result.data.licence.state === "revoked" ? (
            <div className="notice notice-warn" role="alert">
              <p>
                This account&rsquo;s access was withdrawn. Rules cannot be
                activated and automation cannot be started. Contact support.
              </p>
            </div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
