"use client";

import { ShieldCheck } from "lucide-react";
import type { Candle } from "@/lib/api";
import { PriceChart } from "@/components/chart/price-chart";

export type BacktestResult = {
  status: string;
  hypothetical: boolean;
  tradeCount: number;
  totalPnl: number;
  endingBalance: number | null;
  assumptions: Record<string, number>;
  notModelled: string[];
  trades: { pnl: number; timestamp?: number; side?: string }[];
  netProfit?: number | null;
  maxDrawdown?: number | null;
  profitFactor?: number | null;
  expectancy?: number | null;
  averageWin?: number | null;
  averageLoss?: number | null;
  longestLosingStreak?: number | null;
  recoveryFactor?: number | null;
  equityCurve?: { index?: number; timestamp?: number; equity?: number | null; pnl?: number }[];
  resultsPerMonth?: { month: string; trades: number; pnl: number }[];
  longVsShort?: { long: { trades: number; pnl: number | null }; short: { trades: number; pnl: number | null } };
};

export type ForwardEvent = {
  symbol?: string;
  signal?: string;
  decision?: string;
  execution?: { status?: string; price?: number | null; slippage?: number | null };
};

export type OverfitResult = { status: string; warnings: string[]; disclaimer: string };
export type RiskGuardResult = { allowed: boolean; mode: string; blocks: { guard: string; reason: string }[]; state?: Record<string, unknown>; stopNewEntriesOnly?: boolean };
type RuleLayerMetadata = { minLot?: number | null; lotStep?: number | null; contractSize?: number | null; digits?: number | null; minimumStopDistancePips?: number | null; sources?: Record<string, string> };
export type RuleLayerResult =
  | { status: "unavailable"; reason: string; metadata?: RuleLayerMetadata }
  | { status?: "ok"; units: number; unitLabel: string; riskAmount: number; metadata?: RuleLayerMetadata };

function Metric({ label, value }: { label: string; value: unknown }) {
  return <div className="stat"><span className="stat-k">{label}</span><strong className="stat-v">{value == null ? "unknown" : String(value)}</strong></div>;
}

export function BacktestResultCard({ result, equityCandles }: { result: BacktestResult; equityCandles: Candle[] }) {
  return (
    <section className="card" aria-live="polite">
      <div className="grid grid-3">
        <Metric label="Trades" value={result.tradeCount} />
        <Metric label="Net profit" value={result.netProfit} />
        <Metric label="Max drawdown" value={result.maxDrawdown} />
        <Metric label="Profit factor" value={result.profitFactor} />
        <Metric label="Expectancy" value={result.expectancy} />
        <Metric label="Losing streak" value={result.longestLosingStreak} />
      </div>
      {equityCandles.length ? <><h2>Equity curve</h2><PriceChart candles={equityCandles} symbol="equity" timeframe="trade" height={260} /></> : null}
      <p className="muted">Ending balance: {result.endingBalance ?? "unknown"}; average win {result.averageWin ?? "unknown"}; average loss {result.averageLoss ?? "unknown"}; recovery factor {result.recoveryFactor ?? "unknown"}.</p>
      {!result.tradeCount ? <p className="empty">The selected rule produced no hypothetical trades in this window.</p> : null}
      <h2>Assumptions</h2>
      <ul className="plain-list">{Object.entries(result.assumptions).map(([key, value]) => <li key={key}><strong>{key}</strong> <span className="muted">{value}</span></li>)}</ul>
      <h2>Not modelled</h2>
      <ul className="plain-list">{result.notModelled.map((value) => <li key={value}>{value}</li>)}</ul>
    </section>
  );
}

export function ForwardLedger({ events }: { events: ForwardEvent[] }) {
  if (!events.length) return <p className="empty">No hypothetical signals recorded in this session.</p>;
  return (
    <section className="card">
      <h2>Signal ledger</h2>
      <div className="table-wrap"><table><thead><tr><th>Signal</th><th>Decision</th><th>Execution</th></tr></thead><tbody>
        {events.map((event, index) => <tr key={`${event.symbol ?? "unknown"}-${index}`}>
          <td>{event.signal ?? "unknown"}</td>
          <td>{event.decision ?? "unknown"}</td>
          <td>{event.execution?.status ?? "unknown"} · price {event.execution?.price ?? "unknown"} · slippage {event.execution?.slippage ?? "unknown"}</td>
        </tr>)}
      </tbody></table></div>
    </section>
  );
}

export function OverfitResultCard({ result }: { result: OverfitResult }) {
  return <section className="card"><h2>{result.status === "warning" ? "Warnings" : "No obvious warning"}</h2>{result.warnings.length ? <ul className="plain-list">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p className="empty">Not enough evidence to judge this strategy.</p>}<p className="muted">{result.disclaimer}</p></section>;
}

export function RiskGuardResultCard({ result }: { result: RiskGuardResult }) {
  return <section className="card"><div className="stat"><span className="stat-k">Decision</span><strong className="stat-v"><ShieldCheck className="ico" aria-hidden /> {result.allowed ? "Ready" : "Blocked"}</strong></div>{result.blocks.length ? <ul className="plain-list">{result.blocks.map((block) => <li key={`${block.guard}-${block.reason}`}><strong>{block.guard}</strong> · {block.reason}</li>)}</ul> : <p className="empty">Measured guards are within their limits.</p>}</section>;
}

export function RuleLayerResultCard({ result }: { result: RuleLayerResult }) {
  if (result.status === "unavailable") {
    return <div className="notice" role="alert"><p style={{ fontWeight: 600 }}>Rule layer could not be read</p><p className="muted">{result.reason}. No sizing or instrument value was calculated.</p></div>;
  }
  const metadata = result.metadata;
  const rows = [
    ["Minimum lot", metadata?.minLot], ["Lot step", metadata?.lotStep],
    ["Contract size", metadata?.contractSize], ["Digits", metadata?.digits],
    ["Minimum stop distance", metadata?.minimumStopDistancePips],
  ] as const;
  return <section className="card"><div className="grid grid-3"><Metric label="Units" value={result.units} /><Metric label="Unit label" value={result.unitLabel} /><Metric label="Risk amount" value={result.riskAmount} /></div><h2>Instrument metadata</h2><ul className="plain-list">{rows.map(([label, value]) => <li key={label}><strong>{label}</strong>: {value ?? "unknown"}{metadata?.sources?.[label] ? <span className="muted"> · {metadata.sources[label]}</span> : null}</li>)}</ul><p className="muted">This calculation is informational and does not submit an order.</p></section>;
}
