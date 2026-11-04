"use client";

import { useEffect, useMemo, useState } from "react";
import { Pause, Play, RefreshCw, ShieldCheck, SkipForward } from "lucide-react";
import type { ApiResult, Candle, CandlesRead, CtraderStatus, RuleSummary } from "@/lib/api";
import { api } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { PriceChart } from "@/components/chart/price-chart";
import { TIMEFRAMES } from "@/components/app/rule-form";

const DISCLAIMER = "Backtest results are hypothetical and do not predict future performance.";

function Head({ title, detail, reload, loading }: { title: string; detail: string; reload?: () => unknown; loading?: boolean }) {
  return <div className="page-head"><div><h1>{title}</h1><span className="sub">{detail}</span></div>{reload ? <button className="btn btn-ghost btn-sm" onClick={() => void reload()} disabled={loading}><RefreshCw className="ico" aria-hidden /> Refresh</button> : null}</div>;
}

function Failure({ result, retry }: { result: ApiResult<unknown> | null; retry?: () => unknown }) {
  return result && !result.ok ? <ErrorNotice error={result} onRetry={retry} /> : null;
}

function ReadStatus({ data, empty }: { data: CandlesRead | null; empty: string }) {
  if (!data) return null;
  if (data.status === "unavailable" || data.status === "reauth_required" || data.status === "not_connected") {
    return <div className="notice notice-error" role="alert"><strong>Market data could not be read</strong><p className="muted">{data.reason ?? "The broker did not answer."}</p></div>;
  }
  if (!data.candles?.length) return <p className="empty">{empty}</p>;
  return null;
}

function useCandleRead(symbol: string, timeframe: string, days: number) {
  const accounts = useRead<CtraderStatus>("accounts", 60_000);
  const ctid = accounts.result?.ok ? String(accounts.result.data.selected?.ctid ?? "") : "";
  const to = useMemo(() => Math.floor(Date.now() / 1000) - days * 86400, [days]);
  const path = ctid && symbol && timeframe
    ? `accounts/${encodeURIComponent(ctid)}/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=500&to=${to}`
    : null;
  const candles = useRead<CandlesRead>(path, 0);
  return { accounts, candles, ctid };
}

function AccountHint({ accounts }: { accounts: ReturnType<typeof useRead<CtraderStatus>> }) {
  const d = accounts.result?.ok ? accounts.result.data : null;
  if (accounts.loading && !accounts.result) return <Spinner label="Checking connected accounts" />;
  if (accounts.result && !accounts.result.ok) return <Failure result={accounts.result} retry={accounts.reload} />;
  if (!d || !d.connected || !d.accounts?.length) return <p className="empty">No connected account is available for this read.</p>;
  return <p className="muted">Using account {String(d.selected?.ctid ?? d.accounts[0]?.ctid)} · {d.selected?.mode ?? d.accounts[0]?.mode}</p>;
}

export function ReplayView() {
  const [symbol, setSymbol] = useState("EUR_USD");
  const [timeframe, setTimeframe] = useState("1h");
  const [days, setDays] = useState(7);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const { accounts, candles } = useCandleRead(symbol, timeframe, days);
  const data = candles.result?.ok ? candles.result.data : null;
  const bars = data?.status === "ok" ? (data.candles ?? []) : [];
  const visible = bars.slice(0, Math.max(0, cursor + 1));
  useEffect(() => { setCursor(Math.max(0, bars.length - 1)); setPlaying(false); }, [bars.length]);
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setCursor((n) => {
      if (n >= bars.length - 1) { setPlaying(false); return n; }
      return n + 1;
    }), 650);
    return () => window.clearInterval(id);
  }, [playing, bars.length]);
  return <main>
    <Head title="Strategy replay" detail="Read-only candle-by-candle inspection" reload={candles.reload} loading={candles.loading} />
    <p className="notice" role="note">{DISCLAIMER}</p>
    <section className="card">
      <div className="grid grid-3">
        <label>Symbol<input className="input" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label>
        <label>Timeframe<select className="input" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>{TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}</select></label>
        <label>Past window<select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={1}>1 day</option><option value={7}>7 days</option><option value={30}>30 days</option></select></label>
      </div>
      <AccountHint accounts={accounts} />
    </section>
    {candles.loading && !candles.result ? <Spinner label="Reading historical candles" /> : null}
    <Failure result={candles.result} retry={candles.reload} />
    <ReadStatus data={data} empty="The broker returned no candles for this window." />
    {bars.length ? <>
      <section className="card">
        <div className="card-head"><h2>Replay controls</h2><span className="muted">Bar {cursor + 1} of {bars.length}</span></div>
        <div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
          <button className="btn btn-ghost" onClick={() => setPlaying((v) => !v)}>{playing ? <Pause className="ico" aria-hidden /> : <Play className="ico" aria-hidden />}{playing ? "Pause" : "Play"}</button>
          <button className="btn btn-ghost" onClick={() => setCursor((n) => Math.min(n + 1, bars.length - 1))} disabled={cursor >= bars.length - 1}><SkipForward className="ico" aria-hidden /> Step</button>
          <button className="btn btn-ghost" onClick={() => { setCursor(0); setPlaying(false); }}>Restart</button>
        </div>
        <p className="muted" role="status">{visible.length ? "Data available at this replay point." : "No candle is available at this replay point."}</p>
      </section>
      <section className="card"><PriceChart candles={visible as Candle[]} symbol={symbol} timeframe={timeframe} height={340} /></section>
    </> : null}
  </main>;
}

type RuleRead = { rule: Record<string, unknown> };
type BacktestResult = { status: string; hypothetical: boolean; tradeCount: number; totalPnl: number; endingBalance: number | null; assumptions: Record<string, number>; notModelled: string[]; unit?: string; trades: { pnl: number }[] };
type OverfitResult = { status: string; warnings: string[]; disclaimer: string };
type RiskGuardResult = { allowed: boolean; mode: string; blocks: { guard: string; reason: string }[] };
type RuleLayerResult = { units: number; unitLabel: string; riskAmount: number };

export function BacktestView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const list = rules.result?.ok ? rules.result.data.rules : [];
  const [ruleId, setRuleId] = useState("");
  const [symbol, setSymbol] = useState("EUR_USD");
  const [timeframe, setTimeframe] = useState("1h");
  const [spread, setSpread] = useState("1.5");
  const [slippage, setSlippage] = useState("0.5");
  const [commission, setCommission] = useState("0");
  const [result, setResult] = useState<ApiResult<BacktestResult> | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!ruleId && list[0]) setRuleId(list[0].ruleDocId); }, [ruleId, list]);
  const selected = list.find((r) => r.ruleDocId === ruleId);
  useEffect(() => { if (selected?.symbols?.[0]) setSymbol(selected.symbols[0]); if (selected?.timeframe) setTimeframe(selected.timeframe); }, [selected]);
  const { accounts, candles } = useCandleRead(symbol, timeframe, 30);
  const rule = useRead<RuleRead>(ruleId ? `rules/${encodeURIComponent(ruleId)}` : null, 0);
  const candleData = candles.result?.ok ? candles.result.data : null;
  async function run() {
    if (!rule.result?.ok || candleData?.status !== "ok" || !candleData.candles?.length) return;
    setBusy(true);
    setResult(await api<BacktestResult>("backtest", { method: "POST", body: {
      rule: rule.result.data.rule, candles: candleData.candles, symbol, timeframe,
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
        <label>Rule<select className="input" value={ruleId} onChange={(e) => setRuleId(e.target.value)}>{list.map((r) => <option key={r.ruleDocId} value={r.ruleDocId}>{r.name}</option>)}</select></label>
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
    {result?.ok ? <section className="card" aria-live="polite">
      <div className="grid grid-3"><div className="stat"><span className="stat-k">Trades</span><strong className="stat-v">{result.data.tradeCount}</strong></div><div className="stat"><span className="stat-k">Net</span><strong className="stat-v">{result.data.totalPnl}</strong></div><div className="stat"><span className="stat-k">Ending balance</span><strong className="stat-v">{result.data.endingBalance == null ? "unknown" : result.data.endingBalance}</strong></div></div>
      {!result.data.tradeCount ? <p className="empty">The selected rule produced no hypothetical trades in this window.</p> : null}
      <h2>Assumptions</h2><ul className="plain-list">{Object.entries(result.data.assumptions).map(([k, v]) => <li key={k}><strong>{k}</strong> <span className="muted">{v}</span></li>)}</ul>
      <h2>Not modelled</h2><ul className="plain-list">{result.data.notModelled.map((v) => <li key={v}>{v}</li>)}</ul>
    </section> : null}
  </main>;
}

export function ForwardView() {
  const [symbol, setSymbol] = useState("EUR_USD");
  const [decision, setDecision] = useState("BUY");
  const [slippage, setSlippage] = useState("");
  const [events, setEvents] = useState<{ symbol?: string; decision?: string; execution?: string; slippage?: number | null }[]>([]);
  const [error, setError] = useState<ApiResult<unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  async function record() {
    setBusy(true); setError(null);
    const r = await api<{ events: typeof events }>("forward", { method: "POST", body: { signals: [{ symbol, decision, slippage: slippage === "" ? null : Number(slippage), timestamp: Math.floor(Date.now() / 1000) }] } });
    if (r.ok) setEvents((old) => [...old, ...(r.data.events ?? [])]); else setError(r);
    setBusy(false);
  }
  return <main><Head title="Forward testing" detail="Signals are recorded separately from hypothetical execution" /><p className="notice" role="note">Forward testing is hypothetical and does not place orders.</p><section className="card"><div className="grid grid-3"><label>Symbol<input className="input" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label><label>Decision<select className="input" value={decision} onChange={(e) => setDecision(e.target.value)}><option>BUY</option><option>SELL</option><option>HOLD</option></select></label><label>Hypothetical slippage (pips)<input className="input" inputMode="decimal" placeholder="unknown" value={slippage} onChange={(e) => setSlippage(e.target.value)} /></label></div><button className="btn" onClick={() => void record()} disabled={busy}>{busy ? "Recording…" : "Record signal"}</button></section><Failure result={error} />{busy ? <Spinner label="Recording hypothetical signal" /> : events.length ? <section className="card"><h2>Recorded signals</h2><ul className="plain-list">{events.map((e, i) => <li key={`${e.symbol}-${i}`}><strong>{e.symbol ?? "unknown symbol"}</strong> · {e.decision ?? "unknown decision"} · {e.execution ?? "unknown execution"} · slippage {e.slippage == null ? "unknown" : e.slippage}</li>)}</ul></section> : <p className="empty">No hypothetical signals recorded in this session.</p>}</main>;
}

export function OverfitView() {
  const [conditions, setConditions] = useState(""); const [trades, setTrades] = useState(""); const [periods, setPeriods] = useState(""); const [changed, setChanged] = useState(false); const [single, setSingle] = useState(false);
  const [result, setResult] = useState<ApiResult<{ status: string; warnings: string[]; disclaimer: string }> | null>(null); const [busy, setBusy] = useState(false);
  async function analyse() { setBusy(true); const r = await api<OverfitResult>("overfit", { method: "POST", body: { ...(conditions ? { conditionCount: Number(conditions) } : {}), ...(trades ? { tradeCount: Number(trades) } : {}), ...(periods ? { periodCount: Number(periods) } : {}), changedAfterLosses: changed, singleSymbol: single } }); setResult(r); setBusy(false); }
  return <main><Head title="Anti-overfitting assistant" detail="Evidence checks for a testing sample" /><p className="notice" role="note">This diagnostic does not generate signals or predict future performance.</p><section className="card"><div className="grid grid-3"><label>Conditions tested<input className="input" inputMode="numeric" placeholder="unknown" value={conditions} onChange={(e) => setConditions(e.target.value)} /></label><label>Trades in sample<input className="input" inputMode="numeric" placeholder="unknown" value={trades} onChange={(e) => setTrades(e.target.value)} /></label><label>Independent periods<input className="input" inputMode="numeric" placeholder="unknown" value={periods} onChange={(e) => setPeriods(e.target.value)} /></label></div><label><input type="checkbox" checked={changed} onChange={(e) => setChanged(e.target.checked)} /> Rule changed after losses</label><label><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> Single symbol only</label><button className="btn" onClick={() => void analyse()} disabled={busy}>{busy ? "Checking…" : "Check evidence"}</button></section><Failure result={result} />{busy ? <Spinner label="Checking evidence" /> : result?.ok ? <section className="card"><h2>{result.data.status === "warning" ? "Warnings" : "No obvious warning"}</h2>{result.data.warnings.length ? <ul className="plain-list">{result.data.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : <p className="empty">Not enough evidence to judge this strategy.</p>}<p className="muted">{result.data.disclaimer}</p></section> : <p className="empty">No evidence analysis has been run yet.</p>}</main>;
}

export function RiskGuardView() {
  const [stopAll, setStopAll] = useState(false); const [loss, setLoss] = useState(""); const [drawdown, setDrawdown] = useState(""); const [consecutive, setConsecutive] = useState(""); const [trades, setTrades] = useState("");
  const [result, setResult] = useState<ApiResult<{ allowed: boolean; mode: string; blocks: { guard: string; reason: string }[] }> | null>(null); const [busy, setBusy] = useState(false);
  async function evaluate() { setBusy(true); const number = (v: string) => v === "" ? undefined : Number(v); const r = await api<RiskGuardResult>("risk/guard", { method: "POST", body: { state: { stopAll, weeklyLossFraction: number(loss), drawdownFraction: number(drawdown), consecutiveLosses: number(consecutive), tradesToday: number(trades) } } }); setResult(r); setBusy(false); }
  return <main><Head title="Advanced risk guard" detail="A missing input blocks rather than appearing safe" /><section className="card"><label><input type="checkbox" checked={stopAll} onChange={(e) => setStopAll(e.target.checked)} /> Stop new entries and show a stop-all state</label><div className="grid grid-3"><label>Weekly loss fraction<input className="input" inputMode="decimal" placeholder="unknown" value={loss} onChange={(e) => setLoss(e.target.value)} /></label><label>Drawdown fraction<input className="input" inputMode="decimal" placeholder="unknown" value={drawdown} onChange={(e) => setDrawdown(e.target.value)} /></label><label>Consecutive losses<input className="input" inputMode="numeric" placeholder="unknown" value={consecutive} onChange={(e) => setConsecutive(e.target.value)} /></label></div><label>Trades today<input className="input" inputMode="numeric" placeholder="unknown" value={trades} onChange={(e) => setTrades(e.target.value)} /></label><button className="btn" onClick={() => void evaluate()} disabled={busy}>{busy ? "Evaluating…" : "Evaluate guard"}</button></section><Failure result={result} />{busy ? <Spinner label="Evaluating risk guard" /> : result?.ok ? <section className="card"><div className="stat"><span className="stat-k">Decision</span><strong className="stat-v"><ShieldCheck className="ico" aria-hidden /> {result.data.allowed ? "Ready" : "Blocked"}</strong></div>{result.data.blocks.length ? <ul className="plain-list">{result.data.blocks.map((b) => <li key={`${b.guard}-${b.reason}`}><strong>{b.guard}</strong> · {b.reason}</li>)}</ul> : <p className="empty">All supplied guards are within their limits.</p>}</section> : <p className="empty">No guard evaluation has been run yet.</p>}</main>;
}

export function RuleLayerView() {
  const [symbol, setSymbol] = useState("EUR_USD"); const [price, setPrice] = useState("1.1"); const [balance, setBalance] = useState(""); const [risk, setRisk] = useState("0.01"); const [stop, setStop] = useState(""); const [result, setResult] = useState<ApiResult<{ units: number; unitLabel: string; riskAmount: number }> | null>(null); const [busy, setBusy] = useState(false);
  async function calculate() { setBusy(true); const r = await api<RuleLayerResult>("rule-layer", { method: "POST", body: { symbol, price: Number(price), balance: balance === "" ? undefined : Number(balance), riskFraction: Number(risk), stopPips: stop === "" ? undefined : Number(stop) } }); setResult(r); setBusy(false); }
  return <main><Head title="Broker-agnostic rule layer" detail="One read-only risk-unit calculation across instruments" /><section className="card"><div className="grid grid-3"><label>Symbol<input className="input" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label><label>Price<input className="input" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></label><label>Balance<input className="input" inputMode="decimal" placeholder="unknown" value={balance} onChange={(e) => setBalance(e.target.value)} /></label></div><div className="grid grid-3"><label>Risk fraction<input className="input" inputMode="decimal" value={risk} onChange={(e) => setRisk(e.target.value)} /></label><label>Stop distance (pips)<input className="input" inputMode="decimal" placeholder="unknown" value={stop} onChange={(e) => setStop(e.target.value)} /></label></div><button className="btn" onClick={() => void calculate()} disabled={busy}>{busy ? "Calculating…" : "Calculate"}</button></section><Failure result={result} />{busy ? <Spinner label="Calculating risk units" /> : result?.ok ? <section className="card"><div className="grid grid-3"><div className="stat"><span className="stat-k">Units</span><strong className="stat-v">{result.data.units}</strong></div><div className="stat"><span className="stat-k">Unit label</span><strong className="stat-v">{result.data.unitLabel}</strong></div><div className="stat"><span className="stat-k">Risk amount</span><strong className="stat-v">{result.data.riskAmount}</strong></div></div><p className="muted">This calculation is informational and does not submit an order.</p></section> : <p className="empty">No risk-unit calculation has been run yet.</p>}</main>;
}
