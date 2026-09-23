"use client";
/**
 * The market view: pick an instrument and a timeframe, read real bars.
 *
 * Every state this can be in is a different sentence, because they lead to
 * different actions. "No account connected" is fixed by connecting one;
 * "market data unavailable" is fixed by waiting or retrying; "the
 * authorisation expired" is fixed by reconnecting. Collapsing them into one
 * empty chart would make all three look like a quiet market.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { api, type ApiError, type CandlesRead } from "@/lib/api";
import { plainRead } from "@/components/app/plain";
import { CandleChart, type ChartMarker } from "./candles";

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const BARS = 200;

export function MarketPanel({
  ctid, mode, symbols, timeframe: initialTf, markers = [], onLoaded, title = "Market",
}: {
  /** The selected cTrader account, or null when none is selected. */
  ctid: number | string | null;
  mode?: "demo" | "live" | null;
  /** Instruments offered in the selector. Usually the rule's own. */
  symbols: string[];
  timeframe?: string;
  markers?: ChartMarker[];
  /** Handed the bars so a caller can evaluate exactly what is on screen. */
  onLoaded?: (read: CandlesRead) => void;
  title?: string;
}) {
  const [picked, setSymbol] = useState(symbols[0] ?? "");
  const [tf, setTf] = useState(initialTf ?? "1h");
  const [read, setRead] = useState<CandlesRead | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const abort = useRef<AbortController | null>(null);

  // Derived, not corrected by an effect. If the caller's instrument list
  // changes under us, the selection falls back to the first one on the very
  // same render — an effect would paint once with an instrument that is no
  // longer on the rule, and fetch bars for it.
  const symbol = symbols.includes(picked) ? picked : (symbols[0] ?? "");

  const load = useCallback(async () => {
    if (!ctid || !symbol) return;
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setLoading(true);
    setErr(null);
    setRead(null);
    const q = new URLSearchParams({ symbol, timeframe: tf, limit: String(BARS) });
    const r = await api<CandlesRead>(`accounts/${ctid}/candles?${q.toString()}`, { signal: ctl.signal });
    if (ctl.signal.aborted) return;
    setLoading(false);
    if (!r.ok) { setErr(r); return; }
    setRead(r.data);
    onLoaded?.(r.data);
  }, [ctid, symbol, tf, onLoaded]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  const plain = read && read.status !== "ok" ? plainRead(read.status, read.reason) : null;
  const last = read?.candles?.[read.candles.length - 1];

  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
        <span className="btn-row">
          {mode ? (
            <span className={mode === "live" ? "pill pill-live" : "pill pill-demo"}>
              {mode === "live" ? "LIVE" : "DEMO"}
            </span>
          ) : null}
          <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading || !ctid}>
            <RefreshCw className="ico" aria-hidden /> {loading ? "Loading…" : "Refresh"}
          </button>
        </span>
      </div>

      {/* No account selected: nothing can be fetched, and the selectors would
          imply otherwise. */}
      {!ctid ? (
        <div className="notice">
          <p style={{ fontWeight: 600 }}>cTrader account not connected</p>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            The chart shows bars read from your connected account. Connect one
            to see the market this rule watches.
          </p>
          <Link className="btn btn-sm" href="/connect">Connect cTrader</Link>
        </div>
      ) : (
        <>
          <div className="grid grid-2">
            <label className="field" style={{ marginBottom: 0 }}>
              <span>Instrument</span>
              <select value={symbol} onChange={(e) => setSymbol(e.target.value)} disabled={!symbols.length}>
                {symbols.length
                  ? symbols.map((s) => <option key={s} value={s}>{s}</option>)
                  : <option value="">No instrument on this rule</option>}
              </select>
            </label>
            <label className="field" style={{ marginBottom: 0 }}>
              <span>Timeframe</span>
              <select value={tf} onChange={(e) => setTf(e.target.value)}>
                {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
          </div>

          <div style={{ marginTop: "var(--sp-3)" }}>
            {loading ? (
              <div className="chart-skeleton" role="status" aria-label="Loading market data">
                <span className="skel" style={{ display: "block", height: 280, borderRadius: 10 }} />
              </div>
            ) : err ? (
              /* A failed request is a failed request. Not an empty market. */
              <div className="notice notice-error" role="alert">
                <div className="notice-head"><strong>{err.code}</strong>
                  {err.status ? <span className="muted"> · HTTP {err.status}</span> : null}
                </div>
                <p>{err.message}</p>
                <button className="btn btn-ghost btn-sm" onClick={load} style={{ marginTop: ".5rem" }}>
                  Try again
                </button>
              </div>
            ) : plain ? (
              <div className={plain.tone === "short" ? "notice notice-warn" : "notice"} role="status">
                <p style={{ fontWeight: 600 }}>{plain.label}</p>
                {plain.detail ? <p className="muted" style={{ fontSize: ".82rem" }}>{plain.detail}</p> : null}
                {read?.status === "reauth_required" ? (
                  <Link className="btn btn-sm" href="/connect">Reconnect cTrader</Link>
                ) : read?.status === "not_connected" ? (
                  <Link className="btn btn-sm" href="/connect">Connect cTrader</Link>
                ) : (
                  <button className="btn btn-ghost btn-sm" onClick={load}>Try again</button>
                )}
              </div>
            ) : read?.candles?.length ? (
              <>
                <CandleChart
                  candles={read.candles}
                  symbol={read.symbol}
                  timeframe={read.timeframe}
                  markers={markers}
                />
                {/* Source and as-of, on screen. Numbers without a time and a
                    source are a screenshot, not data. */}
                <p className="dim" style={{ fontSize: ".72rem", marginTop: ".35rem" }}>
                  Source: cTrader account <span className="mono">#{read.accountId}</span> ·{" "}
                  {read.count} bars of {read.symbol} {read.timeframe}
                  {read.count !== read.requested ? ` (asked for ${read.requested})` : ""}
                  {typeof last?.time === "number" ? (
                    <> · latest bar <span className="mono">
                      {new Date(last.time * 1000).toISOString().replace("T", " ").slice(0, 16)} UTC
                    </span></>
                  ) : null}
                </p>
              </>
            ) : (
              <p className="empty">
                The broker answered with no bars for {symbol} {tf}.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
