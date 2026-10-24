"use client";
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import { DataTable, Num, Side, When } from "@/components/app/table";
import { PositionDetail } from "@/components/app/position-detail";
import type { ClosedTrade, DealsRead, Position, PositionsRead } from "@/lib/api";

function currentCell(p: Position) {
  if (p.quoteStale) return <><Num value={null} /> <span className="dim">stale</span></>;
  return <Num value={p.currentPrice} />;
}

function distanceCell(value: number | null | undefined) {
  return value === null || value === undefined ? null : <span className="sub">{value.toFixed(1)} pips</span>;
}

function stopCell(p: Position) {
  if (p.hasStop === false) return <div><span className="pill pill-warn">None</span>{p.warning ? <span className="dim"> {p.warning}</span> : null}</div>;
  return <div><Num value={p.stopLoss} />{distanceCell(p.stopDistancePips)}</div>;
}

function targetCell(p: Position) {
  return <div><Num value={p.takeProfit} />{distanceCell(p.targetDistancePips)}</div>;
}

function pnlCell(value: number | null | undefined, estimated?: boolean) {
  return <span><Num value={value} />{estimated ? <span className="dim"> est.</span> : null}</span>;
}

function positionColumns(onDetails: (p: Position) => void) {
 return [
  { key: "symbol", header: "Symbol", cell: (p: Position) => p.symbol },
  { key: "side", header: "Side", cell: (p: Position) => <Side side={p.side} />, hideOnCard: true },
  { key: "units", header: "Volume", num: true, cell: (p: Position) => <Num value={p.units} /> },
  { key: "entry", header: "Entry", num: true, cell: (p: Position) => <Num value={p.entryPrice} /> },
  { key: "current", header: "Current", num: true, cell: currentCell },
  { key: "stop", header: "Stop", num: true, cell: stopCell },
  { key: "target", header: "Target", num: true, cell: targetCell },
  { key: "pnl-pips", header: "P&L (pips)", num: true, cell: (p: Position) => pnlCell(p.pnlPips, p.pnlIsEstimate) },
  { key: "pnl-account", header: "P&L (account)", num: true, cell: (p: Position) => pnlCell(p.pnlAccount, p.pnlIsEstimate) },
  { key: "opened", header: "Opened", cell: (p: Position) => p.openTime == null ? <Num value={null} /> : <When ts={p.openTime} /> },
  { key: "id", header: "Position ID", cell: (p: Position) => <span className="dim">{p.positionId}</span> },
  { key: "details", header: "Details", cell: (p: Position) => <button className="btn btn-ghost btn-sm" onClick={() => onDetails(p)}>View details</button> },
 ];
}

const dealColumns = [
  { key: "symbol", header: "Symbol", cell: (d: ClosedTrade) => d.symbol ?? <Num value={null} /> },
  { key: "side", header: "Side", cell: (d: ClosedTrade) => d.side ? <Side side={d.side} /> : <Num value={null} /> },
  { key: "units", header: "Volume", num: true, cell: (d: ClosedTrade) => <Num value={d.units} /> },
  { key: "entry", header: "Entry", num: true, cell: (d: ClosedTrade) => <Num value={d.entry} /> },
  { key: "exit", header: "Exit", num: true, cell: (d: ClosedTrade) => <Num value={d.exit} /> },
  { key: "net", header: "Net", num: true, cell: (d: ClosedTrade) => <Num value={d.net} /> },
  { key: "closed", header: "Closed", cell: (d: ClosedTrade) => d.closedAt == null ? <Num value={null} /> : <When ts={d.closedAt} /> },
];

export default function PositionsPage() {
  // Only the id is kept. The row itself is looked up in the latest read, so
  // the detail shows what the broker last said and not a copy from the click.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lastSeen, setLastSeen] = useState<Position | null>(null);
  const r = useRead<PositionsRead>("positions", 5_000);
  const accountId = r.result?.ok ? r.result.data.accountId : undefined;
  const dealsPath = accountId ? `accounts/${accountId}/deals?days=7` : null;
  const deals = useRead<DealsRead>(dealsPath, 60_000);
  const rows = r.result?.ok ? (r.result.data.positions ?? []) : [];
  const live = selectedId == null ? null
    : rows.find((p) => String(p.positionId) === selectedId) ?? null;
  const knownPnl = rows.map((p) => p.pnlAccount).filter((v): v is number => v !== null && v !== undefined);
  const unknownPnl = rows.length - knownPnl.length;
  const totalPnl = unknownPnl === 0 ? knownPnl.reduce((sum, value) => sum + value, 0) : null;
  const summary = r.result?.ok
    ? `${rows.length} positions · ${unknownPnl > 0 ? `${unknownPnl} positions without a current price` : `Total estimated P&L ${totalPnl!.toFixed(2)}`}`
    : "Positions — · Total estimated P&L —";

  function openDetails(p: Position) {
    setSelectedId(String(p.positionId));
    setLastSeen(p);
  }

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Positions</h1>
          <span className="sub">{summary} · Last synced {whenSynced(r.lastSync)}</span>
        </div>
        <span className="btn-row">
          {r.result?.ok ? <><>{r.result.data.accountId ? <span className="pill pill-muted mono">#{r.result.data.accountId}</span> : null}</><StatusPill mode={r.result.data.mode} /></> : null}
          <button className="btn btn-ghost btn-sm" onClick={r.reload} disabled={r.loading}><RefreshCw className="ico" aria-hidden /> Refresh</button>
        </span>
      </div>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {selectedId != null && lastSeen ? (
        <PositionDetail
          position={live ?? lastSeen}
          accountId={accountId}
          mode={r.result?.ok ? r.result.data.mode : undefined}
          stillOpen={live !== null}
          onBack={() => { setSelectedId(null); setLastSeen(null); }}
          onClosed={() => void r.reload()}
        />
      ) : null}

      {r.result?.ok ? <section className="card"><ReadPanel read={r.result.data}>
        <DataTable<Position> rows={rows} rowKey={(p) => String(p.positionId)} empty="No open positions." cardTitle={(p) => p.symbol} cardBadge={(p) => <Side side={p.side} />} columns={positionColumns(openDetails)} />
      </ReadPanel></section> : null}

      {deals.result?.ok ? <section className="card"><div className="card-head"><h2>Closed trades · last 7 days</h2></div><ReadPanel read={deals.result.data}>
        <DataTable<ClosedTrade> rows={deals.result.data.deals ?? []} rowKey={(d) => String(d.positionId ?? `${d.symbol}-${d.closedAt}`)} empty="No closed trades in the last 7 days." cardTitle={(d) => d.symbol ?? "—"} cardBadge={(d) => d.side ? <Side side={d.side} /> : null} columns={dealColumns} />
      </ReadPanel></section> : null}
      {deals.result && !deals.result.ok ? <section className="card"><h2>Closed trades · last 7 days</h2><ErrorNotice error={deals.result} onRetry={deals.reload} /></section> : null}
    </main>
  );
}
