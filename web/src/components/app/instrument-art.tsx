/**
 * A picture for each instrument: the two flags of a currency pair, a stack of
 * bars for gold or silver, and a plain chart glyph for anything else. All are
 * drawn here as SVG, so nothing is downloaded and nothing depends on the
 * system having flag emoji (Windows has none).
 */

const NAMES: Record<string, string> = {
  EUR: "Euro", USD: "US Dollar", GBP: "British Pound", JPY: "Japanese Yen",
  CHF: "Swiss Franc", AUD: "Australian Dollar", CAD: "Canadian Dollar", NZD: "New Zealand Dollar",
};

export type InstrumentInfo = { title: string; subtitle: string; kind: "pair" | "gold" | "silver" | "other" };

export function describeInstrument(symbol: string): InstrumentInfo {
  const s = symbol.toUpperCase();
  if (s === "XAUUSD") return { title: "Gold", subtitle: "Gold priced in US Dollars", kind: "gold" };
  if (s === "XAGUSD") return { title: "Silver", subtitle: "Silver priced in US Dollars", kind: "silver" };
  const base = s.slice(0, 3), quote = s.slice(3, 6);
  if (s.length === 6 && NAMES[base] && NAMES[quote]) {
    return { title: `${base}/${quote}`, subtitle: `${NAMES[base]} against the ${NAMES[quote]}`, kind: "pair" };
  }
  return { title: s, subtitle: "Instrument from your broker", kind: "other" };
}

function Union({ s = 1 }: { s?: number }) {
  return (
    <g transform={`scale(${s})`}>
      <rect width="40" height="40" fill="#1b3f94" />
      <path d="M0 0L40 40M40 0L0 40" stroke="#fff" strokeWidth="6" />
      <path d="M0 0L40 40M40 0L0 40" stroke="#c8102e" strokeWidth="2.2" />
      <path d="M20 0V40M0 20H40" stroke="#fff" strokeWidth="10" />
      <path d="M20 0V40M0 20H40" stroke="#c8102e" strokeWidth="5.5" />
    </g>
  );
}

const DOTS = (cx: number, cy: number, r: number, n: number, dot: number, fill: string) =>
  Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    return <circle key={i} cx={cx + Math.cos(a) * r} cy={cy + Math.sin(a) * r} r={dot} fill={fill} />;
  });

function Flag({ code }: { code: string }) {
  switch (code) {
    case "EUR": return <g><rect width="40" height="40" fill="#1b3f94" />{DOTS(20, 20, 11, 12, 1.7, "#ffd617")}</g>;
    case "USD": return (
      <g>
        <rect width="40" height="40" fill="#fff" />
        {[0, 2, 4, 6].map((i) => <rect key={i} y={i * (40 / 7)} width="40" height={40 / 7} fill="#c8102e" />)}
        <rect width="19" height={(40 / 7) * 4} fill="#1b3f94" />
        {[[5, 5], [10, 5], [14.5, 5], [7.5, 10], [12.5, 10], [5, 15], [10, 15], [14.5, 15]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="1" fill="#fff" />)}
      </g>
    );
    case "GBP": return <Union />;
    case "JPY": return <g><rect width="40" height="40" fill="#fff" /><circle cx="20" cy="20" r="9" fill="#bc002d" /></g>;
    case "CHF": return <g><rect width="40" height="40" fill="#da291c" /><rect x="17.2" y="8" width="5.6" height="24" fill="#fff" /><rect x="8" y="17.2" width="24" height="5.6" fill="#fff" /></g>;
    case "AUD": return (
      <g>
        <rect width="40" height="40" fill="#00247d" />
        <g clipPath="url(#a4t-canton)"><Union s={0.5} /></g>
        <circle cx="10" cy="30" r="3.6" fill="#fff" />
        {[[28, 9], [34, 19], [28, 31], [22, 21]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="1.6" fill="#fff" />)}
      </g>
    );
    case "CAD": return (
      <g>
        <rect width="40" height="40" fill="#d52b1e" /><rect x="10" width="20" height="40" fill="#fff" />
        <path d="M20 9l2.4 5 3-1.2-1 6 3.4-2.4-1 3.8 4.2-.2-3 3.6 2.4 1.4-6.4 2.2.4 4.8h-4.8V27l-5-2.6 2.4-1.4-3-3.6 4.2.2-1-3.8 3.4 2.4-1-6 3 1.2z" fill="#d52b1e" transform="translate(0 -1) scale(1)" />
      </g>
    );
    case "NZD": return (
      <g>
        <rect width="40" height="40" fill="#00247d" />
        <g clipPath="url(#a4t-canton)"><Union s={0.5} /></g>
        {[[28, 9], [34, 19], [28, 31], [22, 21]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="2" fill="#cc142b" stroke="#fff" strokeWidth=".8" />)}
      </g>
    );
    default: return <rect width="40" height="40" fill="#2a2a31" />;
  }
}

function Disc({ children, id }: { children: React.ReactNode; id: string }) {
  return (
    <svg viewBox="0 0 40 40" className="ins-disc" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id={`${id}-c`}><circle cx="20" cy="20" r="20" /></clipPath>
        <clipPath id="a4t-canton"><rect width="20" height="20" /></clipPath>
      </defs>
      <g clipPath={`url(#${id}-c)`}>{children}</g>
      <circle cx="20" cy="20" r="19.5" fill="none" stroke="rgba(255,255,255,.18)" />
    </svg>
  );
}

function Bars({ metal }: { metal: "gold" | "silver" }) {
  const [a, b, c] = metal === "gold" ? ["#fff0a8", "#e2b324", "#9a6b0b"] : ["#ffffff", "#c7ccd6", "#7c8494"];
  const id = `bar-${metal}`;
  return (
    <svg viewBox="0 0 64 44" className="ins-bars" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={a} /><stop offset=".5" stopColor={b} /><stop offset="1" stopColor={c} /></linearGradient>
      </defs>
      {[[18, 4], [4, 22], [32, 22]].map(([x, y], i) => (
        <path key={i} d={`M${x + 4} ${y}h24l6 17H${x - 2}z`} fill={`url(#${id})`} stroke="rgba(0,0,0,.35)" strokeWidth=".6" />
      ))}
    </svg>
  );
}

function Glyph({ label }: { label: string }) {
  return (
    <svg viewBox="0 0 40 40" className="ins-disc" aria-hidden="true" focusable="false">
      <circle cx="20" cy="20" r="19.5" fill="#1a1a20" stroke="rgba(255,255,255,.18)" />
      <path d="M8 27l7-8 5 4 6-9 6 6" fill="none" stroke="#ff9484" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <title>{label}</title>
    </svg>
  );
}

/** The picture alone, in a size the caller chooses through CSS (`size` is a class). */
export function InstrumentArt({ symbol, size = "sm" }: { symbol: string; size?: "sm" | "lg" }) {
  const info = describeInstrument(symbol);
  const key = symbol.toUpperCase().replace(/[^A-Z0-9]/g, "");
  return (
    <span className="ins" data-size={size} data-kind={info.kind} aria-hidden="true">
      {info.kind === "pair" ? (
        <>
          <Disc id={`${key}-b`}><Flag code={key.slice(0, 3)} /></Disc>
          <Disc id={`${key}-q`}><Flag code={key.slice(3, 6)} /></Disc>
        </>
      ) : info.kind === "gold" || info.kind === "silver" ? (
        <Bars metal={info.kind} />
      ) : (
        <Glyph label={info.title} />
      )}
    </span>
  );
}

/** The picture with its name, shown once an instrument is chosen. */
export function InstrumentCard({ symbol }: { symbol: string }) {
  const info = describeInstrument(symbol);
  return (
    <div className="ins-card" key={symbol} role="group" aria-label={`Selected instrument: ${info.title}`}>
      <InstrumentArt symbol={symbol} size="lg" />
      <div>
        <strong>{info.title}</strong>
        <span>{info.subtitle}</span>
      </div>
    </div>
  );
}
