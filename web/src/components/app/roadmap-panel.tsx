"use client";

import { useState } from "react";
import { api, type ApiResult } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";

type Props = { title: string; description: string; endpoint: string; readOnly?: boolean; disclaimer?: string };

export function RoadmapPanel({ title, description, endpoint, readOnly = false, disclaimer }: Props) {
  const read = useRead<Record<string, unknown>>(readOnly ? endpoint : null);
  const starter = endpoint === "backtest" || endpoint === "replay"
    ? { candles: [] }
    : endpoint === "forward" ? { signals: [] }
    : endpoint === "overfit" ? { conditionCount: 0, tradeCount: 0, periodCount: 0 }
    : endpoint === "risk/guard" ? { state: { stopAll: false, weeklyLossFraction: 0, drawdownFraction: 0, consecutiveLosses: 0, symbolExposureFraction: 0, tradesToday: 0 }, limits: {} }
    : { balance: 10000, riskFraction: 0.01, stopPips: 20, symbol: "EUR_USD", price: 1.1 };
  const [text, setText] = useState(JSON.stringify(starter, null, 2));
  const [result, setResult] = useState<ApiResult<Record<string, unknown>> | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const body = JSON.parse(text) as unknown;
      if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("Enter a JSON object.");
      setResult(await api<Record<string, unknown>>(endpoint, { method: "POST", body }));
    } catch (e) {
      setResult({ ok: false, status: 400, code: "BAD_REQUEST", message: e instanceof Error ? e.message : "Invalid JSON" });
    } finally { setBusy(false); }
  }

  const current = readOnly ? read.result : result;
  return (
    <main>
      <div className="page-head"><div><h1>{title}</h1><span className="sub">{description}</span></div></div>
      {disclaimer ? <p className="notice" role="note">{disclaimer}</p> : null}
      {!readOnly ? <section className="card">
        <label htmlFor={`${endpoint}-input`}><strong>Input snapshot</strong></label>
        <textarea id={`${endpoint}-input`} className="input" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn" type="button" onClick={run} disabled={busy}>{busy ? "Running…" : "Run read-only analysis"}</button>
      </section> : null}
      {(read.loading || busy) && !current ? <Spinner /> : null}
      {current && !current.ok ? <ErrorNotice error={current} onRetry={readOnly ? read.reload : undefined} /> : null}
      {current?.ok ? <section className="card" aria-live="polite"><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(current.data, null, 2)}</pre></section> : null}
    </main>
  );
}
