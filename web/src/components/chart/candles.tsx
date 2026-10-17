"use client";
/**
 * A read-only candlestick chart.
 *
 * It draws candles it was given. It does not fetch them, it does not invent
 * them, and it imports nothing that could place, close or amend an order —
 * a test asserts that last one against the module's own source, because a
 * chart is exactly the kind of component where an "and also close this
 * position" button gets added later without anyone thinking about it.
 *
 * See docs/CHART_DEPENDENCY_DECISION.md for why this is SVG and not a
 * charting library.
 */
import { useMemo, useState } from "react";
import type { Candle } from "@/lib/api";

export type ChartMarker = {
  /** Unix seconds. Snapped to the nearest bar. */
  time: number;
  label: string;
  tone: "long" | "short" | "neutral";
};

const PAD = { top: 12, right: 58, bottom: 22, left: 8 };

function fmt(n: number, digits: number) {
  return n.toFixed(digits);
}

/** Enough decimals to tell two bars apart, capped so it stays readable. */
function digitsFor(range: number): number {
  if (range === 0) return 2;
  if (range < 0.01) return 5;
  if (range < 1) return 4;
  if (range < 100) return 2;
  return 1;
}

export function CandleChart({
  candles, symbol, timeframe, markers = [], height = 320,
}: {
  candles: Candle[];
  symbol?: string;
  timeframe?: string;
  markers?: ChartMarker[];
  height?: number;
}) {
  // A bar index, or null for "the last one". Hover is a read, not a change.
  const [hover, setHover] = useState<number | null>(null);

  const geom = useMemo(() => {
    if (!candles.length) return null;
    let lo = Infinity;
    let hi = -Infinity;
    for (const c of candles) {
      if (c.low < lo) lo = c.low;
      if (c.high > hi) hi = c.high;
    }
    // A flat series would divide by zero and draw a line through the middle.
    const span = hi - lo || Math.max(Math.abs(hi) * 0.001, 0.0001);
    const pad = span * 0.08;
    return { lo: lo - pad, hi: hi + pad, span: span + pad * 2 };
  }, [candles]);

  if (!candles.length || !geom) {
    return (
      <p className="empty">No bars to draw.</p>
    );
  }

  const W = 1000;
  const H = height;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const step = plotW / candles.length;
  const bodyW = Math.max(1, Math.min(step * 0.62, 14));
  const digits = digitsFor(geom.span);

  const y = (price: number) => PAD.top + (1 - (price - geom.lo) / geom.span) * plotH;
  const x = (i: number) => PAD.left + i * step + step / 2;

  const shown = hover ?? candles.length - 1;
  const bar = candles[shown];
  const up = bar.close >= bar.open;

  // Four gridlines, at prices rather than at pixels, so the labels are round
  // numbers the reader can compare against the OHLC readout.
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => geom.lo + geom.span * f);

  const markerAt = (m: ChartMarker) => {
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < candles.length; i++) {
      const t = candles[i].time;
      if (typeof t !== "number") continue;
      const d = Math.abs(t - m.time);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  };

  return (
    <div>
      {/* The OHLC readout. Always present, so the numbers are legible even
          where the candle is one pixel wide. */}
      <div className="ohlc" role="status" aria-live="polite">
        <span className="sym">{symbol ?? "—"}</span>
        {timeframe ? <span className="pill pill-muted">{timeframe}</span> : null}
        <span><i>O</i> <b className="mono">{fmt(bar.open, digits)}</b></span>
        <span><i>H</i> <b className="mono">{fmt(bar.high, digits)}</b></span>
        <span><i>L</i> <b className="mono">{fmt(bar.low, digits)}</b></span>
        <span><i>C</i> <b className={up ? "mono side-long" : "mono side-short"}>{fmt(bar.close, digits)}</b></span>
        {typeof bar.time === "number" ? (
          <time className="dim mono" dateTime={new Date(bar.time * 1000).toISOString()}>
            {new Date(bar.time * 1000).toISOString().replace("T", " ").slice(0, 16)} UTC
          </time>
        ) : null}
      </div>

      <svg
        className="candles"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={
          `Candlestick chart, ${candles.length} bars of ${symbol ?? "the selected instrument"}` +
          `${timeframe ? ` on ${timeframe}` : ""}`
        }
        onMouseLeave={() => setHover(null)}
      >
        {grid.map((price, i) => (
          <g key={i}>
            <line
              x1={PAD.left} x2={W - PAD.right} y1={y(price)} y2={y(price)}
              stroke="var(--a4t-line-soft)" strokeWidth="1"
            />
            <text
              x={W - PAD.right + 6} y={y(price) + 3}
              fill="var(--a4t-dim)" fontSize="11" fontFamily="var(--font-geist-mono), monospace"
            >
              {fmt(price, digits)}
            </text>
          </g>
        ))}

        {candles.map((c, i) => {
          const isUp = c.close >= c.open;
          const colour = isUp ? "var(--a4t-long)" : "var(--a4t-short)";
          const top = y(Math.max(c.open, c.close));
          const bottom = y(Math.min(c.open, c.close));
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              {/* A transparent column, so hovering works between candles too. */}
              <rect x={PAD.left + i * step} y={PAD.top} width={step} height={plotH} fill="transparent" />
              <line
                x1={x(i)} x2={x(i)} y1={y(c.high)} y2={y(c.low)}
                stroke={colour} strokeWidth="1"
              />
              <rect
                x={x(i) - bodyW / 2}
                y={top}
                width={bodyW}
                /* A doji has zero body height and would vanish. */
                height={Math.max(1, bottom - top)}
                fill={isUp ? "transparent" : colour}
                stroke={colour}
                strokeWidth="1.2"
              />
            </g>
          );
        })}

        {/* The last close, carried across so it can be read off the axis. */}
        <line
          x1={PAD.left} x2={W - PAD.right}
          y1={y(candles[candles.length - 1].close)} y2={y(candles[candles.length - 1].close)}
          stroke="var(--a4t-link)" strokeWidth="1" strokeDasharray="3 3" opacity="0.65"
        />

        {hover !== null ? (
          <line
            x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH}
            stroke="var(--a4t-link)" strokeWidth="1" opacity="0.4"
          />
        ) : null}

        {markers.map((m, k) => {
          const i = markerAt(m);
          const colour = m.tone === "long" ? "var(--a4t-long)"
            : m.tone === "short" ? "var(--a4t-short)" : "var(--a4t-link)";
          return (
            <g key={k} data-testid="chart-marker">
              <line
                x1={x(i)} x2={x(i)} y1={PAD.top} y2={PAD.top + plotH}
                stroke={colour} strokeWidth="1" strokeDasharray="2 4" opacity="0.8"
              />
              <circle cx={x(i)} cy={PAD.top + 6} r="4" fill={colour} />
              <title>{m.label}</title>
            </g>
          );
        })}
      </svg>

      {/* Stated, not hidden: the platform has no volume to draw. */}
      <p className="dim" style={{ fontSize: ".72rem", marginTop: ".4rem" }}>
        Price only — the broker read does not carry volume, so none is shown.
      </p>
    </div>
  );
}
