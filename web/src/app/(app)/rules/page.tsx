"use client";
import { Plus } from "lucide-react";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { DataTable, When } from "@/components/app/table";
import type { AutomationState, RuleSummary } from "@/lib/api";

function StatePill({ state }: { state: string }) {
  const cls = state === "active" ? "pill pill-ok"
    : state === "draft" ? "pill pill-accent"
    : state === "paused" ? "pill pill-warn" : "pill pill-muted";
  return <span className={cls}>{state}</span>;
}

export default function RulesPage() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules");
  const auto = useRead<AutomationState>("automation", 30_000);
  const running = auto.result?.ok ? auto.result.data : null;

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Rules</h1>
          <span className="sub">
            A rule is frozen once active. Editing one creates a new version.
          </span>
        </div>
        <a className="btn" href="/rules/new"><Plus className="ico" aria-hidden /> New rule</a>
      </div>

      {running && running.state !== "stopped" ? (
        <div className="notice notice-accent">
          Automation is <strong>{running.state}</strong>
          {running.ruleDocId ? (
            <> on <a href={`/rules/${running.ruleDocId}`}>this rule</a></>
          ) : null}.
        </div>
      ) : null}

      {rules.loading && !rules.result ? <Spinner /> : null}
      {rules.result && !rules.result.ok
        ? <ErrorNotice error={rules.result} onRetry={rules.reload} /> : null}
      {rules.result?.ok ? (
        <section className="card">
          <DataTable<RuleSummary>
            rows={rules.result.data.rules}
            rowKey={(r) => r.ruleDocId}
            empty="No rules yet. Create one to get started."
            cardTitle={(r) => (
              <a href={`/rules/${r.ruleDocId}`}>{r.name || "(untitled)"}</a>
            )}
            cardBadge={(r) => <StatePill state={r.state} />}
            columns={[
              {
                key: "name", header: "Name",
                cell: (r) => <a href={`/rules/${r.ruleDocId}`}>{r.name || "(untitled)"}</a>,
                hideOnCard: true,
              },
              { key: "state", header: "State", cell: (r) => <StatePill state={r.state} />, hideOnCard: true },
              { key: "symbols", header: "Instruments", cell: (r) => (r.symbols ?? []).join(", ") },
              { key: "tf", header: "Timeframe", cell: (r) => r.timeframe },
              { key: "version", header: "Version", num: true, cell: (r) => `v${r.version}` },
              { key: "updated", header: "Updated", cell: (r) => <When ts={r.updatedAt} /> },
              {
                key: "run", header: "Automation",
                cell: (r) => running && running.ruleDocId === r.ruleDocId && running.state !== "stopped"
                  ? <span className="pill pill-accent">{running.state}</span>
                  : <span className="dim">—</span>,
              },
            ]}
          />
        </section>
      ) : null}
    </main>
  );
}
