"use client";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, LicencePill, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import type {
  AutomationState, CtraderStatus, JournalPage, Me, NotificationPage,
  OrdersRead, PositionsRead,
} from "@/lib/api";

export default function Dashboard() {
  const me = useRead<Me>("me", 120_000);
  const ct = useRead<CtraderStatus>("accounts", 60_000);
  const auto = useRead<AutomationState>("automation", 30_000);
  const pos = useRead<PositionsRead>("positions", 30_000);
  const ord = useRead<OrdersRead>("orders", 60_000);
  const jr = useRead<JournalPage>("journal?limit=1", 60_000);
  const nt = useRead<NotificationPage>("notifications?limit=3", 60_000);

  const lastSync = Math.max(
    ...[me, ct, auto, pos, ord].map((r) => r.lastSync ?? 0),
  ) || null;

  return (
    <main>
      <div className="card-head">
        <h1>Dashboard</h1>
        <span className="muted">Last synced {whenSynced(lastSync)}</span>
      </div>

      <div className="grid grid-3">
        <section className="card">
          <h2>Account</h2>
          {ct.loading && !ct.result ? <Spinner /> : null}
          {ct.result && !ct.result.ok ? <ErrorNotice error={ct.result} onRetry={ct.reload} /> : null}
          {ct.result?.ok ? (
            ct.result.data.connected ? (
              <>
                <p className="mono">
                  {ct.result.data.selected
                    ? `#${ct.result.data.selected.ctid}`
                    : "No account selected"}
                </p>
                <StatusPill mode={ct.result.data.selected?.mode} />
                {!ct.result.data.selected ? (
                  <p><a className="btn btn-ghost" href="/accounts">Choose an account</a></p>
                ) : null}
              </>
            ) : (
              /* Never "connected" unless the API says so. */
              <>
                <p className="muted">Not connected</p>
                <a className="btn" href="/connect">Connect cTrader</a>
              </>
            )
          ) : null}
        </section>

        <section className="card">
          <h2>Licence</h2>
          {me.result?.ok ? (
            <>
              <LicencePill state={me.result.data.licence.state} />
              <p className="muted">{me.result.data.user.email}</p>
              {!me.result.data.user.emailVerified ? (
                <p className="notice notice-warn">Confirm your email to activate rules.</p>
              ) : null}
              <p><a href="/license">Licence details</a></p>
            </>
          ) : me.result && !me.result.ok ? (
            <ErrorNotice error={me.result} onRetry={me.reload} />
          ) : <Spinner />}
        </section>

        <section className="card">
          <h2>Automation</h2>
          {auto.result?.ok ? (
            <>
              <p className="verdict">{auto.result.data.state.toUpperCase()}</p>
              {auto.result.data.mode ? <StatusPill mode={auto.result.data.mode} /> : null}
              <p className="muted">
                {auto.result.data.ruleDocId
                  ? `Rule ${auto.result.data.ruleDocId.slice(0, 8)}`
                  : "No rule running"}
              </p>
              <p><a href="/rules">Manage rules</a></p>
            </>
          ) : auto.result && !auto.result.ok ? (
            <ErrorNotice error={auto.result} onRetry={auto.reload} />
          ) : <Spinner />}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Open positions</h2>
          <a href="/positions">All positions</a>
        </div>
        {pos.result?.ok ? (
          <ReadPanel read={pos.result.data}>
            {pos.result.data.positions?.length ? (
              <div className="scroll-x">
                <table className="tbl">
                  <thead><tr><th>Symbol</th><th>Side</th><th>Units</th><th>Entry</th></tr></thead>
                  <tbody>
                    {pos.result.data.positions.map((p) => (
                      <tr key={String(p.positionId)}>
                        <td>{p.symbol}</td><td>{p.side}</td>
                        <td className="mono">{p.units}</td>
                        <td className="mono">{p.entryPrice ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              /* An empty list only after status ok — so this sentence is a
                 fact the broker confirmed, not a guess. */
              <p className="empty">No open positions.</p>
            )}
          </ReadPanel>
        ) : pos.result && !pos.result.ok ? (
          <ErrorNotice error={pos.result} onRetry={pos.reload} />
        ) : <Spinner />}
      </section>

      <div className="grid grid-2">
        <section className="card">
          <div className="card-head"><h2>Pending orders</h2><a href="/orders">All orders</a></div>
          {ord.result?.ok ? (
            <ReadPanel read={ord.result.data}>
              {ord.result.data.orders?.length
                ? <p>{ord.result.data.orders.length} pending</p>
                : <p className="empty">No pending orders.</p>}
            </ReadPanel>
          ) : ord.result && !ord.result.ok ? <ErrorNotice error={ord.result} /> : <Spinner />}
        </section>

        <section className="card">
          <div className="card-head"><h2>Last decision</h2><a href="/journal">Journal</a></div>
          {jr.result?.ok ? (
            jr.result.data.entries.length ? (
              <>
                <p className="verdict">{jr.result.data.entries[0].status}</p>
                <p className="muted">
                  {jr.result.data.entries[0].symbol ?? "—"} ·{" "}
                  {new Date(jr.result.data.entries[0].ts * 1000).toLocaleString()}
                </p>
              </>
            ) : <p className="empty">Nothing recorded yet.</p>
          ) : jr.result && !jr.result.ok ? <ErrorNotice error={jr.result} /> : <Spinner />}
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>Recent alerts</h2><a href="/notifications">All alerts</a></div>
        {nt.result?.ok ? (
          nt.result.data.notifications.length ? (
            <ul>
              {nt.result.data.notifications.map((n) => (
                <li key={n.id}>
                  <strong>{n.title}</strong>{" "}
                  <span className="muted">{new Date(n.ts * 1000).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          ) : <p className="empty">No alerts.</p>
        ) : nt.result && !nt.result.ok ? <ErrorNotice error={nt.result} /> : <Spinner />}
      </section>
    </main>
  );
}
