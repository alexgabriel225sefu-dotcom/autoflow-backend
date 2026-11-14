/**
 * A picture for every instrument a broker can list: the two flags of a
 * currency pair, the flag of an index's country, bars for metals, a barrel for
 * oil, a flame for gas, a coin with its mark for digital coins, and a coin with the
 * ticker for shares and anything else. All of it is drawn here as SVG, so
 * nothing is downloaded and nothing needs flag emoji (Windows has none).
 *
 * The picture never claims more than is known. A name is given only where the
 * symbol is well known; for the rest the broker's own id is the name and the
 * picture is a coin carrying it.
 */
import { Flag } from "./instrument-flags";

const CURRENCIES: Record<string, string> = {
  EUR: "Euro", USD: "US Dollar", GBP: "British Pound", JPY: "Japanese Yen",
  CHF: "Swiss Franc", AUD: "Australian Dollar", CAD: "Canadian Dollar", NZD: "New Zealand Dollar",
  SEK: "Swedish Krona", NOK: "Norwegian Krone", DKK: "Danish Krone", PLN: "Polish Zloty",
  CZK: "Czech Koruna", HUF: "Hungarian Forint", SGD: "Singapore Dollar", HKD: "Hong Kong Dollar",
  CNH: "Chinese Yuan", MXN: "Mexican Peso", ZAR: "South African Rand", TRY: "Turkish Lira", RON: "Romanian Leu",
};

/** Indices a broker commonly lists, under the names brokers use. */
const INDICES: Record<string, { name: string; flag: string }> = {
  US30: { name: "Dow Jones 30", flag: "USD" }, DJ30: { name: "Dow Jones 30", flag: "USD" }, WS30: { name: "Dow Jones 30", flag: "USD" },
  US500: { name: "S&P 500", flag: "USD" }, SPX500: { name: "S&P 500", flag: "USD" }, SP500: { name: "S&P 500", flag: "USD" },
  NAS100: { name: "Nasdaq 100", flag: "USD" }, USTEC: { name: "Nasdaq 100", flag: "USD" }, US100: { name: "Nasdaq 100", flag: "USD" },
  GER40: { name: "DAX 40", flag: "DE" }, DE40: { name: "DAX 40", flag: "DE" }, GER30: { name: "DAX", flag: "DE" }, DAX40: { name: "DAX 40", flag: "DE" },
  UK100: { name: "FTSE 100", flag: "GBP" }, FRA40: { name: "CAC 40", flag: "FR" }, FR40: { name: "CAC 40", flag: "FR" },
  EU50: { name: "Euro Stoxx 50", flag: "EUR" }, STOXX50: { name: "Euro Stoxx 50", flag: "EUR" },
  JP225: { name: "Nikkei 225", flag: "JPY" }, JPN225: { name: "Nikkei 225", flag: "JPY" }, NI225: { name: "Nikkei 225", flag: "JPY" },
  AUS200: { name: "ASX 200", flag: "AUD" }, AU200: { name: "ASX 200", flag: "AUD" },
};

const TOKENS: Record<string, { name: string; color: string; mark: string }> = {
  BTC: { name: "Bitcoin", color: "#f7931a", mark: "₿" }, ETH: { name: "Ethereum", color: "#627eea", mark: "Ξ" },
  LTC: { name: "Litecoin", color: "#345d9d", mark: "Ł" }, XRP: { name: "XRP", color: "#23292f", mark: "X" },
  SOL: { name: "Solana", color: "#7b3fe4", mark: "S" }, ADA: { name: "Cardano", color: "#0033ad", mark: "A" },
  DOGE: { name: "Dogecoin", color: "#c2a633", mark: "Ð" }, BNB: { name: "BNB", color: "#f3ba2f", mark: "B" },
};

type Metal = "gold" | "silver" | "platinum" | "palladium" | "copper";
const METALS: Record<string, { metal: Metal; name: string }> = {
  XAUUSD: { metal: "gold", name: "Gold" }, XAGUSD: { metal: "silver", name: "Silver" },
  XPTUSD: { metal: "platinum", name: "Platinum" }, XPDUSD: { metal: "palladium", name: "Palladium" },
  XCUUSD: { metal: "copper", name: "Copper" },
};
const OIL = new Set(["XTIUSD", "USOIL", "WTI", "CL", "XBRUSD", "UKOIL", "BRENT", "USOUSD", "UKOUSD"]);
const GAS = new Set(["XNGUSD", "NGAS", "NATGAS", "NGUSD"]);

export type InstrumentKind = "pair" | "metal" | "oil" | "gas" | "index" | "token" | "stock" | "other";
export type InstrumentInfo = { title: string; subtitle: string; kind: InstrumentKind; detail?: string };

/**
 * What a symbol is. `cls` is the class the broker (via the platform) gave it;
 * it only breaks ties, so a symbol that looks like a pair but is classed as a
 * stock is treated as a stock.
 */
export function describeInstrument(symbol: string, cls?: string): InstrumentInfo {
  const s = symbol.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (METALS[s]) return { title: METALS[s].name, subtitle: `${METALS[s].name} priced in US Dollars`, kind: "metal", detail: METALS[s].metal };
  if (OIL.has(s)) return { title: s, subtitle: "Crude oil", kind: "oil" };
  if (GAS.has(s)) return { title: s, subtitle: "Natural gas", kind: "gas" };
  if (INDICES[s]) return { title: s, subtitle: INDICES[s].name, kind: "index", detail: INDICES[s].flag };
  const base = s.slice(0, 3), quote = s.slice(3, 6);
  if (cls !== "stock" && s.length === 6 && CURRENCIES[base] && CURRENCIES[quote]) {
    return { title: `${base}/${quote}`, subtitle: `${CURRENCIES[base]} against the ${CURRENCIES[quote]}`, kind: "pair" };
  }
  if (cls === "stock") return { title: s, subtitle: "Share from your broker", kind: "stock" };
  const coin = Object.keys(TOKENS).find((c) => s.startsWith(c) && /^(USD|USDT|EUR)?$/.test(s.slice(c.length)));
  if (coin) return { title: s, subtitle: TOKENS[coin].name, kind: "token", detail: coin };
  if (cls === "index") return { title: s, subtitle: "Index from your broker", kind: "index" };
  return { title: s || symbol, subtitle: "Instrument from your broker", kind: "other" };
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

/** A coin carrying text: the fallback for anything without a flag or a mark. */
function Coin({ id, label, color }: { id: string; label: string; color?: string }) {
  let h = 0;
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) % 360;
  const fill = color ?? `hsl(${h} 38% 30%)`;
  const text = label.slice(0, 4);
  return (
    <Disc id={id}>
      <rect width="40" height="40" fill={fill} />
      <circle cx="20" cy="20" r="15" fill="none" stroke="rgba(255,255,255,.28)" strokeWidth="1" />
      <text x="20" y="20" textAnchor="middle" dominantBaseline="central" fontSize={text.length > 3 ? 9 : text.length > 2 ? 10.5 : 13} fontWeight="700" fill="#fff" fontFamily="Arial, Helvetica, sans-serif">{text}</text>
    </Disc>
  );
}

function FlagDisc({ id, code }: { id: string; code: string }) {
  const flag = Flag({ code });
  return flag ? <Disc id={id}>{flag}</Disc> : <Coin id={id} label={code} />;
}

const METAL_COLOURS: Record<Metal, [string, string, string]> = {
  gold: ["#fff0a8", "#e2b324", "#9a6b0b"], silver: ["#ffffff", "#c7ccd6", "#7c8494"],
  platinum: ["#f4f7fb", "#b9c4d3", "#6f7d92"], palladium: ["#eef1f4", "#aeb6c1", "#667080"],
  copper: ["#ffd2b0", "#d9823f", "#8a4a1e"],
};

function Bars({ metal }: { metal: Metal }) {
  const [a, b, c] = METAL_COLOURS[metal];
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

function Barrel() {
  return (
    <svg viewBox="0 0 40 40" className="ins-disc ins-plain" aria-hidden="true" focusable="false">
      <defs><linearGradient id="a4t-barrel" x1="0" x2="1"><stop offset="0" stopColor="#3b3f4a" /><stop offset=".5" stopColor="#5a606f" /><stop offset="1" stopColor="#2e323c" /></linearGradient></defs>
      <path d="M9 6h22c2 4 2 24 0 28H9c-2-4-2-24 0-28z" fill="url(#a4t-barrel)" stroke="rgba(255,255,255,.22)" />
      <path d="M8.6 13h22.8M8.4 27h23.2" stroke="#ff9484" strokeWidth="2" />
      <ellipse cx="20" cy="6" rx="11" ry="2.6" fill="#6b7282" />
    </svg>
  );
}

function Flame() {
  return (
    <svg viewBox="0 0 40 40" className="ins-disc ins-plain" aria-hidden="true" focusable="false">
      <path d="M20 4c2 6 9 9 9 18a9 9 0 0 1-18 0c0-4 2-6 4-8 0 3 2 4 3 4 1-4 0-8 2-14z" fill="#ff8a3d" />
      <path d="M20 21c1 3 4 4 4 8a4 4 0 0 1-8 0c0-3 2-4 4-8z" fill="#ffd36b" />
    </svg>
  );
}

function IndexDisc({ id, flag }: { id: string; flag?: string }) {
  return (
    <span className="ins-idx">
      {flag ? <FlagDisc id={id} code={flag} /> : <Coin id={id} label="IDX" color="#2a2a33" />}
      <svg viewBox="0 0 16 16" className="ins-badge" aria-hidden="true" focusable="false">
        <circle cx="8" cy="8" r="8" fill="#111113" />
        <path d="M3 11l3-3.5 2.4 2L13 5" fill="none" stroke="#ff9484" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/** The picture alone, in a size the caller chooses (`size` selects the CSS). */
export function InstrumentArt({ symbol, size = "sm", cls }: { symbol: string; size?: "sm" | "lg"; cls?: string }) {
  const info = describeInstrument(symbol, cls);
  const key = symbol.toUpperCase().replace(/[^A-Z0-9]/g, "") || "X";
  return (
    <span className="ins" data-size={size} data-kind={info.kind} aria-hidden="true">
      {info.kind === "pair" ? (
        <>
          <FlagDisc id={`${key}-b`} code={key.slice(0, 3)} />
          <FlagDisc id={`${key}-q`} code={key.slice(3, 6)} />
        </>
      ) : info.kind === "metal" ? <Bars metal={(info.detail as Metal) ?? "gold"} />
        : info.kind === "oil" ? <Barrel />
        : info.kind === "gas" ? <Flame />
        : info.kind === "index" ? <IndexDisc id={key} flag={info.detail} />
        : info.kind === "token" ? <Coin id={key} label={TOKENS[info.detail ?? ""]?.mark ?? key} color={TOKENS[info.detail ?? ""]?.color} />
        : <Coin id={key} label={key} />}
    </span>
  );
}

/** The picture with its name, shown once an instrument is chosen. */
export function InstrumentCard({ symbol, cls }: { symbol: string; cls?: string }) {
  const info = describeInstrument(symbol, cls);
  return (
    <div className="ins-card" key={symbol} role="group" aria-label={`Selected instrument: ${info.title}`}>
      <InstrumentArt symbol={symbol} size="lg" cls={cls} />
      <div>
        <strong>{info.title}</strong>
        <span>{info.subtitle}</span>
      </div>
    </div>
  );
}

