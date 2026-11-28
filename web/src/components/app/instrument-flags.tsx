/** Simplified flags for the instrument pictures. Drawn in SVG so nothing is downloaded. */

export function Union({ s = 1 }: { s?: number }) {
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

export function Flag({ code }: { code: string }) {
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
    case "DE": return <g><rect width="40" height="13.4" fill="#111" /><rect y="13.3" width="40" height="13.4" fill="#dd0000" /><rect y="26.6" width="40" height="13.4" fill="#ffce00" /></g>;
    case "FR": return <g><rect width="13.4" height="40" fill="#0055a4" /><rect x="13.3" width="13.4" height="40" fill="#fff" /><rect x="26.6" width="13.4" height="40" fill="#ef4135" /></g>;
    case "SEK": return <g><rect width="40" height="40" fill="#006aa7" /><rect x="11" width="7" height="40" fill="#fecc02" /><rect y="16.5" width="40" height="7" fill="#fecc02" /></g>;
    case "NOK": return <g><rect width="40" height="40" fill="#ba0c2f" /><rect x="10" width="10" height="40" fill="#fff" /><rect y="15" width="40" height="10" fill="#fff" /><rect x="12.5" width="5" height="40" fill="#00205b" /><rect y="17.5" width="40" height="5" fill="#00205b" /></g>;
    case "DKK": return <g><rect width="40" height="40" fill="#c8102e" /><rect x="11" width="6" height="40" fill="#fff" /><rect y="17" width="40" height="6" fill="#fff" /></g>;
    case "PLN": return <g><rect width="40" height="20" fill="#fff" /><rect y="20" width="40" height="20" fill="#dc143c" /></g>;
    default: return null;
  }
}

