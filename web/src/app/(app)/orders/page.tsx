"use client";
import { RefreshCw } from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import { DataTable, Num, Side } from "@/components/app/table";
import type { CtraderStatus, Order, OrdersRead } from "@/lib/api";

function OrdersBook({ path, title }: { path: string; title?: string }) {
  const r = useRead<OrdersRead>(path, 60_000);
  return (
    <main>
      <div className="page-head">
        <div>
          <h1>{title || "Orders"}</h1>
          <span className="sub">Last synced {whenSynced(r.lastSync)}</span>
        </div>
        <span className="btn-row">
          {r.result?.ok ? (
            <>
              {r.result.data.accountId ? (
                <span className="pill pill-muted mono">#{r.result.data.accountId}</span>
              ) : null}
              <StatusPill mode={r.result.data.mode} accountId={r.result.data.accountId} />
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
            <DataTable<Order>
              rows={r.result.data.orders ?? []}
              rowKey={(o) => String(o.orderId)}
              empty="No pending orders."
              cardTitle={(o) => o.symbol}
              cardBadge={(o) => <Side side={o.side} />}
              columns={[
                { key: "symbol", header: "Symbol", cell: (o) => o.symbol },
                { key: "side", header: "Side", cell: (o) => <Side side={o.side} />, hideOnCard: true },
                { key: "type", header: "Type", cell: (o) => o.orderType ?? <span className="dim">—</span> },
                { key: "status", header: "Status", cell: (o) => o.status
                    ? <span className="pill pill-muted">{o.status}</span>
                    : <span className="dim">—</span> },
                { key: "units", header: "Units", num: true, cell: (o) => <Num value={o.units} /> },
                { key: "limit", header: "Limit", num: true, cell: (o) => <Num value={o.limitPrice} /> },
                { key: "stop", header: "Stop", num: true, cell: (o) => <Num value={o.stopPrice} /> },
                { key: "id", header: "Order", cell: (o) => <span className="dim">{o.orderId}</span> },
              ]}
            />
          </ReadPanel>
        </section>
      ) : null}
    </main>
  );
}

export default function OrdersPage() {
  const ct = useRead<CtraderStatus>("ctrader/status", 60_000);
  const accounts = ct.result?.ok && Array.isArray(ct.result.data.accounts)
    ? ct.result.data.accounts : [];
  if (accounts.length) {
    return (
      <main>
        {accounts.map((a) => (
          <OrdersBook
            key={`${a.mode}-${a.ctid}`}
            path={`accounts/${encodeURIComponent(String(a.ctid))}/orders`}
            title={`${a.mode === "live" ? "Live" : "Demo"} #${a.ctid}`}
          />
        ))}
      </main>
    );
  }
  return <OrdersBook path="orders" />;
}
