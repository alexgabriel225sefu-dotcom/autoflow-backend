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
  return result && !result.ok ? <div><p className="muted">Could not be read.</p><ErrorNotice error={result} onRetry={retry} /></div> : null;
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
  // Captured once when the screen opens; the window is measured back from then.
  const [openedAt] = useState(() => Math.floor(Date.now() / 1000));
  const to = openedAt - days * 86400;
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
  // The position and the play state belong to one set of bars. When the bars
  // change, both fall back to the end and to paused without an effect.
  const [pos, setPos] = useState<{ n: number; len: number } | null>(null);
  const [playingFor, setPlayingFor] = useState<number | null>(null);
  const { accounts, candles } = useCandleRead(symbol, timeframe, days);
  const data = candles.result?.ok ? candles.result.data : null;
  const bars = data?.status === "ok" ? (data.candles ?? []) : [];
  const last = Math.max(0, bars.length - 1);
  const cursor = pos && pos.len === bars.length ? pos.n : last;
  const playing = playingFor === bars.length && bars.length > 0 && cursor < last;
  const setCursor = (fn: (n: number) => number) => setPos({ n: fn(cursor), len: bars.length });
  const setPlaying = (fn: (v: boolean) => boolean) => setPlayingFor(fn(playing) ? bars.length : null);
  const visible = bars.slice(0, Math.max(0, cursor + 1));
  useEffect(() => {
    if (!playing) return;
    const len = bars.length;
    const id = window.setInterval(() => setPos((p) => {
      const at = p && p.len === len ? p.n : last;
      return { n: Math.min(at + 1, last), len };
    }), 650);
    return () => window.clearInterval(id);
  }, [playing, bars.length, last]);
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
          <button className="btn btn-ghost" onClick={() => setCursor((n) => Math.min(n + 1, last))} disabled={cursor >= last}><SkipForward className="ico" aria-hidden /> Step</button>
          <button className="btn btn-ghost" onClick={() => { setCursor(() => 0); setPlaying(() => false); }}>Restart</button>
        </div>
        <p className="muted" role="status">{visible.length ? "Data available at this replay point." : "No candle is available at this replay point."}</p>
      </section>
      <section className="card"><PriceChart candles={visible as Candle[]} symbol={symbol} timeframe={timeframe} height={340} /></section>
    </> : null}
  </main>;
}

type RuleRead = { rule: Record<string, unknown> };
type BacktestResult = { status: string; hypothetical: boolean; tradeCount: number; totalPnl: number; endingBalance: number | null; assumptions: Record<string, number>; notModelled: string[]; unit?: string; trades: { pnl: number; timestamp?: number; side?: string }[]; netProfit?: number | null; maxDrawdown?: number | null; profitFactor?: number | null; expectancy?: number | null; averageWin?: number | null; averageLoss?: number | null; longestLosingStreak?: number | null; recoveryFactor?: number | null; equityCurve?: { index?: number; timestamp?: number; equity?: number | null; pnl?: number }[]; resultsPerMonth?: { month: string; trades: number; pnl: number }[]; longVsShort?: { long: { trades: number; pnl: number | null }; short: { trades: number; pnl: number | null } } };
type OverfitResult = { status: string; warnings: string[]; disclaimer: string };
type RiskGuardResult = { allowed: boolean; mode: string; blocks: { guard: string; reason: string }[]; state?: Record<string, unknown>; stopNewEntriesOnly?: boolean };
type RuleLayerResult = { units: number; unitLabel: string; riskAmount: number; metadata?: { minLot?: number | null; lotStep?: number | null; contractSize?: number | null; digits?: number | null; minimumStopDistancePips?: number | null; sources?: Record<string, string> } };

export function BacktestView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const list = useMemo(() => (rules.result?.ok && Array.isArray(rules.result.data?.rules) ? rules.result.data.rules : []), [rules.result]);
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
    {result?.ok ? <section className="card" aria-live="polite">
      <div className="grid grid-3"><div className="stat"><span className="stat-k">Trades</span><strong className="stat-v">{result.data.tradeCount}</strong></div><div className="stat"><span className="stat-k">Net profit</span><strong className="stat-v">{result.data.netProfit ?? "unknown"}</strong></div><div className="stat"><span className="stat-k">Max drawdown</span><strong className="stat-v">{result.data.maxDrawdown ?? "unknown"}</strong></div></div>
      <div className="grid grid-3"><div className="stat"><span className="stat-k">Profit factor</span><strong className="stat-v">{result.data.profitFactor ?? "unknown"}</strong></div><div className="stat"><span className="stat-k">Expectancy</span><strong className="stat-v">{result.data.expectancy ?? "unknown"}</strong></div><div className="stat"><span className="stat-k">Losing streak</span><strong className="stat-v">{result.data.longestLosingStreak ?? "unknown"}</strong></div></div>
      {equityCandles.length ? <><h2>Equity curve</h2><PriceChart candles={equityCandles} symbol="equity" timeframe="trade" height={260} /></> : null}
      <p className="muted">Ending balance: {result.data.endingBalance == null ? "unknown" : result.data.endingBalance}; average win {result.data.averageWin ?? "unknown"}; average loss {result.data.averageLoss ?? "unknown"}; recovery factor {result.data.recoveryFactor ?? "unknown"}.</p>
      {!result.data.tradeCount ? <p className="empty">The selected rule produced no hypothetical trades in this window.</p> : null}
      <h2>Assumptions</h2><ul className="plain-list">{Object.entries(result.data.assumptions).map(([k, v]) => <li key={k}><strong>{k}</strong> <span className="muted">{v}</span></li>)}</ul>
      <h2>Not modelled</h2><ul className="plain-list">{result.data.notModelled.map((v) => <li key={v}>{v}</li>)}</ul>
    </section> : null}
  </main>;
}

type ForwardEvent = { symbol?: string; signal?: string; decision?: string; execution?: { status?: string; price?: number | null; slippage?: number | null } };

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
    <Failure result={rules.result} retry={rules.reload} />
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
    {busy ? <Spinner label="Recording hypothetical signal" /> : events.length ? <section className="card">
      <h2>Signal ledger</h2>
      <div className="table-wrap"><table><thead><tr><th>Signal</th><th>Decision</th><th>Execution</th></tr></thead><tbody>
        {events.map((event, index) => <tr key={`${event.symbol ?? "unknown"}-${index}`}>
          <td>{event.signal ?? "unknown"}</td><td>{event.decision ?? "unknown"}</td>
          <td>{event.execution?.status ?? "unknown"} · price {event.execution?.price ?? "unknown"} · slippage {event.execution?.slippage ?? "unknown"}</td>
        </tr>)}
      </tbody></table></div>
    </section> : <p className="empty">No hypothetical signals recorded in this session.</p>}
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
    {busy ? <Spinner label="Checking evidence" /> : result?.ok ? <section className="card"><h2>{result.data.status === "warning" ? "Warnings" : "No obvious warning"}</h2>{result.data.warnings.length ? <ul className="plain-list">{result.data.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : <p className="empty">Not enough evidence to judge this strategy.</p>}<p className="muted">{result.data.disclaimer}</p></section> : <p className="empty">No evidence analysis has been run yet.</p>}
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
    {busy ? <Spinner label="Evaluating risk guard" /> : result?.ok ? <section className="card"><div className="stat"><span className="stat-k">Decision</span><strong className="stat-v"><ShieldCheck className="ico" aria-hidden /> {result.data.allowed ? "Ready" : "Blocked"}</strong></div>{result.data.blocks.length ? <ul className="plain-list">{result.data.blocks.map((b) => <li key={`${b.guard}-${b.reason}`}><strong>{b.guard}</strong> · {b.reason}</li>)}</ul> : <p className="empty">Measured guards are within their limits.</p>}</section> : <p className="empty">Nothing has been calculated yet.</p>}
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
    {busy ? <Spinner label="Calculating risk units" /> : result?.ok ? <section className="card"><div className="grid grid-3"><div className="stat"><span className="stat-k">Units</span><strong className="stat-v">{result.data.units}</strong></div><div className="stat"><span className="stat-k">Unit label</span><strong className="stat-v">{result.data.unitLabel}</strong></div><div className="stat"><span className="stat-k">Risk amount</span><strong className="stat-v">{result.data.riskAmount}</strong></div></div><h2>Instrument metadata</h2><ul className="plain-list"><li>Minimum lot: {result.data.metadata?.minLot ?? "unknown"}</li><li>Lot step: {result.data.metadata?.lotStep ?? "unknown"}</li><li>Contract size: {result.data.metadata?.contractSize ?? "unknown"}</li><li>Digits: {result.data.metadata?.digits ?? "unknown"}</li><li>Minimum stop distance: {result.data.metadata?.minimumStopDistancePips ?? "unknown"}</li></ul><p className="muted">This calculation is informational and does not submit an order.</p></section> : <p className="empty">Nothing has been calculated yet.</p>}
  </main>;
}
