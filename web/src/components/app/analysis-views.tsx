"use client";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";

/**
 * Readable screens for the three read-only analysis surfaces. Each prints what
 * the server measured and says what it could not: an unknown input is shown as
 * unknown, never as healthy, safe or zero.
 */
function Head({ title, sub, r }: { title: string; sub: string; r: { reload: () => unknown; loading: boolean; lastSync: number | null } }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        <span className="sub">{sub} · last synced {whenSynced(r.lastSync)}</span>
      </div>
      <button className="btn btn-ghost btn-sm" onClick={() => void r.reload()} disabled={r.loading}>
        <RefreshCw className="ico" aria-hidden /> Refresh
      </button>
    </div>
  );
}

const CHECK_LABELS: Record<string, string> = {
  broker: "Broker connected", data: "Price data fresh", session: "Session valid",
  rule: "Rule valid", risk: "Risk guard ready", store: "Shared store available",
  incidents: "No critical incident",
};

type Health = {
  score: number; status: "healthy" | "degraded" | "blocked" | "not_connected";
  checks: Record<string, boolean | null | "not_applicable">; warnings: string[];
};

export function HealthView() {
  const r = useRead<Health>("health-score", 30_000);
  const d = r.result?.ok ? r.result.data : null;
  return (
    <main>
      <Head title="Automation health" sub="A technical score, not a profit score" r={r} />
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {d ? (
        <>
          <section className="card">
            <div className="grid grid-3">
              <div className="stat"><span className="stat-k">Score</span><strong className="stat-v">{d.score}/100</strong></div>
              <div className="stat"><span className="stat-k">Status</span><strong className="stat-v" data-status={d.status}>{d.status}</strong></div>
            </div>
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Parts that could not be read lower the score; they are never counted as healthy.
            </p>
          </section>
          <section className="card">
            <div className="card-head"><h2>What was checked</h2></div>
            <ul className="plain-list">
              {Object.entries(d.checks).map(([k, v]) => (
                <li key={k} data-check={v === true ? "ok" : v === false ? "fail" : v === "not_applicable" ? "not-applicable" : "unknown"}>
                  <strong>{CHECK_LABELS[k] ?? k}</strong>{" "}
                  <span className="muted">{v === true ? "yes" : v === false ? "no" : v === "not_applicable" ? "not applicable" : "could not be read"}</span>
                </li>
              ))}
            </ul>
            {d.warnings.length ? (
              <div className="notice notice-warn" role="status">
                {d.warnings.map((w) => <p key={w} className="muted" style={{ margin: 0 }}>{w}</p>)}
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </main>
  );
}

type Incidents = {
  incidents: { severity: string; kind: string; status: string }[];
  checked: string[]; notChecked: string[]; message: string;
};

export function IncidentsView() {
  const r = useRead<Incidents>("incidents", 30_000);
  const d = r.result?.ok ? r.result.data : null;
  return (
    <main>
      <Head title="Incident center" sub="Problems the platform can observe" r={r} />
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {d ? (
        <section className="card">
          <p style={{ fontWeight: 600 }}>{d.message}</p>
          {d.incidents.length ? (
            <ul className="plain-list">
              {d.incidents.map((i, n) => (
                <li key={n}><strong>{i.kind.replace("_", " ")}</strong>{" "}
                  <span className="muted">{i.severity} · {i.status}</span></li>
              ))}
            </ul>
          ) : null}
          {d.notChecked.length ? (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Not checked yet: {d.notChecked.join(", ")}. Start and end times and recovery are not recorded yet.
            </p>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}

type Risk =
  | { status: "unavailable"; reason: string }
  | {
    status: "ok"; totalRisk: number; riskFraction: number | null;
    symbols: Record<string, { long: number; short: number; risk: number }>;
    unreadablePositions: number; warnings: string[];
  };

export function RiskView() {
  const r = useRead<Risk>("risk", 30_000);
  const d = r.result?.ok ? r.result.data : null;
  return (
    <main>
      <Head title="Portfolio risk map" sub="Risk across all open positions" r={r} />
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {d && d.status === "unavailable" ? (
        <div className="notice" role="alert">
          <p style={{ fontWeight: 600 }}>Risk could not be read</p>
          <p className="muted">{d.reason}. This is not a statement that nothing is at risk.</p>
        </div>
      ) : null}
      {d && d.status === "ok" ? (
        <>
          <section className="card">
            <div className="grid grid-3">
              <div className="stat"><span className="stat-k">Risk if every stop is hit</span><strong className="stat-v">{d.totalRisk}</strong></div>
              <div className="stat"><span className="stat-k">Of balance</span>
                <strong className="stat-v">{d.riskFraction == null ? "unknown" : `${(d.riskFraction * 100).toFixed(2)}%`}</strong></div>
              <div className="stat"><span className="stat-k">Unreadable positions</span><strong className="stat-v">{d.unreadablePositions}</strong></div>
            </div>
            {d.warnings.map((w) => <p key={w} className="muted" role="note" style={{ fontSize: ".8rem" }}>{w}</p>)}
          </section>
          <section className="card">
            <div className="card-head"><h2>By instrument</h2></div>
            {Object.keys(d.symbols).length === 0 ? <p className="empty">No open positions with a readable stop.</p> : (
              <ul className="plain-list">
                {Object.entries(d.symbols).map(([s, v]) => (
                  <li key={s}><strong>{s}</strong>{" "}
                    <span className="muted">long {v.long} · short {v.short} · risk {v.risk}</span></li>
                ))}
              </ul>
            )}
            <p className="muted" style={{ fontSize: ".78rem" }}>
              Exposure per currency, correlation and gap scenarios are not computed yet.
            </p>
          </section>
        </>
      ) : null}
    </main>
  );
}
