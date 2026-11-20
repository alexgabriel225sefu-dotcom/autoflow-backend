"use client";

import { useMemo, useState } from "react";
import type { ApiResult, CtraderStatus, RuleSummary } from "@/lib/api";
import { api } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { TIMEFRAMES } from "@/components/app/rule-form";
import { ReplayView } from "@/components/app/simulation-replay";
import {
  AccountHint, CandleReadStatus, SimulationFailure, SimulationHead, useCandleRead,
} from "@/components/app/simulation-shared";
import {
  BacktestResultCard, ForwardLedger, OverfitResultCard, RiskGuardResultCard, RuleLayerResultCard,
  type BacktestResult, type ForwardEvent, type OverfitResult, type RiskGuardResult, type RuleLayerResult,
} from "@/components/app/simulation-result-cards";

const DISCLAIMER = "Backtest results are hypothetical and do not predict future performance.";
const Head = SimulationHead;
const Failure = SimulationFailure;
const ReadStatus = CandleReadStatus;
export { ReplayView };

type RuleRead = { rule: Record<string, unknown> };
export function availableBacktestRules(rules: RuleSummary[] | undefined) {
  return (Array.isArray(rules) ? rules : []).filter((rule) => rule.state === "active");
}
export function BacktestView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const list = useMemo(() => (rules.result?.ok && Array.isArray(rules.result.data?.rules)
    ? availableBacktestRules(rules.result.data.rules)
    : []), [rules.result]);
  const [chosenRule, setRuleId] = useState("");
  const [symbolPick, setSymbol] = useState<string | null>(null);
  const [timeframePick, setTimeframe] = useState<string | null>(null);
  // Defaults come from the chosen rule; typing in a field overrides them.
  const ruleId = chosenRule || list[0]?.ruleDocId || "";
  const selected = list.find((r) => r.ruleDocId === ruleId);
  const symbol = symbolPick ?? selected?.symbols?.[0] ?? "EUR_USD";
  const timeframe = timeframePick ?? selected?.timeframe ?? "1h";
  const [spread, setSpread] = useState("1.5");
  const [slippage, setSlippage] = useState("0.5");
  const [commission, setCommission] = useState("0");
  const [result, setResult] = useState<ApiResult<BacktestResult> | null>(null);
  const [busy, setBusy] = useState(false);
  const { accounts, candles } = useCandleRead(symbol, timeframe, 30);
  const rule = useRead<RuleRead>(ruleId ? `rules/${encodeURIComponent(ruleId)}` : null, 0);
  const candleData = candles.result?.ok ? candles.result.data : null;
  const equityCandles = useMemo(() => (result?.ok ? (result.data.equityCurve ?? [])
    .filter((point): point is { equity: number; timestamp?: number } => typeof point.equity === "number")
    .map((point) => ({ open: point.equity, high: point.equity, low: point.equity,
      close: point.equity, time: point.timestamp })) : []), [result]);
  async function run() {
    if (!rule.result?.ok || candleData?.status !== "ok" || !candleData.candles?.length) return;
    setBusy(true);
    setResult(await api<BacktestResult>("backtest", { method: "POST", body: {
      ruleDocId: ruleId, candles: candleData.candles, symbol, timeframe,
      spreadPips: Number(spread), slippagePips: Number(slippage), commission: Number(commission),
    }}));
    setBusy(false);
  }
  return <main>
    <Head title="Realistic backtest" detail="Run a selected rule over a bounded historical window" />
    <p className="notice" role="note">{DISCLAIMER}</p>
    {rules.loading && !rules.result ? <Spinner label="Reading available rules" /> : null}
    <Failure result={rules.result} retry={rules.reload} />
    {rules.result?.ok && !list.length ? <p className="empty">No rule is available to backtest.</p> : null}
    {list.length ? <section className="card">
      <div className="grid grid-3">
        <label>Rule<select className="input" value={ruleId} onChange={(e) => { setRuleId(e.target.value); setSymbol(null); setTimeframe(null); }}>{list.map((r) => <option key={r.ruleDocId} value={r.ruleDocId}>{r.name}</option>)}</select></label>
        <label>Spread (pips)<input className="input" inputMode="decimal" value={spread} onChange={(e) => setSpread(e.target.value)} /></label>
        <label>Slippage (pips)<input className="input" inputMode="decimal" value={slippage} onChange={(e) => setSlippage(e.target.value)} /></label>
      </div>
      <div className="grid grid-3">
        <label>Symbol<input className="input" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label>
        <label>Timeframe<select className="input" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>{TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}</select></label>
        <label>Commission (price points)<input className="input" inputMode="decimal" value={commission} onChange={(e) => setCommission(e.target.value)} /></label>
      </div>
      <AccountHint accounts={accounts} />
      {rule.result && !rule.result.ok ? <Failure result={rule.result} retry={rule.reload} /> : null}
      <button className="btn" onClick={() => void run()} disabled={busy || candles.loading || !rule.result?.ok}>{busy ? "Running…" : "Run backtest"}</button>
    </section> : null}
    {candles.loading && !candles.result ? <Spinner label="Reading historical candles" /> : null}
    <Failure result={candles.result} retry={candles.reload} />
    <ReadStatus data={candleData} empty="The broker returned no candles for this window." />
    {result && !result.ok ? <ErrorNotice error={result} /> : null}
    {result?.ok ? <BacktestResultCard result={result.data} equityCandles={equityCandles} /> : null}
  </main>;
}

export function ForwardView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const active = useMemo(() => rules.result?.ok && Array.isArray(rules.result.data?.rules)
    ? rules.result.data.rules.find((rule) => rule.state === "active")
    : undefined, [rules.result]);
  const symbol = active?.symbols?.[0] ?? "";
  const { accounts, candles } = useCandleRead(symbol, active?.timeframe ?? "1h", 1);
  const latest = candles.result?.ok && candles.result.data.status === "ok"
    ? candles.result.data.candles?.slice(-1) ?? [] : [];
  const [events, setEvents] = useState<ForwardEvent[]>([]);
  const [error, setError] = useState<ApiResult<unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  async function record() {
    setBusy(true); setError(null);
    const result = await api<{ events?: ForwardEvent[] }>("forward", {
      method: "POST", body: { ...(active ? { ruleDocId: active.ruleDocId } : {}), candles: latest },
    });
    if (result.ok) setEvents((old) => [...(result.data.events ?? []), ...old]);
    else setError(result);
    setBusy(false);
  }
  return <main>
    <Head title="Forward testing" detail="Active-rule signals are recorded separately from hypothetical execution" />
    <p className="notice" role="note">Forward testing is hypothetical and does not place orders.</p>
    {rules.loading && !rules.result ? <Spinner label="Reading active rule" /> : null}
    {rules.result && !rules.result.ok ? <p className="muted">The active rule could not be read.</p> : null}
    {!active && rules.result?.ok ? <p className="empty">No active rule is available for this read.</p> : null}
    {active ? <section className="card">
      <p className="muted">Using {active.name || "active rule"} on {symbol}.</p>
      {accounts.loading && !accounts.result ? <Spinner label="Checking connected accounts" /> : null}
      {accounts.result && !accounts.result.ok ? <p className="muted">The connected account could not be read.</p> : null}
      {candles.loading && !candles.result ? <Spinner label="Reading the latest candle" /> : null}
      {candles.result && !candles.result.ok ? <p className="muted">The latest candle could not be read.</p> : null}
      <ReadStatus data={candles.result?.ok ? candles.result.data : null} empty="The latest candle could not be read." />
      <button className="btn" onClick={() => void record()} disabled={busy || !latest.length}>
        {busy ? "Recording…" : "Record signal"}
      </button>
    </section> : <section className="card"><button className="btn" onClick={() => void record()}>Record signal</button></section>}
    <Failure result={error} />
    {busy ? <Spinner label="Recording hypothetical signal" /> : <ForwardLedger events={events} />}
  </main>;
}

export function OverfitView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const active = useMemo(() => rules.result?.ok && Array.isArray(rules.result.data?.rules)
    ? rules.result.data.rules.find((rule) => rule.state === "active")
    : undefined, [rules.result]);
  const [result, setResult] = useState<ApiResult<OverfitResult> | null>(null);
  const [busy, setBusy] = useState(false);
  async function analyse() {
    setBusy(true);
    const next = await api<OverfitResult>("overfit", {
      method: "POST", body: active ? { ruleDocId: active.ruleDocId } : {},
    });
    setResult(next); setBusy(false);
  }
  return <main>
    <Head title="Anti-overfitting assistant" detail="Evidence is derived from the active rule and its history" />
    <p className="notice" role="note">This diagnostic does not generate signals or predict future performance.</p>
    {rules.loading && !rules.result ? <Spinner label="Reading active rule" /> : null}
    <Failure result={rules.result} retry={rules.reload} />
    {active ? <section className="card"><p className="muted">Analysing {active.name || "active rule"}; counts are read from the rule, versions and trade history.</p><button className="btn" onClick={() => void analyse()} disabled={busy}>{busy ? "Checking…" : "Check evidence"}</button></section> : <section className="card"><button className="btn" onClick={() => void analyse()} disabled={busy}>Check evidence</button><input className="input" placeholder="unknown" value="" readOnly aria-label="Derived evidence is read from the server" /></section>}
    {!active && rules.result?.ok ? <p className="empty">No active rule is available for this read.</p> : null}
    <Failure result={result} />
    {busy ? <Spinner label="Checking evidence" /> : result?.ok ? <OverfitResultCard result={result.data} /> : <p className="empty">No evidence analysis has been run yet.</p>}
  </main>;
}

export function RiskGuardView() {
  const accounts = useRead<CtraderStatus>("accounts", 60_000);
  const [result, setResult] = useState<ApiResult<RiskGuardResult> | null>(null);
  const [busy, setBusy] = useState(false);
  async function evaluate() {
    setBusy(true);
    const accountId = accounts.result?.ok ? accounts.result.data.selected?.ctid : undefined;
    const next = await api<RiskGuardResult>("risk/guard", { method: "POST", body: { accountId } });
    setResult(next); setBusy(false);
  }
  return <main>
    <Head title="Advanced risk guard" detail="Measured account state is evaluated fail-closed" />
    <section className="card"><AccountHint accounts={accounts} /><p className="muted">Weekly loss, drawdown, consecutive losses and trades today are read from broker trades and the journal. Unreadable inputs are named and block the guard.</p><p className="muted">Stop new entries only: displayed state. Stop-all is not changed by this screen.</p><button className="btn" onClick={() => void evaluate()} disabled={busy}>{busy ? "Evaluating…" : "Evaluate guard"}</button></section>
    <Failure result={accounts.result} retry={accounts.reload} /><Failure result={result} />
    {busy ? <Spinner label="Evaluating risk guard" /> : result?.ok ? <RiskGuardResultCard result={result.data} /> : <p className="empty">Nothing has been calculated yet.</p>}
  </main>;
}

export function RuleLayerView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const active = useMemo(() => rules.result?.ok && Array.isArray(rules.result.data?.rules)
    ? rules.result.data.rules.find((rule) => rule.state === "active")
    : undefined, [rules.result]);
  const symbol = active?.symbols?.[0] ?? "";
  const { accounts, candles } = useCandleRead(symbol, active?.timeframe ?? "1h", 1);
  const price = candles.result?.ok && candles.result.data.status === "ok"
    ? candles.result.data.candles?.[candles.result.data.candles.length - 1]?.close : undefined;
  const [result, setResult] = useState<ApiResult<RuleLayerResult> | null>(null);
  const [busy, setBusy] = useState(false);
  async function calculate() {
    if (!active || price == null) return;
    setBusy(true);
    const next = await api<RuleLayerResult>("rule-layer", {
      method: "POST", body: active && price != null ? { ruleDocId: active.ruleDocId, price } : {},
    });
    setResult(next); setBusy(false);
  }
  return <main>
    <Head title="Broker-agnostic rule layer" detail="Account and symbol metadata are read from the selected account" />
    {rules.loading && !rules.result ? <Spinner label="Reading active rule" /> : null}
    <Failure result={rules.result} retry={rules.reload} />
    {active ? <section className="card"><p className="muted">Symbol: {symbol}. Price and balance come from the selected account read.</p><AccountHint accounts={accounts} /><Failure result={candles.result} retry={candles.reload} /><button className="btn" onClick={() => void calculate()} disabled={busy}>{busy ? "Calculating…" : "Calculate"}</button></section> : <section className="card"><button className="btn" onClick={() => void calculate()} disabled={busy}>Calculate</button></section>}
    {!active && rules.result?.ok ? <p className="empty">No active rule is available for this read.</p> : null}
    <Failure result={result} />
    {busy ? <Spinner label="Calculating risk units" /> : result?.ok ? <RuleLayerResultCard result={result.data} /> : <p className="empty">Nothing has been calculated yet.</p>}
  </main>;
}
