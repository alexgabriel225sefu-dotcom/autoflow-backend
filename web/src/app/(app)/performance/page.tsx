"use client";
import { useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import type { CtraderStatus, PerfGroup, PerfSummary, PerformanceRead } from "@/lib/api";
import { CurrencyTicker, formatMoney } from "@/components/app/currency-ticker";

/**
 * What the closed trades say — the same figures the the web app bot showed.
 *
 * Everything on this page is the server's: this file formats, it never
 * computes. Three rules it keeps:
 *  - a missing number is "—", never a 0 that reads as a result;
 *  - no losing trade is said as such, instead of an infinite profit factor;
 *  - a group under the server's `minTrades` is shown last and labelled, because
 *    ranking on three trades recommends whichever one got lucky.
 */
const PERIODS = [
  { id: "today", label: "Today" }, { id: "week", label: "7 days" },
  { id: "month", label: "30 days" }, { id: "all", label: "All time" },
] as const;

function Money({ value }: { value: number | null | undefined }) {
  return <CurrencyTicker value={value} />;
}
function moneyText(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return formatMoney(value);
}
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v}%`);

function pf(s: PerfSummary) {
  if (s.noLosses) return "no losing trades";
  return s.profit_factor == null ? "—" : String(s.profit_factor);
}

function Tile({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="stat">
      <span className="stat-k">{k}</span>
      <strong className="stat-v">{v}</strong>
    </div>
  );
}

function Groups({ title, rows, minTrades }: { title: string; rows: PerfGroup[]; minTrades: number }) {
  if (!rows.length) return null;
  return (
    <section className="card">
      <div className="card-head"><h2>{title}</h2></div>
      <ul className="plain-list">
        {rows.map((g) => (
          <li key={g.id} data-thin={g.thin ? "true" : undefined}>
            <strong>{g.label}</strong>
            {g.thin ? <span className="dim"> · too few to judge</span> : null}
            {g.evidence ? (
              <span className="dim" data-evidence={g.evidence.level} style={{ display: "block", fontSize: ".78rem" }}>
                {g.evidence.text}
              </span>
            ) : null}
            <br />
            <span className="muted">
              {g.trades} trade{g.trades === 1 ? "" : "s"} · {g.wins} won ({pct(g.win_rate)}) ·
              net {moneyText(g.net)} · expectancy {moneyText(g.expectancy)}
            </span>
          </li>
        ))}
      </ul>
      {rows.some((g) => g.thin) ? (
        <p className="muted" style={{ fontSize: ".78rem" }}>
          Fewer than {minTrades} trades is not evidence, so those are listed
          but not ranked.
        </p>
      ) : null}
    </section>
  );
}

function PerformanceBlock({ period, mode, accountId }: {
  period: (typeof PERIODS)[number]["id"];
  mode: "demo" | "live";
  accountId?: string | number | null;
}) {
  const qs = new URLSearchParams({ period, mode });
  if (accountId != null && accountId !== "") qs.set("accountId", String(accountId));
  const r = useRead<PerformanceRead>(`performance?${qs.toString()}`, 60_000);
  const d = r.result?.ok ? r.result.data : null;

  return (
    <section aria-label={`${mode} performance`}>
      <div className="page-head">
        <div>
          <h2>{mode === "live" ? "Live" : "Demo"} performance{accountId != null ? ` #${accountId}` : ""}</h2>
          <span className="sub">{mode === "live" ? "Live account" : "Demo account"} · last synced {whenSynced(r.lastSync)}</span>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={r.reload} disabled={r.loading}>
          <RefreshCw className="ico" aria-hidden /> Refresh
        </button>
      </div>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}

      {d && d.status === "unavailable" ? (
        <div className="notice" role="alert">
          <p style={{ fontWeight: 600 }}>Closed trades could not be read</p>
          <p className="muted">{d.reason}. This is not a statement that there were no trades.</p>
        </div>
      ) : null}

      {d && d.status === "ok" ? (
        <>
          <section className="card">
            {d.summary.trades === 0 ? (
              <p className="empty">
                No closed trades in this period. This fills in as positions
                close.
              </p>
            ) : (
              <div className="grid grid-3">
                <Tile k="Closed trades" v={String(d.summary.trades)} />
                <Tile k="Winning trades"
                      v={d.summary.win_rate == null ? "—" : `${d.summary.wins} of ${d.summary.trades} (${d.summary.win_rate}%)`} />
                <Tile k="Net" v={<Money value={d.summary.net} />} />
                <Tile k="Profit factor" v={pf(d.summary)} />
                <Tile k="Expectancy / trade" v={<Money value={d.summary.expectancy} />} />
                <Tile k="Max drawdown" v={<Money value={d.summary.max_drawdown} />} />
                <Tile k="Average win" v={<Money value={d.summary.avg_win} />} />
                <Tile k="Average loss" v={<Money value={d.summary.avg_loss} />} />
                <Tile k="Best / worst" v={<><Money value={d.summary.best} /> / <Money value={d.summary.worst} /></>} />
              </div>
            )}
            <p className="muted" style={{ fontSize: ".78rem", marginTop: "var(--sp-3)" }}>{d.note}</p>
            {d.source.unattributed > 0 ? (
              <p className="muted" role="note" style={{ fontSize: ".78rem" }}>
                {d.source.unattributed} of {d.summary.trades} trade{d.summary.trades === 1 ? "" : "s"} are
                unlabelled
                {d.source.journalReadable
                  ? " — the platform did not open them, or they pre-date strategy labels."
                  : " — the journal could not be read just now, so strategies are missing."}
              </p>
            ) : null}
            {d.excluded.unknownMode > 0 || d.excluded.otherMode > 0 ? (
              <p className="muted" role="note" style={{ fontSize: ".78rem" }}>
                Not included here:
                {d.excluded.otherMode > 0 ? ` ${d.excluded.otherMode} trade${d.excluded.otherMode === 1 ? "" : "s"} from another account type;` : ""}
                {d.excluded.unknownMode > 0 ? ` ${d.excluded.unknownMode} older trade${d.excluded.unknownMode === 1 ? "" : "s"} with no recorded account type (it is not guessed).` : ""}
              </p>
            ) : null}
          </section>

          <Groups title="By strategy" rows={d.byStrategy} minTrades={d.minTrades} />
          <Groups title="By instrument" rows={d.bySymbol} minTrades={d.minTrades} />
        </>
      ) : null}
    </section>
  );
}

export default function PerformancePage() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]["id"]>("all");
  const ct = useRead<CtraderStatus>("ctrader/status", 120_000);
  const listed = ct.result?.ok && Array.isArray(ct.result.data.accounts)
    ? ct.result.data.accounts : [];
  const accounts = listed.filter(
    (a): a is { ctid: string | number; mode: "demo" | "live" } => a.mode === "demo" || a.mode === "live");
  const blocks = accounts.length ? accounts : [{ ctid: null as string | number | null, mode: "demo" as const }];
  return (
    <main>
      <div className="seg" role="group" aria-label="Period" style={{ marginBottom: "var(--sp-3)" }}>
        {PERIODS.map((p) => (
          <button key={p.id} type="button" aria-pressed={period === p.id}
                  onClick={() => setPeriod(p.id)}>{p.label}</button>
        ))}
      </div>
      {blocks.map((a) => (
        <PerformanceBlock key={`${a.mode}-${a.ctid ?? "none"}`} period={period} mode={a.mode} accountId={a.ctid} />
      ))}
    </main>
  );
}
