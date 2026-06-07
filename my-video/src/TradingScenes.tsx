import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Sequence,
} from "remotion";

const AMBER = "#f59e0b";
const AMBER2 = "#fbbf24";
const BG = "#050505";
const GREEN = "#10b981";
const RED = "#ef4444";
const BLUE = "#3b82f6";
const FONT = "'Plus Jakarta Sans', 'Inter', system-ui, sans-serif";

function spr(frame: number, fps: number, delay = 0, cfg = {}) {
  return spring({ frame: frame - delay, fps, config: { damping: 18, stiffness: 120, mass: 0.8, ...cfg } });
}

// ─────────────────────────────────────────────────────────────
// COMPOSITION 1: BOT SCAN  (15s = 450 frames)
// ─────────────────────────────────────────────────────────────

const PAIRS = [
  { pair: "BTC/USDT", price: "67,841.20", change: "+2.4%", vol: "1.2B", green: true },
  { pair: "ETH/USDT", price: "3,582.10", change: "+1.8%", vol: "820M", green: true },
  { pair: "SOL/USDT", price: "182.44",   change: "-0.6%", vol: "410M", green: false },
  { pair: "BNB/USDT", price: "594.30",   change: "+3.1%", vol: "290M", green: true },
  { pair: "XRP/USDT", price: "0.6182",   change: "+0.9%", vol: "540M", green: true },
  { pair: "AVAX/USDT", price: "41.22",   change: "-1.2%", vol: "180M", green: false },
  { pair: "DOGE/USDT", price: "0.1844",  change: "+4.2%", vol: "620M", green: true },
  { pair: "ARB/USDT",  price: "1.2130",  change: "+2.7%", vol: "95M",  green: true },
];

const Scan1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [66, 80], [1, 0], { extrapolateLeft: "clamp" });
  const numOp = interpolate(frame, [8, 28], [0, 1], { extrapolateRight: "clamp" });
  const numY = interpolate(spr(frame, fps, 8), [0, 1], [30, 0]);

  const dotCount = Math.floor(interpolate(frame, [0, 70], [0, 3], { extrapolateRight: "clamp" }));
  const dots = ".".repeat(dotCount);

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 50% at 50% 50%, rgba(59,130,246,.10), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, fontWeight: 700, color: BLUE, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: BLUE, boxShadow: `0 0 12px ${BLUE}` }} />
          AI Market Scanner
        </div>
        <div style={{ opacity: numOp, transform: `translateY(${numY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 92, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.05em", lineHeight: 1 }}>
            847
          </div>
          <div style={{ fontSize: 20, color: "#64748b", fontWeight: 500, marginTop: 8 }}>
            trading pairs scanned{dots}
          </div>
        </div>
        <div style={{ display: "flex", gap: 32, opacity: numOp }}>
          {[["3", "Signals found"], ["0.8s", "Per scan cycle"], ["24/7", "Monitoring"]].map(([v, l], i) => (
            <div key={i} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: AMBER, letterSpacing: "-0.03em" }}>{v}</div>
              <div style={{ fontSize: 11, color: "#475569", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 4 }}>{l}</div>
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Scan2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [128, 140], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#475569", letterSpacing: "0.08em", textTransform: "uppercase" }}>Live market feed</div>
        <div style={{
          width: 680, background: "rgba(8,8,12,.95)",
          border: "1px solid rgba(255,255,255,.1)", borderRadius: 20,
          overflow: "hidden", boxShadow: "0 40px 80px rgba(0,0,0,.7)",
        }}>
          {/* Header */}
          <div style={{ display: "flex", padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,.06)", background: "rgba(255,255,255,.02)" }}>
            {["Pair", "Price", "24h Change", "Volume", "Signal"].map((h, i) => (
              <div key={i} style={{ flex: i === 0 ? 1.5 : 1, fontSize: 10, fontWeight: 700, color: "#334155", textTransform: "uppercase", letterSpacing: "0.06em", textAlign: i > 0 ? "right" : "left" }}>{h}</div>
            ))}
          </div>
          {/* Rows */}
          {PAIRS.map((p, i) => {
            const rowOp = interpolate(frame, [i * 8, i * 8 + 16], [0, 1], { extrapolateRight: "clamp" });
            const rowY = interpolate(spr(frame, fps, i * 8), [0, 1], [12, 0]);
            const isSignal = i === 0 || i === 3 || i === 6;
            const pulseOp = interpolate(frame % 20, [0, 10, 20], [0.6, 1, 0.6]);
            return (
              <div key={i} style={{
                display: "flex", padding: "11px 20px", alignItems: "center",
                borderBottom: "1px solid rgba(255,255,255,.03)",
                background: isSignal ? "rgba(245,158,11,.04)" : "transparent",
                opacity: rowOp, transform: `translateY(${rowY}px)`,
              }}>
                <div style={{ flex: 1.5, fontSize: 13, fontWeight: 700, color: "#e2e8f0" }}>{p.pair}</div>
                <div style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "#94a3b8", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{p.price}</div>
                <div style={{ flex: 1, fontSize: 12, fontWeight: 700, color: p.green ? GREEN : RED, textAlign: "right" }}>{p.change}</div>
                <div style={{ flex: 1, fontSize: 11, color: "#475569", textAlign: "right" }}>{p.vol}</div>
                <div style={{ flex: 1, textAlign: "right" }}>
                  {isSignal ? (
                    <span style={{ fontSize: 10, fontWeight: 800, padding: "3px 8px", borderRadius: 5, background: "rgba(245,158,11,.15)", color: AMBER, letterSpacing: "0.04em", opacity: pulseOp }}>
                      SIGNAL
                    </span>
                  ) : (
                    <span style={{ fontSize: 10, color: "#1e293b", fontWeight: 600 }}>—</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Scan3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [108, 120], [1, 0], { extrapolateLeft: "clamp" });
  const scale = spr(frame, fps, 0, { damping: 12, stiffness: 90 });
  const badgeOp = interpolate(frame, [12, 28], [0, 1], { extrapolateRight: "clamp" });
  const lineW = interpolate(frame, [20, 80], [0, 100], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(245,158,11,.12), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 28 }}>
        <div style={{ opacity: badgeOp, fontSize: 12, fontWeight: 700, color: AMBER, letterSpacing: "0.12em", textTransform: "uppercase", display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: AMBER, boxShadow: `0 0 12px ${AMBER}` }} />
          Signal Detected
        </div>
        <div style={{ transform: `scale(${scale})`, textAlign: "center" }}>
          <div style={{ fontSize: 108, fontWeight: 800, letterSpacing: "-0.05em", lineHeight: 1, background: `linear-gradient(135deg, ${AMBER}, ${AMBER2})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
            BTC/USDT
          </div>
        </div>
        {/* Signal card */}
        <div style={{
          display: "flex", gap: 1, background: "rgba(255,255,255,.06)", borderRadius: 14,
          overflow: "hidden", border: "1px solid rgba(245,158,11,.2)",
          boxShadow: "0 0 40px rgba(245,158,11,.1)",
        }}>
          {[
            { label: "Direction", value: "LONG", valueColor: GREEN },
            { label: "Confidence", value: "91%", valueColor: AMBER },
            { label: "Entry", value: "$67,841", valueColor: "#f1f5f9" },
            { label: "Take Profit", value: "$68,920", valueColor: GREEN },
          ].map(({ label, value, valueColor }, i) => (
            <div key={i} style={{ padding: "14px 22px", background: "rgba(8,8,12,.9)", textAlign: "center", minWidth: 110 }}>
              <div style={{ fontSize: 10, color: "#475569", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>{label}</div>
              <div style={{ fontSize: 18, fontWeight: 800, color: valueColor }}>{value}</div>
            </div>
          ))}
        </div>
        {/* Confidence bar */}
        <div style={{ width: 400, opacity: badgeOp }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 11, color: "#475569", fontWeight: 600 }}>
            <span>Signal strength</span><span style={{ color: AMBER }}>91%</span>
          </div>
          <div style={{ height: 4, background: "rgba(255,255,255,.06)", borderRadius: 99 }}>
            <div style={{ height: "100%", width: `${lineW}%`, background: `linear-gradient(90deg, ${AMBER}, ${AMBER2})`, borderRadius: 99 }} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Scan4: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const numY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);
  const countdown = Math.max(0, 3 - Math.floor(frame / 30));

  return (
    <AbsoluteFill style={{ opacity: op, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 50% 50% at 50% 50%, rgba(16,185,129,.1), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 28 }}>
        <div style={{ transform: `translateY(${numY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: "#475569", letterSpacing: "-0.01em", marginBottom: 16 }}>Executing in</div>
          <div style={{ fontSize: 140, fontWeight: 800, color: GREEN, letterSpacing: "-0.06em", lineHeight: 1, textShadow: `0 0 60px ${GREEN}` }}>
            {countdown}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: GREEN, fontWeight: 700 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: GREEN }} />
          Apex Trade Bot · BTC/USDT LONG
        </div>
        <div style={{ fontSize: 13, color: "#334155", fontWeight: 600, letterSpacing: "0.04em", marginTop: 8 }}>
          aicashsystem.space
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const BotScanComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={82}><Scan1 frame={frame} fps={fps} /></Sequence>
      <Sequence from={80} durationInFrames={152}><Scan2 frame={frame - 80} fps={fps} /></Sequence>
      <Sequence from={230} durationInFrames={122}><Scan3 frame={frame - 230} fps={fps} /></Sequence>
      <Sequence from={350} durationInFrames={100}><Scan4 frame={frame - 350} fps={fps} /></Sequence>
    </AbsoluteFill>
  );
};

// ─────────────────────────────────────────────────────────────
// COMPOSITION 2: TRADE EXECUTION  (12s = 360 frames)
// ─────────────────────────────────────────────────────────────

const Exec1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [58, 70], [1, 0], { extrapolateLeft: "clamp" });
  const titleSc = spr(frame, fps, 4);
  const rowsOp = interpolate(frame, [16, 36], [0, 1], { extrapolateRight: "clamp" });

  const orderFields = [
    { label: "Symbol", value: "BTC/USDT" },
    { label: "Side", value: "BUY / LONG" },
    { label: "Type", value: "MARKET" },
    { label: "Qty", value: "0.05 BTC" },
    { label: "Leverage", value: "10x" },
  ];

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 40% at 50% 20%, rgba(59,130,246,.10), transparent)" }} />
      <AbsoluteFill style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 60 }}>
        {/* Left: headline */}
        <div style={{ transform: `scale(${titleSc})` }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: BLUE, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 16 }}>Bot placing order</div>
          <div style={{ fontSize: 64, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            Placing<br />
            <span style={{ background: `linear-gradient(135deg,${AMBER},${AMBER2})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              order...
            </span>
          </div>
        </div>
        {/* Right: order form */}
        <div style={{
          width: 280, background: "rgba(8,8,14,.96)",
          border: "1px solid rgba(255,255,255,.1)", borderRadius: 18,
          overflow: "hidden", boxShadow: "0 0 60px rgba(59,130,246,.12), 0 40px 80px rgba(0,0,0,.6)",
          opacity: rowsOp,
        }}>
          <div style={{ padding: "12px 18px", borderBottom: "1px solid rgba(255,255,255,.07)", background: "rgba(255,255,255,.02)", display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 9, height: 9, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 9, height: 9, borderRadius: "50%", background: "#ffbd2e" }} />
            <div style={{ width: 9, height: 9, borderRadius: "50%", background: "#28c840" }} />
            <span style={{ fontSize: 12, color: "#475569", marginLeft: 8, fontWeight: 500 }}>Binance Futures · Order</span>
          </div>
          <div style={{ padding: "14px 18px" }}>
            {orderFields.map(({ label, value }, i) => {
              const fOp = interpolate(frame, [16 + i * 7, 28 + i * 7], [0, 1], { extrapolateRight: "clamp" });
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", marginBottom: 12, opacity: fOp }}>
                  <span style={{ fontSize: 12, color: "#475569", fontWeight: 600 }}>{label}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: label === "Side" ? GREEN : "#e2e8f0" }}>{value}</span>
                </div>
              );
            })}
            <div style={{
              marginTop: 16, padding: "12px 0", background: `linear-gradient(135deg,${AMBER},${AMBER2})`,
              borderRadius: 10, textAlign: "center", fontSize: 14, fontWeight: 800, color: "#000",
              opacity: interpolate(frame, [52, 64], [0, 1], { extrapolateRight: "clamp" }),
            }}>
              CONFIRM ORDER
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Exec2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [98, 110], [1, 0], { extrapolateLeft: "clamp" });

  // Simulated candlestick data (normalized 0-1)
  const candles = [0.4, 0.5, 0.35, 0.55, 0.45, 0.6, 0.52, 0.68, 0.58, 0.72, 0.65, 0.80];
  const chartW = 520;
  const chartH = 160;
  const visibleCandles = Math.floor(interpolate(frame, [10, 80], [1, candles.length], { extrapolateRight: "clamp" }));

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 50% 40% at 50% 60%, rgba(245,158,11,.08), transparent)" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ fontSize: 13, color: "#475569", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Technical Analysis · BTC/USDT 15m
        </div>
        {/* Chart */}
        <div style={{
          width: chartW + 48, background: "rgba(8,8,12,.96)",
          border: "1px solid rgba(255,255,255,.1)", borderRadius: 18,
          padding: "20px 24px", boxShadow: "0 40px 80px rgba(0,0,0,.6)",
        }}>
          {/* Mini chart */}
          <div style={{ position: "relative", width: chartW, height: chartH, marginBottom: 16 }}>
            {/* Grid lines */}
            {[0.25, 0.5, 0.75].map(y => (
              <div key={y} style={{ position: "absolute", left: 0, right: 0, top: `${y * 100}%`, height: 1, background: "rgba(255,255,255,.04)" }} />
            ))}
            {/* Candles */}
            {candles.slice(0, visibleCandles).map((h, i) => {
              const x = (i / (candles.length - 1)) * (chartW - 20);
              const candleH = h * chartH * 0.8;
              const isGreen = i > 0 ? h > candles[i - 1] : true;
              return (
                <div key={i} style={{ position: "absolute", left: x, bottom: 10, width: 12, height: candleH, background: isGreen ? GREEN : RED, borderRadius: 2, opacity: 0.9 }} />
              );
            })}
            {/* Entry arrow */}
            {frame > 50 && (
              <div style={{
                position: "absolute", left: "65%", bottom: "48%",
                opacity: interpolate(frame, [50, 62], [0, 1], { extrapolateRight: "clamp" }),
              }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: AMBER, letterSpacing: "0.04em", marginBottom: 3 }}>▲ ENTRY</div>
                <div style={{ width: 2, height: 20, background: AMBER, margin: "0 auto" }} />
              </div>
            )}
          </div>
          {/* Indicators */}
          <div style={{ display: "flex", gap: 20 }}>
            {[
              { name: "RSI (14)", value: "62.4", color: AMBER },
              { name: "MACD", value: "Bullish", color: GREEN },
              { name: "EMA 50", value: "Above", color: GREEN },
              { name: "Volume", value: "+180%", color: BLUE },
            ].map(({ name, value, color }, i) => {
              const indOp = interpolate(frame, [30 + i * 10, 44 + i * 10], [0, 1], { extrapolateRight: "clamp" });
              return (
                <div key={i} style={{ flex: 1, textAlign: "center", opacity: indOp }}>
                  <div style={{ fontSize: 10, color: "#334155", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{name}</div>
                  <div style={{ fontSize: 14, fontWeight: 800, color }}>{value}</div>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Exec3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [78, 90], [1, 0], { extrapolateLeft: "clamp" });

  // Animated P&L counter
  const pnl = interpolate(frame, [20, 80], [0, 24.18], { extrapolateRight: "clamp" });
  const pct = interpolate(frame, [20, 80], [0, 3.6], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(16,185,129,.12), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        {/* Position status */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, fontWeight: 700, color: GREEN, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: GREEN, boxShadow: `0 0 12px ${GREEN}` }} />
          Position Open · BTC/USDT LONG
        </div>
        {/* P&L Display */}
        <div style={{
          textAlign: "center",
          padding: "40px 80px",
          background: "rgba(16,185,129,.06)",
          border: "1px solid rgba(16,185,129,.2)",
          borderRadius: 24,
          boxShadow: "0 0 60px rgba(16,185,129,.1)",
        }}>
          <div style={{ fontSize: 15, color: "#64748b", fontWeight: 600, marginBottom: 12, letterSpacing: "0.06em", textTransform: "uppercase" }}>Unrealized P&L</div>
          <div style={{ fontSize: 96, fontWeight: 800, color: GREEN, letterSpacing: "-0.05em", lineHeight: 1, textShadow: `0 0 40px rgba(16,185,129,.4)` }}>
            +${pnl.toFixed(2)}
          </div>
          <div style={{ fontSize: 22, color: GREEN, fontWeight: 700, marginTop: 8 }}>
            +{pct.toFixed(1)}%
          </div>
        </div>
        {/* Entry info */}
        <div style={{ display: "flex", gap: 32, opacity: interpolate(frame, [24, 40], [0, 1], { extrapolateRight: "clamp" }) }}>
          {[["$67,841", "Entry Price"], ["$68,920", "Take Profit"], ["$67,200", "Stop Loss"]].map(([v, l], i) => (
            <div key={i} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 18, fontWeight: 800, color: i === 1 ? GREEN : i === 2 ? RED : "#f1f5f9", letterSpacing: "-0.02em" }}>{v}</div>
              <div style={{ fontSize: 11, color: "#334155", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 4 }}>{l}</div>
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Exec4: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const sc = spr(frame, fps, 4, { damping: 12, stiffness: 80 });
  const subOp = interpolate(frame, [28, 44], [0, 1], { extrapolateRight: "clamp" });
  const ctaOp = interpolate(frame, [44, 58], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(16,185,129,.14), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <div style={{ position: "absolute", top: 0, left: "20%", right: "20%", height: 1, background: `linear-gradient(90deg,transparent,${GREEN},transparent)`, opacity: 0.5 }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <div style={{ transform: `scale(${sc})`, textAlign: "center" }}>
          <div style={{ fontSize: 36, fontWeight: 700, color: "#475569", letterSpacing: "-0.02em", marginBottom: 8 }}>Trade closed</div>
          <div style={{ fontSize: 110, fontWeight: 800, color: GREEN, letterSpacing: "-0.06em", lineHeight: 1, textShadow: `0 0 80px rgba(16,185,129,.5)` }}>
            +$24.18
          </div>
        </div>
        <div style={{ opacity: subOp, fontSize: 18, color: "#64748b", fontWeight: 500 }}>
          +3.6% · 47 minutes open
        </div>
        <div style={{
          opacity: ctaOp,
          display: "inline-flex", alignItems: "center", gap: 12,
          padding: "14px 14px 14px 28px", borderRadius: 999,
          background: AMBER, color: "#000", fontSize: 16, fontWeight: 800,
          boxShadow: `0 0 50px rgba(245,158,11,.4)`,
        }}>
          Own the bot — $297 one-time
          <div style={{ width: 38, height: 38, borderRadius: "50%", background: "rgba(0,0,0,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
            </svg>
          </div>
        </div>
        <div style={{ opacity: ctaOp, fontSize: 12, color: "#334155", fontWeight: 600, letterSpacing: "0.04em" }}>aicashsystem.space</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const TradeExecComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={72}><Exec1 frame={frame} fps={fps} /></Sequence>
      <Sequence from={70} durationInFrames={112}><Exec2 frame={frame - 70} fps={fps} /></Sequence>
      <Sequence from={180} durationInFrames={92}><Exec3 frame={frame - 180} fps={fps} /></Sequence>
      <Sequence from={270} durationInFrames={90}><Exec4 frame={frame - 270} fps={fps} /></Sequence>
    </AbsoluteFill>
  );
};

// ─────────────────────────────────────────────────────────────
// COMPOSITION 3: DAILY STATS  (10s = 300 frames)
// ─────────────────────────────────────────────────────────────

const TODAY_TRADES = [
  { pair: "BTC/USDT", dir: "LONG",  pnl: "+$24.18", pct: "+3.6%", dur: "47m" },
  { pair: "ETH/USDT", dir: "LONG",  pnl: "+$11.44", pct: "+2.1%", dur: "1h 12m" },
  { pair: "SOL/USDT", dir: "SHORT", pnl: "+$8.92",  pct: "+4.8%", dur: "22m" },
  { pair: "BNB/USDT", dir: "LONG",  pnl: "+$18.30", pct: "+3.1%", dur: "58m" },
  { pair: "XRP/USDT", dir: "LONG",  pnl: "+$6.74",  pct: "+1.9%", dur: "35m" },
  { pair: "DOGE/USDT",dir: "LONG",  pnl: "+$14.82", pct: "+8.0%", dur: "19m" },
];

const Stats1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [56, 68], [1, 0], { extrapolateLeft: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(245,158,11,.10), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16 }}>
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#475569", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 16 }}>
            Today's Performance
          </div>
          <div style={{
            fontSize: 96, fontWeight: 800, letterSpacing: "-0.05em", lineHeight: 1,
            background: `linear-gradient(135deg, ${AMBER}, ${AMBER2})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>
            +$84.40
          </div>
          <div style={{ fontSize: 20, color: "#64748b", fontWeight: 500, marginTop: 12 }}>
            in 6 automated trades
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Stats2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [108, 120], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155", letterSpacing: "0.08em", textTransform: "uppercase" }}>All trades today</div>
        <div style={{
          width: 640, background: "rgba(8,8,12,.96)",
          border: "1px solid rgba(255,255,255,.1)", borderRadius: 20,
          overflow: "hidden", boxShadow: "0 40px 80px rgba(0,0,0,.7)",
        }}>
          {/* Header */}
          <div style={{ display: "flex", padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,.06)", background: "rgba(255,255,255,.02)" }}>
            {["Pair", "Dir", "P&L", "%", "Duration"].map((h, i) => (
              <div key={i} style={{ flex: i === 0 ? 1.5 : 1, fontSize: 10, fontWeight: 700, color: "#334155", textTransform: "uppercase", letterSpacing: "0.06em", textAlign: i > 0 ? "right" : "left" }}>{h}</div>
            ))}
          </div>
          {/* Trade rows */}
          {TODAY_TRADES.map((t, i) => {
            const rowOp = interpolate(frame, [i * 10, i * 10 + 18], [0, 1], { extrapolateRight: "clamp" });
            const rowY = interpolate(spr(frame, fps, i * 10), [0, 1], [14, 0]);
            return (
              <div key={i} style={{
                display: "flex", padding: "11px 20px", alignItems: "center",
                borderBottom: "1px solid rgba(255,255,255,.03)",
                opacity: rowOp, transform: `translateY(${rowY}px)`,
              }}>
                <div style={{ flex: 1.5, fontSize: 13, fontWeight: 700, color: "#e2e8f0" }}>{t.pair}</div>
                <div style={{ flex: 1, textAlign: "right" }}>
                  <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 7px", borderRadius: 5, background: t.dir === "LONG" ? "rgba(16,185,129,.12)" : "rgba(239,68,68,.12)", color: t.dir === "LONG" ? GREEN : RED }}>
                    {t.dir}
                  </span>
                </div>
                <div style={{ flex: 1, fontSize: 14, fontWeight: 800, color: GREEN, textAlign: "right" }}>{t.pnl}</div>
                <div style={{ flex: 1, fontSize: 12, fontWeight: 600, color: GREEN, textAlign: "right" }}>{t.pct}</div>
                <div style={{ flex: 1, fontSize: 11, color: "#475569", textAlign: "right" }}>{t.dur}</div>
              </div>
            );
          })}
          {/* Footer total */}
          <div style={{ display: "flex", justifyContent: "space-between", padding: "14px 20px", borderTop: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)" }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#64748b" }}>Total · 6/6 wins</span>
            <span style={{ fontSize: 16, fontWeight: 800, color: GREEN }}>+$84.40</span>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Stats3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const numSc = spr(frame, fps, 4, { damping: 12, stiffness: 80 });
  const subOp = interpolate(frame, [28, 44], [0, 1], { extrapolateRight: "clamp" });
  const ctaOp = interpolate(frame, [46, 62], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(245,158,11,.13), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <div style={{ position: "absolute", top: 0, left: "15%", right: "15%", height: 1, background: `linear-gradient(90deg,transparent,${AMBER},transparent)`, opacity: 0.4 }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `scale(${numSc})`, textAlign: "center" }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#64748b", letterSpacing: "-0.02em", marginBottom: 10 }}>
            Apex Trade Bot made
          </div>
          <div style={{
            fontSize: 120, fontWeight: 800, color: AMBER, letterSpacing: "-0.06em", lineHeight: 1,
            textShadow: `0 0 80px rgba(245,158,11,.5)`,
          }}>
            $84
          </div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#64748b", marginTop: 8 }}>
            while you weren't looking
          </div>
        </div>
        <div style={{ opacity: subOp, display: "flex", gap: 32, alignItems: "center" }}>
          {[["6", "Trades"], ["100%", "Win rate"], ["0h", "Your time"]].map(([v, l], i) => (
            <div key={i} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 32, fontWeight: 800, color: i === 2 ? GREEN : AMBER2, letterSpacing: "-0.03em" }}>{v}</div>
              <div style={{ fontSize: 11, color: "#475569", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 4 }}>{l}</div>
            </div>
          ))}
        </div>
        <div style={{
          opacity: ctaOp,
          display: "inline-flex", alignItems: "center", gap: 12,
          padding: "14px 14px 14px 28px", borderRadius: 999,
          background: AMBER, color: "#000", fontSize: 16, fontWeight: 800,
          boxShadow: `0 0 50px rgba(245,158,11,.4)`,
        }}>
          Get the bot — $297 once
          <div style={{ width: 38, height: 38, borderRadius: "50%", background: "rgba(0,0,0,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
            </svg>
          </div>
        </div>
        <div style={{ opacity: ctaOp, fontSize: 12, color: "#334155", fontWeight: 600, letterSpacing: "0.04em" }}>aicashsystem.space</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const DailyStatsComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={70}><Stats1 frame={frame} fps={fps} /></Sequence>
      <Sequence from={68} durationInFrames={132}><Stats2 frame={frame - 68} fps={fps} /></Sequence>
      <Sequence from={198} durationInFrames={102}><Stats3 frame={frame - 198} fps={fps} /></Sequence>
    </AbsoluteFill>
  );
};
