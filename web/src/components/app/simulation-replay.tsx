"use client";

import { useEffect, useMemo, useState } from "react";
import { Pause, Play, SkipForward } from "lucide-react";
import type { ApiResult, Candle, RuleSummary } from "@/lib/api";
import { api } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { Spinner } from "@/components/app/state";
import { PriceChart } from "@/components/chart/price-chart";
import { TIMEFRAMES } from "@/components/app/rule-form";
import {
  AccountHint, CandleReadStatus, SimulationFailure, SimulationHead, useCandleRead,
} from "@/components/app/simulation-shared";

const DISCLAIMER = "Backtest results are hypothetical and do not predict future performance.";

type ReplayCondition = { met?: string[]; unmet?: string[]; unknown?: string[] };
type ReplayEvent = {
  index?: number;
  state?: string;
  conditions?: ReplayCondition;
  entry?: { side?: string; price?: number | null } | null;
  stop?: number | null;
  explanation?: string | null;
  dataAvailableThrough?: number | null;
};
type ReplayResponse = {
  status: string;
  events: ReplayEvent[];
  disclaimer?: string;
  readOnly?: boolean;
};

function ConditionList({ title, values }: { title: string; values: string[] }) {
  if (!values.length) return <p className="muted">{title}: none read</p>;
  return <div><strong>{title}</strong><ul className="plain-list">{values.map((value) => <li key={value}>{value}</li>)}</ul></div>;
}

function ReplayEvidence({ event }: { event: ReplayEvent | null }) {
  if (!event) return <p className="empty">No bar explanation has been read yet.</p>;
  if (event.state === "data_unavailable") return <p className="notice notice-error" role="alert">The selected bar could not be read.</p>;
  const conditions = event.conditions ?? {};
  return (
    <section className="card" aria-live="polite">
      <div className="card-head"><h2>Rule evidence at this bar</h2><span className="muted">No look-ahead</span></div>
      <div className="grid grid-3">
        <div className="stat"><span className="stat-k">Entry</span><strong className="stat-v">{event.entry?.side ?? "unknown"} · {event.entry?.price ?? "unknown"}</strong></div>
        <div className="stat"><span className="stat-k">Stop at bar</span><strong className="stat-v">{event.stop ?? "unknown"}</strong></div>
        <div className="stat"><span className="stat-k">Data through</span><strong className="stat-v">{event.dataAvailableThrough == null ? "unknown" : new Date(event.dataAvailableThrough * 1000).toLocaleString()}</strong></div>
      </div>
      <div className="grid grid-3">
        <ConditionList title="True" values={conditions.met ?? []} />
        <ConditionList title="False" values={conditions.unmet ?? []} />
        <ConditionList title="Unknown" values={conditions.unknown ?? []} />
      </div>
      <p className="muted">{event.explanation ?? "The rule explanation could not be read."}</p>
    </section>
  );
}

export function ReplayView() {
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 60_000);
  const active = useMemo(() => rules.result?.ok && Array.isArray(rules.result.data?.rules)
    ? rules.result.data.rules.find((rule) => rule.state === "active")
    : undefined, [rules.result]);
  const [symbol, setSymbol] = useState("EUR_USD");
  const [timeframe, setTimeframe] = useState("1h");
  const [days, setDays] = useState(7);
  const [pos, setPos] = useState<{ n: number; len: number } | null>(null);
  const [playingFor, setPlayingFor] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<ApiResult<ReplayResponse> | null>(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const { accounts, candles } = useCandleRead(symbol, timeframe, days);
  const data = candles.result?.ok ? candles.result.data : null;
  const bars = data?.status === "ok" ? (data.candles ?? []) : [];
  const last = Math.max(0, bars.length - 1);
  const cursor = pos && pos.len === bars.length ? pos.n : last;
  const playing = playingFor === bars.length && bars.length > 0 && cursor < last;
  const visible = bars.slice(0, Math.max(0, cursor + 1));

  useEffect(() => {
    if (!playing) return;
    const len = bars.length;
    const id = window.setInterval(() => setPos((current) => {
      const at = current && current.len === len ? current.n : last;
      return { n: Math.min(at + 1, last), len };
    }), 650);
    return () => window.clearInterval(id);
  }, [playing, bars.length, last]);

  async function explainAt(nextCursor: number) {
    if (!active || !bars.length) return;
    setEvidenceBusy(true);
    setEvidence(null);
    const result = await api<ReplayResponse>("replay", {
      method: "POST",
      body: { ruleDocId: active.ruleDocId, candles: bars, symbol, timeframe },
    });
    setEvidence(result);
    setEvidenceBusy(false);
    if (result.ok && result.data.events[nextCursor]) setEvidence({ ok: true, data: { ...result.data, events: [result.data.events[nextCursor]] } });
  }

  function step() {
    const next = Math.min(cursor + 1, last);
    setPos({ n: next, len: bars.length });
    void explainAt(next);
  }

  return (
    <main>
      <SimulationHead title="Strategy replay" detail="Read-only candle-by-candle inspection" reload={candles.reload} loading={candles.loading} />
      <p className="notice" role="note">{DISCLAIMER}</p>
      <section className="card">
        <div className="grid grid-3">
          <label>Symbol<input className="input" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></label>
          <label>Timeframe<select className="input" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>{TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label>Past window<select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={1}>1 day</option><option value={7}>7 days</option><option value={30}>30 days</option></select></label>
        </div>
        <AccountHint accounts={accounts} />
        {rules.loading && !rules.result ? <Spinner label="Reading active rule" /> : null}
        <SimulationFailure result={rules.result} retry={rules.reload} />
        {!active && rules.result?.ok ? <p className="empty">No active rule is available for this read.</p> : null}
      </section>
      {candles.loading && !candles.result ? <Spinner label="Reading historical candles" /> : null}
      <SimulationFailure result={candles.result} retry={candles.reload} />
      <CandleReadStatus data={data} empty="The broker returned no candles for this window." />
      {bars.length ? <>
        <section className="card">
          <div className="card-head"><h2>Replay controls</h2><span className="muted">Bar {cursor + 1} of {bars.length}</span></div>
          <div style={{ display: "flex", gap: ".5rem", flexWrap: "wrap" }}>
            <button className="btn btn-ghost" onClick={() => setPlayingFor(playing ? null : bars.length)}>{playing ? <Pause className="ico" aria-hidden /> : <Play className="ico" aria-hidden />}{playing ? "Pause" : "Play"}</button>
            <button className="btn btn-ghost" onClick={step} disabled={cursor >= last}><SkipForward className="ico" aria-hidden /> Step</button>
            <button className="btn btn-ghost" onClick={() => { setPos({ n: 0, len: bars.length }); setPlayingFor(null); }}>Restart</button>
            <button className="btn" onClick={() => void explainAt(cursor)} disabled={evidenceBusy || !active}>{evidenceBusy ? "Reading…" : "Explain current bar"}</button>
          </div>
          <p className="muted" role="status">{visible.length ? "Data available at this replay point." : "No candle is available at this replay point."}</p>
        </section>
        <section className="card"><PriceChart candles={visible as Candle[]} symbol={symbol} timeframe={timeframe} height={340} /></section>
        <SimulationFailure result={evidence} />
        {evidenceBusy ? <Spinner label="Reading rule evidence" /> : null}
        {evidence?.ok ? <ReplayEvidence event={evidence.data.events[0] ?? null} /> : null}
      </> : null}
    </main>
  );
}
