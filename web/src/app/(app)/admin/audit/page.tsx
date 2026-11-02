"use client";
/**
 * Read-only audit of the cTrader accounts this platform has connected.
 *
 * The signed-in session is the only credential. The server answers 403
 * NOT_OPERATOR when that session is not an operator; this page then says so
 * and renders nothing that could be mistaken for a trading control.
 */
import { useEffect, useState } from "react";
import { api, type ApiError, type ApiResult } from "@/lib/api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { DataTable, Num, Side, type Column } from "@/components/app/table";
import { OverviewBand, type Tile } from "@/components/app/overview-band";
import { CurrencyTicker } from "@/components/app/currency-ticker";
import { AUDIT_DAY_CHOICES, DEFAULT_AUDIT_DAYS, auditDetailPaths } from "./range";

type Account = {
  ctidTraderAccountId: number;
  login: number | null;
  environment: string | null;
  broker: string | null;
  platformUserId: string;
  selected: boolean;
  status: string;
};

type Summary = {
  balance: number | null;
  leverage: number | null;
  broker: string | null;
  login: number | null;
  equity: number | null;
  equityKnown: boolean;
  unrealizedPnl: number | null;
  openPositions: number | null;
  environment?: string;
};

type PositionRow = {
  positionId: number;
  symbol: string | null;
  side: string | null;
  lots: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  openTime: string | null;
  placedByPlatform: boolean | null;
};

type PendingRow = {
  orderId: number;
  symbol: string | null;
  side: string | null;
  lots: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  openTime: string | null;
  placedByPlatform: boolean | null;
};

type DealRow = {
  dealId: number;
  time: string | null;
  symbol: string | null;
  side: string | null;
  lots: number | null;
  executionPrice: number | null;
  close: { net: number | null } | null;
  placedByPlatform: boolean | null;
  entry_sl_set: boolean | null;
  entry_tp_set: boolean | null;
};

type OrderRow = {
  orderId: number;
  time: string | null;
  symbol: string | null;
  side: string | null;
  lots: number | null;
  price: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  placedByPlatform: boolean | null;
};

type Details = {
  summary: ApiResult<{ account: Summary }>;
  open: ApiResult<{ positions: PositionRow[]; pendingOrders: PendingRow[] }>;
  deals: ApiResult<{ deals: DealRow[]; from?: string; to?: string; timezone?: string; truncated?: boolean }>;
  orders: ApiResult<{ orders: OrderRow[]; truncated?: boolean }>;
};

function wall(iso: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace(/(?:Z|[+-]\d{2}:\d{2})$/, "");
}

function origin(value: boolean | null) {
  if (value === true) return <span className="pill pill-accent">Platform</span>;
  if (value === false) return <span>Manual</span>;
  return <span className="dim">Unknown</span>;
}

function flag(value: boolean | null) {
  if (value === true) return <span className="pill pill-ok">Yes</span>;
  if (value === false) return <span className="pill pill-warn">No</span>;
  return <span className="dim">—</span>;
}

function operatorOnly(error: ApiError | null): error is ApiError {
  return !!error && error.status === 403 && error.code === "NOT_OPERATOR";
}

const dealColumns: Column<DealRow>[] = [
  { key: "time", header: "Time", cell: (d) => <time dateTime={d.time ?? undefined}>{wall(d.time)}</time> },
  { key: "symbol", header: "Symbol", cell: (d) => d.symbol ?? "—" },
  { key: "side", header: "Side", cell: (d) => d.side ? <Side side={d.side} /> : "—" },
  { key: "lots", header: "Lots", num: true, cell: (d) => <Num value={d.lots} /> },
  { key: "price", header: "Price", num: true, cell: (d) => <Num value={d.executionPrice} /> },
  { key: "net", header: "Net P/L", num: true, cell: (d) => <Num value={d.close?.net} /> },
  { key: "by", header: "placedByPlatform", cell: (d) => origin(d.placedByPlatform) },
  { key: "sl", header: "entry_sl_set", cell: (d) => flag(d.entry_sl_set) },
  { key: "tp", header: "entry_tp_set", cell: (d) => flag(d.entry_tp_set) },
];

const positionColumns: Column<PositionRow>[] = [
  { key: "symbol", header: "Symbol", cell: (p) => p.symbol ?? "—" },
  { key: "side", header: "Side", cell: (p) => p.side ? <Side side={p.side} /> : "—" },
  { key: "lots", header: "Lots", num: true, cell: (p) => <Num value={p.lots} /> },
  { key: "entry", header: "Entry", num: true, cell: (p) => <Num value={p.entryPrice} /> },
  { key: "sl", header: "Stop", num: true, cell: (p) => <Num value={p.stopLoss} /> },
  { key: "tp", header: "Target", num: true, cell: (p) => <Num value={p.takeProfit} /> },
  { key: "open", header: "Open time", cell: (p) => wall(p.openTime) },
  { key: "by", header: "placedByPlatform", cell: (p) => origin(p.placedByPlatform) },
];

const pendingColumns: Column<PendingRow>[] = [
  { key: "symbol", header: "Symbol", cell: (p) => p.symbol ?? "—" },
  { key: "side", header: "Side", cell: (p) => p.side ? <Side side={p.side} /> : "—" },
  { key: "lots", header: "Lots", num: true, cell: (p) => <Num value={p.lots} /> },
  { key: "entry", header: "Entry", num: true, cell: (p) => <Num value={p.entryPrice} /> },
  { key: "sl", header: "Stop", num: true, cell: (p) => <Num value={p.stopLoss} /> },
  { key: "tp", header: "Target", num: true, cell: (p) => <Num value={p.takeProfit} /> },
  { key: "open", header: "Open time", cell: (p) => wall(p.openTime) },
  { key: "by", header: "placedByPlatform", cell: (p) => origin(p.placedByPlatform) },
];

const orderColumns: Column<OrderRow>[] = [
  { key: "time", header: "Time", cell: (o) => wall(o.time) },
  { key: "symbol", header: "Symbol", cell: (o) => o.symbol ?? "—" },
  { key: "side", header: "Side", cell: (o) => o.side ? <Side side={o.side} /> : "—" },
  { key: "lots", header: "Lots", num: true, cell: (o) => <Num value={o.lots} /> },
  { key: "price", header: "Price", num: true, cell: (o) => <Num value={o.price} /> },
  { key: "sl", header: "Stop", num: true, cell: (o) => <Num value={o.stopLoss} /> },
  { key: "tp", header: "Target", num: true, cell: (o) => <Num value={o.takeProfit} /> },
  { key: "by", header: "placedByPlatform", cell: (o) => origin(o.placedByPlatform) },
];

export default function AuditPage() {
  const [days, setDays] = useState(DEFAULT_AUDIT_DAYS);
  const [tick, setTick] = useState(0);
  const [accounts, setAccounts] = useState<ApiResult<{ accounts: Account[] }> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<(Details & { key: string }) | null>(null);

  useEffect(() => {
    let live = true;
    api<{ accounts: Account[] }>("admin/audit/accounts").then((result) => {
      if (!live) return;
      setAccounts(result);
      if (result.ok) {
        const first = result.data.accounts[0];
        setSelected((cur) => cur ?? (first ? String(first.ctidTraderAccountId) : null));
      }
    });
    return () => { live = false; };
  }, [tick]);

  useEffect(() => {
    if (!selected) return;
    let live = true;
    const key = `${selected}:${days}:${tick}`;
    const paths = auditDetailPaths(selected, days);
    Promise.all([
      api<{ account: Summary }>(paths.summary),
      api<{ positions: PositionRow[]; pendingOrders: PendingRow[] }>(paths.open),
      api<{ deals: DealRow[]; from?: string; to?: string; timezone?: string; truncated?: boolean }>(paths.deals),
      api<{ orders: OrderRow[]; truncated?: boolean }>(paths.orders),
    ]).then(([summary, open, deals, orders]) => {
      if (!live) return;
      setDetails({ summary, open, deals, orders, key });
    });
    return () => { live = false; };
  }, [selected, days, tick]);

  const shown = details && details.key === `${selected}:${days}:${tick}` ? details : null;

  const listError = accounts && !accounts.ok ? accounts : null;
  const denied = operatorOnly(listError)
    || operatorOnly(details?.summary && !details.summary.ok ? details.summary : null);

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Audit</h1>
          <span className="sub">
            What the platform placed on a connected cTrader account. Read only.
          </span>
        </div>
        {accounts?.ok ? (
          <button className="btn btn-ghost btn-sm" type="button" onClick={() => setTick((n) => n + 1)}>
            Refresh
          </button>
        ) : null}
      </div>

      {denied ? (
        <section className="notice" role="status">
          <p style={{ fontWeight: 600 }}>Operators only</p>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            This page is limited to an operator. The signed-in session is not one.
          </p>
        </section>
      ) : (
        <>
          {!accounts ? <Spinner /> : null}
          {listError ? <ErrorNotice error={listError} onRetry={() => setTick((n) => n + 1)} /> : null}
          {accounts?.ok ? (
            <section className="card" aria-label="Connected accounts">
              <div className="card-head"><h2>Connected accounts</h2></div>
              {accounts.data.accounts.length ? (
                <ul className="plain-list">
                  {accounts.data.accounts.map((account) => {
                    const id = String(account.ctidTraderAccountId);
                    const current = selected === id;
                    return (
                      <li key={`${account.platformUserId}:${id}`}>
                        <button
                          type="button"
                          className={current ? "btn btn-sm" : "btn btn-ghost btn-sm"}
                          aria-pressed={current}
                          onClick={() => setSelected(id)}
                        >
                          #{id}
                        </button>
                        {" "}
                        <span className={account.environment === "live" ? "pill pill-live" : "pill pill-demo"}>
                          {account.environment === "live" ? "LIVE" : account.environment === "demo" ? "DEMO" : "UNKNOWN"}
                        </span>
                        {" "}
                        <span className="muted">{account.broker ?? "Broker not read"}</span>
                        {" "}
                        <span className="dim">login {account.login ?? "—"}</span>
                        {account.status !== "ok" ? <span className="pill pill-warn">{account.status}</span> : null}
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="empty">No connected cTrader accounts.</p>}
            </section>
          ) : null}

          {selected && accounts?.ok ? (
            <>
              <section className="card">
                <label className="field" style={{ marginBottom: 0 }}>
                  <span>Range</span>
                  <select
                    aria-label="Range"
                    value={days}
                    onChange={(event) => setDays(Number(event.target.value))}
                  >
                    {AUDIT_DAY_CHOICES.map((choice) => (
                      <option key={choice} value={choice}>
                        Last {choice} days
                      </option>
                    ))}
                  </select>
                </label>
              </section>
              {!shown ? <Spinner /> : <AccountAudit details={shown} />}
            </>
          ) : null}
        </>
      )}
    </main>
  );
}

function AccountAudit({ details }: { details: Details }) {
  const summary = details.summary.ok ? details.summary.data.account : null;
  const tiles: Tile[] = summary ? [
    { label: "Balance", value: summary.balance == null ? null : <CurrencyTicker value={summary.balance} /> },
    { label: "Leverage", value: summary.leverage == null ? null : `1:${summary.leverage}` },
    { label: "Broker", value: summary.broker },
    {
      label: "Equity",
      value: summary.equityKnown ? <CurrencyTicker value={summary.equity} /> : null,
      note: summary.equityKnown
        ? "Balance plus unrealized P/L"
        : "Unrealized P/L is not on this read",
    },
  ] : [
    { label: "Balance", value: null },
    { label: "Leverage", value: null },
    { label: "Broker", value: null },
    { label: "Equity", value: null },
  ];

  return (
    <>
      {!details.summary.ok ? <ErrorNotice error={details.summary} /> : <OverviewBand tiles={tiles} />}
      <section className="card">
        <div className="card-head"><h2>Open positions</h2></div>
        {!details.open.ok ? <ErrorNotice error={details.open} /> : (
          <DataTable
            columns={positionColumns}
            rows={details.open.data.positions ?? []}
            rowKey={(row) => String(row.positionId)}
            empty="No open positions."
          />
        )}
      </section>
      <section className="card">
        <div className="card-head"><h2>Pending orders</h2></div>
        {!details.open.ok ? null : (
          <DataTable
            columns={pendingColumns}
            rows={details.open.data.pendingOrders ?? []}
            rowKey={(row) => String(row.orderId)}
            empty="No pending orders."
          />
        )}
      </section>
      <section className="card">
        <div className="card-head">
          <h2>Deals</h2>
          {details.deals.ok ? (
            <span className="dim" style={{ fontSize: ".75rem" }}>
              {details.deals.data.timezone ?? "Europe/Amsterdam"}
              {details.deals.data.from ? ` · ${wall(details.deals.data.from)}` : ""}
              {details.deals.data.to ? ` – ${wall(details.deals.data.to)}` : ""}
            </span>
          ) : null}
        </div>
        {details.deals.ok && details.deals.data.truncated ? (
          <p className="notice notice-warn" role="status">This range was longer than could be read in full.</p>
        ) : null}
        {!details.deals.ok ? <ErrorNotice error={details.deals} /> : (
          <DataTable
            columns={dealColumns}
            rows={details.deals.data.deals ?? []}
            rowKey={(row) => String(row.dealId)}
            empty="No deals in this range."
          />
        )}
      </section>
      <section className="card">
        <div className="card-head"><h2>Orders</h2></div>
        {!details.orders.ok ? <ErrorNotice error={details.orders} /> : (
          <DataTable
            columns={orderColumns}
            rows={details.orders.data.orders ?? []}
            rowKey={(row) => String(row.orderId)}
            empty="No orders in this range."
          />
        )}
      </section>
    </>
  );
}
