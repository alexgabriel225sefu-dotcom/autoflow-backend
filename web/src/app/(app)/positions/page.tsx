"use client";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import { DataTable, Num, Side } from "@/components/app/table";
import type { Position, PositionsRead } from "@/lib/api";

export default function PositionsPage() {
  const r = useRead<PositionsRead>("positions", 30_000);
  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Positions</h1>
          <span className="sub">Last synced {whenSynced(r.lastSync)}</span>
        </div>
        <span className="btn-row">
          {r.result?.ok ? (
            <>
              {r.result.data.accountId ? (
                <span className="pill pill-muted mono">#{r.result.data.accountId}</span>
              ) : null}
              <StatusPill mode={r.result.data.mode} />
            </>
          ) : null}
          <button className="btn btn-ghost btn-sm" onClick={r.reload} disabled={r.loading}>
            <RefreshCw className="ico" aria-hidden /> Refresh
          </button>
        </span>
      </div>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {r.result?.ok ? (
        <section className="card">
          <ReadPanel read={r.result.data}>
            <DataTable<Position>
              rows={r.result.data.positions ?? []}
              rowKey={(p) => String(p.positionId)}
              empty="No open positions."
              cardTitle={(p) => p.symbol}
              cardBadge={(p) => <Side side={p.side} />}
              columns={[
                { key: "symbol", header: "Symbol", cell: (p) => p.symbol },
                { key: "side", header: "Side", cell: (p) => <Side side={p.side} />, hideOnCard: true },
                { key: "units", header: "Units", num: true, cell: (p) => <Num value={p.units} /> },
                { key: "entry", header: "Entry", num: true, cell: (p) => <Num value={p.entryPrice} /> },
                { key: "sl", header: "Stop", num: true, cell: (p) => <Num value={p.stopLoss} /> },
                { key: "tp", header: "Target", num: true, cell: (p) => <Num value={p.takeProfit} /> },
                { key: "id", header: "Position", cell: (p) => <span className="dim">{p.positionId}</span> },
              ]}
            />
          </ReadPanel>
        </section>
      ) : null}
    </main>
  );
}
