"use client";
import { useState } from "react";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import type { JournalPage } from "@/lib/api";

const STATUSES = [
  "", "evaluated", "hold", "reject", "execution_requested", "order_sent",
  "order_confirmed", "order_rejected", "position_closed", "broker_error",
  "automation_started", "automation_paused", "automation_stopped",
];
const PAGE = 25;

export default function JournalView() {
  const [status, setStatus] = useState("");
  const [symbol, setSymbol] = useState("");
  const [offset, setOffset] = useState(0);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  if (status) qs.set("status", status);
  if (symbol.trim()) qs.set("symbol", symbol.trim());
  const r = useRead<JournalPage>(`journal?${qs.toString()}`);

  return (
    <main>
      <h1>Journal</h1>
      <p className="muted">
        Every evaluation, including the ones that decided to do nothing.
      </p>
      <section className="card">
        <div className="grid grid-2">
          <label className="field">
            <span>Status</span>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
              {STATUSES.map((s) => <option key={s} value={s}>{s || "All"}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Symbol</span>
            <input value={symbol} placeholder="EUR_USD"
                   onChange={(e) => { setSymbol(e.target.value); setOffset(0); }} />
          </label>
        </div>
      </section>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {r.result?.ok ? (
        <section className="card">
          {r.result.data.entries.length ? (
            <>
              <div className="scroll-x">
                <table className="tbl">
                  <thead><tr><th>When</th><th>Status</th><th>Symbol</th><th>Detail</th></tr></thead>
                  <tbody>
                    {r.result.data.entries.map((e) => (
                      <tr key={e.entryId}>
                        <td className="mono">{new Date(e.ts * 1000).toLocaleString()}</td>
                        <td>{e.status ?? e.kind}</td>
                        <td>{e.symbol ?? "—"}</td>
                        <td className="muted">
                          {e.error ?? e.decision?.reason ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="btn-row" style={{ marginTop: ".75rem" }}>
                <button className="btn btn-ghost" disabled={offset === 0}
                        onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
                <button className="btn btn-ghost" disabled={!r.result.data.hasMore}
                        onClick={() => setOffset(offset + PAGE)}>Next</button>
                <span className="muted">{r.result.data.total} entries</span>
              </div>
            </>
          ) : <p className="empty">Nothing recorded for this filter.</p>}
        </section>
      ) : null}
    </main>
  );
}
