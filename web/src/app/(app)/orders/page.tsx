"use client";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import type { OrdersRead } from "@/lib/api";

export default function OrdersPage() {
  const r = useRead<OrdersRead>("orders", 60_000);
  return (
    <main>
      <div className="card-head">
        <h1>Orders</h1>
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
            {r.result.data.orders?.length ? (
              <div className="scroll-x">
                <table className="tbl">
                  <thead>
                    <tr><th>Order</th><th>Symbol</th><th>Side</th><th>Type</th><th>Status</th><th>Limit</th><th>Stop</th></tr>
                  </thead>
                  <tbody>
                    {r.result.data.orders.map((o) => (
                      <tr key={String(o.orderId)}>
                        <td className="mono">{o.orderId}</td>
                        <td>{o.symbol}</td><td>{o.side}</td>
                        <td>{o.orderType ?? "—"}</td><td>{o.status ?? "—"}</td>
                        <td className="mono">{o.limitPrice ?? "—"}</td>
                        <td className="mono">{o.stopPrice ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="empty">No pending orders.</p>}
          </ReadPanel>
        </section>
      ) : null}
    </main>
  );
}
