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
const BLUE = "#3b82f6";
const PURPLE = "#8b5cf6";
const FONT = "'Plus Jakarta Sans', 'Inter', system-ui, sans-serif";
const MONO = "'JetBrains Mono', 'Fira Code', 'Courier New', monospace";

function spr(frame: number, fps: number, delay = 0, cfg = {}) {
  return spring({ frame: frame - delay, fps, config: { damping: 18, stiffness: 120, mass: 0.8, ...cfg } });
}

// ─────────────────────────────────────────────────────────────
// COMPOSITION 1: INSTALLATION  (18s = 540 frames)
// ─────────────────────────────────────────────────────────────

const INSTALL_LINES = [
  { text: "$ unzip apex_trade_bot_v2.zip", color: "#94a3b8", delay: 0 },
  { text: "  Archive: apex_trade_bot_v2.zip", color: "#475569", delay: 8 },
  { text: "  inflating: bot.py", color: "#475569", delay: 14 },
  { text: "  inflating: config.py", color: "#475569", delay: 18 },
  { text: "  inflating: requirements.txt", color: "#475569", delay: 22 },
  { text: "$ cd apex_trade_bot", color: "#94a3b8", delay: 30 },
  { text: "$ pip install -r requirements.txt", color: "#94a3b8", delay: 38 },
  { text: "  Collecting ccxt>=4.0.0...", color: "#475569", delay: 48 },
  { text: "  Collecting python-telegram-bot...", color: "#475569", delay: 54 },
  { text: "  Collecting pandas, numpy, ta...", color: "#475569", delay: 60 },
  { text: "  Installing 47 packages...", color: AMBER, delay: 68 },
  { text: "  Successfully installed! ✓", color: GREEN, delay: 80 },
];

const Install1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [66, 78], [1, 0], { extrapolateLeft: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);
  const badgeOp = interpolate(frame, [20, 36], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(139,92,246,.12), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 32 }}>
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 88, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.05em", lineHeight: 1 }}>
            Setup in
          </div>
          <div style={{ fontSize: 88, fontWeight: 800, background: `linear-gradient(135deg,${PURPLE},${BLUE})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.05em", lineHeight: 1 }}>
            60 seconds
          </div>
        </div>
        <div style={{ opacity: badgeOp, display: "flex", gap: 24 }}>
          {[["1", "Download"], ["2", "Install"], ["3", "Run"]].map(([n, l], i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: "50%", background: `linear-gradient(135deg,${PURPLE},${BLUE})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff" }}>{n}</div>
              <span style={{ fontSize: 14, fontWeight: 600, color: "#64748b" }}>{l}</span>
              {i < 2 && <div style={{ width: 24, height: 1, background: "rgba(255,255,255,.1)" }} />}
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Install2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [138, 150], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155", letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Terminal · Installation
        </div>
        {/* Terminal window */}
        <div style={{
          width: 660,
          background: "rgba(6,6,10,.97)",
          border: "1px solid rgba(255,255,255,.1)",
          borderRadius: 18,
          overflow: "hidden",
          boxShadow: "0 0 60px rgba(139,92,246,.1), 0 40px 80px rgba(0,0,0,.7)",
        }}>
          {/* Title bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 18px", borderBottom: "1px solid rgba(255,255,255,.07)", background: "rgba(255,255,255,.02)" }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ffbd2e" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28c840" }} />
            <span style={{ marginLeft: 8, fontSize: 12, color: "#475569", fontWeight: 500, fontFamily: MONO }}>bash — apex_trade_bot</span>
          </div>
          {/* Lines */}
          <div style={{ padding: "16px 20px", fontFamily: MONO }}>
            {INSTALL_LINES.map((line, i) => {
              const lineOp = interpolate(frame, [line.delay, line.delay + 12], [0, 1], { extrapolateRight: "clamp" });
              const lineY = interpolate(spr(frame, fps, line.delay), [0, 1], [8, 0]);
              return (
                <div key={i} style={{ fontSize: 13, color: line.color, lineHeight: 1.7, opacity: lineOp, transform: `translateY(${lineY}px)` }}>
                  {line.text}
                </div>
              );
            })}
            {/* Cursor */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, opacity: interpolate(frame % 20, [0, 10, 20], [1, 0, 1]) }}>
              <span style={{ fontSize: 13, color: "#64748b", fontFamily: MONO }}>$</span>
              <div style={{ width: 8, height: 16, background: GREEN, borderRadius: 1 }} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Install3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [118, 130], [1, 0], { extrapolateLeft: "clamp" });
  const sc = spr(frame, fps, 4, { damping: 12, stiffness: 80 });
  const subOp = interpolate(frame, [28, 44], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(16,185,129,.12), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <div style={{ position: "absolute", top: 0, left: "20%", right: "20%", height: 1, background: `linear-gradient(90deg,transparent,${GREEN},transparent)`, opacity: 0.4 }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `scale(${sc})`, textAlign: "center" }}>
          <div style={{ fontSize: 72, marginBottom: 16 }}>
            <span style={{ fontSize: 80, color: GREEN }}>✓</span>
          </div>
          <div style={{ fontSize: 72, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.04em", lineHeight: 1 }}>
            Installed.
          </div>
          <div style={{ fontSize: 22, color: "#64748b", fontWeight: 500, marginTop: 12 }}>
            Ready in under 60 seconds
          </div>
        </div>
        <div style={{ opacity: subOp, display: "flex", gap: 28 }}>
          {["Python 3.8+", "Windows / Mac / Linux", "47 packages"].map((t, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "#475569", fontWeight: 600 }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={GREEN} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              {t}
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Install4: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);
  const ctaOp = interpolate(frame, [36, 52], [0, 1], { extrapolateRight: "clamp" });
  const ctaY = interpolate(spr(frame, fps, 36), [0, 1], [20, 0]);

  return (
    <AbsoluteFill style={{ opacity: op, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(245,158,11,.10), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 22, color: "#64748b", fontWeight: 600, marginBottom: 12 }}>Full setup guide included.</div>
          <div style={{ fontSize: 76, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            Get started
          </div>
          <div style={{ fontSize: 76, fontWeight: 800, background: `linear-gradient(95deg,${AMBER},${AMBER2})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            today.
          </div>
        </div>
        <div style={{ opacity: ctaOp, transform: `translateY(${ctaY}px)`, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 12,
            padding: "15px 15px 15px 30px", borderRadius: 999,
            background: AMBER, color: "#000", fontSize: 17, fontWeight: 800,
            boxShadow: `0 0 50px rgba(245,158,11,.4)`,
          }}>
            Get Apex Trade Bot — $297
            <div style={{ width: 42, height: 42, borderRadius: "50%", background: "rgba(0,0,0,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
          <div style={{ fontSize: 12, color: "#334155", fontWeight: 600, letterSpacing: "0.04em" }}>aicashsystem.space</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const InstallComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={80}><Install1 frame={frame} fps={fps} /></Sequence>
      <Sequence from={78} durationInFrames={162}><Install2 frame={frame - 78} fps={fps} /></Sequence>
      <Sequence from={238} durationInFrames={142}><Install3 frame={frame - 238} fps={fps} /></Sequence>
      <Sequence from={378} durationInFrames={102}><Install4 frame={frame - 378} fps={fps} /></Sequence>
    </AbsoluteFill>
  );
};

// ─────────────────────────────────────────────────────────────
// COMPOSITION 2: CONFIGURATION  (15s = 450 frames)
// ─────────────────────────────────────────────────────────────

const CONFIG_LINES = [
  { label: "EXCHANGE", value: '"binance"', color: AMBER },
  { label: "API_KEY", value: '"pk_live_4xK9•••••••••••"', color: GREEN },
  { label: "API_SECRET", value: '"sk_live_9mR2•••••••••••"', color: GREEN },
  { label: "TELEGRAM_TOKEN", value: '"7441239:AAF•••••••"', color: BLUE },
  { label: "TELEGRAM_CHAT_ID", value: '"@apextrade_alerts"', color: BLUE },
  { label: "RISK_PER_TRADE", value: "0.01  # 1% per trade", color: "#94a3b8" },
  { label: "LEVERAGE", value: "10", color: AMBER },
  { label: "PAIRS", value: '["BTC","ETH","SOL","BNB"]', color: "#94a3b8" },
];

const Config1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [56, 68], [1, 0], { extrapolateLeft: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(59,130,246,.12), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 18, color: BLUE, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>
            Step 2 — Configuration
          </div>
          <div style={{ fontSize: 80, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            One config file.
          </div>
          <div style={{ fontSize: 80, fontWeight: 800, background: `linear-gradient(135deg,${BLUE},${PURPLE})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            That's it.
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Config2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [148, 160], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155", letterSpacing: "0.08em", textTransform: "uppercase" }}>
          config.py · Edit and save
        </div>
        <div style={{
          width: 660,
          background: "rgba(6,6,10,.97)",
          border: "1px solid rgba(255,255,255,.1)",
          borderRadius: 18, overflow: "hidden",
          boxShadow: "0 0 60px rgba(59,130,246,.1), 0 40px 80px rgba(0,0,0,.7)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 18px", borderBottom: "1px solid rgba(255,255,255,.07)", background: "rgba(255,255,255,.02)" }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ffbd2e" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28c840" }} />
            <span style={{ marginLeft: 8, fontSize: 12, color: "#475569", fontFamily: MONO }}>config.py</span>
            <div style={{ marginLeft: "auto", fontSize: 10, color: "#1e293b", fontFamily: MONO }}>Python</div>
          </div>
          <div style={{ padding: "16px 20px", fontFamily: MONO }}>
            <div style={{ fontSize: 12, color: "#334155", marginBottom: 10 }}># Apex Trade Bot — Configuration</div>
            {CONFIG_LINES.map((line, i) => {
              const lineOp = interpolate(frame, [i * 10, i * 10 + 16], [0, 1], { extrapolateRight: "clamp" });
              const lineX = interpolate(spr(frame, fps, i * 10), [0, 1], [-20, 0]);
              return (
                <div key={i} style={{ fontSize: 13, lineHeight: 1.75, opacity: lineOp, transform: `translateX(${lineX}px)`, display: "flex", gap: 0 }}>
                  <span style={{ color: "#475569", minWidth: 180, fontFamily: MONO }}>{line.label} </span>
                  <span style={{ color: "#334155" }}>= </span>
                  <span style={{ color: line.color, fontFamily: MONO }}>{line.value}</span>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Config3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [98, 110], [1, 0], { extrapolateLeft: "clamp" });

  const bootLines = [
    { text: "$ python bot.py", color: "#94a3b8", delay: 0 },
    { text: "  [INFO] Apex Trade Bot v2.0 starting...", color: "#475569", delay: 10 },
    { text: "  [INFO] Loading config.py...", color: "#475569", delay: 18 },
    { text: `  [OK]   Connected to Binance Futures`, color: GREEN, delay: 28 },
    { text: `  [OK]   Telegram bot active`, color: GREEN, delay: 38 },
    { text: `  [OK]   Monitoring 847 pairs...`, color: GREEN, delay: 48 },
    { text: `  [LIVE] Apex Trade Bot is running 🤖`, color: AMBER, delay: 60 },
  ];

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 50% 40% at 50% 60%, rgba(245,158,11,.08), transparent)" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155", letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Starting the bot
        </div>
        <div style={{
          width: 600,
          background: "rgba(6,6,10,.97)",
          border: "1px solid rgba(255,255,255,.1)",
          borderRadius: 18, overflow: "hidden",
          boxShadow: "0 40px 80px rgba(0,0,0,.7)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 18px", borderBottom: "1px solid rgba(255,255,255,.07)", background: "rgba(255,255,255,.02)" }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ffbd2e" }} />
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28c840" }} />
            <span style={{ marginLeft: 8, fontSize: 12, color: "#475569", fontFamily: MONO }}>bash</span>
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700, color: GREEN }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: GREEN }} />
              LIVE
            </div>
          </div>
          <div style={{ padding: "16px 20px", fontFamily: MONO }}>
            {bootLines.map((line, i) => {
              const lineOp = interpolate(frame, [line.delay, line.delay + 12], [0, 1], { extrapolateRight: "clamp" });
              return (
                <div key={i} style={{ fontSize: 13, color: line.color, lineHeight: 1.75, opacity: lineOp }}>
                  {line.text}
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Config4: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const sc = spr(frame, fps, 4, { damping: 12, stiffness: 80 });
  const ctaOp = interpolate(frame, [32, 48], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(245,158,11,.12), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `scale(${sc})`, textAlign: "center" }}>
          <div style={{ fontSize: 26, color: "#64748b", fontWeight: 600, marginBottom: 12 }}>Bot configured and live.</div>
          <div style={{ fontSize: 86, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.05em", lineHeight: 1 }}>
            It trades.
          </div>
          <div style={{ fontSize: 86, fontWeight: 800, background: `linear-gradient(95deg,${AMBER},${AMBER2})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.05em", lineHeight: 1 }}>
            You relax.
          </div>
        </div>
        <div style={{ opacity: ctaOp, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 12, padding: "14px 14px 14px 28px", borderRadius: 999, background: AMBER, color: "#000", fontSize: 16, fontWeight: 800, boxShadow: `0 0 50px rgba(245,158,11,.4)` }}>
            Get it now — $297 once
            <div style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(0,0,0,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
          <div style={{ fontSize: 12, color: "#334155", fontWeight: 600, letterSpacing: "0.04em" }}>aicashsystem.space</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const ConfigComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={70}><Config1 frame={frame} fps={fps} /></Sequence>
      <Sequence from={68} durationInFrames={172}><Config2 frame={frame - 68} fps={fps} /></Sequence>
      <Sequence from={238} durationInFrames={122}><Config3 frame={frame - 238} fps={fps} /></Sequence>
      <Sequence from={358} durationInFrames={92}><Config4 frame={frame - 358} fps={fps} /></Sequence>
    </AbsoluteFill>
  );
};

// ─────────────────────────────────────────────────────────────
// COMPOSITION 3: TELEGRAM ALERTS  (14s = 420 frames)
// ─────────────────────────────────────────────────────────────

// Phone mockup component
const Phone: React.FC<{ children: React.ReactNode; scale?: number }> = ({ children, scale = 1 }) => (
  <div style={{
    transform: `scale(${scale})`,
    width: 300, height: 600,
    background: "#0d0d12",
    border: "2px solid rgba(255,255,255,.15)",
    borderRadius: 44,
    overflow: "hidden",
    boxShadow: "0 0 0 4px rgba(255,255,255,.04), 0 0 80px rgba(0,0,0,.8), inset 0 1px 0 rgba(255,255,255,.1)",
    position: "relative",
  }}>
    {/* Notch */}
    <div style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", width: 80, height: 26, background: "#000", borderRadius: 13, zIndex: 10 }} />
    {/* Screen */}
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      {children}
    </div>
  </div>
);

const Tg1: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [56, 68], [1, 0], { extrapolateLeft: "clamp" });
  const titleY = interpolate(spr(frame, fps, 4), [0, 1], [40, 0]);

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(59,130,246,.14), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `translateY(${titleY}px)`, textAlign: "center" }}>
          <div style={{ fontSize: 18, color: BLUE, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>
            Telegram Alerts
          </div>
          <div style={{ fontSize: 80, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            Every trade.
          </div>
          <div style={{ fontSize: 80, fontWeight: 800, background: `linear-gradient(135deg,${BLUE},${PURPLE})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            On your phone.
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Tg2: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [118, 130], [1, 0], { extrapolateLeft: "clamp" });
  const phoneY = interpolate(spr(frame, fps, 4), [0, 1], [60, 0]);

  // Notification banner slides in from top
  const notifY = interpolate(spr(frame, fps, 20, { damping: 14, stiffness: 100 }), [0, 1], [-120, 0]);
  const notifOp = interpolate(frame, [20, 34], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 50% 40% at 50% 60%, rgba(59,130,246,.08), transparent)" }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 28 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#334155", letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Signal detected — notification sent
        </div>
        {/* Phone + notification */}
        <div style={{ transform: `translateY(${phoneY}px)`, position: "relative" }}>
          <Phone scale={1.1}>
            {/* Lock screen wallpaper */}
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg,#0a0a18,#050510)" }} />
            {/* Time */}
            <div style={{ position: "absolute", top: 70, left: 0, right: 0, textAlign: "center" }}>
              <div style={{ fontSize: 52, fontWeight: 200, color: "#fff", letterSpacing: "-0.02em", fontFamily: FONT }}>9:41</div>
              <div style={{ fontSize: 14, color: "rgba(255,255,255,.5)", fontWeight: 500 }}>Saturday, 7 June</div>
            </div>
            {/* Notification banner */}
            <div style={{
              position: "absolute", top: 55, left: 14, right: 14,
              background: "rgba(28,28,38,.96)",
              backdropFilter: "blur(20px)",
              borderRadius: 16, padding: "12px 14px",
              border: "1px solid rgba(255,255,255,.1)",
              boxShadow: "0 8px 32px rgba(0,0,0,.6)",
              opacity: notifOp, transform: `translateY(${notifY}px)`,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                {/* Telegram icon */}
                <div style={{ width: 28, height: 28, borderRadius: 8, background: BLUE, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="white">
                    <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.247l-2.013 9.487c-.149.658-.537.818-1.088.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12l-6.871 4.326-2.962-.924c-.643-.204-.657-.643.136-.953l11.57-4.463c.537-.194 1.006.131.88.736z" />
                  </svg>
                </div>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "#fff" }}>Apex Trade Bot</div>
                  <div style={{ fontSize: 10, color: "rgba(255,255,255,.4)" }}>now</div>
                </div>
              </div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,.85)", lineHeight: 1.5, fontFamily: MONO }}>
                <span style={{ color: GREEN, fontWeight: 700 }}>▲ SIGNAL: BTC/USDT LONG</span>{"\n"}
                Entry $67,841 · TP $68,920
              </div>
            </div>
          </Phone>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Tg3: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const exit = interpolate(frame, [118, 130], [1, 0], { extrapolateLeft: "clamp" });
  const phoneY = interpolate(spr(frame, fps, 4), [0, 1], [50, 0]);

  const messages = [
    { text: "🤖 Apex Trade Bot", sub: "", time: "", isHeader: true, delay: 0 },
    { text: "▲ SIGNAL: BTC/USDT LONG", sub: "Confidence: 91%", time: "09:41", isHeader: false, delay: 14, color: GREEN },
    { text: "✅ Trade EXECUTED", sub: "Entry: $67,841 · TP: $68,920 · SL: $67,200", time: "09:41", isHeader: false, delay: 28, color: AMBER },
    { text: "📈 P&L: +$14.20 (+2.1%)", sub: "Trade still open...", time: "10:03", isHeader: false, delay: 48, color: BLUE },
    { text: "💰 Trade CLOSED: +$24.18", sub: "Duration: 47min · +3.6%", time: "10:28", isHeader: false, delay: 66, color: GREEN },
  ];

  return (
    <AbsoluteFill style={{ opacity: op * exit, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <AbsoluteFill style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 60 }}>
        {/* Left: label */}
        <div style={{ maxWidth: 280 }}>
          <div style={{ fontSize: 13, color: BLUE, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 16 }}>
            Full trade lifecycle
          </div>
          <div style={{ fontSize: 44, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.03em", lineHeight: 1.1 }}>
            Signal → Entry → Close
          </div>
          <div style={{ fontSize: 16, color: "#64748b", fontWeight: 500, marginTop: 12, lineHeight: 1.6 }}>
            Every step notified<br />in real-time.
          </div>
        </div>
        {/* Phone with Telegram chat */}
        <div style={{ transform: `translateY(${phoneY}px)` }}>
          <Phone scale={1.05}>
            <div style={{ position: "absolute", inset: 0, background: "#0e1621", display: "flex", flexDirection: "column" }}>
              {/* Telegram chat header */}
              <div style={{ padding: "44px 14px 10px", display: "flex", alignItems: "center", gap: 10, background: "#17212b", borderBottom: "1px solid rgba(255,255,255,.05)" }}>
                <div style={{ width: 36, height: 36, borderRadius: "50%", background: BLUE, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🤖</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#fff" }}>Apex Trade Bot</div>
                  <div style={{ fontSize: 11, color: GREEN, fontWeight: 500 }}>online</div>
                </div>
              </div>
              {/* Messages */}
              <div style={{ flex: 1, padding: "10px 10px", overflow: "hidden", display: "flex", flexDirection: "column", gap: 6 }}>
                {messages.slice(1).map((msg, i) => {
                  const msgOp = interpolate(frame, [msg.delay, msg.delay + 14], [0, 1], { extrapolateRight: "clamp" });
                  const msgY = interpolate(spr(frame, fps, msg.delay), [0, 1], [16, 0]);
                  return (
                    <div key={i} style={{
                      alignSelf: "flex-start",
                      background: "#182533",
                      borderRadius: "4px 12px 12px 12px",
                      padding: "8px 10px",
                      maxWidth: "90%",
                      opacity: msgOp,
                      transform: `translateY(${msgY}px)`,
                    }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: msg.color || "#fff", fontFamily: MONO }}>{msg.text}</div>
                      {msg.sub && <div style={{ fontSize: 10, color: "rgba(255,255,255,.45)", marginTop: 2, fontFamily: MONO }}>{msg.sub}</div>}
                      <div style={{ fontSize: 9, color: "rgba(255,255,255,.25)", marginTop: 3, textAlign: "right" }}>{msg.time}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Phone>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Tg4: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const sc = spr(frame, fps, 4, { damping: 12, stiffness: 80 });
  const subOp = interpolate(frame, [24, 40], [0, 1], { extrapolateRight: "clamp" });
  const ctaOp = interpolate(frame, [40, 56], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ opacity: op, background: BG, fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(59,130,246,.14), transparent)" }} />
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px)", backgroundSize: "60px 60px" }} />
      <div style={{ position: "absolute", top: 0, left: "15%", right: "15%", height: 1, background: `linear-gradient(90deg,transparent,${BLUE},transparent)`, opacity: 0.4 }} />
      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24 }}>
        <div style={{ transform: `scale(${sc})`, textAlign: "center" }}>
          <div style={{ fontSize: 80, fontWeight: 800, color: "#f1f5f9", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            Always informed.
          </div>
          <div style={{ fontSize: 80, fontWeight: 800, background: `linear-gradient(135deg,${BLUE},${PURPLE})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", letterSpacing: "-0.04em", lineHeight: 1.05 }}>
            Never miss a trade.
          </div>
        </div>
        <div style={{ opacity: subOp, display: "flex", gap: 28 }}>
          {["Instant alerts", "Entry & exit prices", "Daily P&L summary"].map((t, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "#475569", fontWeight: 600 }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={GREEN} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              {t}
            </div>
          ))}
        </div>
        <div style={{ opacity: ctaOp, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 12, padding: "14px 14px 14px 28px", borderRadius: 999, background: AMBER, color: "#000", fontSize: 16, fontWeight: 800, boxShadow: `0 0 50px rgba(245,158,11,.4)` }}>
            Get Apex Trade Bot — $297
            <div style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(0,0,0,.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
          <div style={{ fontSize: 12, color: "#334155", fontWeight: 600, letterSpacing: "0.04em" }}>aicashsystem.space</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const TelegramComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: BG }}>
      <Sequence from={0} durationInFrames={70}><Tg1 frame={frame} fps={fps} /></Sequence>
      <Sequence from={68} durationInFrames={142}><Tg2 frame={frame - 68} fps={fps} /></Sequence>
      <Sequence from={208} durationInFrames={142}><Tg3 frame={frame - 208} fps={fps} /></Sequence>
      <Sequence from={348} durationInFrames={72}><Tg4 frame={frame - 348} fps={fps} /></Sequence>
    </AbsoluteFill>
  );
};
