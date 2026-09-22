"use client";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import type { PositionsRead } from "@/lib/api";

export default function PositionsPage() {
  const r = useRead<PositionsRead>("positions", 30_000);
  return (
    <main>
      <div className="card-head">
        <h1>Positions</h1>
        <span className="muted">Last synced {whenSynced(r.lastSync)}</span>
      </div>
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {r.result?.ok ? (
        <section className="card">
          <div className="card-head">
            <span className="muted mono">
              {r.result.data.accountId ? `#${r.result.data.accountId}` : ""}
            </span>
            <StatusPill mode={r.result.data.mode} />
          </div>
          <ReadPanel read={r.result.data}>
            {r.result.data.positions?.length ? (
              <div className="scroll-x">
                <table className="tbl">
                  <thead>
                    <tr><th>Symbol</th><th>Side</th><th>Units</th><th>Entry</th><th>Stop</th><th>Target</th></tr>
                  </thead>
                  <tbody>
                    {r.result.data.positions.map((p) => (
                      <tr key={String(p.positionId)}>
                        <td>{p.symbol}</td><td>{p.side}</td>
                        <td className="mono">{p.units}</td>
                        <td className="mono">{p.entryPrice ?? "—"}</td>
                        <td className="mono">{p.stopLoss ?? "—"}</td>
                        <td className="mono">{p.takeProfit ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="empty">No open positions.</p>}
          </ReadPanel>
        </section>
      ) : null}
    </main>
  );
}
