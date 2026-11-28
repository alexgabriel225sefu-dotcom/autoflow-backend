import type { ReactElement } from "react";
import styles from "./article-cover.module.css";

/**
 * Generative cover art for a guide article. Contract:
 *   <ArticleCover slug="risk-guard-explained" className="..." />
 * Inline, purely graphic SVG (no text, no assets). Fills its container width;
 * the caller sets the aspect ratio through CSS (artwork is drawn on 1200x630).
 */

const CREAM = "#F7F6F2";
const RED = "#D62B45";

/** Fine cream stroke at the given opacity. */
const line = (opacity: number, width = 1.5) => ({
  stroke: CREAM,
  strokeOpacity: opacity,
  strokeWidth: width,
  fill: "none",
});

const dashed = (opacity: number, width = 1.5) => ({
  ...line(opacity, width),
  strokeDasharray: "3 9",
  strokeLinecap: "round" as const,
});

const redLine = (width = 2) => ({ stroke: RED, strokeWidth: width, fill: "none" });

const RED_DOT_R = 7;

function RedDot({ x, y, r = RED_DOT_R }: { x: number; y: number; r?: number }) {
  return (
    <g>
      <circle cx={x} cy={y} r={r * 3} fill={RED} opacity={0.1} />
      <circle cx={x} cy={y} r={r} fill={RED} />
    </g>
  );
}

/** A gate: two posts with a gap; closed gates get a bar across. */
function Gate({ x, y, h = 170, gap = 48, closed = false }: { x: number; y: number; h?: number; gap?: number; closed?: boolean }) {
  const top = y - h / 2;
  const bottom = y + h / 2;
  return (
    <g>
      <path d={`M${x - gap / 2} ${top} V${bottom}`} {...line(0.55, 2)} />
      <path d={`M${x + gap / 2} ${top} V${bottom}`} {...line(0.55, 2)} />
      <path d={`M${x - gap / 2 - 12} ${top} H${x - gap / 2 + 12} M${x + gap / 2 - 12} ${top} H${x + gap / 2 + 12}`} {...line(0.4, 2)} />
      {closed ? <path d={`M${x - gap / 2} ${y} H${x + gap / 2}`} {...redLine(3)} /> : null}
    </g>
  );
}

/* ---------- compositions (each draws inside the 1200x630 canvas) ---------- */

function RulesBased() {
  const rows = [150, 280, 410];
  return (
    <g>
      <path d="M180 110 V520" {...dashed(0.25)} />
      {rows.map((y, i) => (
        <g key={y}>
          <rect x={220} y={y} width={230} height={64} rx={14} {...line(0.4)} fill={CREAM} fillOpacity={0.03} />
          <path d={`M250 ${y + 32} H${330 - i * 20}`} {...line(0.5, 2)} />
          <path d={`M${450} ${y + 32} H${770}`} {...line(0.3)} />
          <rect x={770} y={y + 4} width={56} height={56} rx={6} transform={`rotate(45 ${798} ${y + 32})`} {...line(0.5)} />
          <path d={`M826 ${y + 32} H${940}`} {...line(0.3)} />
          <circle cx={970} cy={y + 32} r={30} {...line(i === 1 ? 0.7 : 0.35)} />
        </g>
      ))}
      <RedDot x={798} y={312} />
    </g>
  );
}

function ConnectCtrader() {
  return (
    <g>
      <circle cx={380} cy={330} r={90} {...line(0.5, 2)} />
      <circle cx={380} cy={330} r={38} {...line(0.35)} />
      <circle cx={380} cy={330} r={150} {...dashed(0.2)} />
      <path d="M470 330 H790 M690 330 V385 M740 330 V372 M790 330 V385" {...line(0.5, 2)} />
      <rect x={830} y={255} width={240} height={150} rx={75} {...line(0.45)} fill={CREAM} fillOpacity={0.03} />
      <circle cx={950} cy={330} r={22} {...line(0.5)} />
      <path d="M950 352 V380" {...line(0.5)} />
      <path d="M380 180 C 480 70, 850 70, 950 250" {...dashed(0.45)} />
      <RedDot x={665} y={102} />
    </g>
  );
}

const MACD_BARS = [10, 22, 34, 40, 30, 14, -8, -24, -36, -28, -14, 6, 20, 32, 44, 38, 24, 8, -12, -26, -18, -4, 14, 28];

function Indicators() {
  return (
    <g>
      {[80, 250, 420].map((y) => (
        <rect key={y} x={140} y={y} width={920} height={130} rx={18} {...line(0.22)} fill={CREAM} fillOpacity={0.025} />
      ))}
      <path d="M160 200 C300 120 380 230 520 160 S760 110 900 180 S1020 150 1040 140" {...line(0.55, 2)} />
      <path d="M160 190 C320 160 420 190 540 170 S780 150 900 170 S1020 160 1040 155" {...line(0.3)} />
      <path d="M160 290 H1040 M160 340 H1040" {...dashed(0.35)} />
      <path d="M160 330 C260 380 340 270 440 300 S600 360 700 315 S880 275 1040 330" {...line(0.55, 2)} />
      <path d="M160 485 H1040" {...line(0.25)} />
      {MACD_BARS.map((v, i) => (
        <rect key={i} x={170 + i * 36} y={v >= 0 ? 485 - v : 485} width={18} height={Math.abs(v)} rx={3} fill={CREAM} fillOpacity={v >= 0 ? 0.3 : 0.16} />
      ))}
      <path d="M700 60 V570" {...line(0.35)} />
      <RedDot x={700} y={315} />
    </g>
  );
}

function DemoVsLive() {
  return (
    <g>
      {[60, 110, 160].map((r, i) => (
        <g key={r}>
          <circle cx={400} cy={315} r={r} {...dashed(0.45 - i * 0.1)} />
          <circle cx={800} cy={315} r={r} {...line(0.6 - i * 0.15, i === 0 ? 2 : 1.5)} />
        </g>
      ))}
      <path d="M600 90 V540" {...dashed(0.3)} />
      <circle cx={800} cy={315} r={26} fill={CREAM} fillOpacity={0.06} />
      <RedDot x={800} y={315} r={8} />
    </g>
  );
}

const TICKS = Array.from({ length: 24 }, (_, i) => 140 + i * 40);

function RiskPerTrade() {
  return (
    <g>
      <rect x={140} y={295} width={920} height={40} rx={20} {...line(0.4)} />
      <rect x={140} y={295} width={280} height={40} rx={20} fill={CREAM} fillOpacity={0.12} />
      {TICKS.map((x, i) => (
        <path key={x} d={`M${x} 360 V${i % 4 === 0 ? 392 : 376}`} {...line(i % 4 === 0 ? 0.45 : 0.25)} />
      ))}
      <path d="M420 215 V400" {...redLine(2.5)} />
      <path d="M420 215 H760 M420 205 V225 M760 205 V225" {...line(0.5)} />
      <path d="M760 225 V295" {...dashed(0.4)} />
      <circle cx={760} cy={315} r={16} {...line(0.7, 2)} />
      <circle cx={760} cy={315} r={5} fill={CREAM} fillOpacity={0.7} />
      <circle cx={420} cy={315} r={RED_DOT_R * 3} fill={RED} opacity={0.1} />
    </g>
  );
}

const LEDGER_COLS = [220, 500, 740, 940];
const LEDGER_LENGTHS = [
  [150, 120, 90, 60],
  [120, 150, 70, 80],
  [170, 90, 110, 50],
  [100, 140, 80, 90],
  [160, 110, 100, 70],
  [130, 130, 60, 100],
];

function Journal() {
  return (
    <g>
      <path d="M150 120 H1050" {...line(0.55, 2)} />
      {LEDGER_COLS.map((x, c) => (
        <path key={x} d={`M${x} 100 H${x + 60 + c * 12}`} {...line(0.4, 3)} strokeLinecap="round" />
      ))}
      {LEDGER_LENGTHS.map((lens, r) => {
        const y = 180 + r * 66;
        return (
          <g key={y}>
            {r === 2 ? <rect x={150} y={y - 28} width={900} height={56} rx={10} fill={CREAM} fillOpacity={0.06} /> : null}
            <path d={`M150 ${y + 33} H1050`} {...line(0.12)} />
            <circle cx={176} cy={y} r={6} {...line(r === 2 ? 0.7 : 0.35)} />
            {LEDGER_COLS.map((x, c) => (
              <path key={x} d={`M${x} ${y} H${x + lens[c]}`} {...line(0.4 - c * 0.05, 2)} strokeLinecap="round" />
            ))}
          </g>
        );
      })}
      <path d="M150 190 V570" {...dashed(0.2)} />
      <RedDot x={1030} y={312} r={6} />
    </g>
  );
}

const arch = (cx: number, half: number, bottom: number) =>
  `M${cx - half} ${bottom} V${bottom - 230 - (120 - half)} A${half} ${half} 0 0 1 ${cx + half} ${bottom - 230 - (120 - half)} V${bottom}`;

function Questions() {
  return (
    <g>
      {[120, 85, 50].map((half, i) => (
        <path key={half} d={arch(400, half, 530)} {...line(0.5 - i * 0.1, i === 2 ? 2 : 1.5)} />
      ))}
      <path d="M200 530 H600" {...line(0.4)} />
      <RedDot x={400} y={430} />
      {[160, 255, 350, 445].map((y, i) => (
        <g key={y}>
          {i === 3 ? (
            <circle cx={738} cy={y} r={20} {...redLine(2)} />
          ) : (
            <rect x={718} y={y - 20} width={40} height={40} rx={10} {...line(0.5)} />
          )}
          {i === 0 || i === 1 ? <path d={`M728 ${y} l8 8 l14 -16`} {...line(0.7, 2.5)} strokeLinecap="round" strokeLinejoin="round" /> : null}
          <path d={`M800 ${y} H${1000 - i * 50}`} {...line(0.4 - i * 0.07, 2)} strokeLinecap="round" />
        </g>
      ))}
    </g>
  );
}

const RUN_DOTS = Array.from({ length: 14 }, (_, i) => 200 + i * 60);

function DemoRunShows() {
  const edge = 620;
  return (
    <g>
      <rect x={140} y={110} width={920} height={410} rx={22} {...line(0.35)} fill={CREAM} fillOpacity={0.025} />
      <path d="M140 165 H1060" {...line(0.2)} />
      {[176, 200, 224].map((x) => (
        <circle key={x} cx={x} cy={138} r={5} {...line(0.4)} />
      ))}
      <path d={`M200 330 H${edge}`} {...line(0.55, 2)} />
      <path d={`M${edge} 330 H1000`} {...dashed(0.35)} />
      {RUN_DOTS.map((x, i) => (
        <circle key={x} cx={x} cy={330} r={x <= edge ? 6 : 5} {...(x <= edge ? { fill: CREAM, fillOpacity: 0.6 } : { ...dashed(0.45 - i * 0.025), strokeDasharray: undefined })} />
      ))}
      {[430, 465].map((y, i) => (
        <g key={y}>
          <path d={`M200 ${y} H${edge - i * 90}`} {...line(0.3, 2)} strokeLinecap="round" />
          <path d={`M${edge - i * 90 + 24} ${y} H${960 - i * 80}`} {...dashed(0.2)} />
        </g>
      ))}
      <path d={`M${edge} 250 V405`} {...redLine(2.5)} />
      <circle cx={edge} cy={330} r={RED_DOT_R * 3} fill={RED} opacity={0.1} />
    </g>
  );
}

function PreviewVsRun() {
  return (
    <g>
      <rect x={130} y={120} width={440} height={390} rx={20} {...dashed(0.45)} />
      <rect x={630} y={120} width={440} height={390} rx={20} {...line(0.55, 2)} fill={CREAM} fillOpacity={0.05} />
      {[190, 240, 290].map((y, i) => (
        <g key={y}>
          <path d={`M180 ${y} H${440 - i * 50}`} {...dashed(0.35)} />
          <path d={`M680 ${y} H${940 - i * 50}`} {...line(0.4, 2)} strokeLinecap="round" />
        </g>
      ))}
      <path d="M570 315 H630" {...line(0.3)} />
      <path d="M180 440 H520" {...dashed(0.25)} />
      <path d="M810 345 L810 425 L880 385 Z" {...line(0.6, 2)} strokeLinejoin="round" />
      <RedDot x={1030} y={160} />
    </g>
  );
}

function RiskGuard() {
  return (
    <g>
      <path d="M600 100 L790 170 V330 C790 430 700 500 600 540 C500 500 410 430 410 330 V170 Z" {...line(0.55, 2)} fill={CREAM} fillOpacity={0.03} />
      <path d="M600 150 L745 205 V330 C745 405 675 460 600 495 C525 460 455 405 455 330 V205 Z" {...line(0.22)} />
      {[200, 240, 280, 320].map((y) => (
        <path key={y} d={`M300 ${y} H900`} {...line(0.08)} />
      ))}
      <path d="M260 360 H940" {...redLine(2.5)} />
      <path d="M260 372 H300 M900 372 H940" {...line(0.3)} />
      <path d="M180 440 H330 M870 440 H1020 M220 480 H320 M880 480 H980" {...dashed(0.25)} />
      <circle cx={600} cy={330} r={RED_DOT_R * 3} fill={RED} opacity={0.08} />
    </g>
  );
}

function WhyNotOpen() {
  const xs = [260, 450, 640, 830];
  return (
    <g>
      <path d="M110 315 H810" {...line(0.45, 2)} />
      <path d="M850 315 H1090" {...dashed(0.3)} />
      {xs.map((x, i) => (
        <Gate key={x} x={x} y={315} closed={i === 3} />
      ))}
      {xs.slice(0, 3).map((x) => (
        <circle key={x} cx={x} cy={315} r={5} fill={CREAM} fillOpacity={0.65} />
      ))}
      <circle cx={830} cy={315} r={95} {...dashed(0.35)} />
      <circle cx={830} cy={315} r={RED_DOT_R * 3} fill={RED} opacity={0.1} />
      <path d="M900 385 L960 445" {...line(0.45, 2.5)} strokeLinecap="round" />
    </g>
  );
}

function Fallback() {
  return (
    <g>
      {[70, 130, 190, 250].map((r, i) => (
        <circle key={r} cx={600} cy={315} r={r} {...line(0.4 - i * 0.07)} />
      ))}
      <path d="M200 315 H1000 M600 80 V550" {...dashed(0.25)} />
      <RedDot x={600} y={315} />
    </g>
  );
}

const SCENES: Readonly<Record<string, () => ReactElement>> = {
  "what-is-rules-based-trading": RulesBased,
  "connect-ctrader-safely": ConnectCtrader,
  "moving-average-rsi-macd-as-rule-conditions": Indicators,
  "demo-vs-live-account": DemoVsLive,
  "risk-per-trade-and-stop-distance": RiskPerTrade,
  "trading-journal-what-to-record": Journal,
  "questions-to-ask-before-trusting-an-automation-platform": Questions,
  "what-a-demo-run-shows-and-what-it-does-not": DemoRunShows,
  "preview-vs-run-what-each-does": PreviewVsRun,
  "risk-guard-explained": RiskGuard,
  "why-did-my-rule-not-open-a-trade": WhyNotOpen,
};

export function ArticleCover({ slug, className }: { slug: string; className?: string }) {
  const known = Object.prototype.hasOwnProperty.call(SCENES, slug);
  const Scene = known ? SCENES[slug] : Fallback;
  const p = `ac-${slug.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const classes = className ? `${styles.cover} ${className}` : styles.cover;

  return (
    <svg
      className={classes}
      viewBox="0 0 1200 630"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={`${p}-bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0B0B0D" />
          <stop offset="1" stopColor="#15151A" />
        </linearGradient>
        <radialGradient id={`${p}-glow`} cx="0.7" cy="0.4" r="0.7">
          <stop offset="0" stopColor={CREAM} stopOpacity="0.08" />
          <stop offset="1" stopColor={CREAM} stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${p}-fade`} cx="0.5" cy="0.5" r="0.65">
          <stop offset="0" stopColor="#fff" stopOpacity="1" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id={`${p}-mask`}>
          <rect width="1200" height="630" fill={`url(#${p}-fade)`} />
        </mask>
        <pattern id={`${p}-dots`} width="30" height="30" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.1" fill={CREAM} fillOpacity="0.22" />
        </pattern>
      </defs>
      <rect width="1200" height="630" fill={`url(#${p}-bg)`} />
      <rect width="1200" height="630" fill={`url(#${p}-glow)`} />
      <rect width="1200" height="630" fill={`url(#${p}-dots)`} mask={`url(#${p}-mask)`} />
      <path d="M36 70 V36 H70 M1130 36 H1164 V70 M1164 560 V594 H1130 M70 594 H36 V560" {...line(0.2)} />
      <Scene />
    </svg>
  );
}
