"use client";
import {
  Activity, Plug, Receipt, ShieldCheck, TrendingUp, Wallet,
} from "lucide-react";
import { useRead, whenSynced } from "@/lib/use-api";
import {
  ErrorNotice, LicencePill, ReadPanel, Skeleton, Spinner, Stat, StatusPill,
} from "@/components/app/state";
import { DataTable, Num, Side, When } from "@/components/app/table";
import type {
  AutomationState, CtraderStatus, JournalPage, Me, NotificationPage,
  OrdersRead, PositionsRead, Position,
} from "@/lib/api";

/** The decision statuses that mean "the engine ran and chose not to act". */
const QUIET = new Set(["hold", "reject"]);

export default function Dashboard() {
  const me = useRead<Me>("me", 120_000);
  const ct = useRead<CtraderStatus>("accounts", 60_000);
  const auto = useRead<AutomationState>("automation", 30_000);
  const pos = useRead<PositionsRead>("positions", 30_000);
  const ord = useRead<OrdersRead>("orders", 60_000);
  const jr = useRead<JournalPage>("journal?limit=6", 60_000);
  const nt = useRead<NotificationPage>("notifications?limit=4", 60_000);

  const lastSync = Math.max(...[me, ct, auto, pos, ord].map((r) => r.lastSync ?? 0)) || null;

  const account = ct.result?.ok ? ct.result.data : null;
  const selected = account?.selected ?? null;
  const running = auto.result?.ok ? auto.result.data : null;
  const positions = pos.result?.ok && pos.result.data.status === "ok"
    ? pos.result.data.positions ?? [] : null;
  const orders = ord.result?.ok && ord.result.data.status === "ok"
    ? ord.result.data.orders ?? [] : null;

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <span className="sub">Last synced {whenSynced(lastSync)}</span>
        </div>
        {!account?.connected && ct.result?.ok ? (
          <a className="btn" href="/connect"><Plug className="ico" aria-hidden /> Connect cTrader</a>
        ) : null}
      </div>

      {/* ── the four numbers, before anything else ───────────────────── */}
      <div className="grid grid-4">
        <Stat
          label="Account"
          icon={Wallet}
          href={account?.connected ? "/accounts" : "/connect"}
          small={!selected}
          value={
            account === null ? <Skeleton w={90} />
              : !account.connected ? <span className="dim">Not connected</span>
              : selected ? <span className="mono">#{selected.ctid}</span>
              : <span className="dim">None selected</span>
          }
          foot={account?.connected
            ? <StatusPill mode={selected?.mode} />
            : <span>Orders are placed through an account you connect.</span>}
        />

        <Stat
          label="Automation"
          icon={Activity}
          tone={running?.state === "running" ? "accent" : undefined}
          href={running?.ruleDocId ? `/rules/${running.ruleDocId}` : "/rules"}
          value={running === null ? <Skeleton w={80} /> : running.state.toUpperCase()}
          foot={running?.ruleDocId
            ? <span className="mono">rule {running.ruleDocId.slice(0, 8)}</span>
            : <span>No rule running</span>}
        />

        <Stat
          label="Open positions"
          icon={TrendingUp}
          href="/positions"
          value={
            pos.result === null ? <Skeleton w={30} />
              : positions === null ? <span className="dim">—</span>
              : positions.length
          }
          foot={positions === null
            ? <span>{pos.result?.ok ? pos.result.data.reason ?? "Not available" : "Not available"}</span>
            : <span>Confirmed by the broker</span>}
        />

        <Stat
          label="Pending orders"
          icon={Receipt}
          href="/orders"
          value={
            ord.result === null ? <Skeleton w={30} />
              : orders === null ? <span className="dim">—</span>
              : orders.length
          }
          foot={orders === null
            ? <span>{ord.result?.ok ? ord.result.data.reason ?? "Not available" : "Not available"}</span>
            : <span>Waiting at the broker</span>}
        />
      </div>

      <div className="grid grid-main" style={{ marginTop: ".85rem" }}>
        <div>
          {/* ── positions ───────────────────────────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Open positions</h2>
              <a className="link-sm" href="/positions">All positions →</a>
            </div>
            {pos.result?.ok ? (
              <ReadPanel read={pos.result.data}>
                <DataTable<Position>
                  rows={pos.result.data.positions ?? []}
                  rowKey={(p) => String(p.positionId)}
                  /* An empty list only after status ok — so this sentence is a
                     fact the broker confirmed, not a guess. */
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
                  ]}
                />
              </ReadPanel>
            ) : pos.result && !pos.result.ok ? (
              <ErrorNotice error={pos.result} onRetry={pos.reload} />
            ) : <Spinner />}
          </section>

          {/* ── the journal, front and centre ───────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Recent decisions</h2>
              <a className="link-sm" href="/journal">Journal →</a>
            </div>
            <p className="muted" style={{ fontSize: ".8rem", marginBottom: ".6rem" }}>
              Including the evaluations that decided to do nothing.
            </p>
            {jr.result?.ok ? (
              jr.result.data.entries.length ? (
                <div className="records">
                  {jr.result.data.entries.map((e) => (
                    <div className="record" key={e.entryId}>
                      <div className="record-head">
                        <span className="record-title">
                          <span className={
                            e.decision?.verdict === "BUY" ? "side-long"
                              : e.decision?.verdict === "SELL" ? "side-short"
                              : undefined
                          }>
                            {e.decision?.verdict ?? e.status ?? e.kind}
                          </span>
                          {e.symbol ? <span className="muted"> · {e.symbol}</span> : null}
                        </span>
                        <span className="dim" style={{ fontSize: ".72rem" }}><When ts={e.ts} /></span>
                      </div>
                      <p className="muted" style={{ fontSize: ".8rem" }}>
                        {e.error ?? e.decision?.reason ?? e.status ?? "—"}
                      </p>
                      {e.status && QUIET.has(e.status) ? (
                        <span className="pill pill-muted" style={{ marginTop: ".4rem" }}>
                          No order placed
                        </span>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : <p className="empty">Nothing recorded yet.</p>
            ) : jr.result && !jr.result.ok ? <ErrorNotice error={jr.result} /> : <Spinner />}
          </section>
        </div>

        <div>
          {/* ── licence ─────────────────────────────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Licence</h2>
              <a className="link-sm" href="/license">Details →</a>
            </div>
            {me.result?.ok ? (
              <>
                <div className="btn-row">
                  <LicencePill state={me.result.data.licence.state} />
                  {me.result.data.licence.plan ? (
                    <span className="pill">{me.result.data.licence.plan}</span>
                  ) : null}
                </div>
                <p className="muted" style={{ marginTop: ".5rem", fontSize: ".82rem" }}>
                  {me.result.data.user.email}
                </p>
                {!me.result.data.user.emailVerified ? (
                  <div className="notice notice-warn" role="alert">
                    Confirm your email to activate rules.
                  </div>
                ) : null}
              </>
            ) : me.result && !me.result.ok ? (
              <ErrorNotice error={me.result} onRetry={me.reload} />
            ) : <Spinner />}
          </section>

          {/* ── pending orders ──────────────────────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Pending orders</h2>
              <a className="link-sm" href="/orders">All orders →</a>
            </div>
            {ord.result?.ok ? (
              <ReadPanel read={ord.result.data}>
                {orders?.length ? (
                  <div className="records">
                    {orders.slice(0, 4).map((o) => (
                      <div className="record" key={String(o.orderId)}>
                        <div className="record-head">
                          <span className="record-title">{o.symbol}</span>
                          <Side side={o.side} />
                        </div>
                        <div className="record-grid">
                          <div><span className="k">Type</span><span className="v">{o.orderType ?? "—"}</span></div>
                          <div><span className="k">Units</span><span className="v mono"><Num value={o.units} /></span></div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <p className="empty">No pending orders.</p>}
              </ReadPanel>
            ) : ord.result && !ord.result.ok ? <ErrorNotice error={ord.result} /> : <Spinner />}
          </section>

          {/* ── alerts ──────────────────────────────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Recent alerts</h2>
              <a className="link-sm" href="/notifications">All alerts →</a>
            </div>
            {nt.result?.ok ? (
              nt.result.data.notifications.length ? (
                <div className="records">
                  {nt.result.data.notifications.map((n) => (
                    <div className="record" key={n.id}
                         style={{ opacity: n.readAt ? 0.62 : 1 }}>
                      <div className="record-head">
                        <span className="record-title" style={{ fontSize: ".84rem" }}>{n.title}</span>
                        {n.level !== "info" ? (
                          <span className="pill pill-warn">{n.level}</span>
                        ) : null}
                      </div>
                      <span className="dim" style={{ fontSize: ".72rem" }}><When ts={n.ts} /></span>
                    </div>
                  ))}
                </div>
              ) : <p className="empty">No alerts.</p>
            ) : nt.result && !nt.result.ok ? <ErrorNotice error={nt.result} /> : <Spinner />}
          </section>

          {/* Demo-first, stated where the client is looking at their account,
              not only in a footer on the marketing page. */}
          <section className="card card-flat">
            <div className="card-head" style={{ marginBottom: ".4rem" }}>
              <h2 style={{ display: "flex", alignItems: "center", gap: ".4rem" }}>
                <ShieldCheck className="ico" aria-hidden style={{ width: 15, height: 15 }} />
                Demo first
              </h2>
            </div>
            <p className="muted" style={{ fontSize: ".8rem", lineHeight: 1.6 }}>
              Automation runs on demo accounts. Live trading is not enabled in
              this release, and nothing starts because you connected an
              account — starting is a separate, deliberate step.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
