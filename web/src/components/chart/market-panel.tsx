"use client";
/**
 * The market view: pick an instrument and a timeframe, watch real bars.
 *
 * Every state this can be in is a different sentence, because they lead to
 * different actions. "No account selected" is fixed by choosing one;
 * "market data unavailable" is fixed by waiting or retrying; "the
 * authorisation expired" is fixed by reconnecting. Collapsing them into one
 * empty chart would make all three look like a quiet market.
 *
 * WHAT "LIVE" MEANS HERE, STATED SO IT IS NOT OVERSOLD
 *
 * The page asks the platform for the bars every 5 seconds (and not at all
 * while the tab is hidden). The platform answers from the broker through a
 * short shared cache, so the newest bar can trail the broker by up to the
 * cache lifetime, and the response carries no "fetched at" time. What this
 * panel can truthfully report is when THIS BROWSER last got an answer, which
 * is what "Last synced" is, and it says so next to the cache note. It does
 * not say "real time".
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import type { CandlesRead, PositionsRead } from "@/lib/api";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice } from "@/components/app/state";
import { plainRead } from "@/components/app/plain";
import { TIMEFRAMES } from "@/components/app/rule-form";
import { isStale, positionOverlays, sameInstrument, type ChartMarker, type PositionOverlay } from "./chart-data";
import { PriceChart, type Overlay } from "./price-chart";

/**
 * How often the chart (and its position lines) are re-read.
 *
 * The broker allows 5 historical requests a second per connection, shared by
 * every client, and the platform meters this route per user. 5 seconds is the
 * floor for one chart; do not lower it.
 */
export const CHART_REFRESH_MS = 5_000;
const BARS = 200;

export const PERIOD_MIN = 2;
export const PERIOD_MAX = 200;

function parsePeriod(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const n = Number(text);
  return n >= PERIOD_MIN && n <= PERIOD_MAX ? n : null;
}

/** A clock that ticks once a second while `active`, so "N seconds ago" and "stale" move without a read. */
function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

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
  const [overlayKind, setOverlayKind] = useState<"none" | "sma" | "ema">("none");
  const [periodText, setPeriodText] = useState("20");
  const [rsiOn, setRsiOn] = useState(false);

  // Derived, not corrected by an effect. If the caller's instrument list
  // changes under us, the selection falls back to the first one on the very
  // same render — an effect would paint once with an instrument that is no
  // longer on the rule, and fetch bars for it.
  const symbol = symbols.includes(picked) ? picked : (symbols[0] ?? "");

  const path = ctid && symbol
    ? `accounts/${ctid}/candles?${new URLSearchParams({ symbol, timeframe: tf, limit: String(BARS) }).toString()}`
    : null;
  const candles = useRead<CandlesRead>(path, CHART_REFRESH_MS);
  const positions = useRead<PositionsRead>(path ? "positions" : null, CHART_REFRESH_MS);
  const now = useNow(path !== null && candles.lastSync !== null);

  const result = candles.result;
  const read = result?.ok ? result.data : null;
  // `useRead` keeps the previous answer while a new path loads, so after the
  // reader picks another instrument or timeframe the answer on hand is for the
  // OLD one. Drawing it would put one instrument's bars under another's name.
  const forThisChart = !!read && read.status === "ok"
    && (!read.symbol || sameInstrument(read.symbol, symbol))
    && (!read.timeframe || read.timeframe.toLowerCase() === tf.toLowerCase());

  useEffect(() => { if (read && forThisChart) onLoaded?.(read); }, [read, forThisChart, onLoaded]);

  const failed = !!result && !result.ok;
  const stale = isStale({ lastSync: candles.lastSync, now, failed });
  const plain = read && read.status !== "ok" ? plainRead(read.status, read.reason) : null;
  const last = read?.candles?.[read.candles.length - 1];

  const period = parsePeriod(periodText);
  const overlay: Overlay | null = overlayKind !== "none" && period !== null ? { kind: overlayKind, period } : null;

  const lines = useMemo(() => {
    const p = positions.result;
    if (!p) return { overlays: [] as PositionOverlay[], note: null as string | null };
    if (!p.ok) return { overlays: [], note: `Position lines unavailable — ${p.code}: ${p.message}` };
    if (p.data.status !== "ok") {
      return { overlays: [], note: `Position lines unavailable — ${plainRead(p.data.status, p.data.reason)?.label ?? p.data.status}` };
    }
    if (p.data.accountId !== undefined && ctid !== null && String(p.data.accountId) !== String(ctid)) {
      return { overlays: [], note: `Position lines hidden — those positions are on account #${p.data.accountId}, not the account charted (#${ctid}).` };
    }
    return { overlays: positionOverlays(p.data.positions, symbol), note: null };
  }, [positions.result, symbol, ctid]);

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
          <button className="btn btn-ghost btn-sm" onClick={candles.reload} disabled={candles.loading || !ctid}>
            <RefreshCw className="ico" aria-hidden /> {candles.loading ? "Loading…" : "Refresh"}
          </button>
        </span>
      </div>

      {/* No account selected: nothing can be fetched, and the selectors would
          imply otherwise. */}
      {!ctid ? (
        /* SAY THE FACT THIS PANEL ACTUALLY HAS.
           `ctid` being null means no account is SELECTED — the prop's own
           doc says so. It said "cTrader account not connected" and pointed
           at /connect, which is a different fact and a different remedy.
           An owner who had just linked cTrader, with the status strip beside
           this panel reading "cTrader Linked", was told here that he had not
           connected and sent back to connect again. Reported from a phone on
           2026-10-04; the second authorisation round is what spent the oauth
           budget and produced RATE_LIMITED.
           /accounts rather than /connect because it is right either way: it
           lists the accounts to choose from when there is a link, and says
           there is none and offers to connect when there is not. */
        <div className="notice">
          <p style={{ fontWeight: 600 }}>No account selected</p>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            The chart shows bars read from the cTrader account you choose.
            Pick one to see the market this rule watches.
          </p>
          <Link className="btn btn-ghost btn-sm" href="/accounts">Choose an account</Link>
        </div>
      ) : (
        <>
          <div className="grid grid-3">
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
            <label className="field" style={{ marginBottom: 0 }}>
              <span>Overlay <span className="hint">(computed)</span></span>
              <select value={overlayKind} onChange={(e) => setOverlayKind(e.target.value as typeof overlayKind)}>
                <option value="none">None</option>
                <option value="sma">SMA</option>
                <option value="ema">EMA</option>
              </select>
            </label>
          </div>
          <div className="grid grid-3" style={{ marginTop: "var(--sp-2)" }}>
            <label className="field" style={{ marginBottom: 0 }}>
              <span>Period</span>
              <input
                type="number" inputMode="numeric" min={PERIOD_MIN} max={PERIOD_MAX} step={1}
                value={periodText} disabled={overlayKind === "none"}
                onChange={(e) => setPeriodText(e.target.value)}
              />
            </label>
            <label className="field-inline" style={{ marginBottom: 0, alignSelf: "end" }}>
              <input type="checkbox" checked={rsiOn} onChange={(e) => setRsiOn(e.target.checked)} />
              <span>Show RSI pane</span>
            </label>
          </div>
          {overlayKind !== "none" && period === null ? (
            <p className="dim" style={{ fontSize: ".75rem", marginTop: ".35rem" }} role="status">
              Period must be a whole number from {PERIOD_MIN} to {PERIOD_MAX}; no line is drawn until it is.
            </p>
          ) : null}

          {path && candles.lastSync !== null ? (
            <p className="dim sync-line" style={{ fontSize: ".75rem", marginTop: ".5rem" }}>
              {failed ? "Last read failed" : "Last synced"} {whenSynced(candles.lastSync)}
              {stale ? <> · <span className="pill pill-warn">stale</span></> : null}
            </p>
          ) : null}

          <div style={{ marginTop: "var(--sp-3)" }}>
            {!symbol ? (
              /* THE BROKER WAS NEVER ASKED, so it cannot have answered.
                 There is no request without an instrument, and the render
                 used to fall through to "The broker answered with no bars
                 for  1h" — with a gap where the instrument should be.
                 This is the normal state for a new client who has just
                 picked an account: the dashboard passes the ACTIVE rule's
                 instruments, and they have no active rule yet. So the first
                 thing the product told them about their broker was a
                 failure that had not happened. */
              <p className="empty">
                No instrument to chart yet. Activate a rule and start it, and
                its instrument appears here.
              </p>
            ) : result && !result.ok ? (
              /* A failed request is a failed request. Not an empty market,
                 and not the last good bars left up as if they were current. */
              <ErrorNotice error={result} onRetry={candles.reload} />
            ) : plain ? (
              <div className={plain.tone === "short" ? "notice notice-warn" : "notice"} role="status">
                <p style={{ fontWeight: 600 }}>{plain.label}</p>
                {plain.detail ? <p className="muted" style={{ fontSize: ".82rem" }}>{plain.detail}</p> : null}
                {read?.status === "reauth_required" ? (
                  <Link className="btn btn-ghost btn-sm" href="/connect">Reconnect cTrader</Link>
                ) : read?.status === "not_connected" ? (
                  /* /accounts, not /connect: this status also covers an
                     account that is linked but not selected, and sending
                     that reader back through authorisation is what spent
                     the oauth budget. The accounts page is right for both. */
                  <Link className="btn btn-ghost btn-sm" href="/accounts">Choose an account</Link>
                ) : (
                  <button className="btn btn-ghost btn-sm" onClick={candles.reload}>Try again</button>
                )}
              </div>
            ) : !read || !forThisChart ? (
              <div className="chart-skeleton" role="status" aria-label="Loading market data">
                <span className="skel" style={{ display: "block", height: 280, borderRadius: 10 }} />
              </div>
            ) : read.candles?.length ? (
              <>
                <div className={stale ? "chart-frame is-stale" : "chart-frame"}>
                  <PriceChart
                    candles={read.candles}
                    symbol={read.symbol}
                    timeframe={read.timeframe}
                    markers={markers}
                    overlay={overlay}
                    showRsi={rsiOn}
                    positions={lines.overlays}
                  />
                </div>
                {stale ? (
                  <p className="dim" style={{ fontSize: ".75rem", marginTop: ".35rem" }}>
                    These bars are from the last answer received and may no longer match the market.
                  </p>
                ) : null}
                {lines.note ? (
                  <p className="dim" style={{ fontSize: ".75rem", marginTop: ".35rem" }}>{lines.note}</p>
                ) : null}
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
                <p className="dim" style={{ fontSize: ".72rem", marginTop: ".2rem" }}>
                  Asked for again every {CHART_REFRESH_MS / 1000} s while this tab is open. The platform
                  caches broker bars briefly (60 s by default), so the newest bar can trail the broker by
                  about that long; &ldquo;Last synced&rdquo; is when this page last got an answer.
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
