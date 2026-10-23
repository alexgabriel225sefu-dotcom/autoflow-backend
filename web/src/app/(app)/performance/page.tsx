"use client";
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, Spinner, StatusPill } from "@/components/app/state";
import { api, type PerformanceRead, type PerformanceSummary } from "@/lib/api";

const periods = [
  ["today", "Today"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All time"],
] as const;

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="card" style={{ padding: "1rem" }}><span className="label-xs">{label}</span><strong style={{ display: "block", marginTop: ".35rem" }}>{value}</strong></div>;
}

function money(value: number) {
  return `${value >= 0 ? "+" : "−"}$${Math.abs(value).toFixed(2)}`;
}

function Group({ title, groups }: { title: string; groups: Record<string, PerformanceSummary> }) {
  return <section className="card"><div className="card-head"><h2>{title}</h2></div>
    {Object.keys(groups).length === 0 ? <p className="sub">No closed trades in this period.</p> :
      <div className="stack">{Object.entries(groups).map(([name, s]) => <div key={name} className="card-row">
        <strong>{name}</strong><span className="sub">{s.trades} trades · {money(s.net)} · {s.trades < 3 ? "too few to judge" : `${s.winRate.toFixed(1)}% win rate`}</span>
      </div>)}</div>}
  </section>;
}

export default function PerformancePage() {
  const [period, setPeriod] = useState<(typeof periods)[number][0]>("7d");
  const r = useRead<PerformanceRead>(`performance?period=${period}`, 60_000);
  const data = r.result?.ok ? r.result.data : null;
  const s = data?.summary ?? null;
  async function retry() { await api<PerformanceRead>(`performance?period=${period}`); void r.reload(); }
  return <main>
    <div className="page-head"><div><h1>Performance</h1><span className="sub">Closed trades only · Last synced {whenSynced(r.lastSync)}</span></div>
      <button className="btn btn-ghost btn-sm" onClick={() => void retry()} disabled={r.loading}><RefreshCw className="ico" aria-hidden /> Refresh</button></div>
    <div className="btn-row" role="tablist" aria-label="Performance period">{periods.map(([value, label]) => <button key={value} className={`btn btn-sm ${period === value ? "btn-primary" : "btn-ghost"}`} onClick={() => setPeriod(value)} role="tab" aria-selected={period === value}>{label}</button>)}</div>
    {r.loading && !r.result ? <Spinner /> : null}
    {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
    {s ? <>
      <div className="grid grid-4" style={{ marginTop: "1rem" }}>
        <Metric label="Winning trades" value={`${s.winningTrades} / ${s.trades}`} />
        <Metric label="Net" value={money(s.net)} />
        <Metric label="Profit factor" value={s.profitFactorStatus ?? (s.profitFactor == null ? "—" : s.profitFactor.toFixed(2))} />
        <Metric label="Win rate" value={`${s.winRate.toFixed(1)}%`} />
      </div>
      <div className="grid grid-2" style={{ marginTop: "1rem" }}><Group title="By strategy" groups={data!.byStrategy} /><Group title="By instrument" groups={data!.byInstrument} /></div>
    </> : null}
  </main>;
}
