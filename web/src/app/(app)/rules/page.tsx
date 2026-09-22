"use client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import type { AutomationState, RuleSummary } from "@/lib/api";

export default function RulesPage() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules");
  const auto = useRead<AutomationState>("automation", 30_000);

  return (
    <main>
      <div className="card-head">
        <h1>Rules</h1>
        <a className="btn" href="/rules/new">New rule</a>
      </div>
      {auto.result?.ok && auto.result.data.state !== "stopped" ? (
        <div className="notice">
          Automation is <strong>{auto.result.data.state}</strong>
          {auto.result.data.ruleDocId ? (
            <> on <a href={`/rules/${auto.result.data.ruleDocId}`}>this rule</a></>
          ) : null}.
        </div>
      ) : null}
      {rules.loading && !rules.result ? <Spinner /> : null}
      {rules.result && !rules.result.ok
        ? <ErrorNotice error={rules.result} onRetry={rules.reload} /> : null}
      {rules.result?.ok ? (
        <section className="card">
          {rules.result.data.rules.length ? (
            <div className="scroll-x">
              <table className="tbl">
                <thead><tr><th>Name</th><th>State</th><th>Version</th><th>Instruments</th><th>Timeframe</th></tr></thead>
                <tbody>
                  {rules.result.data.rules.map((r) => (
                    <tr key={r.ruleDocId}>
                      <td><a href={`/rules/${r.ruleDocId}`}>{r.name || "(untitled)"}</a></td>
                      <td>{r.state}</td>
                      <td className="mono">v{r.version}</td>
                      <td>{(r.symbols ?? []).join(", ")}</td>
                      <td>{r.timeframe}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="empty">No rules yet. Create one to get started.</p>}
        </section>
      ) : null}
    </main>
  );
}
