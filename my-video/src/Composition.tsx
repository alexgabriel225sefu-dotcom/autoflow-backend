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
const FONT = "'Plus Jakarta Sans', 'Inter', system-ui, sans-serif";

// Reusable spring helper
function spr(frame: number, fps: number, delay = 0, config = {}) {
  return spring({
    frame: frame - delay,
    fps,
    config: { damping: 18, stiffness: 120, mass: 0.8, ...config },
  });
}

// Scene 1: Hook — "While you sleep..." (0–60f)
const Scene1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const opacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);
  const dotScale = spr(frame, fps, 10);
  const subOpacity = interpolate(frame, [24, 38], [0, 1], { extrapolateRight: "clamp" });
  const subY = interpolate(spr(frame, fps, 24), [0, 1], [20, 0]);
  const exitOpacity = interpolate(frame, [52, 60], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: opacity * exitOpacity, background: BG, fontFamily: FONT }}>
      {/* Grid background */}
      <AbsoluteFill style={{
        backgroundImage: "linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px)",
        backgroundSize: "60px 60px",
      }} />
      {/* Glow orb */}
      <AbsoluteFill style={{
        background: "radial-gradient(ellipse 60% 40% at 50% 10%, rgba(139,92,246,.18), transparent)",
      }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        {/* Live dot */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, transform: `scale(${dotScale})` }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: GREEN, boxShadow: `0 0 12px ${GREEN}` }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: GREEN, letterSpacing: "0.1em", textTransform: "uppercase" }}>
            Live Trading · AI-Powered
          </span>
        </div>
        {/* Main headline */}
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 86, fontWeight: 800, color: "#f1f5f9", lineHeight: 1.05, letterSpacing: "-0.04em" }}>
            While you sleep...
          </div>
        </div>
        {/* Sub */}
        <div style={{ opacity: subOpacity, transform: `translateY(${subY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 22, color: "#94a3b8", fontWeight: 400, letterSpacing: "-0.01em" }}>
            your AI bot is trading crypto
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Scene 2: Live trades (60–150f)
const Scene2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const opacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const exitOp = interpolate(frame, [80, 90], [1, 0], { extrapolateLeft: "clamp" });

  const trades = [
    { pair: "BTC/USDT", side: "LONG", pnl: "+$24.18", color: GREEN, delay: 0 },
    { pair: "ETH/USDT", side: "LONG", pnl: "+$11.44", color: GREEN, delay: 8 },
    { pair: "SOL/USDT", side: "SHORT", pnl: "+$8.92", color: GREEN, delay: 16 },
    { pair: "BNB/USDT", side: "LONG", pnl: "+$18.30", color: GREEN, delay: 24 },
  ];

  return (
    <AbsoluteFill style={{ opacity: opacity * exitOp, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{
        backgroundImage: "linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px)",
        backgroundSize: "60px 60px",
      }} />
      <AbsoluteFill style={{
        background: "radial-gradient(ellipse 50% 50% at 50% 50%, rgba(245,158,11,.07), transparent)",
      }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 32 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#64748b", letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Executing trades automatically
        </div>
        {/* Terminal card */}
        <div style={{
          width: 560,
          background: "rgba(10,10,15,.9)",
          border: "1px solid rgba(255,255,255,.12)",
          borderRadius: 20,
          overflow: "hidden",
          boxShadow: "0 0 60px rgba(245,158,11,.12), 0 40px 80px rgba(0,0,0,.6)",
        }}>
          {/* Terminal bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 18px", borderBottom: "1px solid rgba(255,255,255,.07)", background: "rgba(255,255,255,.02)" }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ffbd2e" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28c840" }} />
            <span style={{ marginLeft: 10, fontSize: 12, color: "#475569", fontWeight: 500 }}>aicash_bot.py — Live</span>
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700, color: GREEN }}>
              <div style={{ width: 5, height: 5, borderRadius: "50%", background: GREEN }} />
              ACTIVE
            </div>
          </div>
          {/* Trades */}
          <div style={{ padding: "10px 12px" }}>
            {trades.map((t, i) => {
              const rowOp = interpolate(frame, [t.delay, t.delay + 14], [0, 1], { extrapolateRight: "clamp" });
              const rowY = interpolate(spr(frame, fps, t.delay), [0, 1], [16, 0]);
              return (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 12px", borderRadius: 10, marginBottom: 4,
                  background: "rgba(255,255,255,.025)",
                  opacity: rowOp, transform: `translateY(${rowY}px)`,
                }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "#f1f5f9", flex: 1 }}>{t.pair}</span>
                  <span style={{ fontSize: 11, fontWeight: 800, padding: "2px 8px", borderRadius: 5, background: "rgba(16,185,129,.12)", color: GREEN, letterSpacing: "0.04em" }}>{t.side}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: t.color, minWidth: 70, textAlign: "right" }}>{t.pnl}</span>
                  <span style={{ fontSize: 11, color: "#475569", minWidth: 44, textAlign: "right" }}>{i * 6 + 2}m ago</span>
                </div>
              );
            })}
          </div>
          {/* Footer */}
          <div style={{ display: "flex", borderTop: "1px solid rgba(255,255,255,.07)" }}>
            {[["73%", "Win Rate"], ["+$341", "Today"], ["24/7", "Active"]].map(([v, l], i) => (
              <div key={i} style={{ flex: 1, padding: "12px", textAlign: "center", borderRight: i < 2 ? "1px solid rgba(255,255,255,.07)" : "none" }}>
                <div style={{ fontSize: 18, fontWeight: 800, color: AMBER, letterSpacing: "-0.02em" }}>{v}</div>
                <div style={{ fontSize: 10, color: "#475569", marginTop: 2, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>{l}</div>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Scene 3: Stats counter (150–240f)
const Scene3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const opacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const exitOp = interpolate(frame, [80, 90], [1, 0], { extrapolateLeft: "clamp" });

  const stats = [
    { value: "73%", label: "Win Rate", delay: 0 },
    { value: "8+", label: "Exchanges", delay: 10 },
    { value: "24/7", label: "Autonomous", delay: 20 },
    { value: "$0", label: "Monthly Fee", delay: 30 },
  ];

  return (
    <AbsoluteFill style={{ opacity: opacity * exitOp, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{
        backgroundImage: "linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px)",
        backgroundSize: "60px 60px",
      }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 48 }}>
        <div style={{
          fontSize: 18, fontWeight: 700, color: "#64748b",
          letterSpacing: "0.08em", textTransform: "uppercase",
        }}>
          The numbers
        </div>
        <div style={{ display: "flex", gap: 0, border: "1px solid rgba(255,255,255,.1)", borderRadius: 20, overflow: "hidden", width: 760 }}>
          {stats.map((s, i) => {
            const sc = spr(frame, fps, s.delay);
            const y = interpolate(sc, [0, 1], [30, 0]);
            const op = interpolate(frame, [s.delay, s.delay + 14], [0, 1], { extrapolateRight: "clamp" });
            return (
              <div key={i} style={{
                flex: 1, padding: "36px 24px", textAlign: "center",
                background: "rgba(10,10,15,.9)",
                borderRight: i < 3 ? "1px solid rgba(255,255,255,.07)" : "none",
              }}>
                <div style={{
                  fontSize: 52, fontWeight: 800,
                  background: `linear-gradient(135deg, ${AMBER}, ${AMBER2})`,
                  WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
                  letterSpacing: "-0.04em", lineHeight: 1,
                  opacity: op, transform: `translateY(${y}px)`,
                }}>
                  {s.value}
                </div>
                <div style={{ fontSize: 13, color: "#64748b", marginTop: 8, fontWeight: 600 }}>
                  {s.label}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Scene 4: CTA (240–330f / 11s)
const Scene4: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const opacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [50, 0]);
  const priceScale = spr(frame, fps, 18);
  const btnOp = interpolate(frame, [36, 50], [0, 1], { extrapolateRight: "clamp" });
  const btnY = interpolate(spr(frame, fps, 36), [0, 1], [20, 0]);
  const tagOp = interpolate(frame, [52, 64], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{
        backgroundImage: "linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px)",
        backgroundSize: "60px 60px",
      }} />
      <AbsoluteFill style={{
        background: "radial-gradient(ellipse 70% 50% at 50% 50%, rgba(245,158,11,.1), transparent)",
      }} />
      {/* Top line */}
      <div style={{ position: "absolute", top: 0, left: "20%", right: "20%", height: 1, background: `linear-gradient(90deg, transparent, ${AMBER}, transparent)`, opacity: 0.5 }} />

      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 28 }}>
        {/* Headline */}
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 76, fontWeight: 800, color: "#f1f5f9", lineHeight: 1.06, letterSpacing: "-0.04em" }}>
            Own the bot.
          </div>
          <div style={{
            fontSize: 76, fontWeight: 800, lineHeight: 1.06, letterSpacing: "-0.04em",
            background: `linear-gradient(95deg, ${AMBER}, ${AMBER2}, #fb923c)`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>
            Keep the profits.
          </div>
        </div>

        {/* Price */}
        <div style={{ transform: `scale(${priceScale})`, display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontSize: 28, fontWeight: 700, color: AMBER }}>$</span>
          <span style={{ fontSize: 88, fontWeight: 800, color: AMBER, letterSpacing: "-0.05em", lineHeight: 1 }}>297</span>
          <span style={{ fontSize: 16, color: "#64748b", fontWeight: 600 }}>one-time</span>
        </div>

        {/* CTA button */}
        <div style={{ opacity: btnOp, transform: `translateY(${btnY}px)` }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 12,
            padding: "16px 16px 16px 32px",
            borderRadius: 999, background: AMBER, color: "#000",
            fontSize: 18, fontWeight: 800,
            boxShadow: `0 0 60px rgba(245,158,11,.45), 0 20px 40px rgba(245,158,11,.2)`,
          }}>
            Get AiCash System
            <div style={{ width: 44, height: 44, borderRadius: "50%", background: "rgba(0,0,0,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
              </svg>
            </div>
          </div>
        </div>

        {/* Trust tags */}
        <div style={{ opacity: tagOp, display: "flex", gap: 20, alignItems: "center" }}>
          {["One-time payment", "Full source code", "Instant delivery"].map((t, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "#64748b", fontWeight: 500 }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={GREEN} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              {t}
            </div>
          ))}
        </div>

        {/* Domain */}
        <div style={{ fontSize: 13, color: "#334155", fontWeight: 600, letterSpacing: "0.04em", marginTop: 4 }}>
          aicashsystem.space
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Main composition
export const MyComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ background: BG, fontFamily: FONT }}>
      <Sequence from={0} durationInFrames={62}>
        <Scene1 frame={frame} fps={fps} />
      </Sequence>
      <Sequence from={60} durationInFrames={92}>
        <Scene2 frame={frame - 60} fps={fps} />
      </Sequence>
      <Sequence from={150} durationInFrames={92}>
        <Scene3 frame={frame - 150} fps={fps} />
      </Sequence>
      <Sequence from={240} durationInFrames={90}>
        <Scene4 frame={frame - 240} fps={fps} />
      </Sequence>
    </AbsoluteFill>
  );
};
