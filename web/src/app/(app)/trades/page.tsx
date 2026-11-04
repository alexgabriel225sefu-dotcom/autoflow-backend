"use client";
import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import type { TradeRow, TradesRead } from "@/lib/api";
import { formatMoney } from "@/components/app/currency-ticker";

/**
 * Closed trades, one row each, with the curve they make.
 *
 * The server reads the broker's deal history and builds the totals and the
 * series; this file filters and draws them. A failed read says so — it is
 * never drawn as an empty list or a flat line. A missing number is "—".
 */
const PERIODS = [
  { id: 7, label: "7 days" }, { id: 30, label: "30 days" }, { id: 90, label: "90 days" },
] as const;
const RESULTS = [
  { id: "all", label: "All" }, { id: "win", label: "Wins" }, { id: "loss", label: "Losses" },
] as const;

const money = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : formatMoney(v);
const when = (t: number | null) =>
  t == null ? "—" : new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
function held(s: number | null) {
  if (s == null) return "—";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}

/** Running net as a line; draws only what it is given. */
function EquityLine({ points }: { points: { t: number; equity: number }[] }) {
  if (points.length < 2) return <p className="empty">The curve needs at least two closed trades.</p>;
  const W = 600, H = 140, P = 6;
  const xs = points.map((p) => p.t), ys = points.map((p) => p.equity);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
  const sx = (x: number) => P + ((x - x0) / Math.max(1, x1 - x0)) * (W - 2 * P);
  const sy = (y: number) => H - P - ((y - y0) / Math.max(1e-9, y1 - y0)) * (H - 2 * P);
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.t).toFixed(1)},${sy(p.equity).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Running net result of closed trades"
         style={{ width: "100%", height: "auto" }}>
      <line x1={P} x2={W - P} y1={sy(0)} y2={sy(0)} stroke="var(--a4t-line, #444)" strokeDasharray="3 4" />
      <path d={d} fill="none" stroke="var(--a4t-accent, currentColor)" strokeWidth={2} />
    </svg>
  );
}

function DailyBars({ rows }: { rows: { date: string; net: number }[] }) {
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r.net)), 1e-9);
  return (
    <ul className="plain-list" aria-label="Net result per day">
      {rows.slice(-14).map((r) => (
        <li key={r.date} style={{ display: "grid", gridTemplateColumns: "6.5rem 1fr 6rem", gap: ".5rem", alignItems: "center" }}>
          <span className="muted">{r.date}</span>
          <span aria-hidden style={{
            height: 8, width: `${Math.max(2, (Math.abs(r.net) / max) * 100)}%`, borderRadius: 4,
            background: r.net >= 0 ? "var(--a4t-pos, #3a9)" : "var(--a4t-neg, #c54)",
          }} />
          <span style={{ textAlign: "right" }}>{money(r.net)}</span>
        </li>
      ))}
    </ul>
  );
}

function Detail({ t }: { t: TradeRow }) {
  const rows: [string, string][] = [
    ["Opened", when(t.openedAt)], ["Closed", when(t.closedAt)], ["Held", held(t.durationS)],
    ["Entry", t.entry == null ? "—" : String(t.entry)],
    ["Stop at entry", t.slPrice == null ? "—" : String(t.slPrice)],
    ["Target at entry", t.tpPrice == null ? "—" : String(t.tpPrice)],
    ["Exit", t.exit == null ? "—" : String(t.exit)],
    ["Gross", money(t.gross)], ["Swap", money(t.swap)], ["Commission", money(t.commission)],
    ["Net", money(t.net)], ["Strategy", t.strategy ?? "not opened by the engine"],
  ];
  return (
    <dl className="grid grid-3" data-testid="trade-detail">
      {rows.map(([k, v]) => (
        <div className="stat" key={k}><dt className="stat-k">{k}</dt><dd className="stat-v">{v}</dd></div>
      ))}
    </dl>
  );
}

export default function TradesPage() {
  const [days, setDays] = useState<number>(30);
  const [result, setResult] = useState<(typeof RESULTS)[number]["id"]>("all");
  const [symbol, setSymbol] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  const r = useRead<TradesRead>(`trades?days=${days}&mode=demo`, 60_000);
  const d = r.result?.ok ? r.result.data : null;
  const ok = d && d.status === "ok" ? d : null;

  const symbols = useMemo(
    () => (ok ? Array.from(new Set(ok.trades.map((t) => t.symbol).filter((s): s is string => !!s))).sort() : []),
    [ok],
  );
  const shown = useMemo(() => (ok ? ok.trades.filter((t) =>
    (symbol === "all" || t.symbol === symbol) &&
    (result === "all" || (result === "win" ? (t.net ?? 0) > 0 : (t.net ?? 0) < 0))) : []), [ok, symbol, result]);

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Trades</h1>
          <span className="sub">Demo account · last synced {whenSynced(r.lastSync)}</span>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={r.reload} disabled={r.loading}>
          <RefreshCw className="ico" aria-hidden /> Refresh
        </button>
      </div>

      <div className="seg" role="group" aria-label="Period" style={{ marginBottom: "var(--sp-3)" }}>
        {PERIODS.map((p) => (
          <button key={p.id} type="button" aria-pressed={days === p.id} onClick={() => setDays(p.id)}>{p.label}</button>
        ))}
      </div>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {d && d.status === "unavailable" ? (
        <div className="notice" role="alert">
          <p style={{ fontWeight: 600 }}>Closed trades could not be read</p>
          <p className="muted">{d.reason}. This is not a statement that there were no trades.</p>
        </div>
      ) : null}

      {ok ? (
        <>
          <section className="card">
            <div className="grid grid-3">
              <div className="stat"><span className="stat-k">Closed trades</span><strong className="stat-v">{ok.summary.trades}</strong></div>
              <div className="stat"><span className="stat-k">Won / lost</span><strong className="stat-v">{ok.summary.wins} / {ok.summary.losses}</strong></div>
              <div className="stat"><span className="stat-k">Net</span><strong className="stat-v">{money(ok.summary.net)}</strong></div>
            </div>
            <EquityLine points={ok.equity} />
            <DailyBars rows={ok.daily} />
            <p className="muted" style={{ fontSize: ".78rem" }}>{ok.note}</p>
            {ok.excluded.otherMode > 0 ? (
              <p className="muted" role="note" style={{ fontSize: ".78rem" }}>
                {ok.excluded.otherMode} trade{ok.excluded.otherMode === 1 ? "" : "s"} from another account type not shown.
              </p>
            ) : null}
          </section>

          <section className="card">
            <div className="card-head"><h2>Closed trades</h2></div>
            <div className="seg" role="group" aria-label="Result" style={{ marginBottom: "var(--sp-2)" }}>
              {RESULTS.map((x) => (
                <button key={x.id} type="button" aria-pressed={result === x.id} onClick={() => setResult(x.id)}>{x.label}</button>
              ))}
            </div>
            {symbols.length > 1 ? (
              <label className="muted" style={{ display: "block", marginBottom: "var(--sp-2)" }}>
                Instrument{" "}
                <select value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="Instrument">
                  <option value="all">All</option>
                  {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
            ) : null}
            {ok.trades.length === 0 ? (
              <p className="empty">No closed trades in this period. This fills in as positions close.</p>
            ) : shown.length === 0 ? (
              <p className="empty">No trades match these filters.</p>
            ) : (
              <ul className="plain-list">
                {shown.map((t, i) => {
                  const id = t.positionId ?? `row-${i}`;
                  const isOpen = open === id;
                  return (
                    <li key={id}>
                      <button type="button" className="btn btn-ghost btn-sm" aria-expanded={isOpen}
                              onClick={() => setOpen(isOpen ? null : id)} style={{ width: "100%", justifyContent: "space-between" }}>
                        <span><strong>{t.symbol ?? "—"}</strong> {t.side ?? ""} · {when(t.closedAt)}</span>
                        <span>{money(t.net)}</span>
                      </button>
                      {isOpen ? <Detail t={t} /> : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
