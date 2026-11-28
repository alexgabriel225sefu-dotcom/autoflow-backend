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
  broker: "Broker connected", data: "Price data fresh", quotes: "Position quotes safe",
  session: "Session valid",
  rule: "Rule valid", risk: "Risk guard ready", store: "Shared store available",
  incidents: "No critical incident",
};

function checkText(v: boolean | null | string): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  if (v === "not_applicable") return "not applicable";
  if (v === "market_closed") return "market closed";
  return "could not be read";
}

type Health = {
  score: number; status: "healthy" | "degraded" | "blocked" | "not_connected";
  checks: Record<string, boolean | null | "not_applicable" | "market_closed">; warnings: string[];
  accountMode?: "demo" | "live" | null;
  accountId?: string | number | null;
  linkedAccounts?: {
    mode?: string; accountId?: string | number; balance: number | null; equity: number | null;
    positions?: string; orders?: string; errorCode?: string | null; correlationId?: string | null;
  }[] | null;
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
              {d.accountMode ? (
                <div className="stat"><span className="stat-k">Score account</span>
                  <strong className="stat-v">{d.accountMode}{d.accountId != null ? ` #${d.accountId}` : ""}</strong></div>
              ) : null}
            </div>
            {d.linkedAccounts === null ? (
              <p className="muted">The other linked accounts could not be read. That is not an all-clear.</p>
            ) : d.linkedAccounts?.length ? (
              <ul className="plain-list">
                {d.linkedAccounts.map((a) => (
                  <li key={`${a.mode}-${a.accountId}`}>
                    <strong>{a.mode === "live" ? "Live" : a.mode === "demo" ? "Demo" : "Account"} #{a.accountId}</strong>{" "}
                    <span className="muted">
                      balance {a.balance == null ? "unknown" : a.balance} · equity {a.equity == null ? "unknown" : a.equity}
                      {" · "}positions {a.positions || "unknown"} · orders {a.orders || "unknown"}
                      {a.errorCode ? ` · ${a.errorCode}` : ""}
                      {a.correlationId ? ` · ref ${a.correlationId}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Parts that could not be read lower the score; they are never counted as healthy.
            </p>
          </section>
          <section className="card">
            <div className="card-head"><h2>What was checked</h2></div>
            <ul className="plain-list">
              {Object.entries(d.checks).map(([k, v]) => (
                <li key={k} data-check={v === true ? "ok" : v === false ? "fail" : v === "not_applicable" ? "not-applicable" : v === "market_closed" ? "market-closed" : "unknown"}>
                  <strong>{CHECK_LABELS[k] ?? k}</strong>{" "}
                  <span className="muted">{checkText(v)}</span>
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
  incidents?: { severity?: string; kind?: string; status?: string }[];
  checked?: string[]; notChecked?: string[]; message?: string;
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
          <p style={{ fontWeight: 600 }}>{d.message || "Nothing could be checked just now, so this is not an all-clear."}</p>
          {Array.isArray(d.incidents) && d.incidents.length ? (
            <ul className="plain-list">
              {d.incidents.map((i, n) => (
                <li key={n}><strong>{String(i.kind || "incident").replaceAll("_", " ")}</strong>{" "}
                  <span className="muted">{i.severity || "unknown"} · {i.status || "unknown"}</span></li>
              ))}
            </ul>
          ) : null}
          {Array.isArray(d.notChecked) && d.notChecked.length ? (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Not checked yet: {d.notChecked.join(", ")}. Start and end times and recovery are not recorded yet.
            </p>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}

type RiskAccount = {
  status: "unavailable" | "ok";
  reason?: string;
  mode?: "demo" | "live" | null;
  accountId?: string | number | null;
  totalRisk?: number;
  riskFraction?: number | null;
  symbols?: Record<string, { long: number; short: number; risk: number }>;
  unreadablePositions?: number;
  warnings?: string[];
  currencyExposure?: Record<string, number> | null;
  correlatedPairs?: { symbols: string[]; sharedCurrencies: string[]; direction: string }[] | null;
  gapScenario?: { status?: string; reason?: string } | null;
  errorCode?: string | null;
  correlationId?: string | null;
};

type Risk = RiskAccount & { accounts?: RiskAccount[] };

function correlationText(d: RiskAccount): string {
  if (d.correlatedPairs == null || d.currencyExposure == null) {
    return "Correlation: unknown. This is not zero.";
  }
  const pairs = d.correlatedPairs.length
    ? d.correlatedPairs.map((p) => `${p.symbols.join(" & ")} share ${p.sharedCurrencies.join(", ")} (${p.direction})`).join("; ")
    : "No shared-currency correlation in the positions that could be read.";
  const gap = d.gapScenario?.status === "ok" ? "Gap scenario is available." : "Gap scenario: unknown.";
  return `${pairs} ${gap}`;
}

function RiskCard({ d }: { d: RiskAccount }) {
  const label = d.mode === "live" ? "Live account" : d.mode === "demo" ? "Demo account" : "Account";
  if (d.status === "unavailable") {
    return (
      <div className="notice" role="alert">
        <p style={{ fontWeight: 600 }}>Risk could not be read</p>
        <p className="muted">{d.reason}. This is not a statement that nothing is at risk.
          {d.errorCode ? ` ${d.errorCode}` : ""}{d.correlationId ? ` · ref ${d.correlationId}` : ""}</p>
      </div>
    );
  }
  if (d.status !== "ok") return null;
  return (
    <>
      <section className="card">
        <div className="card-head"><h2>{label}{d.accountId != null ? ` #${d.accountId}` : ""}</h2></div>
        <div className="grid grid-3">
          <div className="stat"><span className="stat-k">Risk if every stop is hit</span><strong className="stat-v">{d.totalRisk}</strong></div>
          <div className="stat"><span className="stat-k">Of balance</span>
            <strong className="stat-v">{d.riskFraction == null ? "unknown" : `${(d.riskFraction * 100).toFixed(2)}%`}</strong></div>
          <div className="stat"><span className="stat-k">Unreadable positions</span><strong className="stat-v">{d.unreadablePositions}</strong></div>
        </div>
        {(d.warnings ?? []).map((w) => <p key={w} className="muted" role="note" style={{ fontSize: ".8rem" }}>{w}</p>)}
      </section>
      <section className="card">
        <div className="card-head"><h2>By instrument</h2></div>
        {Object.keys(d.symbols ?? {}).length === 0 ? <p className="empty">No open positions with a readable stop.</p> : (
          <ul className="plain-list">
            {Object.entries(d.symbols ?? {}).map(([s, v]) => (
              <li key={s}><strong>{s}</strong>{" "}
                <span className="muted">long {v.long} · short {v.short} · risk {v.risk}</span></li>
            ))}
          </ul>
        )}
        <p className="muted" style={{ fontSize: ".78rem" }}>{correlationText(d)}</p>
      </section>
    </>
  );
}

export function RiskView() {
  const r = useRead<Risk>("risk", 30_000);
  const d = r.result?.ok ? r.result.data : null;
  const cards = d?.accounts?.length ? d.accounts : d ? [d] : [];
  return (
    <main>
      <Head title="Portfolio risk map" sub="Risk across open positions, per account" r={r} />
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {cards.map((card, i) => <RiskCard key={`${card.mode ?? "account"}-${card.accountId ?? i}`} d={card} />)}
    </main>
  );
}
